import json
from pathlib import Path
import tempfile
import unittest
from dtln_proxy.recording import RecordingStore
from dtln_proxy.settings import SettingsStore


class SettingsTests(unittest.TestCase):
    def test_target_validation_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory))
            for invalid in ('http://host', '../outside', 'host/name', 'a b', 'name\nheader'):
                with self.subTest(host=invalid), self.assertRaises(ValueError):
                    store.update({'upstream_host':invalid})
            for invalid in (0, 65536, True, '10300'):
                with self.subTest(port=invalid), self.assertRaises(ValueError):
                    store.update({'upstream_port':invalid})
            store.update({'upstream_host':'stt-service', 'upstream_port':10401})
            loaded = SettingsStore(Path(directory))
            self.assertEqual(loaded.current.upstream_host, 'stt-service')
            self.assertEqual(loaded.current.upstream_port, 10401)
            store.update({'upstream_host':'::1'})

    def test_legacy_settings_keep_existing_filter_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/'settings.json').write_text(json.dumps({'filter_enabled':True,'recording_enabled':True,'atten_lim_db':18}))
            store = SettingsStore(path)
            self.assertEqual(store.current.atten_lim_db, 18)
            self.assertTrue(store.current.recording_enabled)
            self.assertEqual(store.current.upstream_host, '')


class RecordingDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = SettingsStore(self.root)
        self.store = RecordingStore(self.root, 1024*1024)

    def tearDown(self):
        self.temp.cleanup()

    def clip(self, complete=True):
        record = self.store.start(self.settings.current)
        record.write('original', bytes(1024))
        record.write('filtered', bytes(1024))
        if complete:
            record.finish('complete', 'Synthetic test')
        return record

    def test_delete_one_releases_quota_and_keeps_settings(self):
        self.settings.update({'filter_enabled':False})
        first, second = self.clip(), self.clip()
        before = self.store.used_bytes
        self.store.quota_reached = True
        self.assertEqual(self.store.delete(first.id), 1)
        self.assertFalse(first.path.exists())
        self.assertTrue(second.path.exists())
        self.assertTrue(self.settings.path.exists())
        self.assertLess(self.store.used_bytes, before)
        self.assertFalse(self.store.quota_reached)
        actual = sum(p.stat().st_size for p in self.store.root.rglob('*') if p.is_file())
        self.assertEqual(self.store.used_bytes, actual)

    def test_delete_all_keeps_active_and_unrelated_paths(self):
        first, second, active = self.clip(), self.clip(), self.clip(False)
        unrelated = self.store.root/'unrelated'
        unrelated.mkdir()
        try:
            with self.assertRaises(BlockingIOError):
                self.store.delete(active.id)
            result = self.store.delete_all()
            self.assertEqual(result['deleted'], 2)
            self.assertEqual(result['active_skipped'], 1)
            self.assertTrue(active.path.exists())
            self.assertTrue(unrelated.exists())
            self.assertFalse(first.path.exists())
            self.assertFalse(second.path.exists())
        finally:
            active.finish('aborted')

    def test_traversal_symlink_and_unknown_file_protection(self):
        outside = self.root/'outside.wav'
        outside.write_bytes(b'keep')
        for invalid in ('../outside.wav','abc',''):
            with self.assertRaises(ValueError):
                self.store.delete(invalid)
        link = self.store.root/'20260101T000000Z-000000000001'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.store.delete(link.name)
        record = self.clip()
        (record.path/'unknown.txt').write_text('keep')
        with self.assertRaises(ValueError):
            self.store.delete(record.id)
        self.assertTrue((record.path/'original.wav').exists())
        result = self.store.delete_all()
        self.assertEqual(result['protected_skipped'], 2)
        self.assertEqual(outside.read_bytes(), b'keep')

    def test_nested_symlink_is_not_followed(self):
        record = self.clip()
        (record.path/'filtered.wav').unlink()
        outside = self.root/'protected.wav'
        outside.write_bytes(b'keep')
        (record.path/'filtered.wav').symlink_to(outside)
        with self.assertRaises(ValueError):
            self.store.delete(record.id)
        self.assertEqual(outside.read_bytes(), b'keep')
        self.assertTrue((record.path/'original.wav').exists())
