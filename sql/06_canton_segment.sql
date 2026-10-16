-- Canton segment from winter dependence: Dec-Mar nights / all nights, pooled over 2010-2019.
-- Calendar years (Dec counts with its own year); pre-covid decade so the segment reflects normal seasons.
-- Labels describe seasonality only, not the type of tourism (ski vs city): the metric cannot tell them apart.
-- Thresholds: winter_peak > 0.40, balanced 0.30-0.40, summer_or_flat < 0.30.
-- Note: Geneva lands just inside "balanced" (busy winter months in the city, not snow).
CREATE OR REPLACE VIEW canton_segment AS
WITH totals AS (
    SELECT
        geo,
        SUM(nights) FILTER (WHERE month(date) IN (12, 1, 2, 3)) AS winter_nights,
        SUM(nights) AS annual_nights
    FROM monthly_nights
    WHERE level = 'canton'
      AND year(date) BETWEEN 2010 AND 2019
    GROUP BY geo
)
SELECT
    geo,
    winter_nights,
    annual_nights,
    winter_nights / annual_nights AS winter_share,
    CASE
        WHEN winter_nights / annual_nights > 0.40 THEN 'winter_peak'
        WHEN winter_nights / annual_nights >= 0.30 THEN 'balanced'
        ELSE 'summer_or_flat'
    END AS segment
FROM totals;
