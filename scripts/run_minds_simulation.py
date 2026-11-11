"""Live HelloMinds research of fictional customers; never sends external outreach."""
import argparse
import asyncio
import json
from pathlib import Path
from app.minds_simulation import run_minds_simulation,export_minds_simulation
from app.simulation import DEFAULT_FIXTURES


def main():
    parser=argparse.ArgumentParser(description='HelloMinds-powered synthetic customer simulation')
    parser.add_argument('--fixtures',type=Path,default=DEFAULT_FIXTURES)
    parser.add_argument('--output-dir',type=Path,default=Path('outputs/simulation'))
    parser.add_argument('--db',type=Path,default=Path('data/simulation.sqlite3'))
    parser.add_argument('--threshold',type=int,default=70)
    parser.add_argument('--max-research',type=int,default=3)
    args=parser.parse_args()
    summary=asyncio.run(run_minds_simulation(args.db,args.fixtures,threshold=args.threshold,max_research=args.max_research))
    files=export_minds_simulation(args.db,summary['run_id'],args.output_dir/summary['run_id'])
    print(json.dumps({'summary':summary,'files':files},indent=2))
    print('NOTICE: FICTIONAL PROSPECTS, SCRIPTED CUSTOMER RESPONSES; REAL HelloMinds API calls only.')

if __name__=='__main__':
    main()
