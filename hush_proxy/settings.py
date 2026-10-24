"""Settings are snapshotted at the start of each utterance."""
from dataclasses import asdict, dataclass, replace
import json
import math
import ipaddress
import re
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    filter_enabled: bool = True
    recording_enabled: bool = False
    atten_lim_db: float = 12.0
    upstream_host: str = ''
    upstream_port: int = 10300


def validate_host(value):
    if not isinstance(value, str):
        raise ValueError('STT-Host muss ein Hostname oder eine IP-Adresse sein')
    host = value.strip()
    if not host:
        return ''
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if len(host) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in host.rstrip('.').split('.')):
            raise ValueError('Ungültiger STT-Hostname oder ungültige IP-Adresse')
    return host


class SettingsStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / 'settings.json'
        data_dir.mkdir(parents=True, exist_ok=True)
        self.current = Settings()
        if self.path.exists():
            self.current = self.validate(json.loads(self.path.read_text()))

    def validate(self, values: dict) -> Settings:
        if not isinstance(values, dict) or set(values) - set(asdict(Settings())):
            raise ValueError('Unbekannte Einstellung')
        for key in ('filter_enabled', 'recording_enabled'):
            if key in values and type(values[key]) is not bool:
                raise ValueError('Schalter müssen true oder false sein')
        if 'atten_lim_db' in values:
            limit = values['atten_lim_db']
            if isinstance(limit, bool) or not isinstance(limit, (float, int)) or not math.isfinite(limit) or not 0 <= limit <= 60:
                raise ValueError('Absenkungsgrenze muss zwischen 0 und 60 dB liegen')
        if 'upstream_host' in values:
            values = dict(values, upstream_host=validate_host(values['upstream_host']))
        if 'upstream_port' in values and (type(values['upstream_port']) is not int or not 1 <= values['upstream_port'] <= 65535):
            raise ValueError('STT-Port muss zwischen 1 und 65535 liegen')
        return replace(self.current, **values)

    def update(self, values: dict) -> Settings:
        updated = self.validate(values)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(asdict(updated), indent=2) + '\n')
        temporary.replace(self.path)
        self.current = updated
        return updated
