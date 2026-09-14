-- Additive migration: old fact tables and existing data are preserved.
CREATE TABLE IF NOT EXISTS raw_payloads (
 run_id INTEGER PRIMARY KEY REFERENCES runs(id), sha256 TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS releases (
 release_id INTEGER PRIMARY KEY, dataset TEXT NOT NULL, month TEXT NOT NULL,
 sha256 TEXT NOT NULL, archived_at TEXT NOT NULL, source_kind TEXT NOT NULL,
 zip_bytes BLOB, UNIQUE(dataset,month,sha256));
CREATE TABLE IF NOT EXISTS monthly_imports (
 dataset TEXT, month TEXT, release_id INTEGER REFERENCES releases(release_id),
 imported_at TEXT, scope TEXT, rows_loaded INTEGER, PRIMARY KEY(dataset,month));
CREATE TABLE IF NOT EXISTS rail_names(code TEXT PRIMARY KEY,name TEXT,source TEXT);
CREATE TABLE IF NOT EXISTS calendar_days (
 month TEXT,day_type TEXT,days INTEGER,calendar_status TEXT,PRIMARY KEY(month,day_type));
CREATE TABLE IF NOT EXISTS scheduler_state (job TEXT PRIMARY KEY, last_attempt TEXT);
CREATE INDEX IF NOT EXISTS ix_volume_node ON volumes(mode,month,node,day_type,hour);
CREATE INDEX IF NOT EXISTS ix_arrival_group ON arrivals(stop_code,service,run_id,bus_rank);
CREATE INDEX IF NOT EXISTS ix_od_origin ON od(mode,month,origin,destination);
CREATE INDEX IF NOT EXISTS ix_routes_stop ON routes(stop_code,service);
