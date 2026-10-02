"""Real loopback HTTP and visible CLI checks with isolated local state."""

import hashlib
import http.client
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess


def test_browser_draft(tmp_path):
    from tools.acceptance_runtime import session, board, http
    store, state = session(tmp_path)
    old = state['image_versions']
    with board(store, state) as (_, origin):
        code, _, _ = http(origin, '/api/event', {'session_id':state['id'], 'expected_revision':state['revision'], 'nonce':store.nonce_for(state['id']), 'action':'draft_edit', 'payload':{'text':'A browser-only draft'}}, {'Origin':origin, 'Content-Type':'application/json'})
        assert code == 200
    reopened = store.read(state['id'])
    assert reopened['image_versions'] == old
    assert reopened['drafts'][-1]['text'] == 'A browser-only draft'


def test_restart(tmp_path):
    from tools.acceptance_runtime import session, board, http
    store, state = session(tmp_path)
    with board(store, state) as (_, origin):
        code, before, _ = http(origin, '/api/session?id=' + state['id'])
        assert code == 200
    with board(store, state) as (_, origin):
        code, after, _ = http(origin, '/api/session?id=' + state['id'])
        assert code == 200 and before == after


def test_port_collision(tmp_path):
    test_occupied_port_never_takes_over_sentinel(tmp_path, 'unknown')


def test_loopback_binding(tmp_path):
    import ipaddress
    from tools.acceptance_runtime import session, board
    store, state = session(tmp_path)
    with board(store, state) as (listener, _):
        assert ipaddress.ip_address(listener.socket.getsockname()[0]).is_loopback


def test_origin_rejection(board):
    test_rejected_request_preserves_saved_bytes(board, 'origin')
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from vybe_check import __version__
from vybe_check.workshop import SessionStore


def server_module():
    import vybe_check
    path = Path(vybe_check.__file__).parent / 'studio' / 'server.py'
    source = path.read_text(encoding='utf-8')
    assert 'TOOLS_ROOT' not in source, 'Copied server still alters package import paths'
    assert 'sys.path' not in source, 'Copied server still alters package import paths'
    assert 'vybe_check.local_preview' not in source, 'Optional adapter imported before Task 9'
    from vybe_check.studio import server
    assert Path(server.__file__).resolve().is_relative_to(Path(vybe_check.__file__).parent.resolve())
    return server


def isolated_env(root):
    env = dict(os.environ)
    for key in ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'XDG_DATA_HOME'):
        env[key] = str(root / 'home')
    env['VYBE_CHECK_ROOT'] = str(root / 'environment-state')
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    import vybe_check
    env['PYTHONPATH'] = str(Path(vybe_check.__file__).resolve().parents[1])
    return env


def http_request(port, method, route, body=None, headers=None):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        if isinstance(body, dict) or isinstance(body, list):
            body = json.dumps(body).encode('utf-8')
        base = {'Content-Type': 'application/json'}
        base.update(headers or {})
        connection.request(method, route, body=body, headers=base)
        response = connection.getresponse()
        return response.status, response.read(), dict(response.getheaders())
    finally:
        connection.close()


@pytest.fixture
def board(tmp_path):
    module = server_module()
    store = SessionStore(tmp_path / 'state')
    server = module.create_server(0, root=store.root, store=store)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield store, server, lambda *args, **kwargs: http_request(server.server_port, *args, **kwargs)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=4)
        assert not thread.is_alive()


def event(store, session):
    return {'session_id': session['id'], 'expected_revision': 0,
            'nonce': store.nonce_for(session['id']), 'action': 'draft_edit',
            'payload': {'text': 'Draft', 'target': 'image'}}


def test_public_import_boundary():
    server_module()


