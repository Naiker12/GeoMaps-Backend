from app.infrastructure.database.session import engine, Base
from app.domain.models.user import User

def create_tables():
    print("Creando tablas de Usuarios y Roles en Supabase...")
    # Solo creamos lo relacionado con User ya que Proyecto y Predio no se usarán por ahora
    User.__table__.create(bind=engine, checkfirst=True)
    print("¡Tabla de usuarios preparada!")

if __name__ == "__main__":
    create_tables()
