BEGIN;

-- Running upgrade h8i9j0k1l2m3 -> i9j0k1l2m3n4

LOCK TABLE api_key_daily_stats IN SHARE ROW EXCLUSIVE MODE;

DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM api_key_daily_stats
                GROUP BY api_key_id, stat_date HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION 'Existen estadísticas diarias duplicadas'
                    USING HINT = 'Revisar duplicados por api_key_id y stat_date antes de aplicar esta revisión; no se han fusionado ni eliminado filas.';
            END IF;
        END $$;

ALTER TABLE api_key_daily_stats ADD CONSTRAINT uq_api_key_daily_stats_key_date UNIQUE (api_key_id, stat_date);

ALTER TABLE api_key_usage_logs ADD COLUMN quota_pending BOOLEAN DEFAULT false NOT NULL;

UPDATE alembic_version SET version_num='i9j0k1l2m3n4' WHERE alembic_version.version_num = 'h8i9j0k1l2m3';

COMMIT;
