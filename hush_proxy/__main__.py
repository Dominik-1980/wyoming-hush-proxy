import asyncio
import logging
import os
from pathlib import Path
import signal
from aiohttp import web
from .vendor._hush_model import HushModel
from .settings import SettingsStore
from .recording import RecordingStore
from .proxy import Proxy
from .web import create_app


async def main():
    logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'), format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    data = Path(os.getenv('DATA_DIR', '/data'))
    settings = SettingsStore(data)
    model = await asyncio.to_thread(HushModel)
    max_sessions = int(os.getenv('MAX_SESSIONS', '2'))
    max_seconds = int(os.getenv('MAX_AUDIO_SECONDS', '60'))
    max_mb = int(os.getenv('MAX_RECORDING_MB', '512'))
    if not 1 <= max_sessions <= 8 or not 1 <= max_seconds <= 600 or not 1 <= max_mb <= 102400:
        raise ValueError('Ungültige Ressourcenlimits')
    recordings = RecordingStore(data, max_mb * 1024 * 1024)
    proxy = Proxy(model, settings, recordings, os.getenv('UPSTREAM_URI'), max_audio_seconds=max_seconds, max_sessions=max_sessions)
    host = os.getenv('LISTEN_HOST', '0.0.0.0')
    server = await asyncio.start_server(proxy.handle_client, host, int(os.getenv('WYOMING_PORT', '10322')))
    runner = web.AppRunner(create_app(proxy), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, int(os.getenv('WEB_PORT', '10323'))).start()
    logging.getLogger(__name__).info('Hush bereit; Wyoming %s, Web %s; Aufnahme %s',
        os.getenv('WYOMING_PORT', '10322'), os.getenv('WEB_PORT', '10323'), settings.current.recording_enabled)
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        server.close()
        await server.wait_closed()
        await proxy.close()
        await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
