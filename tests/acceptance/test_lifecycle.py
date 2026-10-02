"""Explicit lifecycle and interrupted move recovery in fresh roots."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_unregister_registration_boundary(tmp_path):
    from tools.acceptance_runtime import environment, cli
    from vybe_check.install import registration_target
    env = environment(tmp_path)
    for agent in ('codex','claude'):
        result = cli(tmp_path,env,'install','--agent',agent,'--scope','project','--project',str(tmp_path))
        assert result.returncode == 0, result.stderr
    owned = registration_target('codex','project',tmp_path)
    modified = registration_target('claude','project',tmp_path)
    (modified/'SKILL.md').write_bytes(b'Locally modified invented skill')
    foreign = tmp_path/'unrelated-registration';foreign.mkdir()
    (foreign/'sentinel').write_bytes(b'Unrelated bytes')
    before = tree(modified)
    result = cli(tmp_path,env,'unregister','--agent','codex','--scope','project','--project',str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert not owned.exists()
    result = cli(tmp_path,env,'unregister','--agent','claude','--scope','project','--project',str(tmp_path))
    assert result.returncode == 2
    assert tree(modified) == before and (foreign/'sentinel').read_bytes() == b'Unrelated bytes'


def test_unregister_preserves_data(tmp_path):
    from tools.acceptance_runtime import environment, cli, registered
    env = environment(tmp_path)
    store, state, picture = registered(tmp_path)
    before = state_digest(store.root)
    source = picture.read_bytes()
    result = cli(tmp_path,env,'install','--agent','codex','--scope','project','--project',str(tmp_path))
    assert result.returncode == 0
    result = cli(tmp_path,env,'unregister','--agent','codex','--scope','project','--project',str(tmp_path))
    assert result.returncode == 0
    assert state_digest(store.root) == before and picture.read_bytes() == source


def test_uninstall_registration_boundary():
    from tools.acceptance_runtime import pending_gate, lifecycle_gate
    pending_gate(lifecycle_gate,'DoD-9.3')


def test_uninstall_preserves_data():
    from tools.acceptance_runtime import pending_gate, lifecycle_gate
    pending_gate(lifecycle_gate,'DoD-10.2')


def test_update_preserves_versions():
    from tools.acceptance_runtime import pending_gate, lifecycle_gate
    pending_gate(lifecycle_gate,'DoD-12')


def test_migration_rollback(tmp_path):
    from tools.acceptance_runtime import environment, installed_guard, registered
    from vybe_check import lifecycle
    installed_guard()
    env = environment(tmp_path)
    store, state, picture = registered(tmp_path)
    before = state_digest(store.root)
    original_picture = picture.read_bytes()
    script = """
import os,sys
from pathlib import Path
from vybe_check import lifecycle
from vybe_check.workshop import SessionStore
store=SessionStore(Path(sys.argv[1]))
assert store.read(sys.argv[2])['image_versions']
def interrupt(snapshot):
    assert Path(snapshot['backup'],'manifest.json').is_file()
    os._exit(23)
