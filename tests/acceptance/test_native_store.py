"""Authoring proofs use synthetic stores. Actual native probes are opt-in.

Run this file directly with --native-probe on each release host. A default
pytest run is not native evidence. Entries are retained; there is no cleanup.
"""
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import pytest


def test_macos_keychain():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import native_gate
    pending_gate(native_gate,'DoD-43','Darwin')


def test_windows_locker():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import native_gate
    pending_gate(native_gate,'DoD-44','Windows')


def test_linux_secret_service():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import native_gate
    pending_gate(native_gate,'DoD-45','Linux')


def test_unregister_preserves_key():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import native_gate
    pending_gate(native_gate,'DoD-11.1')


def test_uninstall_preserves_key():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import native_gate
    pending_gate(native_gate,'DoD-11.2')


def test_rejected_backend(tmp_path, monkeypatch):
    from vybe_check import credentials as c
    # Real adapter selection refuses these unsupported configurations before use.
    for backend in ('keyrings.alt.file.PlaintextKeyring','keyring.backends.null.Keyring','invented.Backend'):
        monkeypatch.setenv('PYTHON_KEYRING_BACKEND',backend)
        with pytest.raises(c.StoreUnavailable): c.native_backend()


def credentials():
    assert importlib.util.find_spec('vybe_check.credentials') is not None, 'Native credential module is missing'
    from vybe_check import credentials
    return credentials


def isolated_environment(root, source, home=None):
    home = home or root / 'home'
    home.mkdir(parents=True, exist_ok=True)
    return {**os.environ, **{name: str(home) for name in
        ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'XDG_DATA_HOME')},
        'VYBE_CHECK_ROOT': str(root / 'environment-state'),
        'PYTHONPATH': str(source), 'PYTHONDONTWRITEBYTECODE': '1'}


def test_default_create_refine_export_never_constructs_adapter(tmp_path, monkeypatch, capsys):
    c = credentials()
    from vybe_check.cli import main
    def forbidden(): pytest.fail('Default workflow accessed the native store')
    monkeypatch.setattr(c, 'native_backend', forbidden)
    monkeypatch.setattr(c, 'Credentials', forbidden)
    root = tmp_path / 'state'
    assert main(['--root', str(root), 'new']) == 0
    session = json.loads(capsys.readouterr().out)
    def event(action, payload):
        nonlocal session
        payload_path = tmp_path / (action + '.json')
        payload_path.write_text(json.dumps(payload))
        assert main(['--root', str(root), 'event', session['id'], '--revision', str(session['revision']),
            '--action', action, '--payload-file', str(payload_path)]) == 0
        session = json.loads(capsys.readouterr().out)
    event('direct_image', {'brief': {'outcome': 'Clay portrait', 'subject_action': 'Hands hold a bowl', 'visual_priority': 'Hands', 'frame': 'Close portrait', 'light': 'Window light'}, 'prompt': 'Potter holds a bowl'})
    event('draft_edit', {'text': 'Hands lift the bowl'})
    event('accept_draft', {'draft_id': session['drafts'][0]['id']})
    assert main(['--root', str(root), 'export', session['id']]) == 0
    assert json.loads(capsys.readouterr().out)['version'] == 2


def test_secret_canary_absent_from_cli_state_http_export_and_child_arguments(tmp_path, monkeypatch, capsys):
    c = credentials()
    from vybe_check.cli import main
    from vybe_check.workshop import SessionStore
    from vybe_check.studio.server import create_server
    import getpass
    import http.client
    import vybe_check
    for name in ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'XDG_DATA_HOME'):
        monkeypatch.setenv(name, str(tmp_path / 'home'))
    monkeypatch.setenv('VYBE_CHECK_ROOT', str(tmp_path / 'environment-state'))
    canary = 'sk-' + secrets.token_hex(24)
    values = {}
    class Synthetic:
        def get_password(self, service, account): return values.get((service, account))
        def add_password(self, service, account, value): values[service, account] = value
    monkeypatch.setattr(c, 'native_backend', Synthetic)
    monkeypatch.setattr(getpass, 'getpass', lambda *a, **kw: canary)
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        monkeypatch.setattr(stream, 'isatty', lambda: True)
    root = tmp_path / 'state'
    assert main(['--root', str(root), 'key', 'setup', '--route', 'typesafe']) == 0
    assert main(['--root', str(root), 'key', 'status']) == 0
    captured = capsys.readouterr()
    assert canary not in captured.out + captured.err
    store = SessionStore(root)
    session = store.create()
    session = store.apply(session['id'], 0, 'direct_image', {'brief': {'outcome': 'Clay study', 'subject_action': 'Hold bowl', 'visual_priority': 'Hands', 'frame': 'Close portrait', 'light': 'Window light'}, 'prompt': 'Clay in hands'})
    output = tmp_path / 'export.json'
    assert main(['--root', str(root), 'export', session['id'], '--out', str(output)]) == 0
    listener = create_server(0, root=root, store=store)
    thread = threading.Thread(target=listener.serve_forever)
    thread.start()
    try:
        connection = http.client.HTTPConnection('127.0.0.1', listener.server_port, timeout=3)
        connection.request('GET', '/api/session?id=' + session['id'])
        response = connection.getresponse()
        assert response.status == 200 and canary.encode() not in response.read()
        connection.close()
        connection = http.client.HTTPConnection('127.0.0.1', listener.server_port, timeout=3)
        connection.request('POST', '/api/key', json.dumps({'route': 'typesafe', 'expected_revision': session['revision'], 'session_id': session['id'], 'nonce': store.nonce_for(session['id'])}),
            {'Origin': f'http://127.0.0.1:{listener.server_port}', 'Content-Type': 'application/json'})
        response = connection.getresponse()
        assert response.status == 404 and canary.encode() not in response.read()
        connection.close()
    finally:
        listener.shutdown(); listener.server_close(); thread.join(timeout=4)
    assert not thread.is_alive()
    assert all(canary.encode() not in path.read_bytes() for path in root.rglob('*') if path.is_file())
    assert canary.encode() not in output.read_bytes()
    source = Path(vybe_check.__file__).resolve().parents[1]
    command = [sys.executable, '-B', '-m', 'vybe_check', '--root', str(tmp_path / 'child-state'), 'new']
    env = isolated_environment(tmp_path / 'child', source)
    assert canary not in repr(command) + repr(env)
    child = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
    assert child.returncode == 0 and canary not in child.stdout + child.stderr
    assert capsys.readouterr().err == ''


