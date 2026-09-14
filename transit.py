"""LTA -> SQLite -> SQL marts -> Power BI. Python 3.11+, standard library ETL."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import getpass
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
SGT = timezone(timedelta(hours=8))
BASE = 'https://datamall2.mytransport.sg/ltaodataservice/'

def now():
    return datetime.now(SGT).isoformat(timespec='seconds')

def config():
    return json.loads((ROOT / 'config.json').read_text())

def connect():
    (ROOT / 'data').mkdir(exist_ok=True)
    db = sqlite3.connect(ROOT / 'data/transit.sqlite', timeout=30)
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript((ROOT / 'sql/schema.sql').read_text())
    source=ROOT/'data/reference/annual.csv'
    if source.exists() and db.execute('SELECT COUNT(*) FROM annual').fetchone()[0]==0:
        with source.open() as stream, db:
            db.executemany('INSERT INTO annual VALUES(?,?,?)', [(int(r['year']),r['mode'],int(r['daily_ridership'])) for r in csv.DictReader(stream)])
    import warehouse
    warehouse.initialize(db, ROOT)
    warehouse.preserve_legacy(db, ROOT, now())
    return db

def account_key():
    key = os.getenv('LTA_ACCOUNT_KEY', '').strip()
    if not key and (ROOT / '.env').exists():
        for line in (ROOT / '.env').read_text().splitlines():
            if line.startswith('LTA_ACCOUNT_KEY='):
                key = line.split('=', 1)[1].strip().strip('\"\'')
    if not key:
        raise RuntimeError('No key configured. Run: python transit.py configure')
    return key

def fetch(url, headers=None, destination=None):
    """Bounded retries; do not log headers, credentials, or signed download URLs."""
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(request, timeout=90) as response:
                if destination:
                    temp = destination.with_suffix('.part')
                    total = 0
                    with temp.open('wb') as out:
                        while chunk := response.read(1024 * 1024):
                            total += len(chunk)
                            if total > 512 * 1024 * 1024:
                                raise RuntimeError('Download exceeds the 512 MiB safety limit.')
                            out.write(chunk)
                    temp.replace(destination)
                    return destination
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt == 2:
                raise RuntimeError(f'HTTP {exc.code}; verify account access and endpoint.') from None
            delay = exc.headers.get('Retry-After','')
            time.sleep(min(60, int(delay)) if delay.isdigit() else 2 ** (attempt+1))
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise RuntimeError('Network request failed after 3 attempts.') from None
            time.sleep(2 ** (attempt+1))

def api(endpoint, **params):
    url = BASE + endpoint + ('?' + urllib.parse.urlencode(params) if params else '')
    body = fetch(url, {'AccountKey': account_key(), 'accept':'application/json'})
    result = json.loads(body)
    if not isinstance(result, dict):
        raise ValueError('Expected an LTA JSON object.')
    return result

def paged(endpoint):
    rows = []
    for offset in range(0,100000,500):
        page = api(endpoint, **{'$skip':offset})['value']
        rows.extend(page)
        if len(page)<500:
            return rows
    raise RuntimeError('Pagination limit reached; refusing partial reference data.')

def begin(db, dataset, scope):
    with db:
        return db.execute('INSERT INTO runs(collected_at,dataset,scope,status) VALUES(?,?,?,?)',
                          (now(),dataset,scope,'running')).lastrowid

def end(db, run_id, count=0, error=None):
    with db:
        db.execute('UPDATE runs SET status=?,rows_loaded=?,error=? WHERE id=?',
                   ('failed' if error else 'ok',count,error,run_id))

def raw_json(db, run_id, payload):
    import warehouse
    warehouse.save_payload(db, run_id, payload)
    folder=ROOT/'data/raw';folder.mkdir(parents=True,exist_ok=True)
    (folder/f'{run_id}.json').write_text(json.dumps(payload),encoding='utf-8')

def reference(db):
    for dataset in ('BusStops','BusRoutes'):
        run_id=begin(db,dataset,'all')
        try:
            rows=paged(dataset)
            if not rows: raise ValueError('Reference data unexpectedly empty')
            raw_json(db,run_id,rows)
            with db:
                if dataset=='BusStops':
                    db.execute('DELETE FROM stops')
                    db.executemany('INSERT INTO stops VALUES(?,?,?,?,?)',
                        [(r['BusStopCode'],r['Description'],r['RoadName'],r['Latitude'],r['Longitude']) for r in rows])
                else:
                    db.execute('DELETE FROM routes')
                    db.executemany('INSERT INTO routes VALUES(?,?,?,?,?)',
                        [(r['ServiceNo'],r['Direction'],r['StopSequence'],r['BusStopCode'],r['Distance']) for r in rows])
            end(db,run_id,len(rows));print(dataset,len(rows),flush=True)
        except Exception as exc:
            end(db,run_id,error=str(exc));raise

def arrival_rows(payload, run_id, stop, collected_at):
    if 'Services' not in payload: raise ValueError('Missing Services in arrival response')
    stamp=datetime.fromisoformat(collected_at)
    rows=[]
    for service in payload['Services']:
        for rank, name in enumerate(('NextBus','NextBus2','NextBus3'),1):
            bus=service.get(name) or {}
            eta=bus.get('EstimatedArrival')
            if not eta: continue
            wait=(datetime.fromisoformat(eta)-stamp).total_seconds()/60
            lat=float(bus.get('Latitude') or 0);lon=float(bus.get('Longitude') or 0)
            if not (1.1<=lat<=1.6 and 103.5<=lon<=104.2): lat=lon=None
            monitored=bus.get('Monitored')
            rows.append((run_id,stop,service['ServiceNo'],rank,eta,wait,lat,lon,
                         bus.get('Load') or None,int(monitored) if str(monitored) in ('0','1') else None,bus.get('Type')))
    return rows

def live(db, with_arrivals=True, with_crowd=True):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    cfg=config(); failures=0
    jobs=[]
    for dataset, scopes in [('arrivals',cfg['bus_stops'] if with_arrivals else []),
                            ('crowd',cfg['train_lines'] if with_crowd else [])]:
        for scope in scopes:
            run_id=begin(db,dataset,scope)
            stamp=db.execute('SELECT collected_at FROM runs WHERE id=?',(run_id,)).fetchone()[0]
            jobs.append((dataset,scope,run_id,stamp))
    def request(job):
        dataset,scope,_,_=job
        return api('v3/BusArrival',BusStopCode=scope) if dataset=='arrivals' else api('PCDRealTime',TrainLine=scope)
    # Only network requests run in worker threads. All database writes stay here.
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending={pool.submit(request,job):job for job in jobs}
        for future in as_completed(pending):
            dataset,scope,run_id,stamp=pending[future]
            try:
                payload=future.result()
                raw_json(db,run_id,payload)
                # Collection time is response receipt, avoiding queued-request bias.
                stamp=now()
                with db: db.execute('UPDATE runs SET collected_at=? WHERE id=?',(stamp,run_id))
                if dataset=='arrivals':
                    rows=arrival_rows(payload,run_id,scope,stamp)
                    with db: db.executemany('INSERT INTO arrivals VALUES(?,?,?,?,?,?,?,?,?,?,?)',rows)
                else:
                    rows=[(run_id,scope,r['Station'],r['StartTime'],r['EndTime'],r['CrowdLevel']) for r in payload['value']]
                    with db: db.executemany('INSERT INTO crowd VALUES(?,?,?,?,?,?)',rows)
                end(db,run_id,len(rows))
                print(dataset,scope,len(rows),flush=True)
            except Exception as exc:
                end(db,run_id,error=str(exc));failures+=1;print(dataset,scope,'FAILED:',str(exc),flush=True)
    return failures

def parse_month(value):
    normalized=value.replace('-','')
    datetime.strptime(normalized,'%Y%m')
    return normalized

def previous_month():
    return (datetime.now(SGT).replace(day=1)-timedelta(days=1)).strftime('%Y%m')

def monthly(db, month, datasets, refresh=False):
    month=parse_month(month)
    for dataset in datasets:
        run_id=begin(db,'PV/'+dataset,month)
        try:
            cache=ROOT/'data/raw'/f'{dataset}_{month}.zip';cache.parent.mkdir(parents=True,exist_ok=True)
            if refresh or not cache.exists():
                payload=api('PV/'+dataset,Date=month)
                values=payload.get('value') or []
                if not values or not values[0].get('Link'):
                    raise ValueError('No monthly download available for this month.')
                link=values[0]['Link']
                if urllib.parse.urlparse(link).scheme!='https':
                    raise ValueError('Monthly download must use HTTPS.')
                # Deliberately do NOT forward the AccountKey to the download host.
                fetch(link,destination=cache)
            count=import_monthly(db,cache,dataset,month)
            end(db,run_id,count);print('PV/'+dataset,month,count,flush=True)
        except Exception as exc:
            end(db,run_id,error=str(exc));raise

def import_monthly(db, path, dataset, expected_month):
    is_od=dataset.startswith('OD');mode=dataset.removeprefix('OD')
    if mode not in ('Bus','Train'): raise ValueError('Unknown volume dataset')
    table='od' if is_od else 'volumes';cfg=config();watched=set(cfg['bus_stops'])
    count=0
    with zipfile.ZipFile(path) as archive, db:
        members=[n for n in archive.namelist() if n.lower().endswith('.csv')]
        if not members: raise ValueError('ZIP contains no CSV data')
        db.execute(f'DELETE FROM {table} WHERE mode=? AND month=?',(mode,expected_month))
        for name in members:
            with archive.open(name) as stream:
                reader=csv.DictReader(io.TextIOWrapper(stream,encoding='utf-8-sig'))
                batch=[]
                for r in reader:
                    month=parse_month(r['YEAR_MONTH'])
                    if month!=expected_month: raise ValueError('Unexpected month in downloaded file')
                    hour=int(r['TIME_PER_HOUR']) if r['TIME_PER_HOUR'].strip() else None
                    prefix=(mode,month,r['DAY_TYPE'],hour)
                    if is_od:
                        origin=r['ORIGIN_PT_CODE'];dest=r['DESTINATION_PT_CODE']
                        if mode=='Bus':
                            origin=origin.zfill(5);dest=dest.zfill(5)
                            if cfg['od_bus_scope']=='watched' and origin not in watched and dest not in watched: continue
                        row=prefix+(origin,dest,int(r['TOTAL_TRIPS']))
                    else:
                        node=r['PT_CODE'].zfill(5) if mode=='Bus' else r['PT_CODE']
                        row=prefix+(node,int(r['TOTAL_TAP_IN_VOLUME']),int(r['TOTAL_TAP_OUT_VOLUME']))
                    batch.append(row)
                    if len(batch)>=10000:
                        db.executemany(f'INSERT INTO {table} VALUES(?,?,?,?,?,?,?)',batch);count+=len(batch);batch=[]
                if batch:
                    db.executemany(f'INSERT INTO {table} VALUES(?,?,?,?,?,?,?)',batch);count+=len(batch)
        if not count: raise ValueError('No rows matched the requested monthly scope')
        # Archive original source bytes and current import provenance in the same transaction.
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='releases'").fetchone():
            import warehouse
            release_id=warehouse.archive_release(db,path,dataset,expected_month,now())
            scope=cfg['od_bus_scope'] if dataset=='ODBus' else 'all'
            db.execute('INSERT OR REPLACE INTO monthly_imports VALUES(?,?,?,?,?,?)',(dataset,expected_month,release_id,now(),scope,count))
    return count

EXPORTS={'Annual':'SELECT * FROM annual','Stops':'SELECT * FROM stops','Routes':'SELECT * FROM routes',
'Arrivals':'SELECT * FROM v_latest_arrivals','Crowd':'SELECT * FROM v_latest_crowd',
'Hourly':'SELECT * FROM v_hourly','Nodes':'SELECT * FROM v_nodes','ODPairs':'SELECT * FROM v_od_pairs',
'TopNodes':"SELECT * FROM (SELECT *, DENSE_RANK() OVER(PARTITION BY mode,month,day_type ORDER BY tap_in DESC) demand_rank FROM v_nodes) WHERE demand_rank<=15",
'Pressure':'SELECT * FROM v_service_pressure','Runs':'SELECT * FROM runs'}

def export(db):
    import analytics
    analytics.refresh(db)
    all_exports = {**EXPORTS, **analytics.EXPORTS}
    folder=ROOT/'data/exports';folder.mkdir(parents=True,exist_ok=True)
    manifest={'exported_at':now(),'tables':{}}
    for name,sql in all_exports.items():
        cursor=db.execute(sql);path=folder/f'{name}.csv';temp=path.with_suffix('.tmp')
        count=0
        with temp.open('w',newline='',encoding='utf-8-sig') as stream:
            writer=csv.writer(stream);writer.writerow([d[0] for d in cursor.description])
            for row in cursor:writer.writerow(row);count+=1
        temp.replace(path)
        manifest['tables'][name]={'rows':count,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print('SQL exports refreshed',flush=True)

def check(db):
    checks={
        'sqlite_integrity':db.execute('PRAGMA integrity_check').fetchone()[0]=='ok',
        'foreign_keys':not db.execute('PRAGMA foreign_key_check').fetchall(),
        'volume_values':db.execute('SELECT COUNT(*) FROM volumes WHERE tap_in<0 OR tap_out<0').fetchone()[0]==0,
        'load_codes':db.execute("SELECT COUNT(*) FROM arrivals WHERE load IS NOT NULL AND load NOT IN ('SEA','SDA','LSD')").fetchone()[0]==0,
        'crowd_codes':db.execute("SELECT COUNT(*) FROM crowd WHERE crowd_level NOT IN ('l','m','h','NA')").fetchone()[0]==0,
        'hourly_reconciliation':db.execute('SELECT COALESCE(SUM(tap_in),0) FROM volumes').fetchone()[0]==db.execute('SELECT COALESCE(SUM(tap_in),0) FROM v_hourly').fetchone()[0],
        'od_reconciliation':db.execute('SELECT COALESCE(SUM(trips),0) FROM od').fetchone()[0]==db.execute('SELECT COALESCE(SUM(trips),0) FROM v_od_pairs').fetchone()[0],
    }
    latest=db.execute("SELECT dataset,scope,status,rows_loaded FROM runs r WHERE id=(SELECT MAX(id) FROM runs r2 WHERE r2.dataset=r.dataset AND r2.scope=r.scope)").fetchall()
    checks['latest_requests_succeeded']=all(r[2]=='ok' for r in latest)
    result={'latest_requests':latest,'checked_at':now(),'checks':checks,'row_counts':{t:db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ['stops','routes','arrivals','crowd','volumes','od']},
            'failed_runs':db.execute("SELECT dataset,scope,error FROM runs WHERE status='failed'").fetchall()}
    (ROOT/'data/validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    if not all(checks.values()):raise RuntimeError('Data checks failed')

def run_loop(db):
    cfg=config();arrival_interval=max(20,int(cfg['arrival_interval_seconds']))
    crowd_interval=max(600,int(cfg['crowd_interval_seconds']));export_interval=max(60,int(cfg['export_interval_seconds']))
    next_arrival=next_crowd=next_export=0
    import warehouse
    # Catch up before live polling, then at most once daily.
    if cfg.get('archive_monthly', True) and warehouse.scheduler_due(db,now()):
        warehouse.mark_attempt(db,now())
        print('Monthly archive:', warehouse.sync_months(db), flush=True)
    try:
        while True:
            tick=time.monotonic();a=tick>=next_arrival;c=tick>=next_crowd
            if a or c:
                live(db,a,c)
                if a:next_arrival=time.monotonic()+arrival_interval
                if c:next_crowd=time.monotonic()+crowd_interval
            if tick>=next_export:
                export(db);next_export=time.monotonic()+export_interval
            if cfg.get('archive_monthly', True) and warehouse.scheduler_due(db,now()):
                warehouse.mark_attempt(db,now())
                print('Monthly archive:', warehouse.sync_months(db), flush=True)
            time.sleep(1)
    except KeyboardInterrupt: export(db);print('Collector stopped cleanly.')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['configure','init','reference','live','monthly','export','check','collect','setup','sync-monthly','backup'])
    p.add_argument('--month',default=previous_month())
    p.add_argument('--datasets',nargs='+',choices=['Bus','Train','ODBus','ODTrain'],default=['Bus','Train','ODTrain','ODBus'])
    p.add_argument('--refresh-source',action='store_true',help='Fetch source again; preserve old release bytes in SQL')
    args=p.parse_args()
    if args.command=='configure':
        key=getpass.getpass('Paste your existing LTA key (input is hidden), then press Enter: ').strip()
        if not key:raise SystemExit('No key entered; nothing saved.')
        (ROOT/'.env').write_text('LTA_ACCOUNT_KEY='+key+'\n');os.chmod(ROOT/'.env',0o600)
        print('Key saved locally. Do not share .env.');return
    with connect() as db:
        if args.command=='reference':reference(db)
        elif args.command=='live':
            failures=live(db);export(db)
            if failures:raise SystemExit(f'{failures} feeds failed. See Runs.csv.')
        elif args.command=='monthly':monthly(db,args.month,args.datasets,args.refresh_source);export(db)
        elif args.command=='sync-monthly':
            import warehouse
            errors=warehouse.sync_months(db,args.refresh_source);export(db)
            if errors:raise SystemExit('Unavailable releases (logged in Runs): '+str(errors))
        elif args.command=='backup':
            dest=ROOT/'data/backups'/('transit_'+datetime.now(SGT).strftime('%Y%m%d_%H%M%S')+'.sqlite')
            dest.parent.mkdir(exist_ok=True)
            with sqlite3.connect(dest) as backup:db.backup(backup)
            print('Backup saved:',dest)
        elif args.command=='export':export(db)
        elif args.command=='check':check(db)
        elif args.command=='collect':run_loop(db)
        elif args.command=='setup':
            reference(db);monthly(db,args.month,args.datasets);failures=live(db);export(db);check(db)
            if failures:raise SystemExit(f'{failures} live feeds failed. Historical data is available.')

if __name__=='__main__':main()
