"""Offline PBIR contract and model-binding validation. Requires optional jsonschema."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
try:from jsonschema import Draft7Validator,RefResolver
except ImportError:raise SystemExit('Install validation dependencies: python -m pip install -r requirements-dev.txt')
cache=ROOT/'tests/schema_cache'
def retrieve(url):
    path=cache/url.split('#')[0].replace('https://','').replace('/','_').replace('schema.embedded.json','schema-embedded.json')
    if not path.exists():raise RuntimeError('Uncached Microsoft schema: '+url)
    return json.loads(path.read_text())
model=json.loads((ROOT/'powerbi/Transit.SemanticModel/model.bim').read_text())['model']
tables={t['name']:t for t in model['tables']}
count=0
for path in (ROOT/'powerbi/Transit.Report').rglob('*.json'):
    data=json.loads(path.read_text());url=data.get('$schema')
    if url:
        schema=retrieve(url);resolver=RefResolver(base_uri=url,referrer=schema,handlers={'https':retrieve})
        errors=list(Draft7Validator(schema,resolver=resolver).iter_errors(data))
        if errors:
            print(path.relative_to(ROOT))
            for e in errors:print(list(e.absolute_path),e.message)
            raise SystemExit(1)
        count+=1
    def check_fields(obj):
        if isinstance(obj,dict):
            for kind,group in [('Column','columns'),('Measure','measures')]:
                if kind in obj and 'Property' in obj[kind]:
                    f=obj[kind];table=f.get('Expression',{}).get('SourceRef',{}).get('Entity')
                    if table:assert table in tables and f['Property'] in {c['name'] for c in tables[table].get(group,[])},(path,table,f['Property'])
            for v in obj.values():check_fields(v)
        elif isinstance(obj,list):
            for v in obj:check_fields(v)
    check_fields(data)
for r in model['relationships']:
    for side in ['from','to']:
        assert r[side+'Table'] in tables
        assert r[side+'Column'] in {c['name'] for c in tables[r[side+'Table']]['columns']}
print(f'PASS: {count} PBIR JSON contracts, visual field bindings and relationship references.')
