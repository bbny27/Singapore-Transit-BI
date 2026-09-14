DROP VIEW IF EXISTS v_place;
CREATE VIEW v_place AS
SELECT 'Bus:'||stop_code place_key,'Bus' mode,stop_code node,description node_name,
 description||' ['||stop_code||']' place_label,road_name,latitude,longitude,
 'LTA BusStops' reference_source FROM stops
UNION ALL
SELECT 'Bus:'||node,'Bus',node,'Unresolved bus stop '||node,'Unresolved bus stop ['||node||']',NULL,NULL,NULL,'Missing from supplied BusStops reference'
FROM (SELECT DISTINCT node FROM volumes WHERE mode='Bus' AND node NOT IN (SELECT stop_code FROM stops))
UNION ALL
SELECT 'Train:'||node,'Train',node,
 COALESCE(n.name,'Unresolved station '||node),COALESCE(n.name,'Unresolved station')||' ['||node||']',
 NULL,NULL,NULL,COALESCE(n.source,'Name not resolved')
FROM (SELECT DISTINCT node FROM volumes WHERE mode='Train') v
LEFT JOIN rail_names n ON n.code=CASE WHEN instr(v.node,'/')>0 THEN substr(v.node,1,instr(v.node,'/')-1) ELSE v.node END;
DROP VIEW IF EXISTS v_demand;
CREATE VIEW v_demand AS
SELECT v.mode||':'||v.node place_key,v.month,v.month||'|'||v.day_type period_key,v.day_type,
 v.hour,v.tap_in,v.tap_out,c.days calendar_days,
 CAST(v.tap_in AS REAL)/c.days daily_boardings,CAST(v.tap_out AS REAL)/c.days daily_alightings,
 CAST(v.tap_in-v.tap_out AS REAL)/NULLIF(v.tap_in+v.tap_out,0) net_flow,
 CASE WHEN v.hour IS NULL THEN 'Unknown hour' ELSE printf('%02d:00',v.hour) END hour_label
FROM volumes v LEFT JOIN calendar_days c USING(month,day_type);
DROP VIEW IF EXISTS v_node_metrics;
CREATE VIEW v_node_metrics AS
WITH n AS (
 SELECT v.mode,v.month,v.node,
 SUM(CASE WHEN day_type='WEEKDAY' THEN tap_in END) wd_boardings,
 SUM(CASE WHEN day_type='WEEKENDS/HOLIDAY' THEN tap_in END) we_boardings,
 SUM(CASE WHEN day_type='WEEKDAY' AND hour BETWEEN 7 AND 9 THEN tap_in ELSE 0 END) am_in,
 SUM(CASE WHEN day_type='WEEKDAY' AND hour BETWEEN 7 AND 9 THEN tap_out ELSE 0 END) am_out,
 SUM(CASE WHEN day_type='WEEKDAY' AND hour BETWEEN 17 AND 19 THEN tap_in ELSE 0 END) pm_in,
 SUM(CASE WHEN day_type='WEEKDAY' AND hour BETWEEN 17 AND 19 THEN tap_out ELSE 0 END) pm_out,
 SUM(CASE WHEN day_type='WEEKDAY' AND hour IS NOT NULL THEN tap_in ELSE 0 END) known_hour_boardings,
 SUM(CASE WHEN day_type='WEEKDAY' AND hour IS NULL THEN tap_in+tap_out ELSE 0 END) unknown_hour_taps
 FROM volumes v GROUP BY mode,month,node
), rates AS (
 SELECT n.*,n.mode||':'||n.node place_key,p.node_name,p.place_label,p.latitude,p.longitude,
 CAST(wd_boardings AS REAL)/wd.days weekday_daily,
 CAST(we_boardings AS REAL)/we.days weekend_daily,
 (CAST(we_boardings AS REAL)/we.days)/NULLIF(CAST(wd_boardings AS REAL)/wd.days,0) weekend_uplift,
 CAST(am_in-am_out AS REAL)/NULLIF(am_in+am_out,0) am_net,
 CAST(pm_in-pm_out AS REAL)/NULLIF(pm_in+pm_out,0) pm_net,
 CAST(am_in+pm_in AS REAL)/NULLIF(known_hour_boardings,0) peak_share,
 CASE WHEN wd.days IS NULL OR we.days IS NULL THEN 'Calendar needs verification' ELSE 'Verified holiday calendar' END calendar_status
 FROM n LEFT JOIN v_place p ON p.place_key=n.mode||':'||n.node
 LEFT JOIN calendar_days wd ON wd.month=n.month AND wd.day_type='WEEKDAY'
 LEFT JOIN calendar_days we ON we.month=n.month AND we.day_type='WEEKENDS/HOLIDAY'
)
SELECT *, (am_net-pm_net)/2 reversal_score,
 CASE WHEN am_in+am_out<100 OR pm_in+pm_out<100 THEN 'Insufficient peak taps'
      WHEN am_net>=0.2 AND pm_net<=-0.2 THEN 'Residential-like origin'
      WHEN am_net<=-0.2 AND pm_net>=0.2 THEN 'Employment-like destination'
      WHEN peak_share<0.4 THEN 'Spread through the day' ELSE 'Mixed pattern' END functional_profile
