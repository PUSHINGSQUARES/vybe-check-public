"""Same-origin loopback board for versioned Vybe-Check prompt sessions."""

from __future__ import annotations

import errno
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import socket
from urllib.parse import parse_qs, urlsplit

import portalocker

from vybe_check import __version__
from vybe_check.workshop import ID_PATTERN, RevisionConflict, SessionStore

HERE = Path(__file__).resolve().parent
STATIC = {'/': 'index.html', '/app.css': 'app.css', '/app.js': 'app.js'}
BROWSER_ACTIONS = {'draft_edit', 'select_image_version', 'promote_preview'}
MAX_BODY = 65536
# Fixed JSON framing, a 32-character ID, and two 64-character SHA256 values.
SESSION_CHECK_SHAPE = {'id': '0' * 32, 'revision_fingerprint': '0' * 64,
                       'nonce_fingerprint': '0' * 64}
MAX_SESSION_CHECK_BYTES = len(json.dumps(SESSION_CHECK_SHAPE).encode('utf-8'))


def session_check(store, identifier):
    state = store.read(identifier)
    if state.get('id') != identifier or type(state.get('revision')) is not int:
        raise ValueError('Invalid listener session')
    return {'id': identifier,
            'revision_fingerprint': hashlib.sha256(str(state['revision']).encode('utf-8')).hexdigest(),
            'nonce_fingerprint': hashlib.sha256(store.nonce_for(identifier).encode('utf-8')).hexdigest()}


class UnavailablePreview:
    def capability(self):
        return {'available': False, 'reason': 'Local study unavailable'}

    def generate(self, *args, **kwargs):
        raise RuntimeError('Local study unavailable')


def board_identity(root):
    return {'application': 'vybe-check', 'version': __version__, 'protocol': 1,
            'root_fingerprint': hashlib.sha256(str(root.resolve()).encode('utf-8')).hexdigest()}


class BoardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, store, preview=None, active_id=None):
        if address[0] != '127.0.0.1':
            raise ValueError('Loopback address required')
        if active_id is not None:
            store.read(active_id)
        super().__init__(address, handler)
        try:
            self.store = store
            self.preview = preview if preview is not None else UnavailablePreview()
            self.active_id = active_id if active_id is not None else store.create()['id']
        except BaseException:
            self.server_close()
            raise


def create_server(port=8765, *, root=None, store=None, preview=None, active_id=None):
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError('Invalid board port')
    if store is None:
        store = SessionStore(root)
    elif root is not None and Path(root).expanduser().resolve() != store.root.resolve():
        raise ValueError('Mismatched workshop root')
    return BoardServer(('127.0.0.1', port), BoardHandler, store, preview, active_id)


def _listener_json(port, route):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
    try:
        connection.request('GET', route)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('Incompatible listener')
        limit = MAX_SESSION_CHECK_BYTES if route.split('?', 1)[0] == '/api/session-check' else 8192
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('Incompatible listener')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('Incompatible listener')
        return value
    finally:
        connection.close()


def compatible_session(port, store, session_id=None):
    """Verify both identity and a session before returning an existing URL."""
    identity = _listener_json(port, '/api/identity')
    if (type(identity.get('protocol')) is not int or identity != board_identity(store.root)):
        raise ValueError('Incompatible listener')
    route = '/api/session-check' + ('?id=' + session_id if session_id is not None else '')
    remote = _listener_json(port, route)
    identifier = remote.get('id')
    if not isinstance(identifier, str) or not ID_PATTERN.fullmatch(identifier):
        raise ValueError('Unknown listener session')
    if session_id is not None and identifier != session_id:
        raise ValueError('Unknown listener session')
    local = session_check(store, identifier)
    if set(remote) != set(SESSION_CHECK_SHAPE):
        raise ValueError('Unknown listener session')
    for field in ('nonce_fingerprint', 'revision_fingerprint'):
        value = remote[field]
        if (not isinstance(value, str) or len(value) != 64 or
                any(char not in '0123456789abcdef' for char in value) or
                not secrets.compare_digest(value, local[field])):
            raise ValueError('Unknown listener session')
    return identifier


