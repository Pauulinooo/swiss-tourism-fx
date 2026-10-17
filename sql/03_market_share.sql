-- Share of each origin market in a geography's nights, per calendar year.
-- Denominator = the 7 tracked markets (CH, DE, FR, IT, UK, US, CN), NOT all guests:
-- the source has no all-guests total, so every share (Swiss above all) is overstated.
-- n_months shows partial years (2026).
CREATE OR REPLACE VIEW market_share AS
SELECT
    level,
    geo,
    year(date) AS year,
    origin,
    SUM(nights) AS nights,
    COUNT(*) AS n_months,
    100.0 * SUM(nights)
        / SUM(SUM(nights)) OVER (PARTITION BY level, geo, year(date)) AS share_of_tracked_pct
FROM monthly_nights
GROUP BY level, geo, year(date), origin;
