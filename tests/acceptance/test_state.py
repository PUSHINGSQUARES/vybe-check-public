"""State checks using supplied platform inputs and real local processes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess


def test_shared_root(tmp_path):
    from tools.acceptance_runtime import environment, cli, board, http
    env = environment(tmp_path)
    result = cli(tmp_path, env, 'new', '--title', 'Shared invented session')
    assert result.returncode == 0, result.stderr
    import json
    state = json.loads(result.stdout)
    from vybe_check.workshop import SessionStore
    store = SessionStore(tmp_path / 'state')
    with board(store, state) as (_, origin):
        code, body, _ = http(origin, '/api/session?id=' + state['id'])
        assert code == 200
        assert json.loads(body)['revision'] == state['revision']
        assert json.loads(body)['id'] == state['id']


def test_prompt_history(tmp_path):
    from tools.acceptance_runtime import session
    store, state = session(tmp_path)
    old = state['image_versions'][0]
    state = store.apply(state['id'], state['revision'], 'add_image_version', {'prompt':'A potter lifts the blue bowl'})
    reopened = store.read(state['id'])
    assert reopened['image_versions'][0] == old
    assert reopened['image_versions'][1]['prompt'] != old['prompt']
    assert reopened['image_versions'][1]['version'] != old['version']


def test_accept_draft(tmp_path):
    from tools.acceptance_runtime import session
    store, state = session(tmp_path)
    old = state['image_versions'][0]
    state = store.apply(state['id'], state['revision'], 'draft_edit', {'text':'A closer view of the blue bowl', 'base_version':1})
    draft = state['drafts'][-1]
    state = store.apply(state['id'], state['revision'], 'accept_draft', {'draft_id':draft['id']})
    assert state['image_versions'][0] == old
    assert len(state['image_versions']) == 2
    assert state['image_versions'][-1]['prompt'].startswith(draft['text'])


def test_stale_revision(tmp_path):
    # Drives the real two-process optimistic-concurrency seam, not a fake event.
    test_real_two_process_revision_conflict_preserves_committed_digest(tmp_path)


def test_atomic_save(tmp_path):
    # A real child interrupts before replacement and the previous bytes reopen.
    test_real_child_interruption_before_replace_preserves_old_sha256(tmp_path)
import sys
import time

import portalocker
import pytest

from vybe_check.cli import _parser, main
from vybe_check.workshop import SessionStore


@pytest.mark.parametrize('system', ['Darwin', 'Windows', 'Linux'])
def test_explicit_root_wins(tmp_path, system):
    from vybe_check.config import data_root

    assert data_root(
        tmp_path, system=system,
        env={'VYBE_CHECK_ROOT': '/other-state'}, home=Path('/example-home'),
    ) == tmp_path.resolve()


@pytest.mark.parametrize('system', ['Darwin', 'Windows', 'Linux'])
def test_environment_root_wins(tmp_path, system):
    from vybe_check.config import data_root

    root = tmp_path / 'state'
    assert data_root(
        None, system=system, env={'VYBE_CHECK_ROOT': str(root)},
        home=Path('/example-home'),
    ) == root.resolve()


@pytest.mark.parametrize(('system', 'env', 'expected'), [
    ('Darwin', {}, Path('/example-home/Library/Application Support/vybe-check')),
    ('Windows', {}, Path('/example-home/AppData/Local/vybe-check')),
    ('Windows', {'LOCALAPPDATA': '/local-data'}, Path('/local-data/vybe-check')),
    ('Linux', {}, Path('/example-home/.local/share/vybe-check')),
    ('Linux', {'XDG_DATA_HOME': '/data'}, Path('/data/vybe-check')),
])
def test_platform_root_uses_supplied_inputs(system, env, expected):
    from vybe_check.config import data_root

    assert data_root(None, system=system, env=env, home=Path('/example-home')) == expected


def test_relative_xdg_root_is_rejected():
    from vybe_check.config import data_root

    with pytest.raises(ValueError, match='XDG_DATA_HOME must be absolute'):
        data_root(None, system='Linux', env={'XDG_DATA_HOME': 'relative'}, home='/example-home')


def test_empty_environment_does_not_inherit_host_root(tmp_path, monkeypatch):
    from vybe_check.config import data_root

    monkeypatch.setenv('VYBE_CHECK_ROOT', str(tmp_path))
    assert data_root(None, system='Linux', env={}, home='/example-home') == Path(
        '/example-home/.local/share/vybe-check'
    )


def test_actual_host_store_resolves_explicit_root(tmp_path):
    root = tmp_path / 'workshop'
    assert SessionStore.__init__.__defaults__ == (None,)
    store = SessionStore(root)
    assert store.root == root.resolve()
    session = store.create('Ceramic portrait')
    assert (root / 'sessions' / f"{session['id']}.json").is_file()


def test_actual_host_default_root_with_supplied_home_and_environment(tmp_path):
    from vybe_check.config import data_root

    expected = {
        'Darwin': tmp_path / 'Library' / 'Application Support' / 'vybe-check',
        'Windows': tmp_path / 'AppData' / 'Local' / 'vybe-check',
    }.get(platform.system(), tmp_path / '.local' / 'share' / 'vybe-check')
    assert data_root(None, env={}, home=tmp_path) == expected


def test_first_creation_establishes_portable_lock(tmp_path):
    root = tmp_path / 'new-workshop'
    assert not root.exists()
    store = SessionStore(root)
    assert not (root / '.write.lock').exists()
    session = store.create('Ceramic portrait')
    assert (root / '.write.lock').is_file()
    assert store.read(session['id']) == session
    assert store.nonce_for(session['id'])


@pytest.mark.parametrize('revision', [True, False, 0.0, '0', None])
def test_revision_is_strict_integer_before_lock(tmp_path, revision):
    store = SessionStore(tmp_path / 'state')
    session = store.create()
    with portalocker.Lock(str(store.root / '.write.lock'), mode='a', timeout=1):
        with pytest.raises(ValueError, match='expected_revision must be an integer'):
            store.apply(session['id'], revision, 'draft_edit', {'text': 'Warm side light'})
    assert store.read(session['id']) == session


def _wait_for(path: Path, process: subprocess.Popen, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(f'Child exited before readiness: {stdout} {stderr}')
        if time.monotonic() >= deadline:
            pytest.fail('Child did not reach the readiness boundary')
        time.sleep(0.01)


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
    process.communicate(timeout=10)


def test_real_two_process_revision_conflict_preserves_committed_digest(tmp_path):
    store = SessionStore(tmp_path / 'state')
    session = store.create('Ceramic portrait')
    script = '''
import hashlib, json, sys
from pathlib import Path
from vybe_check.workshop import RevisionConflict, SessionStore
root, session_id, ready, text = sys.argv[1:]
store = SessionStore(Path(root))
observed = store.read(session_id)
Path(ready).write_text(json.dumps({'revision': observed['revision']}), encoding='utf-8')
sys.stdin.readline()
try:
    committed = store.apply(session_id, observed['revision'], 'draft_edit', {'text': text})
except RevisionConflict as exc:
    print(json.dumps({'status': 'conflict', 'message': str(exc)}), flush=True)
else:
    digest = hashlib.sha256(store._session_path(session_id).read_bytes()).hexdigest()
    print(json.dumps({'status': 'committed', 'revision': committed['revision'], 'sha256': digest}), flush=True)
'''
    children = []
    try:
        for number, text in enumerate(('Warm side light', 'Cool overhead light'), 1):
            ready = tmp_path / f'ready-{number}.json'
            child = subprocess.Popen(
                [sys.executable, '-c', script, str(store.root), session['id'], str(ready), text],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            children.append(child)
            _wait_for(ready, child)
            assert json.loads(ready.read_text(encoding='utf-8')) == {'revision': 0}
        first_stdout, first_stderr = children[0].communicate('Commit\n', timeout=10)
        assert children[0].returncode == 0, first_stderr
        first = json.loads(first_stdout)
        assert first['status'] == 'committed'
        assert first['revision'] == 1
        second_stdout, second_stderr = children[1].communicate('Commit\n', timeout=10)
        assert children[1].returncode == 0, second_stderr
        assert json.loads(second_stdout) == {
            'status': 'conflict', 'message': 'session revision changed',
        }
        final_bytes = store._session_path(session['id']).read_bytes()
        assert hashlib.sha256(final_bytes).hexdigest() == first['sha256']
        final = json.loads(final_bytes)
        assert final['revision'] == 1
        assert [draft['text'] for draft in final['drafts']] == ['Warm side light']
        print(json.dumps({
            'evidence': 'Two real processes read revision zero',
            'first': first, 'second': json.loads(second_stdout),
            'final_sha256': hashlib.sha256(final_bytes).hexdigest(),
        }, sort_keys=True))
    finally:
        for child in children:
            _stop(child)


def test_create_waits_for_state_lock_in_real_process(tmp_path):
    store = SessionStore(tmp_path / 'state')
    ready = tmp_path / 'ready.json'
    script = '''
import json, sys
from pathlib import Path
from vybe_check.workshop import SessionStore
store = SessionStore(Path(sys.argv[1]))
Path(sys.argv[2]).write_text('Ready', encoding='utf-8')
print(json.dumps(store.create('Clay study')), flush=True)
'''
    child = None
    try:
        with portalocker.Lock(str(store.root / '.write.lock'), mode='a', timeout=1):
            child = subprocess.Popen(
                [sys.executable, '-c', script, str(store.root), str(ready)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            _wait_for(ready, child)
            time.sleep(0.2)
            assert child.poll() is None, 'Creation bypassed the state lock'
            assert list((store.root / 'sessions').glob('*.json')) == []
        stdout, stderr = child.communicate(timeout=10)
        assert child.returncode == 0, stderr
        assert store.read(json.loads(stdout)['id'])['title'] == 'Clay study'
    finally:
        if child is not None:
            _stop(child)


def test_registry_registration_waits_for_portable_lock(tmp_path):
    store = SessionStore(tmp_path / 'state')
    session = store.create()
    reference = tmp_path / 'sample.png'
    reference.write_bytes(b'Local reference fixture')
    ready = tmp_path / 'ready.json'
    script = '''
import json, sys
from pathlib import Path
from vybe_check.workshop import SessionStore
store = SessionStore(Path(sys.argv[1]))
Path(sys.argv[4]).write_text('Ready', encoding='utf-8')
media_id = store._register_media(sys.argv[2], Path(sys.argv[3]))
print(json.dumps({'media_id': media_id}), flush=True)
'''
    child = None
    try:
        with portalocker.Lock(str(store.root / '.registry.lock'), mode='a', timeout=1):
            child = subprocess.Popen(
                [sys.executable, '-c', script, str(store.root), session['id'], str(reference), str(ready)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            _wait_for(ready, child)
            time.sleep(0.2)
            assert child.poll() is None, 'Registration bypassed the registry lock'
            registry = json.loads(store._registry_path(session['id']).read_text(encoding='utf-8'))
            assert registry['media'] == {}
        stdout, stderr = child.communicate(timeout=10)
        assert child.returncode == 0, stderr
        media_id = json.loads(stdout)['media_id']
        assert store.resolve_media(session['id'], media_id) == reference.resolve()
    finally:
        if child is not None:
            _stop(child)


def test_image_version_history_survives_selection(tmp_path):
    store = SessionStore(tmp_path / 'state')
    session = store.create('Ceramic portrait')
    session = store.apply(session['id'], 0, 'direct_image', {
        'brief': {
            'outcome': 'Ceramic portrait', 'subject_action': 'Potter holds a bowl',
            'visual_priority': 'Hands', 'frame': 'Close portrait', 'light': 'Window light',
        },
        'prompt': 'A potter holds a glazed bowl', 'locks': ['Blue glaze'],
    })
    first = json.dumps(session['image_versions'][0], sort_keys=True)
    session = store.apply(session['id'], 1, 'add_image_version', {
        'prompt': 'A potter lifts a glazed bowl', 'note': 'Raised hands',
    })
    second = json.dumps(session['image_versions'][1], sort_keys=True)
    session = store.apply(session['id'], 2, 'select_image_version', {'version': 1})
    reopened = SessionStore(store.root).read(session['id'])
    assert reopened['revision'] == 3
    assert reopened['selected_image_version'] == 1
    assert json.dumps(reopened['image_versions'][0], sort_keys=True) == first
    assert json.dumps(reopened['image_versions'][1], sort_keys=True) == second


def test_real_child_interruption_before_replace_preserves_old_sha256(tmp_path):
    store = SessionStore(tmp_path / 'state')
    session = store.create('Study at the café')
    path = store._session_path(session['id'])
    before = path.read_bytes()
    before_digest = hashlib.sha256(before).hexdigest()
    checkpoint = tmp_path / 'before-replace.json'
    script = '''
import json, os, stat, sys
from pathlib import Path
from vybe_check.workshop import SessionStore
store = SessionStore(Path(sys.argv[1]))
def interrupt(source, destination):
    temporary = Path(source)
    Path(sys.argv[3]).write_text(json.dumps({
        'parent': str(temporary.parent),
        'temporary': str(temporary),
        'mode': stat.S_IMODE(temporary.stat().st_mode),
        'value': json.loads(temporary.read_text(encoding='utf-8')),
    }), encoding='utf-8')
    os._exit(23)
os.replace = interrupt
store.apply(sys.argv[2], 0, 'draft_edit', {'text': 'Soft colour at the café'})
'''
    child = subprocess.run(
        [sys.executable, '-c', script, str(store.root), session['id'], str(checkpoint)],
        capture_output=True, text=True, timeout=10,
    )
    assert child.returncode == 23, child.stderr
    interrupted = json.loads(checkpoint.read_text(encoding='utf-8'))
    assert Path(interrupted['parent']) == path.parent
    assert interrupted['value']['revision'] == 1
    assert interrupted['value']['drafts'][0]['text'] == 'Soft colour at the café'
    assert path.read_bytes() == before
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before_digest
    assert store.read(session['id']) == session
    if os.name != 'nt':
        assert interrupted['mode'] == 0o600
    print(json.dumps({
        'evidence': 'Real child stopped before atomic replacement',
        'child_exit': child.returncode,
        'before_sha256': before_digest,
        'after_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'old_revision': store.read(session['id'])['revision'],
        'temporary_revision': interrupted['value']['revision'],
        'same_directory': Path(interrupted['parent']) == path.parent,
        'temporary_mode': interrupted['mode'],
    }, sort_keys=True))


def test_failed_replace_cleans_only_own_new_temporary(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / 'state')
    session = store.create()
    path = store._session_path(session['id'])
    user_file = path.parent / f'.{path.name}.user-note'
    user_file.write_text('Keep this note', encoding='utf-8')
    before = {item.name: item.read_bytes() for item in path.parent.iterdir()}

    def failed_replace(source, destination):
        raise OSError('Replacement interrupted')

    monkeypatch.setattr(os, 'replace', failed_replace)
    with pytest.raises(OSError, match='Replacement interrupted'):
        store.apply(session['id'], 0, 'draft_edit', {'text': 'Warm side light'})
    assert {item.name: item.read_bytes() for item in path.parent.iterdir()} == before


def test_utf8_json_and_private_posix_file_mode(tmp_path):
    store = SessionStore(tmp_path / 'state')
    session = store.create('Study at the café')
    assert 'café' in store._session_path(session['id']).read_text(encoding='utf-8')
    if os.name != 'nt':
        for path in (store._session_path(session['id']), store._registry_path(session['id'])):
            assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_cli_has_no_default_root():
    assert _parser().parse_args(['new']).root is None


def test_cli_uses_explicit_root_without_optional_adapters(tmp_path, capsys):
    root = tmp_path / 'state'
    assert main(['--root', str(root), 'new', '--title', 'Ceramic portrait']) == 0
    captured = capsys.readouterr()
    assert captured.err == ''
    session = json.loads(captured.out)
    assert (root / 'sessions' / f"{session['id']}.json").is_file()


def test_cli_reports_real_lock_timeout_without_traceback(tmp_path):
    store = SessionStore(tmp_path / 'state')
    session = store.create()
    payload = tmp_path / 'payload.json'
    payload.write_text(json.dumps({'version': 1}), encoding='utf-8')
    child = None
    try:
        with portalocker.Lock(str(store.root / '.write.lock'), mode='a', timeout=1):
            child = subprocess.Popen([
                sys.executable, '-m', 'vybe_check', '--root', str(store.root),
                'event', session['id'], '--revision', '0', '--action', 'select_image_version',
                '--payload-file', str(payload),
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                stdout, stderr = child.communicate(timeout=7)
            except subprocess.TimeoutExpired:
                pytest.fail('The CLI did not bound its wait for the state lock')
        assert child.returncode == 2
        assert stdout == ''
        assert 'unavailable' in stderr.lower()
        assert 'Traceback' not in stderr
        assert len(stderr.splitlines()) == 1
        assert store.read(session['id']) == session
        print(json.dumps({
            'evidence': 'Real state lock prevented CLI mutation',
            'cli_exit': child.returncode, 'stdout': stdout, 'stderr': stderr.strip(),
        }, sort_keys=True))
    finally:
        if child is not None:
            _stop(child)


def test_cli_new_registry_timeout_leaves_no_partial_session(tmp_path):
    store = SessionStore(tmp_path / 'state')
    child = None
    try:
        with portalocker.Lock(str(store.root / '.registry.lock'), mode='a', timeout=1):
            child = subprocess.Popen([
                sys.executable, '-m', 'vybe_check', '--root', str(store.root),
                'new', '--title', 'Ceramic portrait',
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = child.communicate(timeout=7)
        assert child.returncode == 2
        assert stdout == ''
        assert 'unavailable' in stderr.lower()
        assert list((store.root / 'sessions').glob('*.json')) == []
        assert list((store.root / 'registry').glob('*.json')) == []
    finally:
        if child is not None:
            _stop(child)


def test_cli_lock_open_error_has_fixed_path_free_unavailable_message(tmp_path):
    root = tmp_path / 'state'
    root.mkdir()
    (root / '.write.lock').mkdir()
    child = subprocess.run([
        sys.executable, '-m', 'vybe_check', '--root', str(root),
        'new', '--title', 'Ceramic portrait',
    ], capture_output=True, text=True, timeout=7)
    assert child.returncode == 2
    assert child.stdout == ''
    assert str(root) not in child.stderr
    assert '.write.lock' not in child.stderr
    assert child.stderr == 'Vybe-Check workshop unavailable: local state could not be accessed\n'
    assert list((root / 'sessions').glob('*.json')) == []
    assert list((root / 'registry').glob('*.json')) == []
