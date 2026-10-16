-- Monthly overnight stays by geography and origin market, with a covid flag.
-- Covid months stay in the data (for plots) but are flagged so FX estimates can exclude them.
-- "Total" across origins = the 7 tracked markets only (no all-guests total in the source).
CREATE OR REPLACE VIEW monthly_nights AS
SELECT
    date,
    level,
    geo,
    origin,
    value AS nights,
    date BETWEEN DATE '2020-03-01' AND DATE '2021-12-01' AS is_covid
FROM tourism
WHERE indicator = 'nights';
