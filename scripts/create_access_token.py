"""Issue/rotate an access code; raw code goes to an ignored local file, not logs."""
import argparse
import hashlib
from pathlib import Path
import re
import secrets
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from finance_detective.rag import store
parser=argparse.ArgumentParser()
parser.add_argument('--user',required=True)
args=parser.parse_args()
if not re.fullmatch(r'[a-zA-Z0-9_-]{1,60}',args.user) or args.user=='local-owner':parser.error('Use 1–60 letters/digits/_/-; local-owner is reserved.')
store.initialize()
code=secrets.token_urlsafe(32)
with store.connection() as db:
    db.execute('INSERT INTO ai_users(id,token_hash) VALUES(%s,%s) ON CONFLICT(id) DO UPDATE SET token_hash=excluded.token_hash,disabled=false',
               (args.user,hashlib.sha256(code.encode()).hexdigest()))
path=ROOT/'data/processed'/('access-'+args.user+'.txt')
path.write_text(code+'\n');path.chmod(0o600)
print('Access code saved to',path.relative_to(ROOT),'; older codes for this user are invalid.')
store.close()
