INSERT INTO stations
(
    station_id,
    mac_address,
    api_key,
    secret_key
)
VALUES
(
    'EST001',
    '24:6F:28:AA:11:01',
    encode(gen_random_bytes(32), 'hex'),
    encode(gen_random_bytes(64), 'hex')
);


INSERT INTO stations
(
    station_id,
    mac_address,
    api_key,
    secret_key
)
VALUES
(
    'EST002',
    '24:6F:28:AA:11:02',
    encode(gen_random_bytes(32), 'hex'),
    encode(gen_random_bytes(64), 'hex')
);