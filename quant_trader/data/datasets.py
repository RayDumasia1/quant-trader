"""Content-addressed, append-only dataset bundles. No research DB writes."""
import hashlib
import json
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def checksum(content):
    return hashlib.sha256(content).hexdigest()


class DatasetStore:
    def __init__(self, root='data/v1.1'):
        self.root = Path(root)

    def put(self, *, raw, bars, actions, calendar, provenance, validation):
        files = {'raw.json': raw, 'bars.json': canonical(bars),
                 'actions.json': canonical(actions), 'calendar.json': canonical(calendar),
                 'validation.json': canonical(validation)}
        identity = {'schema_version': '1.1', 'provenance': provenance,
                    'files': {name: checksum(content) for name, content in files.items()}}
        dataset_id = checksum(canonical(identity))
        directory = self.root / 'datasets' / dataset_id
        directory.parent.mkdir(parents=True, exist_ok=True)
        try:
            directory.mkdir()
        except FileExistsError:
            self.load(dataset_id)
            return dataset_id
        # A manifest is written last. Interrupted bundles fail verification.
        for name, content in files.items():
            with (directory / name).open('xb') as handle:
                handle.write(content)
        with (directory / 'manifest.json').open('xb') as handle:
            handle.write(canonical({'dataset_id': dataset_id, **identity}))
        return dataset_id

    def load(self, dataset_id):
        if len(dataset_id) != 64 or any(c not in '0123456789abcdef' for c in dataset_id):
            raise ValueError('Expected a SHA-256 dataset identifier')
        directory = self.root / 'datasets' / dataset_id
        manifest = json.loads((directory / 'manifest.json').read_bytes())
        identity = {key: value for key, value in manifest.items() if key != 'dataset_id'}
        if manifest['dataset_id'] != dataset_id or checksum(canonical(identity)) != dataset_id:
            raise ValueError('Dataset identity mismatch')
        for name, expected in manifest['files'].items():
            if name not in {'raw.json','bars.json','actions.json','calendar.json','validation.json'}:
                raise ValueError('Unexpected bundle filename')
            if checksum((directory / name).read_bytes()) != expected:
                raise ValueError('Dataset checksum mismatch: ' + name)
        return manifest, json.loads((directory / 'bars.json').read_bytes())
