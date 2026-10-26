import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave
import numpy as np
from aiohttp.test_utils import TestClient, TestServer
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.asr import Transcribe, Transcript
from wyoming.client import AsyncTcpClient
from wyoming.error import Error
from wyoming.info import Describe, Info, AsrModel, AsrProgram, Attribution
from dtln_proxy.audio import AudioStream, FilterModels
from dtln_proxy.proxy import Proxy, read_event
from dtln_proxy.recording import RecordingStore
from dtln_proxy.settings import SettingsStore
from dtln_proxy.vendor._hush_model import HushModel
from dtln_proxy.web import create_app


MODEL = None


def setUpModule():
    global MODEL
    MODEL = FilterModels()


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.pcm = np.random.default_rng(7).integers(-8000, 8000, 1631, dtype=np.int16).astype('<i2').tobytes()

    def render(self, pcm, chunk_size, limit=12):
        stream = AudioStream(MODEL, True, limit, dtln_enabled=False)
        try:
            return b''.join(stream.feed(pcm[i:i + chunk_size]) for i in range(0, len(pcm), chunk_size)) + stream.finish()
        finally:
            stream.close()

    def test_fragmented_input_matches_single_feed_and_preserves_tail(self):
        whole = self.render(self.pcm, len(self.pcm))
        for size in (2, 318, 642, 2048):
            with self.subTest(size=size):
                self.assertEqual(whole, self.render(self.pcm, size))
                self.assertEqual(len(whole), len(self.pcm))

    def test_zero_db_roundtrip_delay_alignment_and_partial_frame(self):
        output = self.render(self.pcm, 318, 0)
        delta = np.frombuffer(output, '<i2').astype(int) - np.frombuffer(self.pcm, '<i2').astype(int)
        self.assertLessEqual(np.max(np.abs(delta)), 1)

    def test_new_session_clears_neural_and_dsp_history(self):
        first = self.render(self.pcm, 320)
        self.render(bytes(1280), 320)
        self.assertEqual(first, self.render(self.pcm, 320))

    def test_bypass_is_bit_exact(self):
        stream = AudioStream(MODEL, False)
        self.assertEqual(stream.feed(self.pcm) + stream.finish(), self.pcm)

    def test_empty_and_odd_audio(self):
        self.assertEqual(self.render(b'', 320), b'')
        stream = AudioStream(MODEL)
        stream.feed(b'\x00')
        with self.assertRaises(ValueError):
            stream.finish()
        stream.close()


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = SettingsStore(self.root)
        self.settings.update({'filter_enabled': False})
        self.recordings = RecordingStore(self.root, 1024 * 1024)
        self.received = []
        self.chunk_seen = asyncio.Event()
        self.backend_failure = None
        self.backend_writers = set()

        async def backend(reader, writer):
            self.backend_writers.add(writer)
            try:
                data = bytearray()
                transcribe = None
                while event := await read_event(reader):
                    if Describe.is_type(event.type):
                        from wyoming.event import async_write_event
                        attribution = Attribution(name='Test STT', url='https://example.org')
                        info = Info(asr=[AsrProgram(name='test-asr', attribution=attribution, installed=True,
                            description='Test backend', version='1', models=[AsrModel(name='test-model', attribution=attribution,
                                installed=True, description='Multilingual', version='1', languages=['de','en','fr'])])])
                        await async_write_event(info.event(), writer)
                        continue
                    if event.type == 'transcribe':
                        transcribe = event.data
                    if AudioChunk.is_type(event.type):
                        data.extend(event.payload)
                        self.chunk_seen.set()
                    if AudioStop.is_type(event.type):
                        self.received.append((bytes(data), transcribe))
                        if self.backend_failure == 'disconnect':
                            return
                        result = Error(text='backend error', code='test-error') if self.backend_failure else Transcript(text='Test erfolgreich')
                        from wyoming.event import async_write_event
                        await async_write_event(result.event(), writer)
                        return
            finally:
                writer.close()
                self.backend_writers.discard(writer)

        self.backend = await asyncio.start_server(backend, '127.0.0.1', 0)
        port = self.backend.sockets[0].getsockname()[1]
        self.proxy = Proxy(MODEL, self.settings, self.recordings, f'tcp://127.0.0.1:{port}')
        self.server = await asyncio.start_server(self.proxy.handle_client, '127.0.0.1', 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.disconnect()
        self.server.close()
        await self.server.wait_closed()
        await self.proxy.close()
        self.backend.close()
        await self.backend.wait_closed()
        for writer in self.backend_writers:
            writer.close()
        await asyncio.sleep(0)
        self.temp.cleanup()

    async def client(self):
        client = AsyncTcpClient('127.0.0.1', self.port)
        await client.connect()
        self.clients.append(client)
        return client

    async def begin(self, client, rate=16000):
        await client.write_event(Transcribe(name='hush-kroko', language='de', context={'test': True}).event())
        await client.write_event(AudioStart(rate=rate, width=2, channels=1).event())

    async def chunk(self, client, pcm):
        await client.write_event(AudioChunk(rate=16000, width=2, channels=1, audio=pcm).event())

    async def end(self, client):
        await client.write_event(AudioStop().event())
        return await asyncio.wait_for(client.read_event(), 3)

    async def test_discovery_then_bit_exact_passthrough_and_context(self):
        client = await self.client()
        await client.write_event(Describe().event())
        info = await client.read_event()
        self.assertTrue(Info.is_type(info.type))
        self.assertTrue(info.data['asr'][0]['requires_external_vad'])
        self.assertEqual(info.data['asr'][0]['name'], 'wyoming-speech-filter')
        self.assertEqual(info.data['asr'][0]['models'][0]['languages'], ['de','en','fr'])
        await self.begin(client)
        pcm = np.arange(1741, dtype='<i2').tobytes()
        await self.chunk(client, pcm)
        self.assertTrue(Transcript.is_type((await self.end(client)).type))
        self.assertEqual(self.received[0][0], pcm)
        self.assertNotIn('name', self.received[0][1])
        self.assertEqual(self.received[0][1]['context'], {'test': True})

    async def test_real_cascade_streams_before_audio_stop_and_preserves_samples(self):
        self.settings.update({'filter_enabled': True})
        client = await self.client()
        await self.begin(client)
        pcm = np.random.default_rng(5).integers(-2000, 2000, 2301, dtype=np.int16).tobytes()
        await self.chunk(client, pcm[:2048])
        await asyncio.wait_for(self.chunk_seen.wait(), 3)
        self.assertEqual(self.received, [])
        await self.chunk(client, pcm[2048:])
        self.assertTrue(Transcript.is_type((await self.end(client)).type))
        reference = AudioStream(MODEL)
        expected = reference.feed(pcm) + reference.finish()
        reference.close()
        self.assertEqual(self.received[0][0], expected)
        self.assertEqual(len(expected), len(pcm))

    async def test_stage_settings_are_snapshotted_for_the_utterance(self):
        self.settings.update({'filter_enabled':True,'dtln_enabled':True,'hush_enabled':True,'recording_enabled':True,'atten_lim_db':16})
        pcm = np.random.default_rng(66).integers(-4000,4000,2307,dtype=np.int16).tobytes()
        client = await self.client()
        await self.begin(client)
        await self.chunk(client,pcm[:2048])
        await asyncio.wait_for(self.chunk_seen.wait(),3)
        self.settings.update({'dtln_enabled':False,'hush_enabled':False})
        await self.chunk(client,pcm[2048:])
        await self.end(client)
        reference = AudioStream(MODEL,True,16,True,True)
        try: expected = reference.feed(pcm)+reference.finish()
        finally: reference.close()
        self.assertEqual(self.received[-1][0],expected)
        metadata = json.loads(next(self.recordings.root.glob('*/metadata.json')).read_text())
        self.assertTrue(metadata['settings']['dtln_enabled'])
        self.assertTrue(metadata['settings']['hush_enabled'])
        second = await self.client()
        await self.begin(second)
        await self.chunk(second,pcm)
        await self.end(second)
        self.assertEqual(self.received[-1][0],pcm)

    async def test_paired_recording_and_setting_snapshot(self):
        self.settings.update({'recording_enabled': True})
        client = await self.client()
        await self.begin(client)
        pcm = bytes(1024)
        await self.chunk(client, pcm)
        await asyncio.wait_for(self.chunk_seen.wait(), 3)
        self.settings.update({'filter_enabled': True, 'recording_enabled': False})
        await self.chunk(client, pcm)
        await self.end(client)
        await asyncio.sleep(.02)
        clips = list(self.recordings.root.iterdir())
        self.assertEqual(len(clips), 1)
        metadata = json.loads((clips[0] / 'metadata.json').read_text())
        self.assertEqual(metadata['status'], 'complete')
        self.assertFalse(metadata['settings']['filter_enabled'])
        for name in ('original.wav', 'filtered.wav'):
            with wave.open(str(clips[0] / name)) as wav:
                self.assertEqual(wav.readframes(wav.getnframes()), pcm + pcm)

    async def test_invalid_rate_and_oversize_audio_return_errors(self):
        client = await self.client()
        await self.begin(client, 8000)
        self.assertTrue(Error.is_type((await client.read_event()).type))
        self.proxy.max_audio_bytes = 100
        client2 = await self.client()
        await self.begin(client2)
        await self.chunk(client2, bytes(1024))
        self.assertTrue(Error.is_type((await client2.read_event()).type))

    async def test_backend_errors_and_disconnects(self):
        for failure in ('error', 'disconnect'):
            self.backend_failure = failure
            client = await self.client()
            await self.begin(client)
            await self.chunk(client, bytes(320))
            reply = await self.end(client)
            self.assertTrue(Error.is_type(reply.type))
            if failure == 'error':
                self.assertEqual(reply.data['code'], 'test-error')

    async def test_busy_limit_and_disconnect_cleanup(self):
        self.proxy.max_sessions = 1
        first = await self.client()
        await self.begin(first)
        await self.chunk(first, bytes(320))
        await asyncio.wait_for(self.chunk_seen.wait(), 3)
        second = await self.client()
        await second.write_event(Transcribe(language='de').event())
        self.assertTrue(Error.is_type((await second.read_event()).type))
        await first.disconnect()
        await asyncio.sleep(.05)
        self.assertEqual(self.proxy.active_sessions, 0)

    async def test_bounded_wire_lengths(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b'{"type":"audio-chunk","payload_length":99999999}\n')
        with self.assertRaises(ValueError):
            await read_event(reader)

    async def test_quota_does_not_interrupt_transcription(self):
        self.proxy.recordings.max_bytes = 9000
        self.settings.update({'recording_enabled': True})
        client = await self.client()
        await self.begin(client)
        await self.chunk(client, bytes(2048))
        self.assertTrue(Transcript.is_type((await self.end(client)).type))
        self.assertTrue(self.recordings.quota_reached)

    async def test_disk_errors_do_not_interrupt_transcription(self):
        self.settings.update({'recording_enabled': True})
        original_write = wave.Wave_write.writeframesraw
        def full_disk(wav, pcm):
            if pcm:
                raise OSError('test: disk full')
            return original_write(wav, pcm)
        for target, replacement in ((wave.Wave_write, full_disk), (Path, None)):
            with self.subTest(stage=target.__name__):
                client = await self.client()
                patcher = patch.object(target, 'writeframesraw', replacement) if replacement else patch.object(Path, 'write_text', side_effect=OSError('test: disk full'))
                with patcher:
                    await self.begin(client)
                    await self.chunk(client, bytes(2048))
                    self.assertTrue(Transcript.is_type((await self.end(client)).type))
                    await asyncio.sleep(.01)
                self.assertIsNotNone(self.recordings.last_error)

    async def test_web_controls_origin_guard_and_download_path(self):
        async with TestClient(TestServer(create_app(self.proxy))) as client:
            origin = str(client.make_url('/')).rstrip('/')
            response = await client.post('/api/settings', json={'recording_enabled': True}, headers={'Origin':origin})
            self.assertEqual(response.status, 200)

            response = await client.post('/api/settings', json={'filter_enabled': True}, headers={'Origin':'https://elsewhere.invalid'})
            self.assertEqual(response.status, 403)
            self.assertFalse(self.settings.current.filter_enabled)
            response = await client.post('/api/settings', json={'atten_lim_db':-1})
            self.assertEqual(response.status, 400)
            response = await client.get('/recordings/invalid/settings.json')
            self.assertEqual(response.status, 404)
            response = await client.get('/healthz')
            self.assertEqual(response.status, 200)

    async def test_model_and_language_are_forwarded(self):
        client = await self.client()
        await client.write_event(Transcribe(name='test-model', language='fr').event())
        await client.write_event(AudioStart(rate=16000, width=2, channels=1).event())
        await self.chunk(client, bytes(320))
        await self.end(client)
        self.assertEqual(self.received[-1][1]['name'], 'test-model')
        self.assertEqual(self.received[-1][1]['language'], 'fr')

    async def test_branded_ui_logo_and_default_hint(self):
        async with TestClient(TestServer(create_app(self.proxy))) as client:
            response=await client.get('/')
            text=await response.text()
            self.assertIn('Wyoming Noise Cancelling Proxy',text)
            self.assertIn('12 dB Voreinstellung.',text)
            self.assertIn('/assets/logo.png',text)
            response=await client.get('/assets/logo.png')
            self.assertEqual(response.status,200)
            self.assertEqual(await response.read(),(Path(__file__).resolve().parents[1]/'assets/logo.png').read_bytes())

    async def test_target_change_applies_only_to_next_utterance(self):
        other_received = []
        async def other_backend(reader, writer):
            from wyoming.event import async_write_event
            data = bytearray()
            try:
                while event := await read_event(reader):
                    if AudioChunk.is_type(event.type):
                        data.extend(event.payload)
                    if AudioStop.is_type(event.type):
                        other_received.append(bytes(data))
                        await async_write_event(Transcript(text='Other target').event(), writer)
                        return
            finally:
                writer.close()
        other = await asyncio.start_server(other_backend, '127.0.0.1', 0)
        try:
            first = await self.client()
            await self.begin(first)
            await self.chunk(first, bytes(320))
            await asyncio.wait_for(self.chunk_seen.wait(), 3)
            self.settings.update({'upstream_host':'127.0.0.1', 'upstream_port':other.sockets[0].getsockname()[1]})
            self.assertEqual((await self.end(first)).data['text'], 'Test erfolgreich')
            second = await self.client()
            await self.begin(second)
            await self.chunk(second, bytes(640))
            self.assertEqual((await self.end(second)).data['text'], 'Other target')
            self.assertEqual(len(self.received), 1)
            self.assertEqual(other_received, [bytes(640)])
        finally:
            other.close()
            await other.wait_closed()

    async def test_recording_delete_api_requires_confirmation_and_origin(self):
        record = self.recordings.start(self.settings.current)
        record.write('original', bytes(320))
        record.write('filtered', bytes(320))
        record.finish('complete')
        async with TestClient(TestServer(create_app(self.proxy))) as client:
            response = await client.delete('/api/recordings/'+record.id, json={})
            self.assertEqual(response.status, 400)
            response = await client.delete('/api/recordings/'+record.id, json={'confirm':True}, headers={'Origin':'https://elsewhere.invalid'})
            self.assertEqual(response.status, 403)
            self.assertTrue(record.path.exists())
            response = await client.delete('/api/recordings/'+record.id, json={'confirm':True})
            self.assertEqual(response.status, 200)
            self.assertFalse(record.path.exists())
            active = self.recordings.start(self.settings.current)
            try:
                response = await client.delete('/api/recordings/'+active.id, json={'confirm':True})
                self.assertEqual(response.status, 409)
                response = await client.delete('/api/recordings', json={'confirm':True})
                self.assertEqual(response.status, 200)
                self.assertEqual((await response.json())['active_skipped'], 1)
            finally:
                active.finish('aborted')



if __name__ == '__main__':
    unittest.main()