lifecycle._identity_publication=interrupt
lifecycle.migrate_state(store.root)
"""
    result = subprocess.run([sys.executable, '-B', '-c', script, str(store.root), state['id']], env=env,
        capture_output=True, text=True, timeout=20, shell=False)
    assert result.returncode == 23, result.stderr
    assert state_digest(store.root) == before and picture.read_bytes() == original_picture
    backups = list((store.root/'backups').glob('before-update-*'))
    assert len(backups) == 1
    manifest = json.loads((backups[0]/'manifest.json').read_bytes())
    assert manifest['complete'] is True
    for name, binding in manifest['files'].items():
        raw = (backups[0]/name).read_bytes()
        assert raw == (store.root/name).read_bytes()
        import hashlib
        assert binding == {'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    assert store.read(state['id'])['image_versions'] == state['image_versions']

from vybe_check import install as adapter
from test_installer import tree, target_at


def child_env(tmp_path):
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LC_ALL': 'C'}
    for name in ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'XDG_DATA_HOME', 'VYBE_CHECK_ROOT', 'TMPDIR'):
        path = tmp_path / name.lower()
        path.mkdir(exist_ok=True)
        env[name] = str(path)
    env['PYTHONPATH'] = str(Path(adapter.__file__).resolve().parents[1])
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    import importlib.util
    for module in ('vybe_check', 'vybe_check.workshop', 'vybe_check.install', 'vybe_check.cli'):
        assert Path(importlib.util.find_spec(module).origin).resolve().is_relative_to(Path(env['PYTHONPATH']) / 'vybe_check')
    for name in ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'XDG_DATA_HOME', 'VYBE_CHECK_ROOT', 'TMPDIR'):
        assert Path(env[name]).is_relative_to(tmp_path)
    return env


@pytest.mark.parametrize('phase', ['before', 'after'])
def test_real_child_interruption_has_receipt_and_explicit_exclusive_recovery(tmp_path, phase, monkeypatch):
    target = target_at(tmp_path)
    adapter.register(target)
    before = tree(target)
    script = '''
import os, sys
from pathlib import Path
from vybe_check import install
real_move = install.rename_absent
def interrupt(source, destination):
    if Path(source) == Path(sys.argv[1]):
        if sys.argv[2] == 'after':
            real_move(source, destination)
        os._exit(23)
    real_move(source, destination)
install.rename_absent = interrupt
install.detach(Path(sys.argv[1]))
'''
    command = [sys.executable, '-B', '-c', script, str(target), phase]
    child = subprocess.run(command, env=child_env(tmp_path), capture_output=True, text=True, timeout=10)
    assert child.returncode == 23, child.stderr
    archive = next(adapter.metadata_root(target).glob('archive-*'))
    transaction = json.loads((archive / 'transaction.json').read_text())
    assert transaction['receipt'] and transaction['identity']
    preserved = target if phase == 'before' else archive / 'registration'
    assert tree(preserved) == before
    with pytest.raises(ValueError, match='recovery required'):
        adapter.register(target)
    calls = []
    real_move = adapter.rename_absent
    def tracked(source, destination):
        calls.append((Path(source), Path(destination)))
        real_move(source, destination)
    monkeypatch.setattr(adapter, 'rename_absent', tracked)
    assert adapter.recover_registration(target, archive)['status'] == 'recovered'
    if phase == 'after':
        assert calls == [(archive / 'registration', target)]
    assert tree(target) == before
    assert adapter.register(target)['status'] == 'unchanged'
    print(json.dumps({'phase': phase, 'args': command, 'root': str(tmp_path), 'exit': child.returncode}))


def cli(tmp_path, env, *args):
    command = [sys.executable, '-B', '-m', 'vybe_check', '--root', str(tmp_path / 'state'), *args]
    assert env['PYTHONDONTWRITEBYTECODE'] == '1'
    assert Path(env['PYTHONPATH']) == Path(adapter.__file__).resolve().parents[1]
    for name in ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'XDG_DATA_HOME', 'VYBE_CHECK_ROOT', 'TMPDIR'):
        assert Path(env[name]).is_relative_to(tmp_path)
    child = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    initial_poll = child.poll()
    try:
        stdout, stderr = child.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        child.terminate()
        child.communicate(timeout=10)
        raise
    result = subprocess.CompletedProcess(command, child.returncode, stdout, stderr)
    print(json.dumps({'args': command, 'cwd': os.getcwd(), 'env': env, 'pid': child.pid,
                      'initial_poll': initial_poll, 'communicate_returncode': child.returncode,
                      'final_poll': child.poll(), 'exit': result.returncode, 'root': str(tmp_path),
                      'stdout': stdout, 'stderr': stderr}))
    return result


@pytest.mark.parametrize('agent', ['codex', 'claude'])
@pytest.mark.parametrize('scope', ['user', 'project'])
def test_source_cli_explicit_selection_and_preserved_unregister(tmp_path, agent, scope):
    env = child_env(tmp_path)
    base = Path(env['HOME']) if scope == 'user' else tmp_path / 'project'
    selection = ['--agent', agent, '--scope', scope]
    if scope == 'project':
        base.mkdir()
        selection += ['--project', str(base)]
    parent = base / ('.agents' if agent == 'codex' else '.claude') / 'skills'
    unrelated = parent / 'other-skill' / 'SKILL.md'
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b'Unrelated sentinel')
    target = parent / 'vybe-check'
    result = cli(tmp_path, env, 'install', *selection)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'installed'
    before = tree(target)
    assert cli(tmp_path, env, 'install', *selection).returncode == 0
    result = cli(tmp_path, env, 'inspect', *selection)
    assert result.returncode == 0 and json.loads(result.stdout)['status'] == 'owned'
    result = cli(tmp_path, env, 'unregister', *selection)
    assert result.returncode == 0, result.stderr
    assert tree(Path(json.loads(result.stdout)['archive'])) == before
    assert not target.exists()
    assert unrelated.read_bytes() == b'Unrelated sentinel'
    assert not (tmp_path / 'state').exists()


def test_cli_modified_detach_refuses_and_help_describes_two_operations(tmp_path):
    env = child_env(tmp_path)
    project = tmp_path / 'project'
    project.mkdir()
    selection = ['--agent', 'codex', '--scope', 'project', '--project', str(project)]
    assert cli(tmp_path, env, 'install', *selection).returncode == 0
    target = project / '.agents' / 'skills' / 'vybe-check'
    (target / 'SKILL.md').write_bytes(b'Modified sentinel')
    before = tree(target)
    result = cli(tmp_path, env, 'unregister', *selection)
    assert result.returncode == 2 and 'conflict' in result.stderr and 'Traceback' not in result.stderr
    assert tree(target) == before
    help_result = cli(tmp_path, env, 'unregister', '--help')
    assert 'python -m pip uninstall vybe-check' in help_result.stdout
    assert 'each' in help_result.stdout


def test_cli_project_requires_explicit_project_and_user_rejects_project(tmp_path):
    env = child_env(tmp_path)
    for arguments in [('install', '--agent', 'codex', '--scope', 'project'),
                      ('install', '--agent', 'claude', '--scope', 'user', '--project', str(tmp_path))]:
        result = cli(tmp_path, env, *arguments)
        assert result.returncode == 2
        assert not (tmp_path / '.claude').exists()
        assert not (tmp_path / '.agents').exists()


def test_cli_explicit_recovery_after_real_interruption(tmp_path):
    env = child_env(tmp_path)
    project = tmp_path / 'project'
    project.mkdir()
    selection = ['--agent', 'codex', '--scope', 'project', '--project', str(project)]
    assert cli(tmp_path, env, 'install', *selection).returncode == 0
    target = project / '.agents' / 'skills' / 'vybe-check'
    before = tree(target)
    script = '''
import os, sys
from pathlib import Path
from vybe_check import install
real_move = install.rename_absent
def interrupt(source, destination):
    real_move(source, destination)
    os._exit(23)
install.rename_absent = interrupt
install.detach(Path(sys.argv[1]))
'''
    child = subprocess.run([sys.executable, '-B', '-c', script, str(target)], env=env,
                           capture_output=True, text=True, timeout=10)
    assert child.returncode == 23
    archive = next(adapter.metadata_root(target).glob('archive-*'))
    result = cli(tmp_path, env, 'inspect', *selection)
    assert result.returncode == 2 and 'recovery required' in result.stderr
    result = cli(tmp_path, env, 'recover-registration', *selection, '--transaction', archive.name.removeprefix('archive-'))
    assert result.returncode == 0 and json.loads(result.stdout)['status'] == 'recovered'
    assert tree(target) == before


def test_registration_waits_for_real_process_lock(tmp_path):
    import time
    import portalocker
    target = target_at(tmp_path)
    target.parent.mkdir(parents=True)
    env = child_env(tmp_path)
    script = '''
import json, sys
from pathlib import Path
from vybe_check.install import register
Path(sys.argv[2]).write_text('Ready')
print(json.dumps(register(Path(sys.argv[1]))), flush=True)
'''
    ready = tmp_path / 'ready'
    child = None
    try:
        with portalocker.Lock(str(target.parent / '.vybe-check-install.lock'), timeout=1):
            child = subprocess.Popen([sys.executable, '-B', '-c', script, str(target), str(ready)],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            deadline = time.monotonic() + 5
            while not ready.exists():
                assert child.poll() is None
                assert time.monotonic() < deadline
                time.sleep(0.01)
            time.sleep(0.2)
            assert child.poll() is None
            assert not target.exists()
        stdout, stderr = child.communicate(timeout=10)
        assert child.returncode == 0, stderr
        assert json.loads(stdout)['status'] == 'installed'
        assert adapter.owned_manifest(target)
    finally:
        if child is not None:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=10)


def preserved_snapshot(root):
    """Capture bytes and link text without following links."""
    import stat
    result = {}
    for path in root.rglob('*'):
        mode = path.lstat().st_mode
        name = path.relative_to(root).as_posix()
        if stat.S_ISLNK(mode):
            result[name] = ('link', os.readlink(path))
        elif stat.S_ISREG(mode):
            result[name] = ('file', path.read_bytes())
        elif stat.S_ISDIR(mode):
            result[name] = ('directory', None)
        else:
            result[name] = ('unsupported', stat.S_IFMT(mode))
    return result


def interrupted_registration(tmp_path, phase):
    target = target_at(tmp_path)
    adapter.register(target)
    script = '''
import os, sys
from pathlib import Path
from vybe_check import install
real_move = install.rename_absent
def interrupt(source, destination):
    if Path(source) == Path(sys.argv[1]):
        if sys.argv[2] == 'after':
            real_move(source, destination)
        os._exit(23)
    real_move(source, destination)
install.rename_absent = interrupt
install.detach(Path(sys.argv[1]))
'''
    command = [sys.executable, '-B', '-c', script, str(target), phase]
    env = child_env(tmp_path)
    child = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
    assert child.returncode == 23, child.stderr
    archive = next(adapter.metadata_root(target).glob('archive-*'))
    candidate = target if phase == 'before' else archive / 'registration'
    print(json.dumps({'phase': phase, 'args': command, 'exit': child.returncode,
                      'root': str(tmp_path), 'source': str(adapter.__file__)}))
    return target, archive, candidate, env


@pytest.mark.parametrize('phase', ['before', 'after'])
@pytest.mark.parametrize('damage', ['modified', 'missing', 'unknown', 'symlink'])
def test_recovery_rejects_invalid_complete_inventory(tmp_path, phase, damage):
    target, archive, candidate, env = interrupted_registration(tmp_path, phase)
    skill = candidate / 'SKILL.md'
    if damage == 'modified':
        skill.write_bytes(skill.read_bytes() + b'\nEdited while interrupted')
    elif damage == 'missing':
        adapter.rename_absent(candidate / 'references' / 'runtime.md', tmp_path / 'saved-runtime.md')
    elif damage == 'unknown':
        (candidate / 'foreign.txt').write_bytes(b'Foreign member sentinel')
    else:
        adapter.rename_absent(skill, tmp_path / 'saved-skill.md')
        external = tmp_path / 'external-sentinel'
        external.write_bytes(b'External sentinel')
        skill.symlink_to(external)
    before = preserved_snapshot(tmp_path)
    with pytest.raises(ValueError, match='recovery required'):
        adapter.recover_registration(target, archive)
    assert preserved_snapshot(tmp_path) == before
    assert not (archive / 'resolved.json').exists()
    assert candidate.is_dir()
    assert target.exists() == (phase == 'before')
    # Exercise the source CLI refusal too, with an explicit fake project selection.
    result = cli(tmp_path, env, 'recover-registration', '--agent', 'codex', '--scope', 'project',
                 '--project', str(tmp_path), '--transaction', archive.name.removeprefix('archive-'))
    assert result.returncode == 2, result.stdout
    assert 'recovery required' in result.stderr and 'Traceback' not in result.stderr
    assert preserved_snapshot(tmp_path) == before


@pytest.mark.parametrize('phase', ['before', 'after'])
def test_recovery_rejects_recomputed_local_ownership(tmp_path, phase):
    target, archive, candidate, _ = interrupted_registration(tmp_path, phase)
    import hashlib
    skill = candidate / 'SKILL.md'
    skill.write_bytes(b'Local ownership forgery sentinel')
    record = json.loads((candidate / adapter.OWNER).read_text())
    record['files']['SKILL.md'] = hashlib.sha256(skill.read_bytes()).hexdigest()
    (candidate / adapter.OWNER).write_text(json.dumps(record))
    before = preserved_snapshot(tmp_path)
    with pytest.raises(ValueError, match='recovery required'):
        adapter.recover_registration(target, archive)
    assert preserved_snapshot(tmp_path) == before
    assert not (archive / 'resolved.json').exists()


def test_recovery_detects_edit_after_exclusive_restoration(tmp_path, monkeypatch):
    target, archive, candidate, _ = interrupted_registration(tmp_path, 'after')
    original = tree(candidate)
    real_move = adapter.rename_absent
    changed = original['SKILL.md'] + b'\nConcurrent edit after restoration'
    def move_and_edit(source, destination):
        real_move(source, destination)
        if Path(destination) == target:
            (target / 'SKILL.md').write_bytes(changed)
    monkeypatch.setattr(adapter, 'rename_absent', move_and_edit)
    with pytest.raises(ValueError, match='recovery required'):
        adapter.recover_registration(target, archive)
    preserved = target if target.exists() else candidate
    assert tree(preserved) == dict(original, **{'SKILL.md': changed})
    assert not (archive / 'resolved.json').exists()
    with pytest.raises(ValueError, match='recovery required'):
        adapter.register(target)
    with pytest.raises(ValueError, match='recovery required'):
        adapter.recover_registration(target, archive)


@pytest.mark.parametrize('phase', ['before', 'after'])
def test_recovery_clean_controls_validate_external_ownership(tmp_path, phase):
    target, archive, candidate, _ = interrupted_registration(tmp_path, phase)
    before = tree(candidate)
    receipt = adapter.owned_manifest(candidate, adapter.metadata_root(target))
    assert adapter.recover_registration(target, archive)['status'] == 'recovered'
    assert tree(target) == before
    assert adapter.owned_manifest(target) == receipt
    assert json.loads((archive / 'resolved.json').read_text()) == {'status': 'recovered'}


def bounded_refusal(command, env, root, category):
    import time
    started = time.monotonic()
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=3)
    except subprocess.TimeoutExpired:
        print(json.dumps({'args': command, 'root': str(root), 'timeout_seconds': 3,
                          'timed_out': True, 'source': str(adapter.__file__)}))
        pytest.fail('Unsupported file open blocked past the bounded refusal deadline')
    elapsed = time.monotonic() - started
    print(json.dumps({'args': command, 'root': str(root), 'exit': result.returncode,
                      'seconds': elapsed, 'stderr': result.stderr, 'stdout': result.stdout,
                      'source': str(adapter.__file__)}))
    assert result.returncode == 2, result.stdout + result.stderr
    assert category in result.stderr
    assert 'Traceback' not in result.stderr and result.stdout == ''
    assert elapsed < 3
    return result


@pytest.mark.skipif(os.name == 'nt', reason='POSIX FIFO test requires mkfifo')
@pytest.mark.parametrize('boundary', ['owner', 'external', 'transaction', 'resource', 'lock'])
@pytest.mark.parametrize('race', [False, True])
def test_fifo_boundaries_refuse_without_blocking_or_losing_bytes(tmp_path, boundary, race):
    import stat
    project = tmp_path
    target = target_at(project)
    env = child_env(tmp_path)
    selection = ['--agent', 'codex', '--scope', 'project', '--project', str(project)]
    if boundary == 'transaction':
        target, archive, _, env = interrupted_registration(tmp_path, 'after')
        unsupported = archive / 'transaction.json'
        action = ['recover-registration', *selection, '--transaction', archive.name.removeprefix('archive-')]
        category = 'recovery required'
    elif boundary in ('owner', 'external'):
        adapter.register(target)
        record = adapter.owned_manifest(target)
        unsupported = (target / adapter.OWNER if boundary == 'owner' else
                       adapter.metadata_root(target) / (record['receipt_id'] + '.json'))
        action = ['inspect', *selection]
        category = 'conflict'
    elif boundary == 'resource':
        package = tmp_path / 'fake-package'
        for name, data in adapter._package_bytes().items():
            path = package / 'skill' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        unsupported = package / 'skill' / 'SKILL.md'
        action = ['install', *selection]
        category = 'conflict'
    else:
        target.parent.mkdir(parents=True)
        unsupported = target.parent / '.vybe-check-install.lock'
        unsupported.write_bytes(b'Original regular lock sentinel')
        action = ['install', *selection]
        category = 'conflict'
    original = unsupported.read_bytes()
    saved = tmp_path / 'preserved-original'
    if not race:
        adapter.rename_absent(unsupported, saved)
        os.mkfifo(unsupported)
    # No writer is opened: a blocking read or write open must time out on R2.
    before = preserved_snapshot(tmp_path)
    script = '''
import builtins, io, os, sys
from pathlib import Path
from vybe_check import install
from vybe_check.cli import main
path, saved, race, package = sys.argv[1:5]
if package:
    install.files = lambda name: Path(package)
if race == 'True':
    real_os_open, real_builtin_open, real_io_open = os.open, builtins.open, io.open
    changed = False
    def swap(filename):
        global changed
        if not changed and isinstance(filename, (str, bytes, os.PathLike)) and Path(filename) == Path(path):
            install.rename_absent(Path(path), Path(saved))
            os.mkfifo(path)
            changed = True
    def racing_os_open(filename, flags, *args, **kwargs):
        swap(filename)
        return real_os_open(filename, flags, *args, **kwargs)
    def racing_builtin_open(filename, *args, **kwargs):
        # Old portalocker uses builtin open directly; a validated opener is
        # interrupted later at os.open, after its own regular-file precheck.
        if 'opener' not in kwargs:
            swap(filename)
        return real_builtin_open(filename, *args, **kwargs)
    def racing_io_open(filename, *args, **kwargs):
        # Old Path resource read uses io.open; new native reads use os.open.
        swap(filename)
        return real_io_open(filename, *args, **kwargs)
    os.open, builtins.open, io.open = racing_os_open, racing_builtin_open, racing_io_open
raise SystemExit(main(sys.argv[5:]))
'''
    command = [sys.executable, '-B', '-c', script, str(unsupported), str(saved), str(race),
               str(package) if boundary == 'resource' else '', '--root', str(tmp_path / 'state'), *action]
    bounded_refusal(command, env, tmp_path, category)
    assert saved.read_bytes() == original
    assert stat.S_ISFIFO(unsupported.lstat().st_mode)
    after = preserved_snapshot(tmp_path)
    if boundary != 'resource':
        if race:
            expected = dict(before)
            relative = unsupported.relative_to(tmp_path).as_posix()
            expected['preserved-original'] = expected.pop(relative)
            expected[relative] = after[relative]
            assert after == expected
        else:
            assert after == before
    else:
        # A resource failure retains its own staging/receipt area; it publishes
        # no discoverable target and keeps every fixture entry and original.
        for name, value in before.items():
            if name == unsupported.relative_to(tmp_path).as_posix() and race:
                assert after['preserved-original'] == value
            else:
                assert after[name] == value
    if boundary in ('lock', 'resource', 'transaction'):
        assert not target.exists()


def test_regular_boundary_control_reads_complete_bytes_and_preserves_lock(tmp_path):
    data = tmp_path / 'regular.json'
    data.write_bytes(b'{"note":"Regular sentinel"}')
    assert adapter._read(data) == b'{"note":"Regular sentinel"}'
    target = target_at(tmp_path)
    target.parent.mkdir(parents=True)
    lock = target.parent / '.vybe-check-install.lock'
    lock.write_bytes(b'Normal lock sentinel')
    with adapter._lock(target):
        assert lock.read_bytes() == b'Normal lock sentinel'
    assert lock.read_bytes() == b'Normal lock sentinel'
    assert adapter.register(target)['status'] == 'installed'
    assert adapter.inspect(target)['status'] == 'owned'


def test_normal_registration_lock_contention_keeps_five_second_timeout(tmp_path):
    import portalocker
    import time
    target = target_at(tmp_path)
    target.parent.mkdir(parents=True)
    env = child_env(tmp_path)
    with portalocker.Lock(str(target.parent / '.vybe-check-install.lock'), timeout=1):
        started = time.monotonic()
        result = cli(tmp_path, env, 'install', '--agent', 'codex', '--scope', 'project', '--project', str(tmp_path))
        elapsed = time.monotonic() - started
    assert result.returncode == 2
    assert 'busy' in result.stderr and 'Traceback' not in result.stderr
    assert 4.5 <= elapsed < 8
    assert not target.exists()
    print(json.dumps({'evidence': 'Normal lock contention retains timeout', 'seconds': elapsed, 'exit': result.returncode}))


TRANSACTION_DAMAGE = ['incomplete', 'missing-target', 'missing-receipt', 'missing-identity',
                      'extra', 'target-type', 'relative-target', 'outside-target',
                      'identity-type', 'identity-length', 'identity-bool', 'identity-negative', 'identity-wrong',
                      'receipt-type', 'receipt-schema', 'trusted-receipt', 'malformed', 'list']


def replace_preserving(path, saved, content):
    adapter.rename_absent(path, saved)
    path.write_bytes(content)


def assert_archive_barrier(tmp_path, target, archive, env):
    before = preserved_snapshot(tmp_path)
    selection = ['--agent', 'codex', '--scope', 'project', '--project', str(tmp_path)]
    for arguments in [('install', *selection), ('inspect', *selection),
                      ('unregister', *selection), ('recover-registration', *selection, '--transaction', archive.name.removeprefix('archive-'))]:
        result = cli(tmp_path, env, *arguments)
        assert result.returncode == 2, result.stdout + result.stderr
        assert 'conflict' in result.stderr.lower() and 'Traceback' not in result.stderr
        assert result.stdout == ''
        assert preserved_snapshot(tmp_path) == before
        assert not target.exists()
    print(json.dumps({'evidence': 'Malformed archive refused across all lifecycle commands',
                      'root': str(tmp_path), 'archive': str(archive), 'target_absent': True}))


@pytest.mark.parametrize('damage', TRANSACTION_DAMAGE)
def test_transaction_barrier_refuses_invalid_records_before_target_filter(tmp_path, damage):
    target, archive, _, env = interrupted_registration(tmp_path, 'after')
    path = archive / 'transaction.json'
    value = json.loads(path.read_text())
    if damage == 'incomplete':
        value = {}
    elif damage.startswith('missing-'):
        value.pop(damage.removeprefix('missing-'))
    elif damage == 'extra':
        value['extra'] = 'Unsupported'
    elif damage == 'target-type':
        value['target'] = 17
    elif damage == 'relative-target':
        value['target'] = 'relative/skills/vybe-check'
    elif damage == 'outside-target':
        value['target'] = str(tmp_path / 'outside' / 'skills' / 'vybe-check')
    elif damage == 'identity-type':
        value['identity'] = {'device': 1, 'inode': 2}
    elif damage == 'identity-length':
        value['identity'] = [1]
    elif damage == 'identity-bool':
        value['identity'] = [True, False]
    elif damage == 'identity-negative':
        value['identity'] = [-1, -1]
    elif damage == 'identity-wrong':
        value['identity'] = [value['identity'][0], value['identity'][1] + 1]
    elif damage == 'receipt-type':
        value['receipt'] = []
    elif damage == 'receipt-schema':
        value['receipt'] = {}
    elif damage == 'trusted-receipt':
        receipt = adapter.metadata_root(target) / (value['receipt']['receipt_id'] + '.json')
        replace_preserving(receipt, tmp_path / 'saved-trusted.json', b'{}')
    elif damage == 'list':
        value = []
    content = b'{broken' if damage == 'malformed' else json.dumps(value).encode()
    replace_preserving(path, tmp_path / 'saved-transaction.json', content)
    assert not (archive / 'resolved.json').exists()
    assert_archive_barrier(tmp_path, target, archive, env)
    assert not (archive / 'resolved.json').exists()


@pytest.mark.parametrize('damage', ['incomplete', 'status-type', 'status-unknown', 'extra', 'malformed', 'list'])
def test_resolution_barrier_refuses_invalid_completion_records(tmp_path, damage):
    target = target_at(tmp_path)
    adapter.register(target)
    result = adapter.detach(target)
    archive = Path(result['archive']).parent
    path = archive / 'resolved.json'
    value = {'status': 'detached'}
    if damage == 'incomplete':
        value = {}
    elif damage == 'status-type':
        value['status'] = ['detached']
    elif damage == 'status-unknown':
        value['status'] = 'installed'
    elif damage == 'extra':
        value['extra'] = 'Unsupported'
    elif damage == 'list':
        value = []
    content = b'{broken' if damage == 'malformed' else json.dumps(value).encode()
    replace_preserving(path, tmp_path / 'saved-resolution.json', content)
    env = child_env(tmp_path)
    assert_archive_barrier(tmp_path, target, archive, env)
    assert path.read_bytes() == content


@pytest.mark.parametrize('status', ['detached', 'restored', 'recovered'])
def test_valid_archive_resolution_controls_allow_ordinary_setup(tmp_path, monkeypatch, status):
    target = target_at(tmp_path)
    if status == 'recovered':
        target, archive, _, env = interrupted_registration(tmp_path, 'after')
        assert adapter.recover_registration(target, archive)['status'] == 'recovered'
    else:
        adapter.register(target)
        env = child_env(tmp_path)
        if status == 'detached':
            archive = Path(adapter.detach(target)['archive']).parent
        else:
            real_move = adapter.rename_absent
            def collide(source, destination):
                if Path(source) == target:
                    Path(destination).mkdir()
                    (Path(destination) / 'sentinel').write_bytes(b'Preserved collision')
                real_move(source, destination)
            with monkeypatch.context() as patch:
                patch.setattr(adapter, 'rename_absent', collide)
                with pytest.raises(ValueError, match='conflict'):
                    adapter.detach(target)
            archive = next(adapter.metadata_root(target).glob('archive-*'))
    assert json.loads((archive / 'resolved.json').read_text()) == {'status': status}
    before = preserved_snapshot(archive)
    expected = 'installed' if status == 'detached' else 'unchanged'
    result = cli(tmp_path, env, 'install', '--agent', 'codex', '--scope', 'project', '--project', str(tmp_path))
    assert result.returncode == 0 and json.loads(result.stdout)['status'] == expected
    assert adapter.inspect(target)['status'] == 'owned'
    assert preserved_snapshot(archive) == before


def test_valid_other_target_transaction_is_validated_before_filtering(tmp_path):
    target, archive, _, _ = interrupted_registration(tmp_path, 'after')
    other = target.parent / 'other-registration'
    # Both generic API targets share the same metadata area. A valid interrupted
    # record stays pending for its own target and never gets silently resolved.
    before = preserved_snapshot(archive)
    assert adapter.register(other)['status'] == 'installed'
    assert adapter.inspect(other)['status'] == 'owned'
    with pytest.raises(ValueError, match='recovery required'):
        adapter.register(target)
    assert preserved_snapshot(archive) == before
    assert not (archive / 'resolved.json').exists()


@pytest.fixture(autouse=True)
def lifecycle_isolation(tmp_path, monkeypatch):
    """Assert source origins and isolate all environment roots before mutation."""
    import importlib.util
    origin = Path(adapter.__file__).resolve().parent
    for module in ('vybe_check', 'vybe_check.workshop', 'vybe_check.cli', 'vybe_check.config'):
        assert Path(importlib.util.find_spec(module).origin).resolve().is_relative_to(origin)
    for name in ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'XDG_DATA_HOME', 'VYBE_CHECK_ROOT', 'TMPDIR'):
        value = tmp_path / ('isolated-' + name.lower())
        value.mkdir()
        assert value.is_relative_to(tmp_path)
        monkeypatch.setenv(name, str(value))
    monkeypatch.setenv('PYTHONPATH', str(origin.parent))
    monkeypatch.setenv('PYTHONDONTWRITEBYTECODE', '1')


def complete_state(tmp_path):
    from vybe_check.workshop import SessionStore
    root = tmp_path / 'state'
    store = SessionStore(root)
    session = store.create('Invented ceramic scene')
    def apply(action, payload):
        nonlocal session
        session = store.apply(session['id'], session['revision'], action, payload)
    apply('direct_image', {'brief': {'outcome':'Ceramic scene', 'subject_action':'Turn bowl',
           'visual_priority':'Rim', 'frame':'Close', 'light':'Soft'}, 'prompt':'Blue ceramic rim',
           'settings':{'seed':123}})
    apply('add_image_version', {'prompt':'Red ceramic rim', 'settings':{'seed':456}})
    apply('draft_edit', {'text':'Amber rim alternative'})
    media = root / 'media'
    media.mkdir()
    source = media / 'source.png'
    source.write_bytes(b'Invented supplied fixture')
    apply('register_reference', {'path':str(source), 'label':'Ceramic fixture', 'role':'Colour'})
    for version in (1, 2):
        study = media / ('study-' + str(version) + '.png')
        study.write_bytes(b'Synthetic study ' + bytes([version]))
        apply('record_preview', {'path':str(study), 'prompt_version':version,
              'model':'Synthetic fixture', 'workflow':'Transport only',
              'source_reference_ids':[session['references'][0]['id']]})
    return store, session


def state_digest(root):
    import hashlib
    return {name: (kind, hashlib.sha256(data).hexdigest() if kind == 'file' else data)
            for name, (kind,data) in preserved_snapshot(root).items()
            if not name.startswith('backups') and not name.startswith('.write.lock')
            and not name.startswith('.registry.lock')}


def test_task10_backup_identity_and_interruption_preserve_complete_state(tmp_path, monkeypatch):
    from vybe_check import lifecycle
    store, session = complete_state(tmp_path)
    before = state_digest(store.root)
    prompts = [image['prompt'] for image in session['image_versions']]
    first = lifecycle.backup_state(store.root)
    assert first['status'] == 'backed_up'
    backup = Path(first['backup'])
    manifest = json.loads((backup / 'manifest.json').read_text())
    assert manifest['schema_version'] == 1 and manifest['complete'] is True
    assert set(manifest['files']) == {'sessions/' + session['id'] + '.json', 'registry/' + session['id'] + '.json'}
    for name, record in manifest['files'].items():
        import hashlib
        raw = (backup/name).read_bytes()
        assert raw == (store.root/name).read_bytes()
        assert record == {'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    assert state_digest(store.root) == before
    result = lifecycle.migrate_state(store.root)
    assert result['status'] == 'unchanged' and result['schema_version'] == 1
    assert result['backup'] != first['backup']
    def interrupted(snapshot):
        assert Path(snapshot['backup']).is_dir()
        raise KeyboardInterrupt
    monkeypatch.setattr(lifecycle, '_identity_publication', interrupted)
    with pytest.raises(KeyboardInterrupt):
        lifecycle.migrate_state(store.root)
    assert state_digest(store.root) == before
    assert [image['prompt'] for image in store.read(session['id'])['image_versions']] == prompts
    assert len(list((store.root/'backups').glob('before-update-*'))) == 3
    if os.name != 'nt':
        import stat
        assert stat.S_IMODE(backup.stat().st_mode) == 0o700
        for p in backup.rglob('*'):
            assert stat.S_IMODE(p.stat().st_mode) == (0o700 if p.is_dir() else 0o600)


@pytest.mark.parametrize('damage', ['unknown-root','unknown-session','unknown-registry','malformed','incomplete-session',
    'missing-registry','orphan-registry','wrong-id','schema','duplicate-json','extra-session-field',
    'invalid-version','invalid-draft','dangling-media','media-changed','media-link','hardlink','symlink','directory','fifo','unreadable'])
def test_task10_backup_refuses_without_silently_omitting_state(tmp_path, monkeypatch, damage):
    from vybe_check import lifecycle
    store, session = complete_state(tmp_path)
    path = store.root / 'sessions' / (session['id'] + '.json')
    if damage == 'unknown-root': (store.root/'keys.json').write_text('{"secret":"Fake sentinel"}')
    elif damage == 'unknown-session': (path.parent/'note.txt').write_text('Unknown sentinel')
    elif damage == 'unknown-registry': (store.root/'registry'/'foreign').mkdir()
    elif damage == 'malformed': path.write_text('{broken')
    elif damage == 'duplicate-json': path.write_text('{"schema_version":1,"schema_version":2}')
    elif damage == 'missing-registry': adapter.rename_absent(store.root/'registry'/path.name, tmp_path/'saved-registry')
    elif damage == 'orphan-registry': (store.root/'registry'/('a'*32+'.json')).write_text('{"nonce":"x","media":{}}')
    elif damage in ('symlink','hardlink','directory','fifo'):
        saved=tmp_path/'saved-state'; adapter.rename_absent(path,saved)
        if damage == 'symlink': path.symlink_to(saved)
        elif damage == 'hardlink': os.link(saved,path)
        elif damage == 'directory': path.mkdir()
        elif hasattr(os,'mkfifo'): os.mkfifo(path)
        else: pytest.skip('FIFO requires POSIX')
    elif damage == 'media-changed': (store.root/'media'/'source.png').write_bytes(b'Changed')
    elif damage == 'media-link': (store.root/'media'/'foreign.png').symlink_to(store.root/'media'/'source.png')
    elif damage == 'unreadable':
        real_read=lifecycle._read_regular
        def deny(candidate,limit):
            if Path(candidate)==path: raise PermissionError('Synthetic unreadable fixture')
            return real_read(candidate,limit)
        monkeypatch.setattr(lifecycle,'_read_regular',deny)
    else:
        value=json.loads(path.read_text())
        if damage == 'incomplete-session': value.pop('drafts')
        elif damage == 'wrong-id': value['id']='a'*32
        elif damage == 'schema': value['schema_version']=2
        elif damage == 'extra-session-field': value['credential']='Fake sentinel'
        elif damage == 'invalid-version': value['image_versions'][0]['version']=17
        elif damage == 'invalid-draft': value['drafts'][0].pop('base_version')
        elif damage == 'dangling-media': value['references'][0]['id']='a'*32
        path.write_text(json.dumps(value))
    before=preserved_snapshot(tmp_path)
    with pytest.raises(ValueError,match='State backup unavailable'):
        lifecycle.backup_state(store.root)
    assert preserved_snapshot(tmp_path)==before
    assert not (store.root/'backups').exists()


def old_registration(tmp_path, monkeypatch):
    target=target_at(tmp_path)
    old={'SKILL.md':b'# Old invented skill\n','references/runtime.md':b'Old invented runtime\n'}
    with monkeypatch.context() as patch:
        patch.setattr(adapter,'__version__','0.0.1')
        patch.setattr(adapter,'_package_bytes',lambda:dict(old))
        adapter.register(target)
    unrelated=target.parent/'unrelated'/'SKILL.md'
    unrelated.parent.mkdir(); unrelated.write_bytes(b'Unrelated sentinel')
    modified=target.parent/'modified'/'SKILL.md'
    modified.parent.mkdir(); modified.write_bytes(b'Modified sentinel')
    return target


def test_task10_successful_update_preserves_old_version_receipt_and_state(tmp_path, monkeypatch):
    store, session=complete_state(tmp_path)
    before=state_digest(store.root)
    target=old_registration(tmp_path,monkeypatch)
    old=tree(target); old_receipt=adapter.owned_manifest(target)
    sentinel={p.name:tree(p) for p in target.parent.iterdir() if p.is_dir() and p!=target}
    result=adapter.update_registration(target)
    archive=Path(result['archive'])
    assert result['status']=='updated' and result['prior_preserved']
    assert result['transaction_id']==archive.name.removeprefix('archive-')
    assert tree(archive/'registration')==old
    assert adapter.owned_manifest(archive/'registration',adapter.metadata_root(target))==old_receipt
    assert adapter.owned_manifest(target)['version']==adapter.__version__
    assert adapter.inspect(target)['status']=='owned'
    assert state_digest(store.root)==before
    assert {p.name:tree(p) for p in target.parent.iterdir() if p.is_dir() and p!=target}==sentinel
    # Unregister also leaves the complete creative state and media intact.
    current=tree(target)
    assert tree(Path(adapter.detach(target)['archive']))==current
    assert state_digest(store.root)==before
    assert len(store.read(session['id'])['previews'])==2


@pytest.mark.parametrize('phase',['stage','archive','publish','postverify','race-target','race-archive','race-old-edit','race-new-edit'])
def test_task10_update_failure_retains_owned_generations_and_requires_recovery(tmp_path,monkeypatch,phase):
    store,_=complete_state(tmp_path); before=state_digest(store.root)
    target=old_registration(tmp_path,monkeypatch); old=tree(target)
    real_move=adapter.rename_absent; real_owned=adapter.owned_manifest
    def move(source,destination):
        source,destination=Path(source),Path(destination)
        if source==target:
            if phase=='archive': raise OSError('Injected archive failure')
            if phase=='race-archive':
                destination.mkdir(); (destination/'sentinel').write_bytes(b'Archive conflict sentinel')
            if phase=='race-old-edit': (target/'SKILL.md').write_bytes(old['SKILL.md']+b'Concurrent edit')
        if source.name.startswith('stage-') and destination==target:
            if phase=='publish': raise OSError('Injected publish failure')
            if phase=='race-target':
                target.mkdir(); (target/'sentinel').write_bytes(b'Target conflict sentinel')
        real_move(source,destination)
        if source.name.startswith('stage-') and destination==target and phase=='race-new-edit':
            (target/'SKILL.md').write_bytes(b'Concurrent new generation edit')
    def owned(candidate,metadata=None):
        if phase=='postverify' and Path(candidate)==target and (target/adapter.OWNER).exists():
            record=json.loads((target/adapter.OWNER).read_text())
            if record['version']==adapter.__version__: raise ValueError('Injected postverify failure')
        return real_owned(candidate,metadata)
    if phase=='stage':
        monkeypatch.setattr(adapter,'_package_bytes',lambda:(_ for _ in ()).throw(ValueError('Injected stage failure')))
    monkeypatch.setattr(adapter,'rename_absent',move); monkeypatch.setattr(adapter,'owned_manifest',owned)
    with pytest.raises(ValueError,match='recovery required'):
        adapter.update_registration(target)
    assert state_digest(store.root)==before
    archives=list(adapter.metadata_root(target).glob('archive-*'))
    if phase=='stage':
        assert tree(target)==old and not archives
    elif phase in ('archive','race-archive'):
        assert tree(target)==old
    else:
        archive=archives[0]
        preserved=archive/'registration'
        expected=dict(old)
        if phase=='race-old-edit': expected['SKILL.md']+=b'Concurrent edit'
        assert tree(preserved)==expected
        assert not (archive/'resolved.json').exists()
        if phase in ('publish','race-target'):
            stages=list(adapter.metadata_root(target).glob('stage-*'))
            assert len(stages)==1 and real_owned(stages[0],adapter.metadata_root(target))
        if phase=='race-target': assert tree(target)=={'sentinel':b'Target conflict sentinel'}
        with pytest.raises(ValueError,match='recovery required'): adapter.inspect(target)
    print(json.dumps({'failure_phase':phase,'state_digest':before,'archives':[str(p) for p in archives]}))


@pytest.mark.parametrize('phase',['before-archive','after-archive','after-publish'])
def test_task10_real_child_update_interruption_and_id_recovery(tmp_path,monkeypatch,phase):
    store,session=complete_state(tmp_path); before=state_digest(store.root)
    target=old_registration(tmp_path,monkeypatch); old=tree(target)
    env=child_env(tmp_path)
    script='''
import os,sys
from pathlib import Path
from vybe_check import install
from vybe_check.cli import main
origin=Path(install.__file__).resolve().parents[1]
assert str(origin)==os.environ['PYTHONPATH']
for name in ('HOME','USERPROFILE','LOCALAPPDATA','XDG_DATA_HOME','VYBE_CHECK_ROOT','TMPDIR'):
    assert Path(os.environ[name]).is_relative_to(Path(sys.argv[3]))
target=Path(sys.argv[1]); phase=sys.argv[2]; real=install.rename_absent
def move(source,destination):
    source,destination=Path(source),Path(destination)
    if source==target and phase=='before-archive': os._exit(23)
    real(source,destination)
    if source==target and phase=='after-archive': os._exit(23)
    if source.name.startswith('stage-') and destination==target and phase=='after-publish': os._exit(23)
install.rename_absent=move
install.update_registration(target)
'''
    command=[sys.executable,'-B','-c',script,str(target),phase,str(tmp_path)]
    child=subprocess.Popen(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    initial=child.poll(); stdout,stderr=child.communicate(timeout=10)
    assert child.returncode==23,stderr
    archive=next(adapter.metadata_root(target).glob('archive-*'))
    preserved=target if phase=='before-archive' else archive/'registration'
    assert tree(preserved)==old and state_digest(store.root)==before
    with pytest.raises(ValueError,match='recovery required'): adapter.inspect(target)
    selection=['--agent','codex','--scope','project','--project',str(tmp_path)]
    result=cli(tmp_path,env,'recover-registration',*selection,'--transaction',archive.name.removeprefix('archive-'))
    if phase=='after-publish':
        assert result.returncode==2 and 'recovery required' in result.stderr
        assert tree(archive/'registration')==old and target.exists()
    else:
        assert result.returncode==0,result.stderr
        assert tree(target)==old
        assert adapter.owned_manifest(target)['version']=='0.0.1'
    assert state_digest(store.root)==before
    assert [x['prompt'] for x in store.read(session['id'])['image_versions']]==['Blue ceramic rim','Red ceramic rim']
    print(json.dumps({'args':command,'cwd':os.getcwd(),'env':env,'pid':child.pid,'initial_poll':initial,
                      'communicate_returncode':child.returncode,'final_poll':child.poll(),'stdout':stdout,'stderr':stderr,
                      'recovery_exit':result.returncode,'phase':phase,'state_digest':before}))


@pytest.mark.parametrize('identifier',['../archive-'+'a'*32,'/tmp/arbitrary','archive-'+'a'*32,'a'*31,'g'*32])
def test_task10_cli_recovery_requires_derived_id(tmp_path,identifier):
    env=child_env(tmp_path)
    before=preserved_snapshot(tmp_path)
    result=cli(tmp_path,env,'recover-registration','--agent','codex','--scope','project',
               '--project',str(tmp_path),'--transaction',identifier)
    assert result.returncode==2 and 'Traceback' not in result.stderr
    assert preserved_snapshot(tmp_path)==before


def test_task10_source_cli_documented_backup_and_reopen(tmp_path):
    store,session=complete_state(tmp_path); before=state_digest(store.root)
    env=child_env(tmp_path)
    # Wheel installation and real board stop/start are Task 12 evidence.
    result=cli(tmp_path,env,'backup')
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['status']=='backed_up'
    assert cli(tmp_path,env,'show',session['id']).returncode==0
    assert state_digest(store.root)==before
    assert cli(tmp_path,env,'unregister','--recover','/tmp/arbitrary','--agent','codex','--scope','project','--project',str(tmp_path)).returncode==2


@pytest.mark.parametrize('fault',['copy','manifest','input-race','output-unknown'])
def test_task10_incomplete_backup_retained_without_success_manifest(tmp_path,monkeypatch,fault):
    from vybe_check import lifecycle
    store,session=complete_state(tmp_path); before=state_digest(store.root)
    real_write=lifecycle._write_exclusive
    writes=0
    def write(path,data):
        nonlocal writes
        writes+=1
        if fault=='copy' and writes==2: raise OSError('Injected copy interruption')
        if fault=='manifest' and Path(path).name=='manifest.json': raise OSError('Injected manifest interruption')
        real_write(path,data)
        if writes==1 and fault=='input-race':
            (store.root/'sessions'/(session['id']+'.json')).write_bytes(b'{"changed":"Retained concurrent edit"}')
        if writes==1 and fault=='output-unknown':
            folder=Path(path).parent.parent if Path(path).parent.name in ('sessions','registry') else Path(path).parent
            (folder/'unknown.json').write_text('{"unknown":"Retained"}')
    monkeypatch.setattr(lifecycle,'_write_exclusive',write)
    with pytest.raises(ValueError,match='State backup unavailable'): lifecycle.backup_state(store.root)
    backups=list((store.root/'backups').glob('before-update-*'))
    assert len(backups)==1 and not (backups[0]/'manifest.json').exists()
    if fault!='input-race': assert state_digest(store.root)==before
    else:
        assert (store.root/'sessions'/(session['id']+'.json')).read_bytes()==b'{"changed":"Retained concurrent edit"}'
        assert all(state_digest(store.root)[key]==value for key,value in before.items() if not key.startswith('sessions/'))


def test_task10_backup_valid_config_video_advice_and_empty_controls(tmp_path):
    from vybe_check import lifecycle
    from vybe_check.local_preview import CORE_WORKFLOW
    from vybe_check.workshop import SessionStore
    from vybe_check.judge import MODELS
    import copy
    store,session=complete_state(tmp_path)
    config={'base_url':'http://127.0.0.1:8188','workflow':copy.deepcopy(CORE_WORKFLOW),
            'prompt_node':'2','checkpoint':'selected-local-checkpoint.safetensors'}
    raw=(json.dumps(config,indent=2)+'\n').encode()
    (store.root/'comfyui.json').write_bytes(raw)
    session=store.apply(session['id'],session['revision'],'add_video_version',
                        {'mode':'preserve','duration':15,'motion':'Turn bowl','camera':'Fixed'})
    session=store.apply(session['id'],session['revision'],'draft_edit',{'target':'video','text':'Gentle turn'})
    session=store.apply(session['id'],session['revision'],'record_advice',{
        'source_image_version':1,'route':'typesafe','model':MODELS['typesafe'],'payload_sha256':'a'*64,
        'questions':{'pick':{'type':'choice','criteria':{'option_1':'Blue','option_2':'Red'}}},
        'answers':{'pick':{'type':'choice','choice':'option_1','confidence':0.7,'probabilities':{'option_1':0.6,'option_2':0.4}}}})
    before=state_digest(store.root)
    backup=Path(lifecycle.backup_state(store.root)['backup'])
    assert (backup/'comfyui.json').read_bytes()==raw
    assert json.loads((backup/'sessions'/(session['id']+'.json')).read_text())==session
    assert state_digest(store.root)==before
    empty=SessionStore(tmp_path/'empty'); empty_session=empty.create()
    assert lifecycle.backup_state(empty.root)['status']=='backed_up'
    assert empty.read(empty_session['id'])['schema_version']==1


@pytest.mark.parametrize('key',['base_url','workflow','prompt_node','checkpoint','unknown'])
def test_task10_config_validation_refuses_incomplete_or_unknown_config(tmp_path,key):
    from vybe_check import lifecycle
    from vybe_check.local_preview import CORE_WORKFLOW
    import copy
    store,_=complete_state(tmp_path)
    config={'base_url':'http://127.0.0.1:8188','workflow':copy.deepcopy(CORE_WORKFLOW),
            'prompt_node':'2','checkpoint':'selected-local-checkpoint.safetensors'}
    if key=='unknown': config['token']='Invented sentinel'
    else: config.pop(key)
    (store.root/'comfyui.json').write_text(json.dumps(config))
    before=preserved_snapshot(store.root)
    with pytest.raises(ValueError,match='State backup unavailable'): lifecycle.backup_state(store.root)
    assert preserved_snapshot(store.root)==before


@pytest.mark.parametrize('lock_name',['.write.lock','.registry.lock'])
def test_task10_backup_waits_for_same_real_process_state_locks(tmp_path,lock_name):
    import portalocker,time
    from vybe_check import lifecycle
    store,_=complete_state(tmp_path); before=state_digest(store.root); env=child_env(tmp_path)
    ready=tmp_path/'backup-ready'
    script='''
import importlib.util,json,os,sys
from pathlib import Path
for module in ('vybe_check','vybe_check.workshop','vybe_check.lifecycle'):
    assert Path(importlib.util.find_spec(module).origin).is_relative_to(Path(os.environ['PYTHONPATH'])/'vybe_check')
for name in ('HOME','USERPROFILE','LOCALAPPDATA','XDG_DATA_HOME','VYBE_CHECK_ROOT','TMPDIR'):
    assert Path(os.environ[name]).is_relative_to(Path(sys.argv[3]))
from vybe_check.lifecycle import backup_state
Path(sys.argv[2]).write_text('Ready')
print(json.dumps(backup_state(Path(sys.argv[1]))),flush=True)
'''
    args=[sys.executable,'-B','-c',script,str(store.root),str(ready),str(tmp_path)]
    child=None
    try:
        with portalocker.Lock(str(store.root/lock_name),timeout=1):
            child=subprocess.Popen(args,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            initial=child.poll(); deadline=time.monotonic()+5
            while not ready.exists():
                assert child.poll() is None and time.monotonic()<deadline
                time.sleep(0.01)
            time.sleep(0.2); held_poll=child.poll()
            assert held_poll is None and not (store.root/'backups').exists()
        stdout,stderr=child.communicate(timeout=10)
        assert child.returncode==0,stderr
        assert json.loads(stdout)['status']=='backed_up' and state_digest(store.root)==before
        print(json.dumps({'args':args,'env':env,'pid':child.pid,'initial_poll':initial,'held_poll':held_poll,
                          'communicate_returncode':child.returncode,'final_poll':child.poll(),'stdout':stdout,'stderr':stderr}))
    finally:
        if child is not None:
            if child.poll() is None: child.terminate()
            child.communicate(timeout=10)


@pytest.mark.parametrize('agent',['codex','claude'])
@pytest.mark.parametrize('scope',['user','project'])
def test_task10_source_cli_update_selection_preserves_old_state(tmp_path,monkeypatch,agent,scope):
    store,session=complete_state(tmp_path); before=state_digest(store.root); env=child_env(tmp_path)
    base=Path(env['HOME']) if scope=='user' else tmp_path/'project'
    base.mkdir(exist_ok=True)
    target=adapter.registration_target(agent,scope,base if scope=='project' else None,home=base)
    with monkeypatch.context() as patch:
        patch.setattr(adapter,'__version__','0.0.1')
        patch.setattr(adapter,'_package_bytes',lambda:{'SKILL.md':b'Old invented skill','references/runtime.md':b'Old invented runtime'})
        adapter.register(target)
    old=tree(target)
    selection=['--agent',agent,'--scope',scope]+(['--project',str(base)] if scope=='project' else [])
    result=cli(tmp_path,env,'backup'); assert result.returncode==0,result.stderr
    result=cli(tmp_path,env,'update-registration',*selection); assert result.returncode==0,result.stderr
    archive=Path(json.loads(result.stdout)['archive'])
    assert tree(archive/'registration')==old and state_digest(store.root)==before
    assert cli(tmp_path,env,'show',session['id']).returncode==0


@pytest.mark.parametrize('damage',['modified-old','missing-old','unknown-old','forged-owner','bad-resources','hardlinked-old'])
def test_task10_update_validates_all_bytes_before_detachment(tmp_path,monkeypatch,damage):
    target=old_registration(tmp_path,monkeypatch)
    if damage=='modified-old': (target/'SKILL.md').write_bytes(b'Edited old sentinel')
    elif damage=='missing-old': adapter.rename_absent(target/'SKILL.md',tmp_path/'saved-skill')
    elif damage=='unknown-old': (target/'foreign.txt').write_bytes(b'Foreign sentinel')
    elif damage=='forged-owner':
        import hashlib
        (target/'SKILL.md').write_bytes(b'Forged sentinel')
        value=json.loads((target/adapter.OWNER).read_text())
        value['files']['SKILL.md']=hashlib.sha256(b'Forged sentinel').hexdigest()
        (target/adapter.OWNER).write_text(json.dumps(value))
    elif damage=='hardlinked-old': os.link(target/'SKILL.md',tmp_path/'linked-skill')
    else: monkeypatch.setattr(adapter,'_package_bytes',lambda:{'SKILL.md':b'Missing runtime fixture'})
    before=tree(target)
    with pytest.raises(ValueError,match='recovery required'): adapter.update_registration(target)
    assert tree(target)==before and not list(adapter.metadata_root(target).glob('archive-*'))


def test_task10_backup_root_spelling_refuses_link_without_touching_destination(tmp_path,monkeypatch):
    from vybe_check import lifecycle
    store,_=complete_state(tmp_path)
    alias=tmp_path/'alias'; alias.symlink_to(store.root,target_is_directory=True)
    before=preserved_snapshot(store.root)
    for explicit in (alias,None):
        monkeypatch.setenv('VYBE_CHECK_ROOT',str(alias))
        with pytest.raises(ValueError,match='State backup unavailable'): lifecycle.backup_state(explicit)
        assert preserved_snapshot(store.root)==before


# T10-SPEC-R1-01: Persisted settings must be objects, while API shorthand stays valid.
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def persisted_settings_state(tmp_path, monkeypatch):
    package = Path(os.environ['PYTHONPATH'].split(os.pathsep)[0]) / 'vybe_check'
    for module in ('vybe_check', 'vybe_check.workshop', 'vybe_check.lifecycle'):
        assert Path(importlib.util.find_spec(module).origin).resolve().is_relative_to(package)
    assert os.environ['PYTHONDONTWRITEBYTECODE'] == '1'
    for name in ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'XDG_DATA_HOME', 'VYBE_CHECK_ROOT', 'TMPDIR'):
        path = tmp_path / ('settings-isolated-' + name.lower())
        path.mkdir()
        monkeypatch.setenv(name, str(path))
        assert Path(os.environ[name]).is_relative_to(tmp_path)
    from vybe_check.workshop import SessionStore
    store = SessionStore(tmp_path / 'state')
    session = store.create('Invented clay form')
    session = store.apply(session['id'], session['revision'], 'direct_image', {
        'brief': {'outcome':'Clay study', 'subject_action':'Turn form', 'visual_priority':'Rim', 'frame':'Close', 'light':'Soft'},
        'shots':[{'id':'rim', 'title':'Rim', 'prompt':'A blue clay rim', 'settings':{'seed':7}}],
        'settings':{'seed':7}})
    session = store.apply(session['id'], session['revision'], 'add_video_version', {
        'mode':'preserve', 'duration':15, 'motion':'Turn form', 'camera':'Fixed', 'settings':{'seed':7}})
    return store, session


def persisted_settings_record(session, seam):
    if seam == 'image': return session['image_versions'][0]
    if seam == 'shot': return session['image_versions'][0]['shots'][0]
    return session['video_versions'][0]


def settings_tree_bytes(root):
    return {p.relative_to(root).as_posix():('directory',None) if p.is_dir() else ('file',p.read_bytes())
            for p in root.rglob('*')}


@pytest.mark.parametrize('seam',['image','shot','video'])
def test_persisted_settings_null_refuses_before_backup_copy(persisted_settings_state, seam):
    from vybe_check.lifecycle import backup_state
    store,session=persisted_settings_state
    record=persisted_settings_record(session,seam)
    assert record['settings']=={'seed':7}
    record['settings']=None
    state_path=store.root/'sessions'/(session['id']+'.json')
    state_path.write_text(json.dumps(session))
    before=settings_tree_bytes(store.root)
    with pytest.raises(ValueError,match='State backup unavailable'):
        backup_state(store.root)
    assert settings_tree_bytes(store.root)==before
    assert not (store.root/'backups').exists()
    assert json.loads(state_path.read_bytes())==session
    print(json.dumps({'seam':seam,'negative':'refused_null','state_sha256':hashlib.sha256(state_path.read_bytes()).hexdigest(),'source':str(Path(__import__('vybe_check.lifecycle',fromlist=['lifecycle']).__file__))}))


@pytest.mark.parametrize('seam',['image','shot','video'])
@pytest.mark.parametrize('settings',[{}, {'seed':7}])
def test_persisted_settings_objects_remain_byte_identical(persisted_settings_state,seam,settings):
    from vybe_check.lifecycle import backup_state
    store,session=persisted_settings_state
    persisted_settings_record(session,seam)['settings']=settings
    state_path=store.root/'sessions'/(session['id']+'.json')
    state_path.write_text(json.dumps(session))
    raw=state_path.read_bytes()
    result=backup_state(store.root)
    assert result['status']=='backed_up'
    backup=Path(result['backup'])
    copied=backup/'sessions'/state_path.name
    assert state_path.read_bytes()==copied.read_bytes()==raw
    assert persisted_settings_record(json.loads(copied.read_bytes()),seam)['settings']==settings
    manifest=json.loads((backup/'manifest.json').read_bytes())
    assert manifest['complete'] is True
    assert manifest['files']['sessions/'+state_path.name]=={'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    print(json.dumps({'seam':seam,'settings':settings,'positive':'complete_unchanged_backup','state_sha256':hashlib.sha256(raw).hexdigest()}))


def test_persisted_settings_repair_keeps_event_input_null_shorthand():
    from vybe_check.workshop import generation_settings
    assert generation_settings(None)=={}
    assert generation_settings(None,video=True)=={}
