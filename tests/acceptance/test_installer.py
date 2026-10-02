"""Owned registration preservation on isolated local directories."""
import hashlib
import json
import platform
from pathlib import Path

import pytest


def test_registration_idempotency(tmp_path):
    from tools.acceptance_runtime import environment, cli
    from vybe_check.install import registration_target
    env = environment(tmp_path)
    target = registration_target('codex','project',tmp_path)
    first = cli(tmp_path,env,'install','--agent','codex','--scope','project','--project',str(tmp_path))
    assert first.returncode == 0, first.stderr
    before = tree(target)
    second = cli(tmp_path,env,'install','--agent','codex','--scope','project','--project',str(tmp_path))
    assert second.returncode == 0, second.stderr
    assert tree(target) == before and before


def test_registration_conflict(tmp_path):
    from tools.acceptance_runtime import environment, cli
    from vybe_check.install import registration_target
    env = environment(tmp_path)
    target = registration_target('claude','project',tmp_path)
    target.mkdir(parents=True)
    (target/'SKILL.md').write_bytes(b'Invented foreign registration')
    before = tree(target)
    result = cli(tmp_path,env,'install','--agent','claude','--scope','project','--project',str(tmp_path))
    assert result.returncode == 2 and 'conflict' in result.stderr.lower()
    assert tree(target) == before
from vybe_check import install as adapter


def tree(path):
    return {p.relative_to(path).as_posix(): p.read_bytes()
            for p in path.rglob('*') if p.is_file()}


def target_at(tmp_path):
    return tmp_path / '.agents' / 'skills' / 'vybe-check'


def test_repeated_setup_modified_conflict_and_owned_detach(tmp_path):
    target = target_at(tmp_path)
    unrelated = target.parent / 'other-skill' / 'SKILL.md'
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b'Unrelated skill sentinel\x00')
    assert adapter.register(target)['status'] == 'installed'
    before = tree(target)
    assert adapter.register(target)['status'] == 'unchanged'
    assert adapter.register(target)['status'] == 'unchanged'
    assert tree(target) == before
    (target / 'SKILL.md').write_bytes(before['SKILL.md'] + b'\nLocal edit\n')
    modified = tree(target)
    for action in (adapter.register, adapter.detach):
        with pytest.raises(ValueError, match='conflict'):
            action(target)
        assert tree(target) == modified
    assert unrelated.read_bytes() == b'Unrelated skill sentinel\x00'
    control = tmp_path / 'control' / 'skills' / 'vybe-check'
    adapter.register(control)
    original = tree(control)
    result = adapter.detach(control)
    assert result['status'] == 'detached' and result['preserved']
    assert not control.exists()
    assert tree(Path(result['archive'])) == original
    assert adapter.register(control)['status'] == 'installed'


@pytest.mark.parametrize('damage', ['missing', 'recomputed', 'extra', 'directory', 'owner', 'receipt'])
def test_complete_inventory_and_external_receipt_refuse_damage(tmp_path, damage):
    target = target_at(tmp_path)
    adapter.register(target)
    if damage == 'missing':
        adapter.rename_absent(target / 'references' / 'runtime.md', tmp_path / 'saved-runtime.md')
    elif damage == 'recomputed':
        (target / 'SKILL.md').write_bytes(b'User authored content')
        owner = json.loads((target / adapter.OWNER).read_text())
        owner['files']['SKILL.md'] = hashlib.sha256(b'User authored content').hexdigest()
        (target / adapter.OWNER).write_text(json.dumps(owner))
    elif damage == 'extra':
        (target / 'note.txt').write_bytes(b'Keep this note')
    elif damage == 'directory':
        (target / 'unexpected').mkdir()
    elif damage == 'owner':
        (target / adapter.OWNER).write_text('{}')
    else:
        record = json.loads((target / adapter.OWNER).read_text())
        adapter.rename_absent(adapter.metadata_root(target) / (record['receipt_id'] + '.json'), tmp_path / 'saved-receipt.json')
    before = tree(target)
    for action in (adapter.register, adapter.detach):
        with pytest.raises(ValueError, match='conflict'):
            action(target)
        assert tree(target) == before and target.is_dir()


@pytest.mark.parametrize('location', ['target', 'entry', 'parent', 'receipt', 'lock'])
def test_links_refuse_before_reading_or_writing(tmp_path, location):
    target = target_at(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'sentinel').write_bytes(b'Untouched')
    if location == 'parent':
        (tmp_path / '.agents').symlink_to(outside, target_is_directory=True)
    elif location == 'target':
        target.parent.mkdir(parents=True)
        target.symlink_to(outside, target_is_directory=True)
    else:
        adapter.register(target)
        if location == 'entry':
            path = target / 'SKILL.md'
        elif location == 'receipt':
            record = adapter.owned_manifest(target)
            path = adapter.metadata_root(target) / (record['receipt_id'] + '.json')
        else:
            path = target.parent / '.vybe-check-install.lock'
        adapter.rename_absent(path, tmp_path / 'saved-original')
        path.symlink_to(outside / 'sentinel')
    for action in (adapter.register, adapter.detach):
        with pytest.raises(ValueError, match='conflict'):
            action(target)
    assert (outside / 'sentinel').read_bytes() == b'Untouched'


