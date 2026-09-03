-- =====================================================
-- Extensión para generación de claves aleatorias
-- =====================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- =====================================================
-- Trigger genérico para updated_at
-- =====================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$

BEGIN

    NEW.updated_at = CURRENT_TIMESTAMP;

    RETURN NEW;

END;

$$ LANGUAGE plpgsql;


-- =====================================================
-- STATIONS
-- =====================================================

CREATE TABLE stations (

    id BIGSERIAL PRIMARY KEY,

    station_code VARCHAR(50) NOT NULL UNIQUE,
    
    name VARCHAR(100) NOT NULL,

    mac_address VARCHAR(17) NOT NULL UNIQUE,

    secret_key VARCHAR(128) NOT NULL,
    
    latitude DOUBLE PRECISION,

    longitude DOUBLE PRECISION,

    last_timestamp BIGINT NOT NULL DEFAULT 0,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE TRIGGER update_station_updated_at

BEFORE UPDATE ON stations

FOR EACH ROW

EXECUTE FUNCTION update_updated_at_column();


-- =====================================================
-- SENSORS
-- =====================================================

CREATE TABLE sensors (

    id BIGSERIAL PRIMARY KEY,

    sensor_code VARCHAR(100) NOT NULL UNIQUE,

    sensor_name VARCHAR(200) NOT NULL,

    unit VARCHAR(50),

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE TRIGGER update_sensor_updated_at

BEFORE UPDATE ON sensors

FOR EACH ROW

EXECUTE FUNCTION update_updated_at_column();


-- =====================================================
-- STATION_SENSORS
-- =====================================================

CREATE TABLE station_sensors (

    id BIGSERIAL PRIMARY KEY,

    station_id BIGINT NOT NULL,

    sensor_id BIGINT NOT NULL,

    enabled BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_station_sensors_station
        FOREIGN KEY (station_id)
        REFERENCES stations(id),

    CONSTRAINT fk_station_sensors_sensor
        FOREIGN KEY (sensor_id)
        REFERENCES sensors(id),

    CONSTRAINT uq_station_sensor
        UNIQUE (
            station_id,
            sensor_id
        )
);


CREATE TRIGGER update_station_sensors_updated_at

BEFORE UPDATE ON station_sensors

FOR EACH ROW

EXECUTE FUNCTION update_updated_at_column();


-- =====================================================
-- STATION_MEASUREMENTS
-- =====================================================

CREATE TABLE station_measurements (

    id BIGSERIAL PRIMARY KEY,

    station_id BIGINT NOT NULL,

    measurement_timestamp BIGINT NOT NULL,

    latitude NUMERIC(10,7),

    longitude NUMERIC(10,7),

    battery_level NUMERIC(5,2),

    received_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_station_measurements_station
        FOREIGN KEY (station_id)
        REFERENCES stations(id)
);


-- =====================================================
-- SENSOR_MEASUREMENTS
-- =====================================================

CREATE TABLE sensor_measurements (

    id BIGSERIAL PRIMARY KEY,

    measurement_id BIGINT NOT NULL,

    sensor_id BIGINT NOT NULL,

    measurement_timestamp BIGINT NOT NULL,

    sensor_value NUMERIC(12,4) NOT NULL,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_sensor_measurements_measurement
        FOREIGN KEY (measurement_id)
        REFERENCES station_measurements(id),

    CONSTRAINT fk_sensor_measurements_sensor
        FOREIGN KEY (sensor_id)
        REFERENCES sensors(id)
);

CREATE TABLE station_events (

    id BIGSERIAL PRIMARY KEY,

    station_id BIGINT NOT NULL,

    measurement_id BIGINT,

    event_timestamp BIGINT NOT NULL,

    event_type VARCHAR(100) NOT NULL,

    event_message TEXT,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_station_events_station
        FOREIGN KEY (station_id)
        REFERENCES stations(id),

    CONSTRAINT fk_station_events_measurement
        FOREIGN KEY (measurement_id)
        REFERENCES station_measurements(id)
);

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    firstname VARCHAR(255),
    father_lastname VARCHAR(255),
    mother_lastname VARCHAR(255),
    document_of_identity VARCHAR(255),
    cellphone VARCHAR(20),
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    verification_token VARCHAR(255),
    reset_password_token VARCHAR(255),
    reset_password_token_expiry TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

