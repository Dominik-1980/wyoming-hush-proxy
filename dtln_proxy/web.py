"""Small same-origin LAN UI: settings and opt-in recording downloads."""
from dataclasses import asdict
import json
from pathlib import Path
from urllib.parse import urlsplit
from aiohttp import web
from . import __version__
from .recording import CLIP_ID as CLIP


def create_app(proxy):
    @web.middleware
    async def headers(request, handler):
        response = await handler(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    app = web.Application(client_max_size=4096, middlewares=[headers])

    async def index(request):
        return web.Response(text=Path(__file__).with_name('index.html').read_text(), content_type='text/html')

    async def logo(request):
        return web.FileResponse(Path(__file__).resolve().parent.parent / 'assets' / 'logo.png')

    async def state(request):
        return web.json_response({'version': __version__, 'settings': asdict(proxy.settings.current),
            'active_sessions': proxy.active_sessions, 'total_sessions': proxy.total_sessions,
            'last_error': proxy.last_error, 'last_run': proxy.last_run,
            'upstream': f'{proxy.upstream[0]}:{proxy.upstream[1]}',
            'storage': {'used_bytes': proxy.recordings.used_bytes, 'max_bytes': proxy.recordings.max_bytes,
                        'quota_reached': proxy.recordings.quota_reached, 'last_error': proxy.recordings.last_error}})

    async def mutation_body(request):
        origin = request.headers.get('Origin')
        if request.content_type != 'application/json' or (origin and urlsplit(origin).netloc != request.host):
            raise web.HTTPForbidden(text='Nur JSON vom selben Ursprung erlaubt')
        try:
            body = await request.json()
        except (ValueError, TypeError) as exc:
            raise web.HTTPBadRequest(text='Ungültiges JSON') from exc
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text='JSON-Objekt erwartet')
        return body

    async def update(request):
        body = await mutation_body(request)
        try:
            settings = proxy.settings.update(body)
        except (ValueError, TypeError) as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        except OSError as exc:
            raise web.HTTPInternalServerError(text='Einstellungen konnten nicht gespeichert werden') from exc
        return web.json_response(asdict(settings))

    async def remove_recording(request):
        body = await mutation_body(request)
        if body.get('confirm') is not True:
            raise web.HTTPBadRequest(text='Löschen muss ausdrücklich bestätigt werden')
        try:
            clip_id = request.match_info.get('clip')
            result = {'deleted': proxy.recordings.delete(clip_id), 'active_skipped':0} if clip_id else proxy.recordings.delete_all()
            return web.json_response(result)
        except FileNotFoundError as exc:
            raise web.HTTPNotFound(text='Aufnahme nicht gefunden') from exc
        except BlockingIOError as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        except OSError as exc:
            raise web.HTTPInternalServerError(text='Aufnahme konnte nicht gelöscht werden') from exc

    async def recordings(request):
        clips = []
        paths = sorted(proxy.recordings.root.iterdir(), reverse=True)
        for path in paths:
            if path.is_symlink() or not path.is_dir() or path.name in proxy.recordings.active or not CLIP.fullmatch(path.name):
                continue
            meta = path / 'metadata.json'
            if not meta.exists():
                continue
            try:
                item = json.loads(meta.read_text())
                item['bytes'] = sum(p.stat().st_size for p in path.iterdir() if p.is_file())
                clips.append(item)
            except (OSError, ValueError):
                continue
            if len(clips) == 100:
                break
        return web.json_response(clips)

    async def download(request):
        clip = request.match_info['clip']
        filename = request.match_info['filename']
        if not CLIP.fullmatch(clip) or filename not in ('original.wav', 'filtered.wav', 'metadata.json'):
            raise web.HTTPNotFound()
        target = proxy.recordings.root / clip / filename
        if not target.is_file() or not target.resolve().is_relative_to(proxy.recordings.root.resolve()):
            raise web.HTTPNotFound()
        # Ongoing clips are not downloadable until WAV headers have been finalized.
        if not (target.parent / 'metadata.json').is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(target, headers={'Content-Disposition': f'inline; filename="{clip}-{filename}"'})

    async def health(request):
        return web.json_response({'status': 'ready', 'version': __version__})

    app.add_routes([web.get('/', index), web.get('/assets/logo.png', logo), web.get('/api/state', state), web.post('/api/settings', update),
                    web.get('/api/recordings', recordings), web.delete('/api/recordings', remove_recording),
                    web.delete('/api/recordings/{clip}', remove_recording), web.get('/recordings/{clip}/{filename}', download),
                    web.get('/healthz', health)])
    return app
