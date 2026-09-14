-- Run individual statements in a SQLite editor, or with Python's sqlite3.
-- 1. Peak hours by mode and day type. Counts aggregate the month's matching days.
SELECT mode,day_type,hour,tap_in,
 RANK() OVER(PARTITION BY mode,month,day_type ORDER BY tap_in DESC) demand_rank
FROM v_hourly;

-- 2. Ten busiest train origin-destination pairs across all day types.
SELECT origin,destination,SUM(trips) trips
FROM od WHERE mode='Train'
GROUP BY origin,destination ORDER BY trips DESC LIMIT 10;

-- 3. Morning bus stop inflow/outflow imbalance (08:00-08:59).
SELECT v.node,s.description,SUM(tap_in) boardings,SUM(tap_out) alightings,
 SUM(tap_out)-SUM(tap_in) net_alightings
FROM volumes v LEFT JOIN stops s ON s.stop_code=v.node
WHERE v.mode='Bus' AND v.hour=8
GROUP BY v.node ORDER BY net_alightings DESC LIMIT 20;

-- 4. Service pressure with an explicit minimum sample threshold.
-- 100 is an analyst-selected filter, not proof of statistical representativeness.
SELECT * FROM v_service_pressure
WHERE known_load_observations>=100
ORDER BY limited_standing_share DESC;

-- 5. Raw hourly OD totals and published station volume reconciliation.
-- They need not agree if coverage/grain differs; inspect rather than force equality.
SELECT mode,month,SUM(trips) od_trips FROM od GROUP BY mode,month;
SELECT mode,month,SUM(tap_in) boardings FROM volumes GROUP BY mode,month;
