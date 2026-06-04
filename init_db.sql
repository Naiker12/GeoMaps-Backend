-- Habilitar extensión PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;

-- Crear Enums
CREATE TYPE user_role AS ENUM ('admin', 'user');
CREATE TYPE project_status AS ENUM ('planning', 'in_progress', 'completed', 'cancelled');
CREATE TYPE internal_status AS ENUM ('activo', 'archivado');
CREATE TYPE currency_type AS ENUM ('COP', 'USD', 'EUR');

-- Tabla de Usuarios
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    role user_role DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla de Proyectos
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(150) NOT NULL,
    description TEXT NOT NULL,
    status project_status DEFAULT 'planning',
    developer_company VARCHAR(255),
    manager_name VARCHAR(255),
    contact_phone VARCHAR(50),
    contact_email VARCHAR(255),
    
    latitude NUMERIC(10,8),
    longitude NUMERIC(11,8),
    geometry GEOMETRY(POLYGON, 4326),
    
    external_location_url VARCHAR(500),
    
    total_area NUMERIC,
    built_area NUMERIC,
    levels INTEGER,
    total_units INTEGER,
    lots INTEGER,
    max_height NUMERIC,
    
    progress_percentage INTEGER CHECK (progress_percentage >= 0 AND progress_percentage <= 100) DEFAULT 0,
    estimated_delivery_date DATE,
    
    custom_metrics JSONB,
    
    estimated_investment NUMERIC,
    average_unit_price NUMERIC,
    currency currency_type DEFAULT 'COP',
    
    map_color VARCHAR(50),
    map_opacity INTEGER CHECK (map_opacity >= 0 AND map_opacity <= 100) DEFAULT 100,
    show_label_on_map BOOLEAN DEFAULT TRUE,
    custom_label_text VARCHAR(255),
    
    is_featured BOOLEAN DEFAULT FALSE,
    is_publicly_visible BOOLEAN DEFAULT TRUE,
    display_priority INTEGER DEFAULT 0,
    internal_status internal_status DEFAULT 'activo',
    
    enable_3d_visualizer BOOLEAN DEFAULT FALSE,
    shapefile_url VARCHAR(500),
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Imágenes del Proyecto
CREATE TABLE IF NOT EXISTS project_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    url VARCHAR(500) NOT NULL,
    order_index INTEGER DEFAULT 0
);

-- Modelos 3D del Proyecto
CREATE TABLE IF NOT EXISTS project_models_3d (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    url VARCHAR(500) NOT NULL
);

-- Índices para Rendimiento
CREATE INDEX IF NOT EXISTS idx_projects_geometry ON projects USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects (status);
CREATE INDEX IF NOT EXISTS idx_projects_internal_status ON projects (internal_status);
CREATE INDEX IF NOT EXISTS idx_projects_coords ON projects (latitude, longitude);

-- No se insertan usuarios por defecto.
-- Crea administradores mediante el flujo seguro de la aplicacion o una migracion controlada.
