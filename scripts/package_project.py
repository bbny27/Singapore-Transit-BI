"""Build a checked distributable, packaging SQLite through an online backup."""
from pathlib import Path
import argparse
import io
import sqlite3
import tempfile
import zipfile
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('output',type=Path);args=p.parse_args()
args.output=args.output.resolve();args.output.parent.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as d:
    snapshot=Path(d)/'transit.sqlite'
    with sqlite3.connect(ROOT/'data/transit.sqlite') as src,sqlite3.connect(snapshot) as dst:src.backup(dst)
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for f in sorted(ROOT.rglob('*')):
            if not f.is_file():continue
            rel=f.relative_to(ROOT)
            if any(part in {'.git','.pbi','__pycache__','backups','.venv'} for part in rel.parts):continue
            if f.name in {'.env','collector.lock'} or f.name.endswith(('.pyc','-wal','-shm','.tmp','.part','.zip')):continue
            z.write(snapshot if rel.as_posix()=='data/transit.sqlite' else f,Path('transit_bi')/rel)
    body=buf.getvalue();args.output.write_bytes(body)
    assert args.output.stat().st_size==len(body)
    with zipfile.ZipFile(args.output) as z:
        assert z.testzip() is None
        for n in ['transit_bi/powerbi/Transit.pbip','transit_bi/README.md','transit_bi/data/transit.sqlite']:
            assert n in z.namelist()
        print(f'ZIP verified: {len(z.namelist())} files; {len(body):,} bytes; one transit_bi root.')
print(args.output)
