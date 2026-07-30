-- =====================================================
-- ESTACIONES DE EJEMPLO
-- =====================================================

INSERT INTO stations (

    station_code,
    mac_address,
    secret_key

)
VALUES

(
    'EST001-PALTAS',
    'AA:BB:CC:DD:EE:01',

    encode(
        gen_random_bytes(32),
        'hex'
    )
),

(
    'EST002-PALTAS',
    'AA:BB:CC:DD:EE:02',

    encode(
        gen_random_bytes(32),
        'hex'
    )
);