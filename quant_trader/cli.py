"""Read-only development commands. No broker or order-submission commands."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

from quant_trader.data.repository import ResearchRepository
from quant_trader.data.validation import validate


def file_hash(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['validate'])
    parser.add_argument('--database', default='trading.duckdb')
    parser.add_argument('--as-of', required=True, help='Explicit YYYY-MM-DD assessment date')
    parser.add_argument('--output', help='New JSON report path; existing files are never overwritten')
    args = parser.parse_args(argv)
    database = Path(args.database).resolve(strict=True)
    output = Path(args.output).resolve() if args.output else None
    if output and (output == database or output.exists()):
        parser.error('Output must be a new file distinct from the database')
    before = file_hash(database)
    with ResearchRepository(database) as repository:
        report = validate(repository, as_of=args.as_of)
    after = file_hash(database)
    if before != after:
        raise RuntimeError('Database bytes changed during assessment; report is invalid')
    report['manifest'] = {
        'database_sha256': before, 'database_bytes_unchanged': True,
        'python': platform.python_version(), 'environment': 'paper',
        'order_submission_enabled': False,
        'dependencies': {name: importlib.metadata.version(name)
                         for name in ['duckdb', 'pandas', 'numpy', 'yfinance', 'requests']},
        'source_sha256': {str(path): file_hash(path) for path in
                          sorted(Path(__file__).parent.rglob('*.py'))},
        'note': 'Fingerprint of existing data, not a retained immutable dataset snapshot.',
    }
    payload = json.dumps(report, indent=2, default=str) + '\n'
    if output:
        with output.open('x', encoding='utf-8') as handle:
            handle.write(payload)
        print(f'Report saved: {output}')
    else:
        print(payload)
    return 1 if report['warnings'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
