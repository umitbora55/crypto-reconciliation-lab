"""Experiment serialization and filesystem helpers, without financial imports."""
import hashlib
import json
from pathlib import Path


def encoded(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)+'\n').encode()


def digest_bytes(data): return hashlib.sha256(data).hexdigest()


def receipt_id(envelope):
    # Wire-envelope hash only; no production normalization or economic calculation.
    return digest_bytes(encoded(envelope).rstrip(b'\n'))


def save(path,value):
    Path(path).write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')


def load(path): return json.loads(Path(path).read_text())


def fresh(path):
    path=Path(path)
    path.mkdir(parents=True,exist_ok=False)
    return path


def build_fingerprint():
    root=Path(__file__).resolve().parents[1]
    entries={str(p.relative_to(root)):digest_bytes(p.read_bytes()) for p in sorted(root.rglob('*.py'))}
    return digest_bytes(encoded(entries))
