-- Average length of stay (nights per arrival) by commune, origin and month.
-- Commune level only: the canton table has no arrivals.
-- Germany vs Switzerland only: other markets are too small per commune (see ROADMAP notes).
CREATE OR REPLACE VIEW length_of_stay AS
SELECT
    n.date,
    n.geo,
    n.origin,
    n.value AS nights,
    a.value AS arrivals,
    CASE WHEN a.value > 0 THEN n.value / a.value END AS avg_stay_nights,
    n.date BETWEEN DATE '2020-03-01' AND DATE '2021-12-01' AS is_covid
FROM tourism AS n
JOIN tourism AS a
    ON  a.level  = n.level
    AND a.geo    = n.geo
    AND a.origin = n.origin
    AND a.date   = n.date
    AND a.indicator = 'arrivals'
WHERE n.indicator = 'nights'
  AND n.level = 'commune'
  AND n.origin IN ('Switzerland', 'Germany');
