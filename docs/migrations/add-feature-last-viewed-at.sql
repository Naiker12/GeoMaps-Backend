BEGIN;

-- Running upgrade g7h8i9j0k1l2 -> h8i9j0k1l2m3

ALTER TABLE layer_features ADD COLUMN last_viewed_at TIMESTAMP WITH TIME ZONE;

UPDATE alembic_version SET version_num='h8i9j0k1l2m3' WHERE alembic_version.version_num = 'g7h8i9j0k1l2';

COMMIT;
