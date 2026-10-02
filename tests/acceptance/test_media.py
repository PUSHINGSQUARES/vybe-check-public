"""Opaque media and bounded state file checks, preserving original bytes."""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess


def test_media_boundary(tmp_path):
    from tools.acceptance_runtime import registered, board, http
    store, state, picture = registered(tmp_path)
    before = picture.read_bytes()
    with board(store, state) as (_, origin):
        code, body, _ = http(origin, '/media/' + state['id'] + '/' + state['references'][0]['id'])
        assert code == 200 and body == before
        for suffix in ('missing', '../invented-reference.png', '%2e%2e%2finvented-reference.png'):
            code, body, _ = http(origin, '/media/' + state['id'] + '/' + suffix)
            assert code in (400,403,404) and before not in body


def test_original_readonly(tmp_path):
    from tools.acceptance_runtime import session, image, board, http
    store, state = session(tmp_path)
    picture = image(tmp_path)
    before = picture.read_bytes()
    state = store.apply(state['id'], state['revision'], 'register_reference', {'path':str(picture), 'label':'Original colour', 'role':'Colour'})
    with board(store, state) as (_, origin):
        assert http(origin, '/media/' + state['id'] + '/' + state['references'][0]['id'])[1] == before
    assert picture.read_bytes() == before
import sys
import time

import pytest

from vybe_check.workshop import SessionStore
from test_board import board, isolated_env


def register(store, session, path):
    return store.apply(session['id'], session['revision'], 'register_reference', {
        'path': str(path), 'label': 'Clay study', 'role': 'Colour reference'})['references'][-1]['id']


def test_real_http_media_is_opaque_bounded_and_unchanged(board, tmp_path):
    store, _, request = board
    a, b = store.create(), store.create()
    path = tmp_path / 'sample.png'
    original = b'Local image fixture'
    path.write_bytes(original)
    digest = hashlib.sha256(original).hexdigest()
    media_id = register(store, a, path)
    status, raw, headers = request('GET', f'/media/{a["id"]}/{media_id}')
    assert status == 200 and raw == original
    assert headers['Content-Type'] == 'image/png'
    assert path.read_bytes() == original
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    for route in (f'/media/{b["id"]}/{media_id}', f'/media/{a["id"]}/{"0" * 32}',
                  '/media/%2e%2e/sample.png', f'/media/{a["id"]}/%2e%2e',
                  '/media/?path=' + str(path), f'/media/{a["id"]}/{media_id}?path=/invented/file'):
        status = request('GET', route)[0]
        assert status == (200 if route.startswith(f'/media/{a["id"]}/{media_id}?') else 404)
    path.write_bytes(b'Changed reference')
    assert request('GET', f'/media/{a["id"]}/{media_id}')[0] == 404


