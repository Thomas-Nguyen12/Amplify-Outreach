"""One-shot safe HelloMinds history recovery for a Daytona hourly job.

python -m scripts.reconcile_research --limit 2
"""
import argparse
import asyncio
import json
from app.surreal_store import enabled_store
from app.research_jobs import reconcile_pending


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=2)
    args = parser.parse_args()
    store = enabled_store()
    if not store:
        parser.error('SURREAL_ENABLED=true is required; pending recovery must be durable')
    if not 1 <= args.limit <= 10:
        parser.error('--limit must be 1..10')
    print(json.dumps(asyncio.run(reconcile_pending(store, limit=args.limit)), indent=2))

if __name__ == '__main__':
    main()
