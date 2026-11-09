#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from spec_workshop.demo import definition
from spec_workshop.store import Store
from spec_workshop.verify import verify

parser=argparse.ArgumentParser(description='Database-defined framework screen prototype')
parser.add_argument('action',choices=['seed-demo','publish','show','activate','verify-framework'])
parser.add_argument('--code',default='ZDE0001')
parser.add_argument('--revision',type=int,default=1)
parser.add_argument('--database',default='mdi_local')
parser.add_argument('--provision',action='store_true')
parser.add_argument('--file',type=Path)
args=parser.parse_args()
store=Store(args.database)
if args.action=='seed-demo':
    store.initialize(); print(json.dumps(store.release(definition(),args.revision),ensure_ascii=False,indent=2))
elif args.action=='show': print(json.dumps(store.load(args.code,args.revision),ensure_ascii=False,indent=2))
elif args.action=='publish':
    if not args.file: parser.error('publish requires --file')
    store.initialize();print(json.dumps(store.release(json.loads(args.file.read_text()),args.revision),ensure_ascii=False,indent=2))
elif args.action=='activate': print(json.dumps(store.activate(args.code,args.revision,args.provision),ensure_ascii=False,indent=2))
else:
    result=verify(args.code,args.revision,args.database)
    raise SystemExit(0 if result['status']=='succeeded' else 1)
