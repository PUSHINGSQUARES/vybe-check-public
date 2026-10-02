"""Real local runtime seams shared by the named acceptance probes."""
from contextlib import contextmanager
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tools import verify_host as verification

BRIEF = {'outcome':'Ceramic study', 'subject_action':'Turn a bowl', 'visual_priority':'Rim', 'frame':'Close portrait', 'light':'Soft reflected light'}


def environment(tmp_path, monkeypatch=None):
    parent = tmp_path / 'isolated-environment'
    env = verification.isolated_environment(parent)
    source = os.environ.get('VYBE_LAYOUT_SOURCE_ORIGIN')
    if source:
        verification.require(os.environ.get('VYBE_AUTHORING_ONLY') == '1', 'Source origin is authoring only')
        env['PYTHONPATH'] = str(Path(source).parent)
    if monkeypatch is not None:
        for key, value in env.items(): monkeypatch.setenv(key, value)
    return env


def installed_guard():
    import vybe_check
    origin = Path(vybe_check.__file__).resolve()
    source = os.environ.get('VYBE_LAYOUT_SOURCE_ORIGIN')
    if source and os.environ.get('VYBE_AUTHORING_ONLY') == '1':
        verification.require(origin.parent == Path(source).resolve(), 'Wrong authoring module origin')
        return 'AUTHORING SNAPSHOT'
    verification.require(not os.environ.get('PYTHONPATH'), 'Installed probe cannot use source PYTHONPATH')
    distribution = importlib.metadata.distribution('vybe-check')
    verification.require(distribution.version == vybe_check.__version__ and origin.is_relative_to(Path(sys.prefix).resolve()), 'Clean installed origin required')
    verification.require(any(Path(distribution.locate_file(f)).resolve() == origin for f in distribution.files or ()), 'Module absent from installed distribution')
    return 'INSTALLED RUNTIME'


def pending_gate(callback, *args, **kwargs):
    """Authoring may report pending; release probes always fail absent evidence."""
    import pytest
    if os.environ.get('VYBE_AUTHORING_ONLY') == '1':
        pytest.skip('PENDING actual final installed/native evidence; source authoring only')
    try:
        callback(*args, **kwargs)
    except (ValueError, OSError, KeyError, TypeError) as error:
        pytest.fail('Required acceptance evidence refused: ' + str(error))


def session(tmp_path):
    installed_guard()
    from vybe_check.workshop import SessionStore
    store = SessionStore(tmp_path / 'state')
    state = store.create('Invented ceramic study')
    state = store.apply(state['id'], 0, 'direct_image', {'brief':BRIEF, 'prompt':'A potter turns a bowl',
        'locks':['Blue glaze'], 'provenance':[{'kind':'supplied','text':'Bowl','source':'Invented brief'},
            {'kind':'inferred','text':'Visible rim','source':'Composition'}, {'kind':'proposed','text':'Soft shadow','source':'Creative choice'}]})
    return store, state


def cli(tmp_path, env, *args):
    return subprocess.run([sys.executable, '-B', '-m', 'vybe_check', '--root', str(tmp_path / 'state'), *args],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20, shell=False)


@contextmanager
def board(store, state):
    from vybe_check.studio.server import create_server
    listener = create_server(0, root=store.root, store=store, active_id=state['id'])
    thread = threading.Thread(target=listener.serve_forever)
    thread.start()
    try:
        yield listener, 'http://127.0.0.1:' + str(listener.server_port)
    finally:
        listener.shutdown(); listener.server_close(); thread.join(timeout=5)
        assert not thread.is_alive()


def http(origin, path, payload=None, headers=None):
    raw = None if payload is None else json.dumps(payload).encode()
    request = Request(origin + path, data=raw, headers=headers or {}, method='GET' if raw is None else 'POST')
    try:
        with urlopen(request, timeout=5) as response: return response.status, response.read(), dict(response.headers)
    except HTTPError as error:
        with error: return error.code, error.read(), dict(error.headers)


def image(tmp_path):
    from PIL import Image
    path = tmp_path / 'invented-reference.png'
    pixels = Image.new('RGB', (32, 24))
    pixels.putdata([(x * 7 % 256, y * 11 % 256, (x + y) * 3 % 256) for y in range(24) for x in range(32)])
    pixels.save(path)
    return path


