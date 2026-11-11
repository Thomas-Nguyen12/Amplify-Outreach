"""Daytona smoke/simulation runner (current synchronous Daytona SDK).

Run from your own computer, not from within the sandbox:
    python -m pip install daytona python-dotenv
    python -m scripts.run_daytona --zip ./social-trend-agent-daytona-ready.zip --mode offline

Optional HelloMinds research on fictional leads:
    python -m scripts.run_daytona --zip ./social-trend-agent-daytona-ready.zip --mode minds --max-research 2

No real outreach is performed. Daytona, HelloMinds, and networking require
account access; this runner has not been live-tested with a Daytona account.
"""
import argparse
import os
from pathlib import Path
from dotenv import load_dotenv


def _check(result, description):
    output = getattr(result, 'result', '') or ''
    print(f'[{description}] exit={result.exit_code}\n{output[-3500:]}')
    if result.exit_code != 0:
        raise RuntimeError(f'{description} failed (exit={result.exit_code})')


def main():
    parser = argparse.ArgumentParser(description='Run offline or HelloMinds synthetic tests in a Daytona sandbox')
    parser.add_argument('--zip', type=Path, required=True, help='Project archive on this computer')
    parser.add_argument('--mode', choices=('offline', 'minds'), default='offline')
    parser.add_argument('--snapshot', default='daytona-medium', help='Daytona snapshot with 2 vCPU, 4 GiB RAM, 8 GiB disk')
    parser.add_argument('--max-research', type=int, default=2)
    parser.add_argument('--output-zip', type=Path, default=Path('daytona-simulation-logs.zip'))
    args = parser.parse_args()
    load_dotenv()
    archive = args.zip.expanduser().resolve()
    if not archive.is_file():
        parser.error(f'Project ZIP not found: {archive}')
    if not os.environ.get('DAYTONA_API_KEY'):
        parser.error('DAYTONA_API_KEY is required')
    if args.mode == 'minds':
        needed = ('MINDS_BUILDER_API_KEY', 'MINDS_RESEARCH_MIND_ID')
        missing = [key for key in needed if not os.environ.get(key)]
        if missing:
            parser.error('Missing HelloMinds settings: ' + ', '.join(missing))
        if not 1 <= args.max_research <= 20:
            parser.error('--max-research must be between 1 and 20')

    # Imports deferred so --help is usable without the Daytona package.
    from daytona import Daytona, CreateSandboxFromSnapshotParams
    daytona = Daytona()
    sandbox = None
    try:
        sandbox = daytona.create(CreateSandboxFromSnapshotParams(snapshot=args.snapshot))
        print(f'Created sandbox: {sandbox.id}')
        sandbox.fs.upload_file(str(archive), '/tmp/agent-project.zip')
        _check(sandbox.process.exec('mkdir -p /tmp/test-agent && python3 -m zipfile -e /tmp/agent-project.zip /tmp/test-agent'), 'extract')
        cwd = '/tmp/test-agent/social-trend-customer-agent'
        _check(sandbox.process.exec('python3 -m pip install -q -r requirements.txt', cwd=cwd, timeout=300), 'install Python deps')
        _check(sandbox.process.exec('python3 -m pytest -q', cwd=cwd, timeout=180), 'pytest')
        output_dir = 'outputs/daytona_test'
        if args.mode == 'offline':
            command = f'python3 -m scripts.run_simulation --output-dir {output_dir} --db data/daytona-sim.sqlite3'
            env = {'SURREAL_ENABLED': 'false', 'TAVILY_ENABLED': 'false', 'TREG_ENABLED': 'false', 'MINDS_ENABLED': 'false'}
        else:
            # Never upload your .env file. Pass only the minimal Minds credentials.
            _check(sandbox.process.exec('node --version', cwd=cwd, timeout=30), 'check Node')
            node = sandbox.process.exec('node --version', cwd=cwd, timeout=30).result.strip()
            if int(node.lstrip('v').split('.')[0]) < 22:
                raise RuntimeError('HelloMinds mode requires Node.js 22+ in your Daytona snapshot')
            _check(sandbox.process.exec('npm install --no-audit --no-fund', cwd=f'{cwd}/bridge', timeout=300), 'install Minds bridge')
            command = (f'python3 -m scripts.run_minds_simulation --max-research {args.max_research} '
                       f'--output-dir {output_dir} --db data/daytona-sim.sqlite3')
            env = {
                'SURREAL_ENABLED': 'false', 'TAVILY_ENABLED': 'false', 'TREG_ENABLED': 'false',
                'MINDS_ENABLED': 'true', 'MINDS_BUILDER_API_KEY': os.environ['MINDS_BUILDER_API_KEY'],
                'MINDS_RESEARCH_MIND_ID': os.environ['MINDS_RESEARCH_MIND_ID'],
                'MINDS_TIMEOUT_SECONDS': os.getenv('MINDS_TIMEOUT_SECONDS', '180'),
            }
        _check(sandbox.process.exec(command, cwd=cwd, env=env, timeout=1200), 'synthetic simulation')
        _check(sandbox.process.exec(f'python3 -m zipfile -c /tmp/simulation-logs.zip {output_dir}', cwd=cwd, timeout=90), 'archive logs')
        args.output_zip.parent.mkdir(parents=True, exist_ok=True)
        sandbox.fs.download_file('/tmp/simulation-logs.zip', str(args.output_zip.resolve()))
        print(f'Logs downloaded: {args.output_zip}')
    finally:
        if sandbox:
            daytona.delete(sandbox)
            print('Sandbox deleted')


if __name__ == '__main__':
    main()
