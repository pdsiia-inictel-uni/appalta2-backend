-- =====================================================
-- STATIONS
-- =====================================================

CREATE INDEX idx_stations_station_code
ON stations(station_code);

CREATE INDEX idx_stations_mac_address
ON stations(mac_address);


-- =====================================================
-- STATION_SENSORS
-- =====================================================

CREATE INDEX idx_station_sensors_station
ON station_sensors(station_id);

CREATE INDEX idx_station_sensors_sensor
ON station_sensors(sensor_id);


-- =====================================================
-- STATION_MEASUREMENTS
-- =====================================================

CREATE INDEX idx_station_measurements_station
ON station_measurements(station_id);

CREATE INDEX idx_station_measurements_timestamp
ON station_measurements(measurement_timestamp);

CREATE INDEX idx_station_measurements_station_timestamp
ON station_measurements(
    station_id,
    measurement_timestamp DESC
);


-- =====================================================
-- SENSOR_MEASUREMENTS
-- =====================================================

CREATE INDEX idx_sensor_measurements_measurement
ON sensor_measurements(measurement_id);

CREATE INDEX idx_sensor_measurements_sensor
ON sensor_measurements(sensor_id);

CREATE INDEX idx_sensor_measurements_timestamp
ON sensor_measurements(measurement_timestamp);

CREATE INDEX idx_sensor_measurements_sensor_timestamp
ON sensor_measurements(
    sensor_id,
    measurement_timestamp DESC
);
-- Índices
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_cellphone ON users(cellphone);