-- =====================================================
-- Extensión para generación de claves aleatorias
-- =====================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- =====================================================
-- Tabla de estaciones meteorológicas
-- =====================================================

CREATE TABLE stations (

    -- ID interno de PostgreSQL
    id BIGSERIAL PRIMARY KEY,

    -- Identificador público de la estación
    station_code VARCHAR(50) NOT NULL UNIQUE,

    -- MAC del ESP32
    mac_address VARCHAR(17) NOT NULL UNIQUE,

    -- Clave pública para identificar la estación
    api_key VARCHAR(64) NOT NULL UNIQUE,

    -- Clave secreta usada para HMAC-SHA256
    secret_key VARCHAR(128) NOT NULL,

    -- Último timestamp aceptado (anti replay attack)
    last_timestamp BIGINT NOT NULL DEFAULT 0,

    -- Auditoría
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- =====================================================
-- Trigger para actualizar updated_at automáticamente
-- =====================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$

BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;

$$ LANGUAGE plpgsql;


CREATE TRIGGER update_station_updated_at
BEFORE UPDATE ON stations
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();