FROM rates;
DROP VIEW IF EXISTS v_flow;
CREATE VIEW v_flow AS
SELECT o.mode,o.month,o.month||'|'||o.day_type period_key,o.day_type,
 o.mode||':'||origin origin_key,o.mode||':'||destination destination_key,
 COALESCE(p.place_label,origin) origin_name,COALESCE(d.place_label,destination) destination_name,
 SUM(trips) trips,SUM(CASE WHEN hour BETWEEN 7 AND 9 THEN trips ELSE 0 END) am_trips,
 SUM(CASE WHEN hour BETWEEN 17 AND 19 THEN trips ELSE 0 END) pm_trips,
 SUM(CASE WHEN hour IS NULL THEN trips ELSE 0 END) unknown_hour_trips,
 CAST(SUM(trips) AS REAL)/c.days daily_trips,
 COALESCE(i.scope,'Unknown import scope') od_scope
FROM od o LEFT JOIN v_place p ON p.place_key=o.mode||':'||o.origin
LEFT JOIN v_place d ON d.place_key=o.mode||':'||o.destination
LEFT JOIN calendar_days c USING(month,day_type)
LEFT JOIN monthly_imports i ON i.dataset='OD'||o.mode AND i.month=o.month
GROUP BY o.mode,o.month,o.day_type,o.origin,o.destination;
DROP VIEW IF EXISTS v_flow_balance;
CREATE VIEW v_flow_balance AS
SELECT f.*,COALESCE(r.am_trips,0) reverse_am_trips,COALESCE(r.pm_trips,0) reverse_pm_trips,
 CAST(f.am_trips-COALESCE(r.am_trips,0) AS REAL)/NULLIF(f.am_trips+COALESCE(r.am_trips,0),0) am_direction_balance,
 CASE WHEN f.am_trips>COALESCE(r.am_trips,0) AND COALESCE(r.pm_trips,0)>f.pm_trips THEN 'AM out / PM return' ELSE 'Other direction pattern' END reversal_label
FROM v_flow f LEFT JOIN v_flow r ON f.month=r.month AND f.day_type=r.day_type AND f.origin_key=r.destination_key AND f.destination_key=r.origin_key;
DROP VIEW IF EXISTS v_poll_samples;
CREATE VIEW v_poll_samples AS
SELECT a.*,r.collected_at,date(r.collected_at,'+8 hours') sg_date,
 CAST(strftime('%H',r.collected_at,'+8 hours') AS INTEGER) sg_hour,
 CASE WHEN strftime('%w',r.collected_at,'+8 hours') IN ('0','6') THEN 'Weekend' ELSE 'Weekday (holidays not separated)' END day_group,
 p.place_label stop_name,p.latitude stop_latitude,p.longitude stop_longitude,
 CASE WHEN a.load IN ('SDA','LSD') THEN 1 WHEN a.load='SEA' THEN 0 END standing,
 CASE WHEN a.load='LSD' THEN 1 WHEN a.load IN ('SEA','SDA') THEN 0 END limited,
 CASE WHEN a.monitored=1 AND b.monitored=1 AND b.wait_minutes>=a.wait_minutes AND a.wait_minutes>=0
      THEN b.wait_minutes-a.wait_minutes END predicted_gap_minutes,
 CASE WHEN a.monitored=1 AND a.wait_minutes>=0 THEN a.wait_minutes END monitored_wait
FROM arrivals a JOIN runs r ON r.id=a.run_id
LEFT JOIN arrivals b ON b.run_id=a.run_id AND b.stop_code=a.stop_code AND b.service=a.service AND b.bus_rank=2
LEFT JOIN v_place p ON p.place_key='Bus:'||a.stop_code
WHERE a.bus_rank=1 AND r.status='ok';
DROP VIEW IF EXISTS v_collection;
CREATE VIEW v_collection AS
SELECT dataset,scope,count(*) attempts,SUM(status='ok') successes,
 SUM(status='failed') failures,SUM(status='ok' AND rows_loaded=0) empty_responses,
 MIN(collected_at) first_seen,MAX(collected_at) last_seen,
 CAST(SUM(status='ok') AS REAL)/COUNT(*) success_share
FROM runs GROUP BY dataset,scope;
DROP VIEW IF EXISTS v_releases;
CREATE VIEW v_releases AS
SELECT r.release_id,r.dataset,r.month,r.archived_at,r.source_kind,r.sha256,length(r.zip_bytes) archived_bytes,
 CASE WHEN i.release_id=r.release_id THEN 'Current imported version' ELSE 'Older archived version' END version_status,
 i.scope FROM releases r LEFT JOIN monthly_imports i ON i.dataset=r.dataset AND i.month=r.month;
