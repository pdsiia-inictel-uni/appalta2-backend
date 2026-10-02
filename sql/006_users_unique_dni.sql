-- El DNI (document_of_identity) solo puede pertenecer a un usuario.
-- Para bases creadas antes de este cambio; las nuevas ya lo traen en 001_schema.sql.
--
-- Antes de aplicarla, verificar que no haya DNI repetidos (la restricción fallaría):
--   SELECT document_of_identity, count(*) FROM users GROUP BY 1 HAVING count(*) > 1;

BEGIN;

ALTER TABLE users
    ADD CONSTRAINT users_document_of_identity_key UNIQUE (document_of_identity);

COMMIT;
