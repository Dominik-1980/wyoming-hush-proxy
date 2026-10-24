"""Verify public release contents without external services or credentials."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
try:
    tracked = subprocess.check_output(['git','ls-files','-z'], cwd=root, stderr=subprocess.DEVNULL).decode().split('\0')
    files = [root/p for p in tracked if p]
except subprocess.CalledProcessError:
    files = [p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.git' not in p.parts]
assert files, 'No release files found'
forbidden_path = re.compile(r'(?i)(Audioanalyse|recordings/|/data/|results\.json|settings\.json|\.wav$|\.flac$|\.mp3$|\.ckpt$|\.pem$|\.key$|\.env$)')
private_ipv4 = re.compile(r'\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b')
secret = re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')
for path in files:
    name = str(path.relative_to(root))
    assert not forbidden_path.search(name), f'Private/runtime file in release: {name}'
    if path.suffix == '.png':
        assert path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'), name
    elif path.suffix in ('.jpg', '.jpeg'):
        assert path.read_bytes().startswith(b'\xff\xd8\xff'), name
    elif path.suffix != '.onnx':
        text = path.read_text()
        assert not private_ipv4.search(text), f'Private IPv4 address: {name}'
        assert not secret.search(text), f'Credential-like content: {name}'
        assert ('/'+'Users/') not in text and ('Codex'+' Assist') not in text, f'Local/private path: {name}'

manifest = json.loads((root/'vendor-manifest.json').read_text())
vendor = root/'hush_proxy/vendor'
for name, source in zip(('_hush_model.py','_libdf/__init__.py'), manifest['source_files']):
    data = (vendor/name).read_bytes()
    assert hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest() == source['git_blob_sha'], name
for model in json.loads((root/'model-checksums.json').read_text()):
    data = (vendor/'models'/model['name']).read_bytes()
    assert len(data) == model['bytes']
    assert hashlib.sha256(data).hexdigest() == model['sha256'], model['name']
print(f'Verified {len(files)} release files; no private audio/settings/addresses; source and model hashes match.')
