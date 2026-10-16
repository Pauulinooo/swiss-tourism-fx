-- Year-over-year % change: each month vs the same month one year earlier.
-- Joined on date - 12 months (not LAG) because suppressed months have no row,
-- and LAG would then silently compare against the wrong month.
CREATE OR REPLACE VIEW yoy_change AS
SELECT
    cur.date,
    cur.level,
    cur.geo,
    cur.origin,
    cur.nights,
    prev.nights AS nights_prev_year,
    CASE WHEN prev.nights > 0
         THEN 100.0 * (cur.nights / prev.nights - 1) END AS yoy_pct,
    cur.is_covid
FROM monthly_nights AS cur
LEFT JOIN monthly_nights AS prev
    ON  prev.level  = cur.level
    AND prev.geo    = cur.geo
    AND prev.origin = cur.origin
    AND prev.date   = CAST(cur.date - INTERVAL 1 YEAR AS DATE);
