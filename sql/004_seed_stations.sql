-- =====================================================
-- ESTACIONES DE EJEMPLO
-- =====================================================

INSERT INTO stations (

    station_code,
    name,
    mac_address,
    secret_key

)
VALUES

(
    'EST001-PALTAS',
    'ESTACIÓN 1',
    'AA:BB:CC:DD:EE:01',
    encode(gen_random_bytes(32), 'hex')
),

(
    'EST002-PALTAS',
    'ESTACIÓN 2',
    'AA:BB:CC:DD:EE:02',
    encode(gen_random_bytes(32), 'hex')
),

(
    'EST003-PALTAS',
    'ESTACIÓN 3',
    'AA:BB:CC:DD:EE:03',
    encode(gen_random_bytes(32), 'hex')
);