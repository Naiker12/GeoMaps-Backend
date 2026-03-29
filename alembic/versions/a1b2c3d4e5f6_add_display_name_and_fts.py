"""add_display_name_and_fts

Revision ID: a1b2c3d4e5f6
Revises: 233b7ac7eaf6
Create Date: 2026-03-29 10:45:00.000000

Agrega columna display_name y search_vector a layer_features,
crea índice FTS (GIN), elimina índice GIST duplicado, instala
extensión unaccent, y crea trigger para actualizar search_vector
automáticamente.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '233b7ac7eaf6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Instalar extensión unaccent
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    # Agregar columnas
    op.add_column('layer_features', sa.Column('display_name', sa.Text(), nullable=True))
    op.add_column('layer_features', sa.Column('search_vector', sa.Column('TSVECTOR'), nullable=True))

    # Índice GIN para FTS
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_layer_features_fts
        ON layer_features USING GIN(search_vector)
    """)

    # Eliminar índice GIST duplicado
    op.execute("DROP INDEX IF EXISTS ix_layer_features_geom")

    # Función trigger para actualizar search_vector
    op.execute("""
        CREATE OR REPLACE FUNCTION fn_update_layer_feature_search_vector()
        RETURNS TRIGGER AS $$
        BEGIN
          NEW.search_vector := to_tsvector(
            'spanish',
            COALESCE(NEW.display_name, '') || ' ' ||
            COALESCE(NEW.properties->>'barrio', '') || ' ' ||
            COALESCE(NEW.properties->>'sector', '') || ' ' ||
            COALESCE(NEW.properties->>'comuna', '') || ' ' ||
            COALESCE(NEW.properties->>'sig_territ', '') || ' ' ||
            COALESCE(NEW.properties->>'sig_locali', '') || ' ' ||
            COALESCE(NEW.properties->>'municipio', '') || ' ' ||
            COALESCE(NEW.properties->>'localidad', '') || ' ' ||
            COALESCE(NEW.properties->>'direccion', '')
          );
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    # Trigger
    op.execute("DROP TRIGGER IF EXISTS trg_layer_feature_search_vector ON layer_features")
    op.execute("""
        CREATE TRIGGER trg_layer_feature_search_vector
          BEFORE INSERT OR UPDATE ON layer_features
          FOR EACH ROW EXECUTE FUNCTION fn_update_layer_feature_search_vector()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_layer_feature_search_vector ON layer_features")
    op.execute("DROP FUNCTION IF EXISTS fn_update_layer_feature_search_vector()")
    op.execute("DROP INDEX IF EXISTS idx_layer_features_fts")
    op.drop_column('layer_features', 'search_vector')
    op.drop_column('layer_features', 'display_name')
    op.execute("""
        CREATE INDEX ix_layer_features_geom
        ON layer_features USING gist (geom)
    """)
