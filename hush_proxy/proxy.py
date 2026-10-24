"""Wyoming ASR bridge. No Home Assistant API or cloud dependency."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import logging
import time
from urllib.parse import urlparse
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.asr import Transcribe, Transcript
from wyoming.client import AsyncTcpClient
from wyoming.error import Error
from wyoming.event import Event, async_write_event
from wyoming.info import Describe, Info
from .audio import AudioStream
from . import __version__

LOG = logging.getLogger(__name__)


async def read_event(reader):
    """Wyoming framing with bounded headers, metadata and audio payloads."""
    line = await reader.readline()
    if not line:
        return None
    obj = json.loads(line)
    if not isinstance(obj, dict) or not isinstance(obj.get('type'), str):
        raise ValueError('Ungültiges Wyoming-Ereignis')
    data = obj.get('data', {})
    if not isinstance(data, dict):
        raise ValueError('Ungültige Metadaten')
    payload = None
    for key, maximum in (('data_length', 65536), ('payload_length', 262144)):
        size = obj.get(key, 0)
        if type(size) is not int or not 0 <= size <= maximum:
            raise ValueError('Wyoming-Ereignis überschreitet das Größenlimit')
        if size:
            block = await reader.readexactly(size)
            if key == 'data_length':
                extra = json.loads(block)
                if not isinstance(extra, dict):
                    raise ValueError('Ungültige Metadaten')
                data.update(extra)
            else:
                payload = block
    return Event(type=obj['type'], data=data, payload=payload)


def upstream_address(uri):
    parsed = urlparse(uri)
    if parsed.scheme != 'tcp' or not parsed.hostname or not parsed.port or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('UPSTREAM_URI muss tcp://host:port sein')
    return parsed.hostname, parsed.port


class Proxy:
    def __init__(self, model, settings, recordings, upstream_uri=None, max_audio_seconds=60, max_sessions=2, upstream_timeout=30):
        self.model = model
        self.settings = settings
        self.recordings = recordings
        # Environment/constructor supplies initial defaults; saved UI settings win.
        if upstream_uri and not settings.current.upstream_host:
            host, port = upstream_address(upstream_uri)
            settings.current = settings.validate({'upstream_host': host, 'upstream_port': port})
        self.max_audio_bytes = int(max_audio_seconds * 16000 * 2)
        self.max_sessions = max_sessions
        self.upstream_timeout = upstream_timeout
        self.active_sessions = 0
        self.total_sessions = 0
        self.last_error = None
        self.last_run = None
        self.clients = set()
        self.executor = ThreadPoolExecutor(max_workers=max_sessions, thread_name_prefix='hush')
        self._info_cache = None

    @property
    def upstream(self):
        current = self.settings.current
        return current.upstream_host, current.upstream_port

    async def info(self):
        target = self.upstream
        if not target[0]:
            raise ValueError('Bitte zuerst STT-Host und Port in der Weboberfläche einstellen')
        if self._info_cache and self._info_cache[0] == target and time.monotonic() - self._info_cache[1] < 15:
            return self._info_cache[2]
        client = AsyncTcpClient(*target)
        try:
            async with asyncio.timeout(5):
                await client.connect()
                await client.write_event(Describe().event())
                reply = await read_event(client._reader)
                if reply is None or not Info.is_type(reply.type):
                    raise ValueError('STT-Ziel antwortet nicht mit Wyoming-Informationen')
                services = reply.data.get('asr', [])
                models = [dict(model) for service in services for model in service.get('models', [])
                          if model.get('installed', True)]
                if not models:
                    raise ValueError('STT-Ziel bietet kein installiertes ASR-Modell an')
                announcement = Event(type='info', data={'asr': [{
                    'name': 'wyoming-speech-filter', 'installed': True, 'version': __version__,
                    'description': 'Wyoming Sprachfilter Proxy',
                    'attribution': {'name': 'Wyoming Hush Proxy', 'url': 'https://github.com/Dominik-1980/wyoming-hush-proxy'},
                    'models': models,
                    'supports_transcript_streaming': any(s.get('supports_transcript_streaming', False) for s in services),
                    'requires_external_vad': True,
                }]})
                self._info_cache = target, time.monotonic(), announcement
                return announcement
        finally:
            await client.disconnect()

    async def compute(self, fn, *args):
        future = asyncio.get_running_loop().run_in_executor(self.executor, fn, *args)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # Do not close a session while its worker is still using ONNX/DSP state.
            await asyncio.shield(future)
            raise

    async def handle_client(self, reader, writer):
        task = asyncio.current_task()
        self.clients.add(task)
        backend = None
        stream = None
        recording = None
        acquired = False
        try:
            # HA may describe and transcribe on the same connection.
            while True:
                event = await asyncio.wait_for(read_event(reader), 30)
                if event is None:
                    return
                if Describe.is_type(event.type):
                    await async_write_event(await self.info(), writer)
                    continue
                if not Transcribe.is_type(event.type):
                    raise ValueError('Erwartet: transcribe')
                break
            if self.active_sessions >= self.max_sessions:
                raise ValueError('Alle Hush-Sitzungen sind belegt; bitte erneut versuchen')
            self.active_sessions += 1
            acquired = True
            settings = self.settings.current
            if not settings.upstream_host:
                raise ValueError('STT-Ziel ist noch nicht konfiguriert')
            backend = AsyncTcpClient(settings.upstream_host, settings.upstream_port)
            await asyncio.wait_for(backend.connect(), 5)
            transcribe = Transcribe.from_event(event)
            # Legacy generic IDs are local aliases; real discovered model IDs pass through.
            model_name = transcribe.name
            if model_name in ('hush-kroko', 'hush-kroko-filter', 'wyoming-speech-filter'):
                model_name = None
            await backend.write_event(Transcribe(name=model_name, language=transcribe.language, context=transcribe.context).event())
            start = await asyncio.wait_for(read_event(reader), 30)
            if start is None or not AudioStart.is_type(start.type):
                raise ValueError('Erwartet: audio-start')
            fmt = AudioStart.from_event(start)
            if (fmt.rate, fmt.width, fmt.channels) != (16000, 2, 1):
                raise ValueError('Benötigt 16000 Hz, Mono, PCM16')
            stream = await self.compute(AudioStream, self.model, settings.filter_enabled, settings.atten_lim_db)
            if settings.recording_enabled:
                try:
                    recording = self.recordings.start(settings)
                except OSError:
                    self.recordings.last_error = 'Aufnahmeordner ist nicht beschreibbar'
                    LOG.exception('Aufnahme konnte nicht gestartet werden; STT läuft weiter')
            await backend.write_event(AudioStart(rate=16000, width=2, channels=1).event())
            started = time.monotonic()
            filter_seconds = 0.0

            async def send_audio(pcm):
                nonlocal recording
                if not pcm:
                    return
                if recording:
                    try:
                        recording.write('filtered', pcm)
                    except OSError:
                        LOG.exception('Aufnahmefehler; STT läuft weiter')
                        recording.finish('recording_error')
                        recording = None
                await asyncio.wait_for(backend.write_event(AudioChunk(rate=16000, width=2, channels=1, audio=pcm).event()), 10)

            while True:
                if time.monotonic() - started > self.max_audio_bytes / 32000 + 30:
                    raise ValueError('Zeitlimit der Aufnahme erreicht')
                event = await asyncio.wait_for(read_event(reader), 30)
                if event is None:
                    return
                if AudioStop.is_type(event.type):
                    tick = time.perf_counter()
                    await send_audio(await self.compute(stream.finish))
                    filter_seconds += time.perf_counter() - tick
                    break
                if not AudioChunk.is_type(event.type):
                    raise ValueError('Erwartet: audio-chunk oder audio-stop')
                chunk = AudioChunk.from_event(event)
                if (chunk.rate, chunk.width, chunk.channels) != (16000, 2, 1) or len(chunk.audio) % 2:
                    raise ValueError('Ungültiges PCM16-Format')
                if stream.input_bytes + len(chunk.audio) > self.max_audio_bytes:
                    raise ValueError('Maximale Audiodauer überschritten')
                if recording:
                    try:
                        recording.write('original', chunk.audio)
                    except OSError:
                        LOG.exception('Aufnahmefehler; STT läuft weiter')
                        recording.finish('recording_error')
                        recording = None
                tick = time.perf_counter()
                filtered = await self.compute(stream.feed, chunk.audio)
                filter_seconds += time.perf_counter() - tick
                await send_audio(filtered)
            await backend.write_event(AudioStop().event())
            async with asyncio.timeout(self.upstream_timeout):
                while True:
                    reply = await backend.read_event()
                    if reply is None:
                        raise ConnectionError('STT-Verbindung vor dem Transkript beendet')
                    if Error.is_type(reply.type):
                        # Preserve the backend's structured error for the caller.
                        await async_write_event(reply, writer)
                        self.last_error = 'Der STT-Dienst hat einen Fehler gemeldet'
                        return
                    if Transcript.is_type(reply.type):
                        await async_write_event(reply, writer)
                        if recording:
                            recording.finish('complete', Transcript.from_event(reply).text)
                        self.total_sessions += 1
                        self.last_error = None
                        self.last_run = {'audio_s': stream.input_bytes / 32000, 'filter_s': round(filter_seconds, 4),
                                         'settings': asdict(settings)}
                        return
                    # Forward partial transcript events if a future backend uses them.
                    if reply.type in ('transcript-start', 'transcript-chunk', 'transcript-stop'):
                        await async_write_event(reply, writer)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = f'{type(exc).__name__}: {exc}'
            LOG.warning('Wyoming-Anfrage abgebrochen: %s', self.last_error)
            try:
                await async_write_event(Error(text=self.last_error, code='hush-proxy-error').event(), writer)
            except (OSError, ConnectionError):
                pass
        finally:
            if recording:
                try:
                    recording.finish('aborted')
                except OSError:
                    LOG.exception('Aufnahme konnte nicht abgeschlossen werden')
            if stream:
                await self.compute(stream.close)
            if backend:
                try:
                    await backend.disconnect()
                except OSError:
                    pass
            if acquired:
                self.active_sessions -= 1
            writer.close()
            self.clients.discard(task)

    async def close(self):
        tasks = list(self.clients)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.executor.shutdown(wait=True)
