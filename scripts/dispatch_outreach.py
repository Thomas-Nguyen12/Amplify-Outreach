"""Daytona/cron one-shot: research reconciliation, then consent-gated email dispatch.

python -m scripts.dispatch_outreach --limit 2
"""
import argparse
import asyncio
import json
from app.surreal_store import enabled_store
from app.research_jobs import reconcile_pending
from app.outreach import configure_status, dispatch_ready


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--limit',type=int,default=2)
    args=parser.parse_args()
    if not 1<=args.limit<=10:parser.error('--limit must be 1..10')
    store=enabled_store()
    if not store:parser.error('SurrealDB is mandatory for durable outreach')
    research=asyncio.run(reconcile_pending(store,limit=args.limit))
    permission=configure_status()
    sending=dispatch_ready(store,limit=args.limit) if permission['ready'] else []
    print(json.dumps({'research_reconciliation':research,'sending_ready':permission['ready'],
                      'outreach':sending},indent=2))

if __name__=='__main__':main()
