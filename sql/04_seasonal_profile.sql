-- Typical seasonal profile: average share of annual nights falling in each calendar month.
-- 2013-2019 only: common window for cantons and communes, before covid.
-- Only complete geo-years (12 months) count, so a missing month cannot distort the shares.
CREATE OR REPLACE VIEW seasonal_profile AS
WITH geo_month AS (
    SELECT level, geo, date, SUM(nights) AS nights
    FROM monthly_nights
    WHERE year(date) BETWEEN 2013 AND 2019
    GROUP BY level, geo, date
),
full_years AS (
    SELECT level, geo, year(date) AS year
    FROM geo_month
    GROUP BY level, geo, year(date)
    HAVING COUNT(*) = 12
),
monthly_share AS (
    SELECT
        g.level,
        g.geo,
        month(g.date) AS month,
        g.nights / SUM(g.nights) OVER (PARTITION BY g.level, g.geo, year(g.date)) AS share
    FROM geo_month AS g
    JOIN full_years AS f
        ON f.level = g.level AND f.geo = g.geo AND f.year = year(g.date)
)
SELECT
    level,
    geo,
    month,
    100.0 * AVG(share) AS avg_share_pct,
    COUNT(*) AS n_years
FROM monthly_share
GROUP BY level, geo, month;
