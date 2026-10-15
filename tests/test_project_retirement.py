import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.maintenance.project_retirement import PROJECT_TABLES, rows_digest, select_storage_objects, storage_references, verified_backup


class ProjectRetirementTests(unittest.TestCase):
    def test_retired_tables_are_not_recreated_by_orm_metadata(self):
        from app.db.base import Base
        self.assertTrue(set(PROJECT_TABLES).isdisjoint(Base.metadata.tables))

    def make_backup(self, root):
        rows = {name: [] for name in PROJECT_TABLES}
        files = []
        for name, content in {"tables.json": json.dumps(rows), "restore.sql": "-- respaldo de prueba"}.items():
            payload = content.encode()
            (root / name).write_bytes(payload)
            files.append({"path": name, "sha256": hashlib.sha256(payload).hexdigest()})
        manifest = {"format": "geomaps-project-retirement-v1", "files": files, "objects": [],
                    "table_digests": {name: rows_digest(data) for name, data in rows.items()}}
        path = root / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def migration(self):
        path = Path("alembic/versions/k1l2m3n4o5p6_retire_project_tables.py")
        spec = importlib.util.spec_from_file_location("project_retirement_migration", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_shared_files_abort_and_unrelated_files_are_preserved(self):
        objects = [{"bucket_id": "project", "name": "own.pdf"}, {"bucket_id": "Imagen", "name": "other.png"}, {"bucket_id": "Capas", "name": "layer.zip"}]
        self.assertEqual(select_storage_objects(objects, {}, set()), [objects[0]])
        with self.assertRaises(RuntimeError):
            select_storage_objects(objects, {}, {("project", "own.pdf")})

    def test_shared_bucket_only_deletes_referenced_project_file(self):
        objects = [{"bucket_id": "Imagen", "name": "photo.png"}, {"bucket_id": "Imagen", "name": "unrelated.png"}]
        rows = {"url": "https://example.supabase.co/storage/v1/object/public/Imagen/photo.png"}
        self.assertEqual(select_storage_objects(objects, rows, set()), [objects[0]])

    def test_signed_urls_and_explicit_paths_are_resolved(self):
        refs = storage_references([{"storage_bucket": "project", "storage_path": "asset.pdf"}, "https://example.supabase.co/storage/v1/object/sign/Imagen/a%20b.png?token=redacted"])
        self.assertEqual(refs, {("project", "asset.pdf"), ("Imagen", "a b.png")})

    def test_backup_tampering_stops_retirement(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.make_backup(root)
            verified_backup(path)
            (root / "restore.sql").write_text("modificado", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                verified_backup(path)

    def test_missing_storage_backup_is_rejected(self):
        with TemporaryDirectory() as directory:
            path = self.make_backup(Path(directory))
            manifest = json.loads(path.read_text())
            manifest["objects"] = [{"backup_file": "missing.bin"}]
            path.write_text(json.dumps(manifest))
            with self.assertRaises(RuntimeError):
                verified_backup(path)

    def test_migration_requires_backup_before_any_database_work(self):
        migration = self.migration()
        context = SimpleNamespace(is_offline_mode=lambda: False, config=SimpleNamespace(attributes={}), get_x_argument=lambda **kwargs: {})
        with patch.object(migration, "context", context), patch.object(migration.op, "get_bind") as bind:
            with self.assertRaises(RuntimeError):
                migration.upgrade()
            bind.assert_not_called()

    def test_migration_drops_only_explicit_project_tables(self):
        migration = self.migration()
        with TemporaryDirectory() as directory:
            path = self.make_backup(Path(directory))
            context = SimpleNamespace(is_offline_mode=lambda: False, config=SimpleNamespace(attributes={"project_retirement_backup": str(path)}))
            bind = Mock()
            bind.execute.return_value = []
            with patch.object(migration, "context", context), patch.object(migration.op, "get_bind", return_value=bind), patch.object(migration.op, "drop_table") as drop:
                migration.upgrade()
                self.assertEqual([call.args[0] for call in drop.call_args_list], list(PROJECT_TABLES))
                self.assertTrue(all(call.kwargs == {"schema": "public"} for call in drop.call_args_list))

    def test_changed_data_blocks_every_drop(self):
        migration = self.migration()
        with TemporaryDirectory() as directory:
            path = self.make_backup(Path(directory))
            context = SimpleNamespace(is_offline_mode=lambda: False, config=SimpleNamespace(attributes={"project_retirement_backup": str(path)}))
            bind = Mock()
            bind.execute.side_effect = [[], [], [({"id": "new"},)]]
            with patch.object(migration, "context", context), patch.object(migration.op, "get_bind", return_value=bind), patch.object(migration.op, "drop_table") as drop:
                with self.assertRaises(RuntimeError):
                    migration.upgrade()
                drop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
