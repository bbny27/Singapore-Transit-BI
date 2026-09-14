"""Portable build commands: python make.py [setup|refresh|report|check|preview|collect|archive|backup]."""
import argparse
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parent

def run(*args):subprocess.run([sys.executable,*args],cwd=ROOT,check=True)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('target',nargs='?',default='setup',choices=['setup','refresh','report','check','preview','collect','archive','backup'])
    target=p.parse_args().target
    if target in ('setup','refresh','report'):
        run('transit.py','export')
        run('build_powerbi.py',*(['--rebuild-report'] if target=='report' else []))
    elif target=='check':
        run('-m','unittest','discover','-s','tests','-v')
        run('scripts/check_project.py')
    elif target=='preview':run('preview.py')
    elif target=='collect':run('transit.py','collect')
    elif target=='archive':run('transit.py','sync-monthly')
    elif target=='backup':run('transit.py','backup')
if __name__=='__main__':main()
