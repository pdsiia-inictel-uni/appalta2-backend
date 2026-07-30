-- =====================================================
-- SENSORES DE EST001
-- =====================================================

INSERT INTO station_sensors (

    station_id,
    sensor_id

)
SELECT

    st.id,
    s.id

FROM stations st

CROSS JOIN sensors s

WHERE

    st.station_code = 'EST001-PALTAS'

AND

    s.sensor_code IN (

        'ambient_temperature',
        'ambient_humidity',
        'atmospheric_pressure',
        'soil_temperature',
        'soil_moisture',
        'soil_ph'

    );


-- =====================================================
-- SENSORES DE EST002
-- =====================================================

INSERT INTO station_sensors (

    station_id,
    sensor_id

)
SELECT

    st.id,
    s.id

FROM stations st

CROSS JOIN sensors s

WHERE

    st.station_code = 'EST002-PALTAS'

AND

    s.sensor_code IN (

        'ambient_temperature',
        'ambient_humidity',
        'atmospheric_pressure',
        'soil_temperature',
        'soil_moisture',
        'soil_ph'

    );