def test_case_variant_target_is_a_conflict(tmp_path):
    target = target_at(tmp_path)
    alternate = target.parent / 'VYBE-CHECK'
    alternate.mkdir(parents=True)
    (alternate / 'SKILL.md').write_bytes(b'Other registration')
    with pytest.raises(ValueError, match='conflict'):
        adapter.register(target)
    assert (alternate / 'SKILL.md').read_bytes() == b'Other registration'


def test_real_host_exclusive_move_positive_and_existing_destination(tmp_path):
    source, destination = tmp_path / 'source', tmp_path / 'destination'
    source.mkdir()
    (source / 'sentinel').write_bytes(b'Source bytes')
    identity = (source.stat().st_dev, source.stat().st_ino)
    adapter.rename_absent(source, destination)
    assert not source.exists()
    assert (destination.stat().st_dev, destination.stat().st_ino) == identity
    assert (destination / 'sentinel').read_bytes() == b'Source bytes'
    source.mkdir()
    (source / 'sentinel').write_bytes(b'New source')
    with pytest.raises(ValueError, match='Exclusive move'):
        adapter.rename_absent(source, destination)
    assert (source / 'sentinel').read_bytes() == b'New source'
    assert (destination / 'sentinel').read_bytes() == b'Source bytes'
    print('Native exclusive directory move verified on ' + platform.system())


def test_destination_race_preserves_stage_and_competing_target(tmp_path, monkeypatch):
    target = target_at(tmp_path)
    real_move = adapter.rename_absent
    stages = []
    def collide(source, destination):
        if Path(destination) == target:
            target.mkdir()
            (target / 'sentinel').write_bytes(b'Concurrent target')
            stages.append(Path(source))
        real_move(source, destination)
    monkeypatch.setattr(adapter, 'rename_absent', collide)
    with pytest.raises(ValueError, match='conflict'):
        adapter.register(target)
    assert (target / 'sentinel').read_bytes() == b'Concurrent target'
    assert adapter.owned_manifest(stages[0], adapter.metadata_root(target))


def test_archive_child_collision_leaves_original_tree(tmp_path, monkeypatch):
    target = target_at(tmp_path)
    adapter.register(target)
    before = tree(target)
    real_move = adapter.rename_absent
    def collide(source, destination):
        if Path(source) == target:
            Path(destination).mkdir()
            (Path(destination) / 'sentinel').write_bytes(b'Archive child')
        real_move(source, destination)
    monkeypatch.setattr(adapter, 'rename_absent', collide)
    with pytest.raises(ValueError, match='conflict'):
        adapter.detach(target)
    assert tree(target) == before
    archives = list(adapter.metadata_root(target).glob('archive-*'))
    assert (archives[0] / 'registration' / 'sentinel').read_bytes() == b'Archive child'


@pytest.mark.parametrize('competing', [False, True])
def test_edit_after_initial_inventory_restores_or_preserves_both(tmp_path, monkeypatch, competing):
    target = target_at(tmp_path)
    adapter.register(target)
    before = tree(target)
    real_move = adapter.rename_absent
    moved = []
    def edit_and_move(source, destination):
        if Path(source) == target:
            (target / 'SKILL.md').write_bytes(before['SKILL.md'] + b'\nConcurrent edit')
            real_move(source, destination)
            moved.append(Path(destination))
            if competing:
                target.mkdir()
                (target / 'sentinel').write_bytes(b'Concurrent registration')
        else:
            real_move(source, destination)
    monkeypatch.setattr(adapter, 'rename_absent', edit_and_move)
    with pytest.raises(ValueError, match='recovery required' if competing else 'conflict'):
        adapter.detach(target)
    preserved = moved[0] if competing else target
    expected = dict(before, **{'SKILL.md': before['SKILL.md'] + b'\nConcurrent edit'})
    assert tree(preserved) == expected
    if competing:
        assert (target / 'sentinel').read_bytes() == b'Concurrent registration'
        with pytest.raises(ValueError, match='recovery required'):
            adapter.recover_registration(target, moved[0].parent)
        assert tree(moved[0]) == expected


def test_receipts_and_transactions_are_private(tmp_path):
    import os
    import stat
    target = target_at(tmp_path)
    adapter.register(target)
    result = adapter.detach(target)
    metadata = adapter.metadata_root(target)
    if os.name != 'nt':
        for path in list(metadata.glob('*.json')) + [Path(result['archive']).parent / 'transaction.json']:
            assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_unavailable_native_primitive_preserves_stage(tmp_path, monkeypatch):
    target = target_at(tmp_path)
    monkeypatch.setattr(adapter.ctypes, 'CDLL', lambda *a, **k: object())
    with pytest.raises(ValueError, match='Exclusive move unavailable'):
        adapter.register(target)
    assert not target.exists()
    stage = next(adapter.metadata_root(target).glob('stage-*'))
    assert adapter.owned_manifest(stage, adapter.metadata_root(target))


def test_reparse_attribute_refuses_before_reading(tmp_path, monkeypatch):
    target = target_at(tmp_path)
    target.parent.mkdir(parents=True)
    target.mkdir()
    real_lstat = Path.lstat
    class Reparse:
        st_mode = 0o40755
        st_file_attributes = 0x400
    def lstat(path, *args, **kwargs):
        return Reparse() if path == target else real_lstat(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', lstat)
    with pytest.raises(ValueError, match='conflict'):
        adapter.register(target)
