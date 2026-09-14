"""Dependency-free integrity, reconciliation, reference, CSV and model checks."""
import csv,hashlib,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import transit
with transit.connect() as db:
    checks={'sqlite_integrity':db.execute('PRAGMA integrity_check').fetchone()[0]=='ok',
            'foreign_keys':not db.execute('PRAGMA foreign_key_check').fetchall(),
            'demand_reconciliation':db.execute('SELECT SUM(tap_in) FROM volumes').fetchone()[0]==db.execute('SELECT SUM(tap_in) FROM v_demand').fetchone()[0],
            'flow_reconciliation':db.execute('SELECT SUM(trips) FROM od').fetchone()[0]==db.execute('SELECT SUM(trips) FROM v_flow').fetchone()[0],
            'places_unique':db.execute('SELECT COUNT(*)=COUNT(DISTINCT place_key) FROM v_place').fetchone()[0]==1,
            'all_demand_places_exist':db.execute('SELECT COUNT(*) FROM v_demand d LEFT JOIN v_place p USING(place_key) WHERE p.place_key IS NULL').fetchone()[0]==0,
            'maps_valid':db.execute('SELECT count(*) FROM redundancy_metrics WHERE latitude IS NOT NULL AND NOT (latitude BETWEEN 1.1 AND 1.6 AND longitude BETWEEN 103.5 AND 104.2)').fetchone()[0]==0,
            'raw_payload_checksums':all(hashlib.sha256(body.encode()).hexdigest()==sha for sha,body in db.execute('SELECT sha256,payload_json FROM raw_payloads')),
            'release_checksums':all(hashlib.sha256(body).hexdigest()==sha for sha,body in db.execute('SELECT sha256,zip_bytes FROM releases'))}
    model=json.loads((ROOT/'powerbi/Transit.SemanticModel/model.bim').read_text())['model']
    manifests=json.loads((ROOT/'data/exports/manifest.json').read_text())
    checks['export_checksums']=all(hashlib.sha256((ROOT/'data/exports'/f'{n}.csv').read_bytes()).hexdigest()==m['sha256'] for n,m in manifests['tables'].items())
    checks['model_csv_headers']=True;checks['no_self_referential_m']=True
    for t in model['tables']:
        path=ROOT/'data/exports'/f"{t['name']}.csv"
        with path.open(encoding='utf-8-sig') as f:headers=next(csv.reader(f))
        checks['model_csv_headers'] &= headers==[c['name'] for c in t['columns']]
        text='\n'.join(t['partitions'][0]['source']['expression'])
        checks['no_self_referential_m'] &= 'File.Contents(' in text and 'in Typed' in text
    counts={t:db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ['volumes','od','arrivals','crowd','raw_payloads','releases','clusters','scenarios']}
    result={'checked_at':transit.now(),'checks':checks,'row_counts':counts,'desktop_open_test':'Not available in this Linux environment; JSON validation is separate.'}
    (ROOT/'data/validation_revamp.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    if not all(checks.values()):raise SystemExit('Validation failed.')
