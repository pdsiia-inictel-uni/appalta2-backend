-- =====================================================
-- Crear mediciones de estaciones
-- =====================================================

CREATE TABLE station_measurements (

    id BIGSERIAL PRIMARY KEY,

    station_id BIGINT NOT NULL,

    measurement_timestamp BIGINT NOT NULL,

    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,

    battery_level NUMERIC(5,2),

    ambient_temperature NUMERIC(6,2),
    ambient_humidity NUMERIC(6,2),
    atmospheric_pressure NUMERIC(8,2),

    soil_temperature NUMERIC(6,2),
    soil_moisture NUMERIC(5,2),
    soil_ph NUMERIC(4,2),

    received_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_station_measurements_station
        FOREIGN KEY (station_id)
        REFERENCES stations(id)
);