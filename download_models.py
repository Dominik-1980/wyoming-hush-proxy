"""Fetch pinned public ONNX files; verify exact Git blob identity before saving."""
import hashlib
import json
from pathlib import Path
import urllib.request

root = Path(__file__).resolve().parent
manifest = json.loads((root / 'vendor-manifest.json').read_text())
out = root / 'hush_proxy' / 'vendor' / 'models'
out.mkdir(parents=True, exist_ok=True)
for entry in manifest['models']:
    target = out / entry['name']
    if target.exists():
        data = target.read_bytes()
    else:
        with urllib.request.urlopen(entry['url'], timeout=60) as response:
            data = response.read(12 * 1024 * 1024)
    git_hash = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
    assert len(data) == entry['bytes'] and git_hash == entry['git_blob_sha'], entry['name']
    if not target.exists():
        with target.open('xb') as file:
            file.write(data)
    entry['sha256'] = hashlib.sha256(data).hexdigest()
    print(entry['name'], len(data), entry['sha256'])
(root / 'model-checksums.json').write_text(json.dumps(manifest['models'], indent=2) + '\n')