def test_identity_root_and_unavailable_adapter(board):
    store, server, request = board
    status, raw, headers = request('GET', '/api/identity')
    assert status == 200
    assert json.loads(raw) == {'application': 'vybe-check', 'version': __version__, 'protocol': 1,
        'root_fingerprint': hashlib.sha256(str(store.root.resolve()).encode()).hexdigest()}
    assert str(store.root).encode() not in raw
    assert json.loads(request('GET', '/api/capability')[1]) == {'available': False, 'reason': 'Local study unavailable'}
    assert headers['Cross-Origin-Resource-Policy'] == 'same-origin'
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert request('GET', '/')[0] == 200
    session = store.create()
    body = event(store, session)
    body['prompt_version'] = 1
    assert request('POST', '/api/preview', body, {'Origin': f'http://127.0.0.1:{server.server_port}'})[:2] == (409, b'{"error": "Local study unavailable"}')
    assert store.read(session['id']) == session
    assert 'vybe_check.judge' not in sys.modules
    assert 'vybe_check.local_preview' not in sys.modules


def test_session_authorisation(board):
    store, server, request = board
    a, b = store.create(), store.create()
    origin = f'http://127.0.0.1:{server.server_port}'
    before = store._session_path(a['id']).read_bytes()
    for token in (None, '', 'wrong', store.nonce_for(b['id']), [], 123):
        body = event(store, a)
        if token is None:
            body.pop('nonce')
        else:
            body['nonce'] = token
        assert request('POST', '/api/event', body, {'Origin': origin})[0] == 403
        assert store._session_path(a['id']).read_bytes() == before
    body = event(store, a)
    assert request('POST', '/api/event', body, {'Origin': origin})[0] == 200
    assert store.read(a['id'])['revision'] == 1
    status, conflict, _ = request('POST', '/api/event', body, {'Origin': origin})
    assert status == 409
    assert json.loads(conflict)['current']['revision'] == 1
    assert store.read(a['id'])['revision'] == 1


@pytest.mark.parametrize('case', ['host', 'origin', 'missing-origin', 'type', 'list', 'invalid-json', 'large', 'small', 'length', 'transfer', 'id', 'action', 'payload', 'revision', 'route'])
def test_rejected_request_preserves_saved_bytes(board, case):
    store, server, request = board
    session = store.create()
    before = store._session_path(session['id']).read_bytes()
    body = event(store, session)
    headers = {'Origin': f'http://127.0.0.1:{server.server_port}'}
    route, expected = '/api/event', 400
    if case == 'host': headers['Host'], expected = 'outside.invalid', 403
    if case == 'origin': headers['Origin'], expected = 'https://outside.invalid', 403
    if case == 'missing-origin': headers, expected = {}, 403
    if case == 'type': headers['Content-Type'], expected = 'text/plain', 415
    if case == 'list': body = []
    if case == 'invalid-json': body = b'{'
    if case == 'large': body = b' ' * 65537
    if case == 'small': body = b''
    if case == 'length': headers['Content-Length'] = '-1'
    if case == 'transfer': headers['Transfer-Encoding'] = 'chunked'
    if case == 'id': body['session_id'], expected = '../example', 403
    if case == 'action': body['action'] = 'register_reference'
    if case == 'payload': body['payload'] = {'path': '/invented/example', 'text': 'Draft'}
    if case == 'revision': body['expected_revision'] = True
    if case == 'route': route, expected = '/unknown', 404
    status, raw, _ = request('POST', route, body, headers)
    assert status == expected
    assert str(store.root).encode() not in raw
    assert store._session_path(session['id']).read_bytes() == before


def cli_run(root, *args, timeout=6):
    return subprocess.run([sys.executable, '-m', 'vybe_check', '--root', str(root / 'state'), *args],
                          env=isolated_env(root), capture_output=True, text=True, timeout=timeout)


def read_line(child):
    selector = selectors.DefaultSelector()
    try:
        selector.register(child.stdout, selectors.EVENT_READ)
        assert selector.select(6), 'CLI did not print a visible board URL'
        line = child.stdout.readline().strip()
        assert line.startswith('http://127.0.0.1:'), line
        return line
    finally:
        selector.close()


