"""Respalda y retira el módulo de proyectos. Sin --apply solo muestra el alcance."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from supabase import create_client

from app.core.config import settings
from app.maintenance.project_retirement import (
    DEDICATED_BUCKETS, PROJECT_TABLES, rows_digest, select_storage_objects, verified_backup,
)


def connect():
    return psycopg.connect(settings.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://"),
                           connect_timeout=15, row_factory=dict_row, prepare_threshold=None)


def write_file(root, relative, content, manifest):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    manifest["files"].append({"path": relative, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)})


def active_references(connection, objects):
    """Busca nombres originales y codificados; una coincidencia protege el archivo."""
    from urllib.parse import quote
    references = set()
    tables = connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()
    for table in tables:
        if table["tablename"] in PROJECT_TABLES:
            continue
        for obj in objects:
            patterns = []
            for name in {obj["name"], quote(obj["name"], safe="/")}:
                escaped = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                patterns.append(f"%{escaped}%")
            query = sql.SQL("SELECT EXISTS (SELECT 1 FROM public.{} t WHERE to_jsonb(t)::text LIKE ANY(%s)) AS found").format(sql.Identifier(table["tablename"]))
            if connection.execute(query, (patterns,)).fetchone()["found"]:
                references.add((obj["bucket_id"], obj["name"]))
    return references


def inventory(connection):
    rows = {}
    for name in PROJECT_TABLES:
        rows[name] = [record["data"] for record in connection.execute(
            sql.SQL("SELECT to_jsonb(t) AS data FROM public.{} t").format(sql.Identifier(name)))]
    objects = connection.execute("SELECT bucket_id,name,updated_at FROM storage.objects ORDER BY bucket_id,name").fetchall()
    selected = select_storage_objects(objects, rows, active_references(connection, objects))
    return rows, selected


def restore_sql(connection):
    """DDL y valores literales emitidos por PostgreSQL, sin redondear JSON/decimales."""
    statements = ["BEGIN;", "SET LOCAL datestyle = 'ISO, YMD';"]
    fks, indexes, triggers, policies, grants, rls = [], [], [], [], [], []
    for name in reversed(PROJECT_TABLES):
        relation = f"public.{name}"
        columns = connection.execute("""
            SELECT a.attname, format_type(a.atttypid,a.atttypmod) AS type,
                   a.attnotnull, pg_get_expr(d.adbin,d.adrelid) AS default
            FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
            WHERE a.attrelid=%s::regclass AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum
        """, (relation,)).fetchall()
        constraints = connection.execute("SELECT conname,contype,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE conrelid=%s::regclass", (relation,)).fetchall()
        identifier = sql.SQL("public.{}").format(sql.Identifier(name)).as_string(connection)
        definitions = []
        for column in columns:
            definition = sql.Identifier(column["attname"]).as_string(connection) + " " + column["type"]
            if column["default"] is not None:
                definition += " DEFAULT " + column["default"]
            if column["attnotnull"]:
                definition += " NOT NULL"
            definitions.append(definition)
        for constraint in constraints:
            definition = "CONSTRAINT " + sql.Identifier(constraint["conname"]).as_string(connection) + " " + constraint["definition"]
            if constraint["contype"] == "f":
                fks.append(f"ALTER TABLE {identifier} ADD {definition};")
            else:
                definitions.append(definition)
        statements.append(f"CREATE TABLE {identifier} (" + ", ".join(definitions) + ");")
        column_names = sql.SQL(", ").join(sql.Identifier(column["attname"]) for column in columns).as_string(connection)
        literals = sql.SQL(", ").join(sql.SQL("quote_nullable({}::text)").format(sql.Identifier(column["attname"])) for column in columns)
        query = sql.SQL("SELECT concat_ws(',', {}) AS literals FROM public.{}").format(literals, sql.Identifier(name))
        for row in connection.execute(query):
            statements.append(f"INSERT INTO {identifier} ({column_names}) VALUES ({row['literals']});")
        indexes.extend(row["definition"] + ";" for row in connection.execute("""
            SELECT pg_get_indexdef(indexrelid) AS definition FROM pg_index
            WHERE indrelid=%s::regclass AND indexrelid NOT IN
                (SELECT conindid FROM pg_constraint WHERE conrelid=%s::regclass)
        """, (relation, relation)))
        for trigger in connection.execute("SELECT tgname,tgenabled,pg_get_triggerdef(oid) AS definition FROM pg_trigger WHERE tgrelid=%s::regclass AND NOT tgisinternal", (relation,)):
            triggers.append(trigger["definition"] + ";")
            mode = {"D": "DISABLE", "R": "ENABLE REPLICA", "A": "ENABLE ALWAYS"}.get(trigger["tgenabled"])
            if mode:
                triggers.append(f"ALTER TABLE {identifier} {mode} TRIGGER {sql.Identifier(trigger['tgname']).as_string(connection)};")
        for policy in connection.execute("SELECT * FROM pg_policies WHERE schemaname='public' AND tablename=%s", (name,)):
            roles = ", ".join("PUBLIC" if role == "public" else sql.Identifier(role).as_string(connection) for role in policy["roles"])
            statement = f"CREATE POLICY {sql.Identifier(policy['policyname']).as_string(connection)} ON {identifier} AS {policy['permissive']} FOR {policy['cmd']} TO {roles}"
            if policy["qual"]:
                statement += " USING (" + policy["qual"] + ")"
            if policy["with_check"]:
                statement += " WITH CHECK (" + policy["with_check"] + ")"
            policies.append(statement + ";")
        flags = connection.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass", (relation,)).fetchone()
        if flags["relrowsecurity"]:
            rls.append(f"ALTER TABLE {identifier} ENABLE ROW LEVEL SECURITY;")
        if flags["relforcerowsecurity"]:
            rls.append(f"ALTER TABLE {identifier} FORCE ROW LEVEL SECURITY;")
        for grant in connection.execute("SELECT grantee,privilege_type,is_grantable FROM information_schema.role_table_grants WHERE table_schema='public' AND table_name=%s", (name,)):
            role = "PUBLIC" if grant["grantee"] == "PUBLIC" else sql.Identifier(grant["grantee"]).as_string(connection)
            grants.append(f"GRANT {grant['privilege_type']} ON {identifier} TO {role}" + (" WITH GRANT OPTION" if grant["is_grantable"] == "YES" else "") + ";")
    statements.extend(fks + indexes + triggers + policies + grants + rls + ["COMMIT;"])
    return "\n".join(statements) + "\n"


def verify_restore(ddl, expected):
    """Prueba el respaldo en un esquema aislado y revierte toda la comprobación."""
    import uuid
    schema = "verify_project_retirement_" + uuid.uuid4().hex
    connection = connect()
    try:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        original_schemas = connection.execute("SELECT current_schemas(false) AS schemas").fetchone()["schemas"]
        connection.execute(sql.SQL("SET LOCAL search_path TO {}, {}").format(
            sql.Identifier(schema), sql.SQL(", ").join(sql.Identifier(name) for name in original_schemas)))
        # Los datos se insertan con el SQL original; solo se cambia el esquema cualificado.
        verification_sql = ddl.removeprefix("BEGIN;\n").removesuffix("COMMIT;\n")
        verification_sql = verification_sql.replace('public.', sql.Identifier(schema).as_string(connection) + '.')
        connection.execute(verification_sql)
        for name in PROJECT_TABLES:
            restored = [row["data"] for row in connection.execute(sql.SQL("SELECT to_jsonb(t) AS data FROM {}.{} t").format(sql.Identifier(schema), sql.Identifier(name)))]
            if rows_digest(restored) != rows_digest(expected[name]):
                raise RuntimeError("La prueba de restauración no coincide con los datos originales")
    finally:
        connection.rollback()
        connection.close()


def cleanup_storage(manifest_path, client):
    manifest = verified_backup(manifest_path)
    with connect() as connection:
        existing = connection.execute("SELECT bucket_id,name,updated_at FROM storage.objects").fetchall()
        protected = active_references(connection, manifest["objects"])
        if protected:
            raise RuntimeError("Un recurso activo empezó a usar un archivo retirado; se conserva Storage para revisión")
        for obj in manifest["objects"]:
            current = next((item for item in existing if item["bucket_id"] == obj["bucket_id"] and item["name"] == obj["name"]), None)
            if current is None:
                continue  # Permite reanudar después de una limpieza parcial.
            if str(current["updated_at"]) != obj["updated_at"]:
                raise RuntimeError("Un archivo cambió después del respaldo; no se elimina")
            client.storage.from_(obj["bucket_id"]).remove([obj["name"]])
        connection.commit()
    with connect() as connection:
        remaining = connection.execute("SELECT bucket_id,name FROM storage.objects").fetchall()
        expected = {(obj["bucket_id"], obj["name"]) for obj in manifest["objects"]}
        if any((obj["bucket_id"], obj["name"]) in expected for obj in remaining):
            raise RuntimeError("Storage no confirmó la eliminación completa; reanuda con --resume-storage")
        for bucket in sorted(DEDICATED_BUCKETS):
            if any(obj["bucket_id"] == bucket for obj in remaining):
                continue  # Nunca vaciar un bucket con objetos nuevos o ajenos al plan.
            if connection.execute("SELECT id FROM storage.buckets WHERE id=%s", (bucket,)).fetchone():
                client.storage.delete_bucket(bucket)
    manifest["storage_completed"] = True
    Path(manifest_path).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--apply", action="store_true")
    actions.add_argument("--apply-backup", type=Path)
    actions.add_argument("--resume-storage", type=Path)
    args = parser.parse_args()
    if args.apply or args.resume_storage or args.apply_backup:
        if not settings.SUPABASE_SERVICE_KEY:
            raise RuntimeError("Hace falta SUPABASE_SERVICE_KEY para respaldar/limpiar Storage")
        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    if args.resume_storage:
        cleanup_storage(args.resume_storage, client)
        print("Storage de proyectos verificado y retirado")
        return
    if args.apply_backup:
        verified_backup(args.apply_backup)
        root = args.apply_backup.resolve().parent
        rows = json.loads((root / "tables.json").read_text(encoding="utf-8"))
        verify_restore((root / "restore.sql").read_text(encoding="utf-8"), rows)
        print("Respaldo existente y restauración verificados")
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["project_retirement_backup"] = str(args.apply_backup.resolve())
        command.upgrade(config, "k1l2m3n4o5p6")
        cleanup_storage(args.apply_backup, client)
        print("Tablas y Storage de proyectos retirados")
        return
    with connect() as connection:
        connection.execute("SET LOCAL lock_timeout='10s'")
        connection.execute(sql.SQL("LOCK TABLE {} IN SHARE MODE").format(
            sql.SQL(", ").join(sql.SQL("public.{}").format(sql.Identifier(name)) for name in PROJECT_TABLES)))
        rows, objects = inventory(connection)
        print("Filas por tabla:", {name: len(data) for name, data in rows.items()})
        print("Objetos propios a retirar:", len(objects), "; buckets exclusivos:", sorted(DEDICATED_BUCKETS))
        if not args.apply:
            return
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        if [item["version_num"] for item in revision] != ["j0k1l2m3n4o5"]:
            raise RuntimeError("La base debe estar en j0k1l2m3n4o5 antes de retirar proyectos")
        backup = ROOT / ".git" / "private-backups" / ("projects-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        backup.mkdir(parents=True, exist_ok=False)
        manifest = {"format": "geomaps-project-retirement-v1", "revision_before": "j0k1l2m3n4o5",
                    "table_digests": {name: rows_digest(data) for name, data in rows.items()},
                    "objects": [], "files": []}
        write_file(backup, "tables.json", json.dumps(rows, default=str, ensure_ascii=False).encode(), manifest)
        ddl = restore_sql(connection)
        write_file(backup, "restore.sql", ddl.encode(), manifest)
        buckets = connection.execute("SELECT to_jsonb(b) AS data FROM storage.buckets b").fetchall()
        write_file(backup, "buckets.json", json.dumps(buckets, default=str, ensure_ascii=False).encode(), manifest)
        for index, obj in enumerate(objects):
            payload = client.storage.from_(obj["bucket_id"]).download(obj["name"])
            relative = f"objects/{index:04d}.bin"
            write_file(backup, relative, payload, manifest)
            manifest["objects"].append({**obj, "updated_at": str(obj["updated_at"]), "backup_file": relative})
        manifest_path = backup / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        verified_backup(manifest_path)
        verify_restore(ddl, rows)
        print("Restauración de las diez tablas verificada en un esquema temporal revertido")
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["project_retirement_backup"] = str(manifest_path)
    command.upgrade(config, "k1l2m3n4o5p6")
    print("Tablas de proyectos retiradas; respaldo privado:", manifest_path)
    cleanup_storage(manifest_path, client)
    print("Limpieza de Storage completada")


if __name__ == "__main__":
    main()
