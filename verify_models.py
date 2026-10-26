"""Fail the build/startup check if any bundled model differs from its manifest."""
from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parent
groups=[(root/'model-checksums.json',root/'dtln_proxy/vendor/models'),
        (root/'dtln-models.json',root/'dtln_proxy/models')]
for manifest,directory in groups:
    for entry in json.loads(manifest.read_text()):
        data=(directory/entry['name']).read_bytes()
        if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:
            raise SystemExit('Model verification failed: '+entry['name'])
print('Hush and DTLN models verified.')