PROCESS_CODE = r'''import json, pathlib, secrets, sys, time
from vybe_check import credentials as c
home, state, store, ready, release, started, role = map(pathlib.Path, sys.argv[1:])
assert pathlib.Path.home() == home
assert state != home and state.name.startswith('session-')
value = secrets.token_urlsafe(32)
class Synthetic:
    def get_password(self, service, account):
        assert service == 'vybe-check' and account == 'typesafe'
        if store.exists():
            return json.loads(store.read_text())['value']
        if role.name == 'first':
            ready.touch(exist_ok=False)
            deadline = time.monotonic() + 8
            while not release.exists():
                assert time.monotonic() < deadline
                time.sleep(.02)
        return None
    def add_password(self, service, account, secret):
        with store.open('x') as stream:
            json.dump({'value': secret}, stream)
c.native_backend = Synthetic
started.touch(exist_ok=False)
try:
    c.Credentials().store_new('typesafe', value)
    print(json.dumps({'created': True, 'equal': c.Credentials().read('typesafe') == value}))
except c.CredentialConflict:
    print(json.dumps({'created': False, 'conflict': True}))
'''


def test_two_real_processes_share_fixed_lock_across_different_session_roots(tmp_path):
    c = credentials()
    source = Path(c.__file__).resolve().parents[1]
    home = tmp_path / 'home'
    store, ready, release = [tmp_path / name for name in ('synthetic-store', 'ready', 'release')]
    script = tmp_path / 'process.py'
    script.write_text(PROCESS_CODE)
    commands = []
    children = []
    def start(role):
        root = tmp_path / role
        root.mkdir()
        command = [sys.executable, '-B', str(script), str(home), str(root / ('session-' + role)),
            str(store), str(ready), str(release), str(root / 'started'), role]
        commands.append(command)
        child = subprocess.Popen(command, env=isolated_environment(root, source, home),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        children.append(child)
        return child
    def wait_file(path):
        deadline = time.monotonic() + 6
        while not path.exists():
            assert time.monotonic() < deadline, 'Synthetic process did not reach the controlled seam'
            time.sleep(.02)
    first = start('first')
    try:
        wait_file(ready)
        second = start('second')
        wait_file(tmp_path / 'second' / 'started')
        time.sleep(.15)
        assert second.poll() is None and not store.exists()
        release.touch()
        first_out, first_err = first.communicate(timeout=8)
        first_bytes = store.read_bytes()
        second_out, second_err = second.communicate(timeout=8)
        assert first.returncode == second.returncode == 0
        assert first_err == second_err == ''
        assert json.loads(first_out) == {'created': True, 'equal': True}
        assert json.loads(second_out) == {'created': False, 'conflict': True}
        preserved = store.read_bytes() == first_bytes
        assert preserved, 'Second creator changed the winning store bytes'
        secret = json.loads(store.read_text())['value']
        assert secret not in repr(commands) + first_out + first_err + second_out + second_err
        assert (home / '.vybe-check-security' / 'typesafe.setup.lock').is_file()
        assert not list((tmp_path / 'first').rglob('*.setup.lock'))
        assert not list((tmp_path / 'second').rglob('*.setup.lock'))
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=8)


def native_probe():
    """Explicit release action. No enumeration, operator reads, or deletion."""
    c = credentials()
    namespace = 'vybe-check-acceptance-' + secrets.token_hex(16)
    account = 'invented-' + secrets.token_hex(16)
    value = secrets.token_urlsafe(32)
    backend_name = 'unavailable'
    import platform
    observed = {'scope':'actual-native-store-probe', 'system':platform.system(),
                'python':platform.python_version(), 'namespace':namespace}
    try:
        backend = c.native_backend()
        backend_name = {'macOS Keychain':'macos-keychain',
                        'Windows PasswordVault / Credential Locker':'windows-credential-locker',
                        'Linux Secret Service':'linux-secret-service'}.get(backend.identity, 'unavailable')
        if backend.get_password(namespace, account) is not None:
            raise c.StoreUnavailable()
        backend.add_password(namespace, account, value)
        equal = backend.get_password(namespace, account) == value
        duplicate_preserved = False
        try:
            backend.add_password(namespace, account, secrets.token_urlsafe(32))
        except Exception:
            pass
        duplicate_preserved = backend.get_password(namespace, account) == value
    except Exception:
        print(json.dumps({**observed, 'backend': backend_name, 'available': False, 'equal': False, 'duplicate_preserved': False}))
        return 2
    print(json.dumps({**observed, 'backend': backend_name, 'available': True, 'equal': equal, 'duplicate_preserved': duplicate_preserved}))
    return 0 if equal and duplicate_preserved else 2


if __name__ == '__main__':
    if sys.argv[1:] != ['--native-probe']:
        print('Native probe requires explicit --native-probe')
        raise SystemExit(2)
    raise SystemExit(native_probe())
