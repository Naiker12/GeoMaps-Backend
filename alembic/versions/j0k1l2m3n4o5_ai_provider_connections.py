"""Add provider connections and a unique default AI model."""
from alembic import op
import sqlalchemy as sa
revision = 'j0k1l2m3n4o5'
down_revision = 'i9j0k1l2m3n4'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('ia_models_config', sa.Column('base_url', sa.Text(), nullable=True))
    op.add_column('ia_models_config', sa.Column('api_key_encrypted', sa.Text(), nullable=True))
    op.add_column('ia_models_config', sa.Column('is_default', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.execute('CREATE UNIQUE INDEX uq_ia_default_model ON ia_models_config (is_default) WHERE is_default = true')
    op.execute('ALTER TABLE ia_models_config ADD CONSTRAINT ck_ia_default_active CHECK (NOT is_default OR is_active)')

def downgrade():
    op.drop_constraint('ck_ia_default_active', 'ia_models_config', type_='check')
    op.drop_index('uq_ia_default_model', 'ia_models_config')
    for column in ('is_default', 'api_key_encrypted', 'base_url'):
        op.drop_column('ia_models_config', column)