def interrupt(child):
    if child.poll() is None:
        child.send_signal(signal.SIGINT)
    return child.communicate(timeout=6)


def test_cli_visible_shutdown_restart_and_compatible_reuse(tmp_path):
    server_module()
    root = tmp_path
    store = SessionStore(root / 'state')
    a, b = store.create(), store.create()
    command = [sys.executable, '-m', 'vybe_check', '--root', str(store.root), 'board', '--session', a['id'], '--port', '0']
    child = subprocess.Popen(command, env=isolated_env(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        url = read_line(child)
        port = int(url.split(':')[2].split('/')[0])
        assert child.poll() is None
        assert http_request(port, 'GET', '/api/session?id=' + a['id'])[0] == 200
        reused = cli_run(root, 'board', '--session', b['id'], '--port', str(port))
        assert reused.returncode == 0, reused.stderr
        assert reused.stdout.strip() == f'http://127.0.0.1:{port}/?session={b["id"]}'
        unknown = cli_run(root, 'board', '--session', '0' * 32, '--port', str(port))
        assert unknown.returncode == 2
        assert http_request(port, 'GET', '/api/identity')[0] == 200
    finally:
        _, stderr = interrupt(child)
    assert child.returncode == 0, stderr
    assert stderr == ''
    restarted = subprocess.Popen(command[:-1] + [str(port)], env=isolated_env(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert read_line(restarted) == f'http://127.0.0.1:{port}/?session={a["id"]}'
        assert json.loads(http_request(port, 'GET', '/api/session')[1])['id'] == a['id']
    finally:
        interrupt(restarted)
    assert restarted.returncode == 0


@pytest.mark.parametrize('identity_case', ['unknown', 'version', 'protocol', 'root', 'application', 'malformed', 'oversized', 'missing-session'])
def test_occupied_port_never_takes_over_sentinel(tmp_path, identity_case):
    server_module()
    store = SessionStore(tmp_path / 'state')
    session = store.create()
    from vybe_check.studio.server import board_identity
    identity = board_identity(store.root)
    if identity_case in ('version', 'protocol', 'root', 'application'):
        field = {'root': 'root_fingerprint'}.get(identity_case, identity_case)
        identity[field] = 'different'
    class Sentinel(BaseHTTPRequestHandler):
        def do_GET(self):
            data = b'Sentinel'
            if self.path == '/api/identity' and identity_case != 'unknown':
                data = b'{}' if identity_case == 'malformed' else (b'x' * 8193 if identity_case == 'oversized' else json.dumps(identity).encode())
            if self.path.startswith('/api/session') and identity_case == 'missing-session':
                data = b'{}'
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def log_message(self, *args): pass
    sentinel = ThreadingHTTPServer(('127.0.0.1', 0), Sentinel)
    thread = threading.Thread(target=sentinel.serve_forever)
    thread.start()
    try:
        result = cli_run(tmp_path, 'board', '--session', session['id'], '--port', str(sentinel.server_port))
        assert result.returncode == 2
        assert result.stdout == ''
        assert 'port conflict' in result.stderr.lower()
        assert '--port' in result.stderr
        assert str(tmp_path) not in result.stderr
        assert http_request(sentinel.server_port, 'GET', '/sentinel')[1] == b'Sentinel'
    finally:
        sentinel.shutdown()
        sentinel.server_close()
        thread.join(timeout=4)


def test_root_constructor_and_invalid_session_do_not_leak_socket(tmp_path):
    module = server_module()
    server = module.create_server(0, root=tmp_path / 'root')
    port = server.server_port
    server.server_close()
    with pytest.raises(ValueError):
        module.create_server(port, root=tmp_path / 'root', active_id='bad')
    server = module.create_server(port, root=tmp_path / 'root')
    server.server_close()


def test_nonce_uses_constant_time_comparison(board, monkeypatch):
    import secrets
    store, server, request = board
    body = event(store, store.create())
    calls = []
    original = secrets.compare_digest
    def compare(left, right):
        calls.append((left, right))
        return original(left, right)
    monkeypatch.setattr(secrets, 'compare_digest', compare)
    assert request('POST', '/api/event', body, {'Origin': f'http://127.0.0.1:{server.server_port}'})[0] == 200
    assert calls, 'The HTTP authorisation boundary did not use constant-time comparison'


def test_error_categories_hide_validation_details(board):
    store, server, request = board
    body = event(store, store.create())
    body['payload']['text'] = ''
    status, raw, _ = request('POST', '/api/event', body, {'Origin': f'http://127.0.0.1:{server.server_port}'})
    assert status == 400
    assert json.loads(raw) == {'error': 'Invalid request'}


def test_transfer_encoding_with_length_is_rejected_before_mutation(board):
    store, server, request = board
    session = store.create()
    body = event(store, session)
    before = store._session_path(session['id']).read_bytes()
    headers = {'Origin': f'http://127.0.0.1:{server.server_port}',
               'Transfer-Encoding': 'chunked', 'Content-Length': str(len(json.dumps(body).encode()))}
    assert request('POST', '/api/event', body, headers)[0] == 400
    assert store._session_path(session['id']).read_bytes() == before


@pytest.mark.parametrize('folder', ['sessions', 'registry'])
def test_linked_state_directory_cannot_redirect_creation(tmp_path, folder):
    root = tmp_path / 'state'
    root.mkdir()
    target = tmp_path / 'outside'
    target.mkdir()
    (root / folder).symlink_to(target, target_is_directory=True)
    with pytest.raises(OSError):
        SessionStore(root).create()
    assert list(target.iterdir()) == []


@pytest.mark.parametrize('kind', ['state', 'registry'])
def test_http_nonregular_state_refusal_preserves_originals(board, tmp_path, kind):
    if not hasattr(os, 'mkfifo'):
        pytest.skip('POSIX nonregular boundary')
    store, _, request = board
    session = store.create()
    path = store._session_path(session['id']) if kind == 'state' else store._registry_path(session['id'])
    before = path.read_bytes()
    preserved = tmp_path / 'preserved.json'
    path.rename(preserved)
    os.mkfifo(path)
    started = time.monotonic()
    assert request('GET', '/api/session?id=' + session['id'])[0] == 404
    assert time.monotonic() - started < 2
    assert preserved.read_bytes() == before


def test_compatible_reuse_accepts_a_valid_substantial_session(board, tmp_path):
    store, server, _ = board
    session = store.create()
    store.apply(session['id'], 0, 'draft_edit', {'text': 'Soft reflected light. ' * 1000})
    result = cli_run(tmp_path, 'board', '--session', session['id'], '--port', str(server.server_port))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f'http://127.0.0.1:{server.server_port}/?session={session["id"]}'


def test_size_refusal_http_preserves_readable_state_and_registry(board):
    from test_media import fill_state_to_size, state_bytes
    from vybe_check.workshop import MAX_STATE_BYTES
    store, server, request = board
    session = store.create()
    fill_state_to_size(store, session['id'], MAX_STATE_BYTES - 1000)
    before, registry = state_bytes(store, session['id'])
    body = event(store, session)
    body['payload']['text'] = 'Soft light ' * 300
    status, raw, _ = request('POST', '/api/event', body, {'Origin': f'http://127.0.0.1:{server.server_port}'})
    assert status == 400 and json.loads(raw) == {'error': 'Invalid request'}
    after, registry_after = state_bytes(store, session['id'])
    assert hashlib.sha256(after).hexdigest() == hashlib.sha256(before).hexdigest()
    assert after == before and registry_after == registry
    assert request('GET', '/api/session?id=' + session['id'])[0] == 200
    assert store.read(session['id'])['revision'] == 0


def test_reuse_near_limit_registered_media_session(board, tmp_path):
    from test_media import persisted_bytes, state_bytes
    from vybe_check.workshop import MAX_STATE_BYTES
    store, server, request = board
    session = store.create()
    media = tmp_path / 'sample.png'
    media.write_bytes(b'Preserved local clay study')
    for number in range(20):
        session = store.apply(session['id'], session['revision'], 'register_reference', {
            'path': str(media), 'label': f'Clay study {number}', 'role': 'Colour reference'})
    brief = {'outcome': '', 'subject_action': 'Potter holds a bowl', 'visual_priority': 'Hands'}
    prospective = dict(session, brief=brief, brief_status='proposed', revision=session['revision'] + 1)
    remaining = MAX_STATE_BYTES - len(persisted_bytes(prospective))
    brief['outcome'] = 'S ' * (remaining // 2) + ('S' if remaining % 2 else '')
    session = store.apply(session['id'], session['revision'], 'propose_brief', {'brief': brief})
    before = state_bytes(store, session['id'])
    assert len(before[0]) == MAX_STATE_BYTES
    status, raw, _ = request('GET', '/api/session?id=' + session['id'])
    assert status == 200 and len(raw) > MAX_STATE_BYTES
    assert len(json.loads(raw)['references']) == 20
    result = cli_run(tmp_path, 'board', '--session', session['id'], '--port', str(server.server_port))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f'http://127.0.0.1:{server.server_port}/?session={session["id"]}'
    assert state_bytes(store, session['id']) == before
    assert media.read_bytes() == b'Preserved local clay study'
    assert request('GET', '/api/identity')[0] == 200


def test_compact_session_lookup_checks_local_identity_and_nonce(board):
    store, server, request = board
    session = store.create()
    status, raw, _ = request('GET', '/api/session-check?id=' + session['id'])
    assert status == 200
    assert json.loads(raw) == {'id': session['id'],
        'revision_fingerprint': hashlib.sha256(str(session['revision']).encode()).hexdigest(),
        'nonce_fingerprint': hashlib.sha256(store.nonce_for(session['id']).encode()).hexdigest()}
    assert len(raw) == len(json.dumps(json.loads(raw)).encode())
    assert request('GET', '/api/session-check?id=' + '0' * 32)[0] == 404
    status, raw, _ = request('GET', '/api/session-check')
    assert status == 200 and json.loads(raw)['id'] == server.active_id


@pytest.mark.parametrize('case', ['nonce', 'revision', 'id', 'list', 'malformed', 'oversized'])
def test_compact_lookup_refuses_unverified_listener(tmp_path, case):
    module = server_module()
    store = SessionStore(tmp_path / 'state')
    session = store.create()
    before = (store._session_path(session['id']).read_bytes(), store._registry_path(session['id']).read_bytes())
    value = {'id': session['id'], 'revision_fingerprint': hashlib.sha256(b'0').hexdigest(),
             'nonce_fingerprint': hashlib.sha256(store.nonce_for(session['id']).encode()).hexdigest()}
    if case in {'nonce', 'revision'}: value[case + '_fingerprint'] = '0' * 64
    if case == 'id': value['id'] = '0' * 32
    data = json.dumps(value).encode()
    if case == 'list': data = b'[]'
    if case == 'malformed': data = b'{'
    if case == 'oversized': data += b' '  # One byte above the exact compact response bound.
    class Sentinel(BaseHTTPRequestHandler):
        def do_GET(self):
            raw = json.dumps(module.board_identity(store.root)).encode() if self.path == '/api/identity' else data
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def log_message(self, *args): pass
    listener = ThreadingHTTPServer(('127.0.0.1', 0), Sentinel)
    thread = threading.Thread(target=listener.serve_forever)
    thread.start()
    try:
        result = cli_run(tmp_path, 'board', '--session', session['id'], '--port', str(listener.server_port))
        assert result.returncode == 2 and result.stdout == ''
        assert 'port conflict' in result.stderr.lower()
        assert http_request(listener.server_port, 'GET', '/sentinel')[0] == 200
        assert (store._session_path(session['id']).read_bytes(), store._registry_path(session['id']).read_bytes()) == before
    finally:
        listener.shutdown()
        listener.server_close()
        thread.join(timeout=4)
        assert not thread.is_alive()


@pytest.mark.parametrize('revision', [True, '0'])
def test_compact_lookup_refuses_noninteger_saved_revision(board, tmp_path, revision):
    store, server, request = board
    session = store.create()
    session['revision'] = revision
    store._write(store._session_path(session['id']), session)
    before = store._session_path(session['id']).read_bytes()
    assert request('GET', '/api/session-check?id=' + session['id'])[0] == 404
    result = cli_run(tmp_path, 'board', '--session', session['id'], '--port', str(server.server_port))
    assert result.returncode == 2 and result.stdout == ''
    assert store._session_path(session['id']).read_bytes() == before


@pytest.mark.parametrize('depth', [1100, 10000])
def test_recursive_draft_payload_has_controlled_http_refusal(board, tmp_path, depth):
    import contextlib
    import io
    from test_media import state_bytes
    store, server, request = board
    session = store.create()
    before = state_bytes(store, session['id'])
    media = tmp_path / 'preserved.png'
    media.write_bytes(b'Preserved local source')
    body = event(store, session)
    body['payload']['text'] = 'NESTED_MARKER'
    raw = json.dumps(body).encode().replace(b'"NESTED_MARKER"', b'[' * depth + b'0' + b']' * depth)
    assert len(raw) < 65536
    request_path = tmp_path / f'recursive-{depth}-request.bin'
    request_path.write_bytes(raw)
    stderr = io.StringIO()
    status, response, error = None, b'', None
    with contextlib.redirect_stderr(stderr):
        try:
            status, response, _ = request('POST', '/api/event', raw,
                {'Origin': f'http://127.0.0.1:{server.server_port}'})
        except http.client.RemoteDisconnected as exc:
            error = type(exc).__name__
            time.sleep(0.1)
    stderr_path = tmp_path / f'recursive-{depth}-stderr.txt'
    stderr_path.write_text(stderr.getvalue())
    after = state_bytes(store, session['id'])
    evidence = {'depth': depth, 'request_bytes': len(raw),
        'request_sha256': hashlib.sha256(raw).hexdigest(), 'status': status,
        'client_exception': error, 'response_bytes': len(response), 'response': response.decode(),
        'stderr_bytes': len(stderr_path.read_bytes()),
        'stderr_sha256': hashlib.sha256(stderr_path.read_bytes()).hexdigest(),
        'contains_recursion_error': 'RecursionError' in stderr.getvalue(),
        'baseline_callsites': {name: name in stderr.getvalue()
                              for name in ('validated_payload', 'json.loads')},
        'before_hashes': [hashlib.sha256(value).hexdigest() for value in before],
        'after_hashes': [hashlib.sha256(value).hexdigest() for value in after],
        'media_sha256': hashlib.sha256(media.read_bytes()).hexdigest(),
        'revision_after': store.read(session['id'])['revision'],
        'listener_status_after': request('GET', '/api/identity')[0]}
    (tmp_path / f'recursive-{depth}-evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence))
    assert after == before and evidence['revision_after'] == 0
    assert media.read_bytes() == b'Preserved local source'
    assert evidence['listener_status_after'] == 200
    assert status == 400 and response == b'{"error": "Invalid request"}'
    assert stderr.getvalue() == ''
    normal = event(store, session)
    assert request('POST', '/api/event', normal,
        {'Origin': f'http://127.0.0.1:{server.server_port}'})[0] == 200
    assert store.read(session['id'])['revision'] == 1
