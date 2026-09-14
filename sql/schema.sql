PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY, collected_at TEXT NOT NULL, dataset TEXT NOT NULL,
 scope TEXT NOT NULL, status TEXT NOT NULL, rows_loaded INTEGER NOT NULL DEFAULT 0, error TEXT);
CREATE INDEX IF NOT EXISTS ix_runs ON runs(dataset,scope,id);
CREATE TABLE IF NOT EXISTS stops (
 stop_code TEXT PRIMARY KEY, description TEXT, road_name TEXT, latitude REAL, longitude REAL);
CREATE TABLE IF NOT EXISTS routes (
 service TEXT, direction INTEGER, sequence INTEGER, stop_code TEXT, distance_km REAL,
 PRIMARY KEY(service,direction,sequence));
CREATE TABLE IF NOT EXISTS arrivals (
 run_id INTEGER REFERENCES runs(id), stop_code TEXT, service TEXT, bus_rank INTEGER,
 estimated_arrival TEXT, wait_minutes REAL, latitude REAL, longitude REAL,
 load TEXT, monitored INTEGER, bus_type TEXT,
 PRIMARY KEY(run_id,stop_code,service,bus_rank));
CREATE TABLE IF NOT EXISTS crowd (
 run_id INTEGER REFERENCES runs(id), line TEXT, station TEXT, start_time TEXT, end_time TEXT,
 crowd_level TEXT, PRIMARY KEY(run_id,line,station,start_time));
CREATE TABLE IF NOT EXISTS volumes (
 mode TEXT, month TEXT, day_type TEXT, hour INTEGER CHECK(hour BETWEEN 0 AND 23),
 node TEXT, tap_in INTEGER CHECK(tap_in>=0), tap_out INTEGER CHECK(tap_out>=0),
 PRIMARY KEY(mode,month,day_type,hour,node));
CREATE TABLE IF NOT EXISTS od (
 mode TEXT, month TEXT, day_type TEXT, hour INTEGER CHECK(hour BETWEEN 0 AND 23),
 origin TEXT, destination TEXT, trips INTEGER CHECK(trips>=0),
 PRIMARY KEY(mode,month,day_type,hour,origin,destination));
CREATE TABLE IF NOT EXISTS annual (
 year INTEGER, mode TEXT, daily_ridership INTEGER, PRIMARY KEY(year,mode));
CREATE VIEW IF NOT EXISTS v_arrivals AS
SELECT a.*, r.collected_at, s.description, s.road_name,
 CASE WHEN a.load='LSD' THEN 1 WHEN a.load IN ('SEA','SDA') THEN 0 END limited_standing
FROM arrivals a JOIN runs r ON r.id=a.run_id LEFT JOIN stops s USING(stop_code);
-- Latest attempt per stop, including failed/empty attempts, prevents stale carry-forward.
CREATE VIEW IF NOT EXISTS v_latest_arrivals AS
SELECT a.*, CASE WHEN (julianday('now')-julianday(collected_at))*86400 <=120
 THEN 'Recent snapshot' ELSE 'Historical snapshot' END freshness
FROM v_arrivals a WHERE run_id=(SELECT MAX(id) FROM runs WHERE dataset='arrivals' AND scope=a.stop_code);
CREATE VIEW IF NOT EXISTS v_latest_crowd AS
SELECT c.*,r.collected_at FROM crowd c JOIN runs r ON r.id=c.run_id
WHERE c.run_id=(SELECT MAX(id) FROM runs WHERE dataset='crowd' AND scope=c.line);
CREATE VIEW IF NOT EXISTS v_hourly AS
SELECT mode,month,day_type,hour,SUM(tap_in) tap_in,SUM(tap_out) tap_out
FROM volumes GROUP BY mode,month,day_type,hour;
CREATE VIEW IF NOT EXISTS v_nodes AS
SELECT v.mode,v.month,v.day_type,v.node,COALESCE(s.description,v.node) node_name,
 s.latitude,s.longitude,SUM(v.tap_in) tap_in,SUM(v.tap_out) tap_out
FROM volumes v LEFT JOIN stops s ON v.mode='Bus' AND s.stop_code=v.node
GROUP BY v.mode,v.month,v.day_type,v.node;
CREATE VIEW IF NOT EXISTS v_od_pairs AS
SELECT mode,month,day_type,origin,destination,SUM(trips) trips
FROM od GROUP BY mode,month,day_type,origin,destination;
-- Poll-weighted service/stop indicators, not unique vehicle or capacity utilisation.
CREATE VIEW IF NOT EXISTS v_service_pressure AS
SELECT a.stop_code,a.service,COUNT(*) observations,
 AVG(CASE WHEN a.load='LSD' THEN 1.0 WHEN a.load IN ('SEA','SDA') THEN 0.0 END) limited_standing_share,
 SUM(CASE WHEN a.load IN ('SEA','SDA','LSD') THEN 1 ELSE 0 END) known_load_observations,
 AVG(CASE WHEN a.wait_minutes>=0 THEN a.wait_minutes END) mean_predicted_wait_minutes
FROM arrivals a WHERE bus_rank=1 GROUP BY a.stop_code,a.service;
