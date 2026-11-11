"""Backward-compatible wrapper for the current Daytona simulator.

Use: python -m scripts.run_daytona_minds --zip path/to/archive --max-research 2
"""
import sys
from .run_daytona import main

if __name__ == '__main__':
    if '--mode' not in sys.argv:
        sys.argv.extend(['--mode', 'minds'])
    main()
