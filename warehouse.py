"""Durable raw archives, release versions, calendar and bounded monthly catch-up."""
import calendar
import csv
from datetime import date,datetime,timedelta
import hashlib
import io
import json
from pathlib import Path
import zipfile

def initialize(db,root):
    db.executescript((root/'sql/warehouse.sql').read_text())
    with (root/'data/reference/rail_names.csv').open(encoding='utf-8') as f, db:
        db.executemany('INSERT OR REPLACE INTO rail_names VALUES(?,?,?)',[(r['code'],r['name'],r['source']) for r in csv.DictReader(f)])
    cal=json.loads((root/'data/reference/calendar.json').read_text())
    holidays=set(cal['holidays'])
    months=[r[0] for r in db.execute('SELECT DISTINCT month FROM volumes UNION SELECT DISTINCT month FROM od')]
    with db:
        for month in months:
            y,m=int(month[:4]),int(month[4:]); verified=y in cal['verified_years']
            counts={'WEEKDAY':0,'WEEKENDS/HOLIDAY':0}
            for n in range(1,calendar.monthrange(y,m)[1]+1):
                d=date(y,m,n);counts['WEEKENDS/HOLIDAY' if d.weekday()>=5 or d.isoformat() in holidays else 'WEEKDAY']+=1
            for day,count in counts.items():
                db.execute('INSERT OR REPLACE INTO calendar_days VALUES(?,?,?,?)',(month,day,count if verified else None,'Verified holiday calendar' if verified else 'Calendar needs verification'))
    # Recover previous JSON snapshots into SQL exactly once.
    known={r[0] for r in db.execute('SELECT run_id FROM raw_payloads')}
    runs={r[0] for r in db.execute('SELECT id FROM runs')}
    for p in (root/'data/raw').glob('*.json'):
        if p.stem.isdigit() and int(p.stem) in runs and int(p.stem) not in known:
            save_payload(db,int(p.stem),json.loads(p.read_text()))

def save_payload(db,run_id,payload):
    text=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
    with db:
        db.execute('INSERT OR IGNORE INTO raw_payloads VALUES(?,?,?)',(run_id,hashlib.sha256(text.encode()).hexdigest(),text))

def archive_release(db,path,dataset,month,stamp,kind='Original LTA ZIP'):
    body=Path(path).read_bytes();digest=hashlib.sha256(body).hexdigest()
    db.execute('INSERT OR IGNORE INTO releases(dataset,month,sha256,archived_at,source_kind,zip_bytes) VALUES(?,?,?,?,?,?)',(dataset,month,digest,stamp,kind,body))
    return db.execute('SELECT release_id FROM releases WHERE dataset=? AND month=? AND sha256=?',(dataset,month,digest)).fetchone()[0]

def preserve_legacy(db,root,stamp):
    """Original ZIPs were omitted previously. Preserve the exact supplied SQL facts, explicitly labelled."""
    for dataset in ['Bus','Train','ODBus','ODTrain']:
        mode=dataset.removeprefix('OD');table='od' if dataset.startswith('OD') else 'volumes'
        for (month,) in db.execute(f'SELECT DISTINCT month FROM {table} WHERE mode=?',(mode,)).fetchall():
            if db.execute('SELECT 1 FROM monthly_imports WHERE dataset=? AND month=?',(dataset,month)).fetchone():continue
            buffer=io.BytesIO()
            q=db.execute(f'SELECT * FROM {table} WHERE mode=? AND month=?',(mode,month))
            with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
                with z.open('legacy_sql_rows.csv','w') as b:
                    with io.TextIOWrapper(b,encoding='utf-8',newline='') as stream:
                        w=csv.writer(stream);w.writerow([x[0] for x in q.description]);w.writerows(q)
            body=buffer.getvalue();sha=hashlib.sha256(body).hexdigest()
            with db:
                cur=db.execute('INSERT INTO releases(dataset,month,sha256,archived_at,source_kind,zip_bytes) VALUES(?,?,?,?,?,?)',(dataset,month,sha,stamp,'Legacy SQL extract; original ZIP unavailable',body))
                count=db.execute(f'SELECT count(*) FROM {table} WHERE mode=? AND month=?',(mode,month)).fetchone()[0]
                scope='watched endpoints (original project)' if dataset=='ODBus' else 'all'
                db.execute('INSERT INTO monthly_imports VALUES(?,?,?,?,?,?)',(dataset,month,cur.lastrowid,stamp,scope,count))

def recent_months(stamp,count=3):
    d=stamp.date().replace(day=1);out=[]
    for _ in range(count):
        d=(d-timedelta(days=1)).replace(day=1);out.append(d.strftime('%Y%m'))
    return out

def sync_months(db,force=False):
    import transit
    errors=[]
    for month in reversed(recent_months(datetime.now(transit.SGT))):
        for dataset in ['Bus','Train','ODBus','ODTrain']:
            row=db.execute('SELECT scope FROM monthly_imports WHERE dataset=? AND month=?',(dataset,month)).fetchone()
            needs_full=dataset=='ODBus' and transit.config()['od_bus_scope']=='all' and row and row[0]!='all'
            if row and not force and not needs_full:continue
            try:transit.monthly(db,month,[dataset],refresh=force)
            except Exception as exc:errors.append((dataset,month,str(exc)))
    return errors

def scheduler_due(db,stamp):
    row=db.execute("SELECT last_attempt FROM scheduler_state WHERE job='monthly'").fetchone()
    return not row or datetime.fromisoformat(stamp)-datetime.fromisoformat(row[0])>=timedelta(hours=24)

def mark_attempt(db,stamp):
    with db:db.execute("INSERT OR REPLACE INTO scheduler_state VALUES('monthly',?)",(stamp,))
