"""Offline customer simulation: python -m scripts.run_simulation --output-dir outputs/simulation"""
import argparse
import json
from pathlib import Path
from app.simulation import DEFAULT_FIXTURES, run_simulation, export_simulation


def main():
    parser=argparse.ArgumentParser(description='OFFLINE synthetic prospect and message simulation')
    parser.add_argument('--fixtures',type=Path,default=DEFAULT_FIXTURES)
    parser.add_argument('--output-dir',type=Path,default=Path('outputs/simulation'))
    parser.add_argument('--db',type=Path,default=Path('data/simulation.sqlite3'))
    parser.add_argument('--threshold',type=int,default=70)
    args=parser.parse_args()
    summary=run_simulation(args.db,args.fixtures,threshold=args.threshold)
    output_dir=args.output_dir/summary['run_id']
    exported=export_simulation(args.db,summary['run_id'],output_dir)
    print(json.dumps({'summary':summary,'exported_files':exported},indent=2))
    print('ALL MESSAGES AND RESPONSES ABOVE ARE SYNTHETIC. No external communication occurred.')

if __name__=='__main__': main()