def registered(tmp_path):
    store, state = session(tmp_path)
    path = image(tmp_path)
    state = store.apply(state['id'], state['revision'], 'register_reference', {'path':str(path), 'label':'Invented colour reference', 'role':'Colour', 'source_kind':'supplied_reference'})
    return store, state, path


def state_digest(store):
    return hashlib.sha256(store._session_path(next(p.stem for p in (store.root / 'sessions').glob('*.json'))).read_bytes()).hexdigest()


def lifecycle_gate(criterion):
    """Package removal/update must run in its own disposable installed environment."""
    manifest, records, root = verification.required_records('installed-lifecycle')
    for system in verification.SYSTEMS:
        found = [r for r in records if r.get('system') == system and r.get('criterion') == criterion]
        verification.require(len(found) == 1, 'Missing installed lifecycle host')
        row = found[0]
        verification.require(row.get('scope') == 'installed-lifecycle-observed', 'Synthetic lifecycle receipt refused')
        commands = row.get('commands')
        verification.require(isinstance(commands, list) and commands, 'Actual lifecycle commands required')
        observed = []
        for ref in commands:
            command = verification.json_bytes(verification.bound_bytes(ref, root))
            verification.validate_command(command, Path(root) / Path(ref['path']).parent)
            observed.append(command['argv'])
        before = verification.json_bytes(verification.bound_bytes(row.get('before_data'), root))
        after = verification.json_bytes(verification.bound_bytes(row.get('after_data'), root))
        verification.require(before and before == after, 'Creative data preservation failed')
        verification.require(before.get('scope') == after.get('scope') == 'retained-state-observed' and before.get('state_files') and before.get('schema_version') == after.get('schema_version') == 1, 'Compatible retained state and media verification required')
        verifier = verification.bound_bytes(row.get('retained_verifier_code'), root)
        verification.require(hashlib.sha256(verifier).hexdigest() == after.get('verifier_sha256'), 'Retained verifier byte origin mismatch')
        check = verification.json_bytes(verification.bound_bytes(row.get('retained_verifier_command'), root))
        check_root = Path(root) / Path(row['retained_verifier_command']['path']).parent
        verification.validate_command(check, check_root)
        verification.require(check['system'] == system and check['argv'][1:3] == ['-B',row.get('retained_verifier_origin')] and 'retained-state' in check['argv'], 'Actual separate retained verifier required')
        output = verification.json_bytes(verification.regular_bytes(check_root/'stdout.log'))
        verification.require(output.get('scope') == 'retained-state-observed' and output.get('verifier_sha256') == after['verifier_sha256'] and output.get('state_files') == len(after['state_files']) and output.get('media') == len(after['media']), 'Retained verifier output mismatch')
        if criterion in ('DoD-9.3','DoD-10.2'):
            verification.require(any(a[1:5] == ['-B','-m','pip','uninstall'] and 'vybe-check' in a for a in observed), 'Documented pip uninstall not executed')
            absent = verification.json_bytes(verification.bound_bytes(row.get('package_absence_command'), root))
            absent_root = Path(root) / Path(row['package_absence_command']['path']).parent
            verification.validate_command(absent, absent_root)
            verification.require(absent['system'] == system and absent['argv'][1:3] == ['-B','-c'] and "find_spec('vybe_check')" in absent['argv'][3], 'Actual import absence observation required')
            verification.require(verification.json_bytes(verification.regular_bytes(absent_root/'stdout.log')) == {'package_absent':True}, 'Package removal not observed')
        if criterion == 'DoD-9.3':
            verification.require(row.get('unrelated_before') == row.get('unrelated_after') and row.get('modified_before') == row.get('modified_after') and row.get('owned_detached') is True, 'Registration boundary failed')
        if criterion == 'DoD-12':
            verification.require(row.get('old_runtime_version') != row.get('new_runtime_version') == manifest['candidate']['version'] and row.get('prior_versions_readable') and any('install' in a and '--upgrade' in a for a in observed), 'Real runtime update not observed')
        if criterion == 'DoD-13':
            verification.require(row.get('interruption_after_backup') is True and row.get('original_readable') is True and row.get('backup_readable') is True, 'Migration interruption not observed')
