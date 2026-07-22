CREATE INDEX idx_measurements_station
ON station_measurements(station_id);


CREATE INDEX idx_measurements_timestamp
ON station_measurements(measurement_timestamp);


CREATE INDEX idx_measurements_station_timestamp
ON station_measurements(
    station_id,
    measurement_timestamp
);