def run_board(root, session_id=None, port=8765, *, preview=None):
    store = SessionStore(root)
    if session_id is not None:
        store.read(session_id)
    try:
        server = create_server(port, root=store.root, store=store, active_id=session_id, preview=preview)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        if preview is not None:
            raise ValueError('Local studies require an explicit alternate --port when a board is already running') from None
        try:
            identifier = compatible_session(port, store, session_id)
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            raise ValueError('Board port conflict; choose an explicit alternate --port') from None
        print(f'http://127.0.0.1:{port}/?session={identifier}', flush=True)
        return 0
    try:
        print(f'http://127.0.0.1:{server.server_port}/?session={server.active_id}', flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


class BoardHandler(BaseHTTPRequestHandler):
    server: BoardServer

    def setup(self):
        super().setup()
        self.connection.settimeout(2)

    def log_message(self, *args):
        # The board URL and request paths need not be logged.
        pass

    def _origin(self):
        return f'http://127.0.0.1:{self.server.server_port}'

    def _single_header(self, name):
        values = self.headers.get_all(name, [])
        return values[0] if len(values) == 1 else None

    def _host_ok(self):
        return self._single_header('Host') == f'127.0.0.1:{self.server.server_port}'

    def _base_headers(self, length, content_type):
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; media-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'")

    def _bytes(self, payload, content_type, status=200):
        self.send_response(status)
        self._base_headers(len(payload), content_type)
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, value, status=200):
        self._bytes(json.dumps(value, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8', status)

    def _session(self, session_id):
        state = self.server.store.read(session_id)
        state['nonce'] = self.server.store.nonce_for(session_id)
        for name in ('references', 'previews', 'assets'):
            state[name] = [{**item, 'url': f"/media/{session_id}/{item['id']}"} for item in state.get(name, [])]
        return state

    def do_GET(self):  # noqa: N802
        if not self._host_ok() or (self.headers.get_all('Origin') and self._single_header('Origin') != self._origin()):
            self._json({'error': 'Foreign request'}, 403)
            return
        parsed = urlsplit(self.path)
        route = parsed.path
        try:
            if route in STATIC:
                path = HERE / STATIC[route]
                content_type = {'/': 'text/html; charset=utf-8', '/app.css': 'text/css; charset=utf-8', '/app.js': 'text/javascript; charset=utf-8'}[route]
                self._bytes(path.read_bytes(), content_type)
            elif route == '/api/identity':
                self._json(board_identity(self.server.store.root))
            elif route == '/api/session':
                requested = parse_qs(parsed.query).get('id', [self.server.active_id])[0]
                self._json(self._session(requested))
            elif route == '/api/session-check':
                requested = parse_qs(parsed.query).get('id', [self.server.active_id])[0]
                self._json(session_check(self.server.store, requested))
            elif route == '/api/capability':
                self._json(self.server.preview.capability())
            elif route.startswith('/media/'):
                parts = route.split('/')
                media = self.server.store.read_media(parts[2], parts[3]) if len(parts) == 4 else None
                if media is None:
                    self._json({'error': 'Media unavailable'}, 404)
                else:
                    data, mime = media
                    self._bytes(data, mime)
            else:
                self._json({'error': 'Not found'}, 404)
        except (OSError, ValueError, KeyError, TypeError, portalocker.exceptions.LockException):
            self._json({'error': 'Local state unavailable'}, 404)

    def do_POST(self):  # noqa: N802
        if not self._host_ok() or self._single_header('Origin') != self._origin():
            self._json({'error': 'Foreign request'}, 403)
            return
        content_type = self._single_header('Content-Type') or ''
        if content_type.split(';', 1)[0].strip().lower() != 'application/json':
            self._json({'error': 'JSON required'}, 415)
            return
        try:
            if self.headers.get_all('Transfer-Encoding'):
                raise ValueError('Invalid request')
            raw_length = self._single_header('Content-Length')
            if raw_length is None or not raw_length.isascii() or not raw_length.isdecimal():
                raise ValueError('Invalid request')
            length = int(raw_length)
            if not 2 <= length <= MAX_BODY:
                raise ValueError('Invalid request')
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('Invalid request')
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError('Invalid request')
            session_id, nonce = body.get('session_id'), body.get('nonce')
            try:
                authorised = (isinstance(session_id, str) and ID_PATTERN.fullmatch(session_id) and
                    isinstance(nonce, str) and bool(nonce) and secrets.compare_digest(
                        nonce.encode(), self.server.store.nonce_for(session_id).encode()))
            except (ValueError, OSError, KeyError, TypeError):
                authorised = False
            if not authorised:
                self._json({'error': 'Invalid session nonce'}, 403)
                return
            expected_revision = body.get('expected_revision')
            if type(expected_revision) is not int:
                raise ValueError('Invalid revision')
            route = urlsplit(self.path).path
            if route == '/api/event':
                if not isinstance(body.get('action'), str) or body['action'] not in BROWSER_ACTIONS or not isinstance(body.get('payload'), dict):
                    raise ValueError('Invalid action')
                result = self.server.store.apply(session_id, expected_revision, body['action'], body['payload'])
            elif route == '/api/preview':
                if type(body.get('prompt_version')) is not int or body['prompt_version'] < 1:
                    raise ValueError('Invalid version')
                try:
                    result = self.server.preview.generate(self.server.store, session_id, expected_revision,
                                                         body['prompt_version'], body.get('shot_id'))
                except RuntimeError:
                    self._json({'error': 'Local study unavailable'}, 409)
                    return
                if isinstance(result, dict) and result.get('status') == 'unregistered':
                    self._json({'status': 'unregistered', 'error':
                        'Generation completed after the session changed. The file is preserved and not registered; reconcile it explicitly.'}, 409)
                    return
            else:
                self._json({'error': 'Not found'}, 404)
                return
            self._json(self._session(result['id']))
        except RevisionConflict:
            try:
                current = self._session(session_id)
            except (OSError, ValueError, KeyError, TypeError):
                self._json({'error': 'Local state unavailable'}, 503)
            else:
                self._json({'error': 'Stale revision', 'current': current}, 409)
        except (OSError, portalocker.exceptions.LockException):
            self._json({'error': 'Local state unavailable'}, 503)
        except (ValueError, KeyError, TypeError, UnicodeError, RecursionError, socket.timeout):
            self._json({'error': 'Invalid request'}, 400)
