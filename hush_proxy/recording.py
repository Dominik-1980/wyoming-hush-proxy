"""Opt-in paired WAV recording with quota and explicit inactive-clip deletion."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import stat
import uuid
import wave

LOG = logging.getLogger(__name__)
CLIP_ID = re.compile(r'^\d{8}T\d{6}Z-[0-9a-f]{12}$')
RECORDING_FILES = {'original.wav', 'filtered.wav', 'metadata.json'}


class RecordingStore:
    def __init__(self, data_dir: Path, max_bytes: int):
        self.root = data_dir / 'recordings'
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.used_bytes = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
        self.quota_reached = self.used_bytes >= max_bytes
        self.last_error = None
        self.active = set()

    def start(self, settings):
        # Reserve space for headers/metadata even for aborted sessions.
        if self.used_bytes + 8192 >= self.max_bytes:
            self.quota_reached = True
            return None
        return Recording(self, settings)

    def delete(self, clip_id):
        """Never follows symlinks or removes unknown files, subfolders or active audio."""
        if not CLIP_ID.fullmatch(clip_id):
            raise ValueError('Ungültige Aufnahme-ID')
        if clip_id in self.active:
            raise BlockingIOError('Eine laufende Aufnahme kann nicht gelöscht werden')
        target = self.root / clip_id
        if target.is_symlink():
            raise ValueError('Verknüpfungen werden nicht gelöscht')
        fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        removed = 0
        try:
            files = os.listdir(fd)
            if set(files) - RECORDING_FILES:
                raise ValueError('Aufnahmeordner enthält unbekannte Dateien')
            sizes = {}
            for name in files:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('Aufnahmeordner enthält Verknüpfungen oder Unterordner')
                sizes[name] = info.st_size
            for name in files:
                os.unlink(name, dir_fd=fd)
                removed += sizes[name]
        finally:
            os.close(fd)
            self.used_bytes = max(0, self.used_bytes - removed)
            self.quota_reached = self.used_bytes + 8192 >= self.max_bytes
        target.rmdir()
        return 1

    def delete_all(self):
        deleted = 0
        skipped = 0
        protected = 0
        for path in list(self.root.iterdir()):
            if not CLIP_ID.fullmatch(path.name):
                continue
            if path.name in self.active:
                skipped += 1
                continue
            try:
                deleted += self.delete(path.name)
            except (ValueError, OSError):
                protected += 1
        return {'deleted': deleted, 'active_skipped': skipped, 'protected_skipped': protected}


class Recording:
    def __init__(self, store, settings):
        self.store = store
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        self.id = stamp + '-' + uuid.uuid4().hex[:12]
        self.path = store.root / self.id
        self.path.mkdir()
        self.meta = {'id': self.id, 'created': datetime.now(timezone.utc).isoformat(),
                     'settings': asdict(settings), 'status': 'recording', 'sample_rate': 16000}
        self.waves = {}
        try:
            for name in ('original', 'filtered'):
                wav = wave.open(str(self.path / (name + '.wav')), 'wb')
                self.waves[name] = wav
                wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                wav.writeframesraw(b'')
        except OSError as exc:
            self.store.last_error = str(exc)
            for wav in self.waves.values():
                try:
                    wav.close()
                except (OSError, wave.Error):
                    pass
            raise
        self.store.last_error = None
        self.bytes_written = 0
        self.store.used_bytes += 8192
        self.reserved = 8192
        self.closed = False
        self.store.active.add(self.id)

    def write(self, name, pcm):
        if self.closed or not pcm:
            return
        if self.store.used_bytes + len(pcm) > self.store.max_bytes:
            self.store.quota_reached = True
            self.finish('quota_reached')
            return
        try:
            self.waves[name].writeframesraw(pcm)
        except OSError as exc:
            self.store.last_error = str(exc)
            LOG.warning('WAV-Aufnahme gestoppt: %s', exc)
            self.finish('recording_error')
            return
        self.bytes_written += len(pcm)
        self.store.used_bytes += len(pcm)

    def finish(self, status, text=None):
        if self.closed:
            return
        self.closed = True
        self.store.active.discard(self.id)
        for wav in self.waves.values():
            try:
                wav.close()
            except OSError as exc:
                self.store.last_error = str(exc)
                status = 'recording_error'
        self.meta['status'] = status
        if text is not None:
            self.meta['transcript'] = text
        try:
            (self.path / 'metadata.json').write_text(json.dumps(self.meta, ensure_ascii=False, indent=2) + '\n')
            actual = sum(p.stat().st_size for p in self.path.iterdir() if p.is_file())
            self.store.used_bytes += actual - self.bytes_written - self.reserved
        except OSError as exc:
            self.store.last_error = str(exc)
            LOG.warning('Aufnahme konnte nicht gespeichert werden: %s', exc)