def test_registration_records_digest_size_and_mime(tmp_path):
    store = SessionStore(tmp_path / 'state')
    session = store.create()
    path = tmp_path / 'sample.png'
    path.write_bytes(b'Local image fixture')
    media_id = register(store, session, path)
    entry = json.loads(store._registry_path(session['id']).read_text())['media'][media_id]
    assert entry['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert entry['size'] == path.stat().st_size
    assert entry['mime'] == 'image/png'


@pytest.mark.parametrize('change', ['content', 'symlink', 'directory', 'hardlink', 'parent-link', 'large', 'suffix'])
def test_resolve_refuses_changed_or_unavailable_media(tmp_path, change):
    store = SessionStore(tmp_path / 'state')
    session = store.create()
    folder = tmp_path / 'media'
    folder.mkdir()
    path = folder / 'sample.png'
    path.write_bytes(b'Local image fixture')
    original = path.read_bytes()
    media_id = register(store, session, path)
    registry_before = store._registry_path(session['id']).read_bytes()
    saved = tmp_path / 'saved.png'
    if change == 'content': path.write_bytes(b'Changed reference')
    elif change in ('symlink', 'directory', 'hardlink'):
        path.rename(saved)
        if change == 'symlink': path.symlink_to(saved)
        if change == 'directory': path.mkdir()
        if change == 'hardlink': os.link(saved, path)
        assert saved.read_bytes() == original
    elif change == 'parent-link':
        folder.rename(tmp_path / 'saved-media')
        folder.symlink_to(tmp_path / 'saved-media', target_is_directory=True)
    elif change == 'large':
        with path.open('r+b') as stream: stream.truncate(65 * 1024 * 1024)
    elif change == 'suffix':
        registry = json.loads(registry_before)
        replacement = tmp_path / 'sample.txt'
        replacement.write_bytes(original)
        registry['media'][media_id]['path'] = str(replacement)
        store._registry_path(session['id']).write_text(json.dumps(registry))
    assert store.resolve_media(session['id'], media_id) is None


@pytest.mark.parametrize('kind', ['directory', 'symlink', 'hardlink', 'empty', 'unsupported', 'large'])
def test_invalid_registration_does_not_change_state(tmp_path, kind):
    store = SessionStore(tmp_path / 'state')
    session = store.create()
    path = tmp_path / 'sample.png'
    if kind == 'directory': path.mkdir()
    elif kind in ('symlink', 'hardlink'):
        target = tmp_path / 'original.png'
        target.write_bytes(b'Keep original')
        if kind == 'symlink': path.symlink_to(target)
        else: os.link(target, path)
    else:
        path.write_bytes(b'' if kind == 'empty' else b'Keep original')
        if kind == 'unsupported': path = path.rename(tmp_path / 'sample.txt')
        if kind == 'large':
            with path.open('r+b') as stream: stream.truncate(65 * 1024 * 1024)
    before = [p.read_bytes() for p in (store._session_path(session['id']), store._registry_path(session['id']))]
    with pytest.raises((ValueError, OSError)):
        register(store, session, path)
    assert [p.read_bytes() for p in (store._session_path(session['id']), store._registry_path(session['id']))] == before


BOUNDARY_SCRIPT = '''
import json, os, sys
from pathlib import Path
import vybe_check.workshop as workshop
store = workshop.SessionStore(Path(sys.argv[1]))
session_id, kind, race = sys.argv[2:]
path = {'state': store._session_path(session_id), 'registry': store._registry_path(session_id),
        'write-lock': store.root / '.write.lock', 'registry-lock': store.root / '.registry.lock'}[kind]
original_open, original_path_open = os.open, Path.open
swapped = False
def swap():
    global swapped
    if not swapped:
        swapped = True
        path.rename(path.with_name(path.name + '.preserved'))
        os.mkfifo(path)
def wrapped_open(name, *args, **kwargs):
    if (str(name) == str(path) or (str(name) == path.name and 'dir_fd' in kwargs)) and race == 'race': swap()
    return original_open(name, *args, **kwargs)
def wrapped_path_open(self, *args, **kwargs):
    if self == path and race == 'race': swap()
    return original_path_open(self, *args, **kwargs)
os.open, Path.open = wrapped_open, wrapped_path_open
try:
    if kind == 'state': store.read(session_id)
    elif kind == 'registry': store.nonce_for(session_id)
    elif kind == 'write-lock': store.apply(session_id, 0, 'draft_edit', {'text': 'Draft'})
    else: store.create()
except (OSError, ValueError):
    print('Refused', flush=True)
else:
    print('Accepted', flush=True)
'''


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='POSIX nonregular boundary')
@pytest.mark.parametrize('kind', ['state', 'registry', 'write-lock', 'registry-lock'])
@pytest.mark.parametrize('boundary', ['fifo', 'race', 'link', 'directory'])
def test_state_registry_and_lock_boundaries_are_prompt_and_safe(tmp_path, kind, boundary):
    store = SessionStore(tmp_path / 'state')
    session = store.create()
    path = {'state': store._session_path(session['id']), 'registry': store._registry_path(session['id']),
            'write-lock': store.root / '.write.lock', 'registry-lock': store.root / '.registry.lock'}[kind]
    before = path.read_bytes()
    preserved = tmp_path / 'original'
    if boundary != 'race':
        path.rename(preserved)
        if boundary == 'fifo': os.mkfifo(path)
        if boundary == 'link': path.symlink_to(preserved)
        if boundary == 'directory': path.mkdir()
    child = subprocess.Popen([sys.executable, '-c', BOUNDARY_SCRIPT, str(store.root), session['id'], kind, boundary],
        env=isolated_env(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        try:
            stdout, stderr = child.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            child.send_signal(signal.SIGINT)
            child.communicate(timeout=4)
            pytest.fail('Nonregular state boundary blocked beyond two seconds')
        assert child.returncode == 0, stderr
        assert stdout.strip() == 'Refused'
        if boundary == 'race': preserved = path.with_name(path.name + '.preserved')
        assert preserved.read_bytes() == before
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGINT)
            child.communicate(timeout=4)


def test_malformed_ids_are_refused_before_path_access(tmp_path):
    store = SessionStore(tmp_path / 'state')
    for value in ('../example', '', None, [], 'A' * 32):
        with pytest.raises(ValueError): store.read(value)


@pytest.mark.parametrize('change', ['symlink', 'directory', 'hardlink', 'unsupported'])
def test_http_unavailable_media_uses_checked_bytes(board, tmp_path, change):
    store, _, request = board
    session = store.create()
    path = tmp_path / 'sample.png'
    path.write_bytes(b'Preserved source')
    media_id = register(store, session, path)
    saved = tmp_path / 'preserved.png'
    path.rename(saved)
    if change == 'symlink': path.symlink_to(saved)
    elif change == 'directory': path.mkdir()
    elif change == 'hardlink': os.link(saved, path)
    else:
        unsupported = tmp_path / 'sample.txt'
        unsupported.write_bytes(saved.read_bytes())
        registry = json.loads(store._registry_path(session['id']).read_text())
        registry['media'][media_id]['path'] = str(unsupported)
        store._registry_path(session['id']).write_text(json.dumps(registry))
    assert request('GET', f'/media/{session["id"]}/{media_id}')[0] == 404
    assert saved.read_bytes() == b'Preserved source'


def persisted_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')


def state_bytes(store, identifier):
    return store._session_path(identifier).read_bytes(), store._registry_path(identifier).read_bytes()


def fill_state_to_size(store, identifier, target):
    state = store.read(identifier)
    state['title'] = ''
    state['title'] = 'S' * (target - len(persisted_bytes(state)))
    assert len(persisted_bytes(state)) == target
    store._write(store._session_path(identifier), state)
    assert len(store._session_path(identifier).read_bytes()) == target
    assert store.read(identifier)['id'] == identifier
    return state


@pytest.mark.parametrize('offset', [0, 1])
def test_size_shared_writer_checks_complete_utf8_serialisation(tmp_path, offset):
    from vybe_check.workshop import MAX_STATE_BYTES
    store = SessionStore(tmp_path / 'state')
    session = store.create()
    before, registry = state_bytes(store, session['id'])
    value = dict(session, title='')
    overhead = len(persisted_bytes(value))
    remaining = MAX_STATE_BYTES + offset - overhead
    value['title'] = '\u00e9' * (remaining // 2) + ('S' if remaining % 2 else '')
    assert len(persisted_bytes(value)) == MAX_STATE_BYTES + offset
    assert len(json.dumps(value, ensure_ascii=False)) < MAX_STATE_BYTES
    if offset:
        with pytest.raises(ValueError, match='Local file too large'):
            store._write(store._session_path(session['id']), value)
        assert state_bytes(store, session['id']) == (before, registry)
        assert store.read(session['id']) == session
    else:
        store._write(store._session_path(session['id']), value)
        assert len(store._session_path(session['id']).read_bytes()) == MAX_STATE_BYTES
        assert store.read(session['id']) == value
        assert store._registry_path(session['id']).read_bytes() == registry


def test_size_creation_refuses_oversized_unicode_title_without_partial_records(tmp_path):
    from vybe_check.workshop import MAX_STATE_BYTES
    store = SessionStore(tmp_path / 'state')
    with pytest.raises(ValueError, match='Local file too large'):
        store.create('\U0001f312 ' * (MAX_STATE_BYTES // 5))
    assert list((store.root / 'sessions').iterdir()) == []
    assert list((store.root / 'registry').iterdir()) == []


def test_size_api_event_refusal_preserves_readable_state(tmp_path):
    from vybe_check.workshop import MAX_STATE_BYTES
    store = SessionStore(tmp_path / 'state')
    session = store.create()
    fill_state_to_size(store, session['id'], MAX_STATE_BYTES - 1000)
    before = state_bytes(store, session['id'])
    with pytest.raises(ValueError, match='Local file too large'):
        store.apply(session['id'], 0, 'draft_edit', {'text': 'Soft light ' * 300})
    assert state_bytes(store, session['id']) == before
    assert store.read(session['id'])['revision'] == 0


def test_size_cli_event_refusal_preserves_readable_state(tmp_path):
    from test_board import cli_run
    from vybe_check.workshop import MAX_STATE_BYTES
    store = SessionStore(tmp_path / 'state')
    session = store.create()
    fill_state_to_size(store, session['id'], MAX_STATE_BYTES - 1000)
    before = state_bytes(store, session['id'])
    payload = tmp_path / 'payload.json'
    payload.write_text(json.dumps({'text': 'Soft light ' * 300}), encoding='utf-8')
    result = cli_run(tmp_path, 'event', session['id'], '--revision', '0', '--action', 'draft_edit', '--payload-file', str(payload))
    assert result.returncode == 2
    assert result.stdout == '' and str(tmp_path) not in result.stderr
    assert state_bytes(store, session['id']) == before
    assert store.read(session['id'])['revision'] == 0


@pytest.mark.parametrize('action', ['register_reference', 'record_preview'])
def test_size_media_event_refusal_preserves_registry_and_source(tmp_path, action):
    from vybe_check.workshop import MAX_STATE_BYTES
    store = SessionStore(tmp_path / 'state')
    session = store.create()
    if action == 'record_preview':
        session = store.apply(session['id'], 0, 'direct_image', {'brief': {
            'outcome': 'Clay portrait', 'subject_action': 'Potter holds a bowl',
            'visual_priority': 'Hands', 'frame': 'Close portrait', 'light': 'Window light'},
            'prompt': 'A potter holds a glazed bowl'})
    fill_state_to_size(store, session['id'], MAX_STATE_BYTES - 10)
    path = tmp_path / 'sample.png'
    path.write_bytes(b'Preserved local source')
    payload = {'path': str(path), 'label': 'Clay study', 'role': 'Colour reference'} if action == 'register_reference' else {
        'path': str(path), 'prompt_version': 1, 'model': 'Local study', 'workflow': 'Still study'}
    before = state_bytes(store, session['id'])
    source = path.read_bytes()
    with pytest.raises(ValueError, match='Local file too large'):
        store.apply(session['id'], session['revision'], action, payload)
    assert state_bytes(store, session['id']) == before
    assert store.read(session['id'])['revision'] == session['revision']
    assert path.read_bytes() == source


def test_size_registry_refusal_preserves_both_records(tmp_path):
    from vybe_check.workshop import MAX_STATE_BYTES
    store = SessionStore(tmp_path / 'state')
    session = store.create()
    registry = json.loads(store._registry_path(session['id']).read_text())
    registry['padding'] = ''
    registry['padding'] = 'R' * (MAX_STATE_BYTES - 10 - len(persisted_bytes(registry)))
    store._write(store._registry_path(session['id']), registry)
    path = tmp_path / 'sample.png'
    path.write_bytes(b'Preserved local source')
    before = state_bytes(store, session['id'])
    with pytest.raises(ValueError, match='Local file too large'):
        register(store, session, path)
    assert state_bytes(store, session['id']) == before
    assert store.nonce_for(session['id']) == registry['nonce']
    assert store.read(session['id']) == session
    assert path.read_bytes() == b'Preserved local source'
