"""Preserving, explicitly selected skill registrations.

Receipts and locks establish provenance, not a same-user security boundary.
Archives and interrupted transactions are retained for explicit recovery.
"""
from __future__ import annotations

import ctypes
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import platform
import re
import stat
from uuid import uuid4

import portalocker
from . import __version__

OWNER = '.vybe-check-owner.json'
REQUIRED = {'SKILL.md', 'references/runtime.md'}


def no_links(path):
    path = Path(path).absolute()
    for part in reversed((path, *path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Registration conflict')
        if part.parent.is_dir():
            variants = [p.name for p in part.parent.iterdir()
                        if p.name.casefold() == part.name.casefold()]
            if variants and variants != [part.name]:
                raise ValueError('Registration conflict')
    return path


def rename_absent(source, destination):
    """Native exclusive move only; never replace or copy and delete."""
    source, destination = no_links(source), no_links(destination)
    system = platform.system()
    if system == 'Windows':
        try:
            os.rename(source, destination)
        except OSError:
            raise ValueError('Exclusive move unavailable or conflicting') from None
        return
    libc = ctypes.CDLL(None, use_errno=True)
    old, new = os.fsencode(source), os.fsencode(destination)
    if system == 'Darwin':
        fn = getattr(libc, 'renamex_np', None)
        if fn is None:
            raise ValueError('Exclusive move unavailable')
        fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        fn.restype = ctypes.c_int
        result = fn(old, new, 0x4)
    elif system == 'Linux':
        fn = getattr(libc, 'renameat2', None)
        if fn is None:
            raise ValueError('Exclusive move unavailable')
        fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                       ctypes.c_char_p, ctypes.c_uint]
        fn.restype = ctypes.c_int
        result = fn(-100, old, -100, new, 1)
    else:
        raise ValueError('Exclusive move unavailable')
    if result != 0:
        raise ValueError('Exclusive move unavailable or conflicting')


def _open_regular(path, flags, *, create=False):
    """Refuse special files without blocking, including swaps before open."""
    try:
        path = no_links(path)
        try:
            info = path.lstat()
        except FileNotFoundError:
            if not create:
                raise ValueError('Registration conflict') from None
        else:
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('Registration conflict')
        flags |= getattr(os, 'O_NOFOLLOW', 0)
        if os.name != 'nt':
            flags |= os.O_NONBLOCK
        fd = os.open(path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError('Registration conflict')
        except BaseException:
            os.close(fd)
            raise
        return fd
    except OSError:
        raise ValueError('Registration conflict') from None


def _read(path):
    fd = _open_regular(path, os.O_RDONLY)
    with os.fdopen(fd, 'rb') as stream:
        return stream.read()


def _lock_opener(path, flags):
    # Portalocker retains its ordinary contention timeout after this safe open.
    return _open_regular(path, flags, create=True)


def inventory(folder):
    folder = no_links(folder)
    if not folder.is_dir():
        raise ValueError('Registration conflict')
    result, pending = {}, [folder]
    while pending:
        for child in sorted(pending.pop().iterdir()):
            no_links(child)
            name = child.relative_to(folder).as_posix()
            mode = child.lstat().st_mode
            if stat.S_ISDIR(mode):
                if name != 'references':
                    raise ValueError('Registration conflict')
                pending.append(child)
            elif stat.S_ISREG(mode) and name in REQUIRED:
                result[name] = hashlib.sha256(_read(child)).hexdigest()
            elif not (stat.S_ISREG(mode) and name == OWNER):
                raise ValueError('Registration conflict')
    if set(result) != REQUIRED:
        raise ValueError('Registration conflict')
    return result


def metadata_root(target):
    return no_links(Path(target).parent.parent / '.vybe-check-registrations')


def _record(value):
    if not isinstance(value, dict) or set(value) != {'owner', 'version', 'files', 'receipt_id'}:
        raise ValueError('Registration conflict')
    if (value['owner'] != 'vybe-check' or not isinstance(value['version'], str)
            or not isinstance(value['receipt_id'], str)
            or not re.fullmatch('[a-f0-9]{32}', value['receipt_id'])
            or not isinstance(value['files'], dict) or set(value['files']) != REQUIRED
            or any(not isinstance(d, str) or not re.fullmatch('[a-f0-9]{64}', d)
                   for d in value['files'].values())):
        raise ValueError('Registration conflict')
    return value


def owned_manifest(target, metadata=None):
    target = no_links(target)
    metadata = metadata_root(target) if metadata is None else no_links(metadata)
    try:
        record = _record(json.loads(_read(target / OWNER)))
        trusted = _record(json.loads(_read(metadata / (record['receipt_id'] + '.json'))))
        if record != trusted or record['files'] != inventory(target):
            raise ValueError('Registration conflict')
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError('Registration conflict') from None
    return record


def _write_json(path, value):
    path = no_links(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(path.parent)


def _sync_directory(path):
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _package_bytes():
    resource = files('vybe_check').joinpath('skill')
    result = {}
    for name in sorted(REQUIRED):
        entry = resource.joinpath(name)
        if isinstance(entry, Path):
            result[name] = _read(entry)
        else:
            # Archive-backed package resources have logical regular entries,
            # rather than native device or named-pipe paths.
            if not entry.is_file():
                raise ValueError('Registration conflict')
            result[name] = entry.read_bytes()
    return result


def prepared(target, *, resources=None):
    target = no_links(target)
    metadata = metadata_root(target)
    metadata.mkdir(parents=True, exist_ok=True)
    stage = metadata / ('stage-' + uuid4().hex)
    stage.mkdir(exist_ok=False)
    resources = _package_bytes() if resources is None else resources
    if (not isinstance(resources, dict) or set(resources) != REQUIRED or
            any(not isinstance(data, bytes) or not data for data in resources.values())):
        raise ValueError('Registration conflict')
    for name, data in resources.items():
        destination = stage / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory(destination.parent)
    record = {'owner': 'vybe-check', 'version': __version__,
              'files': inventory(stage), 'receipt_id': uuid4().hex}
    _write_json(stage / OWNER, record)
    _write_json(metadata / (record['receipt_id'] + '.json'), record)
    return stage, metadata, record


def _identity(path):
    info = no_links(path).stat()
    return [info.st_dev, info.st_ino]


def _archive_record(archive, metadata):
    """Validate retained records before filtering or accepting completion."""
    try:
        archive = no_links(archive)
        if (archive.parent != metadata or not archive.is_dir()
                or not re.fullmatch('archive-[a-f0-9]{32}', archive.name)):
            raise ValueError('Registration conflict')
        transaction = json.loads(_read(archive / 'transaction.json'))
        if (not isinstance(transaction, dict)
                or set(transaction) != {'target', 'receipt', 'identity'}
                or not isinstance(transaction['target'], str)
                or not transaction['target']
                or not Path(transaction['target']).is_absolute()
                or '..' in Path(transaction['target']).parts
                or not isinstance(transaction['identity'], list)
                or len(transaction['identity']) != 2
                or any(type(i) is not int or i < 0 for i in transaction['identity'])):
            raise ValueError('Registration conflict')
        recorded_target = no_links(transaction['target'])
        if (str(recorded_target) != transaction['target']
                or metadata_root(recorded_target) != metadata):
            raise ValueError('Registration conflict')
        record = _record(transaction['receipt'])
        trusted = _record(json.loads(_read(metadata / (record['receipt_id'] + '.json'))))
        if record != trusted:
            raise ValueError('Registration conflict')
        resolution = no_links(archive / 'resolved.json')
        status = None
        if resolution.exists():
            value = json.loads(_read(resolution))
            if (not isinstance(value, dict) or set(value) != {'status'}
                    or not isinstance(value['status'], str)
                    or value['status'] not in {'detached', 'restored', 'recovered'}):
                raise ValueError('Registration conflict')
            status = value['status']
        # Unresolved and detached records still identify the original tree.
        # Completed restoration may be followed by another ordinary detach.
        if status is None or status == 'detached':
            preserved = no_links(archive / 'registration')
            candidate = preserved if preserved.exists() else recorded_target
            if status == 'detached' and not preserved.exists():
                raise ValueError('Registration conflict')
            if not candidate.is_dir() or _identity(candidate) != transaction['identity']:
                raise ValueError('Registration conflict')
        return transaction, status
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError('Registration conflict; preserved recovery required') from None


def _pending(target):
    metadata = metadata_root(target)
    if not metadata.exists():
        return []
    result = []
    for archive in metadata.glob('archive-*'):
        transaction, status = _archive_record(archive, metadata)
        if transaction['target'] == str(target) and status is None:
            result.append(archive)
    return result


def _assert_settled(target):
    if _pending(target):
        raise ValueError('Registration conflict; preserved recovery required')


def _lock(target):
    return portalocker.Lock(str(no_links(target.parent / '.vybe-check-install.lock')),
                            timeout=5, opener=_lock_opener)


def register(target):
    target = no_links(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _lock(target):
        _assert_settled(target)
        if target.exists():
            record = owned_manifest(target)
            expected = {name: hashlib.sha256(data).hexdigest()
                        for name, data in _package_bytes().items()}
            if record['version'] != __version__ or record['files'] != expected:
                raise ValueError('Registration conflict: use explicit update')
            return {'status': 'unchanged', 'version': __version__}
        stage, metadata, record = prepared(target)
        rename_absent(stage, target)
        _sync_directory(target.parent)
        _sync_directory(metadata)
        try:
            owned_manifest(target, metadata)
        except (OSError, ValueError):
            raise ValueError('Registration conflict; published tree preserved') from None
        return {'status': 'installed', 'version': record['version']}


def preserve_registration(target, *, resolve=True, restore_on_failure=True):
    """Caller must hold the registration lock, also used by updates."""
    target = no_links(target)
    _assert_settled(target)
    metadata = metadata_root(target)
    before = owned_manifest(target, metadata)
    identity = _identity(target)
    archive = metadata / ('archive-' + uuid4().hex)
    archive.mkdir(exist_ok=False)
    destination = archive / 'registration'
    _write_json(archive / 'transaction.json',
                {'target': str(target), 'receipt': before, 'identity': identity})
    try:
        rename_absent(target, destination)
        _sync_directory(target.parent)
        _sync_directory(archive)
        after = owned_manifest(destination, metadata)
        if after != before or _identity(destination) != identity:
            raise ValueError('Registration changed')
    except (OSError, ValueError):
        if not restore_on_failure:
            raise ValueError('Registration conflict; preserved recovery required') from None
        if destination.exists() and _identity(destination) == identity:
            try:
                rename_absent(destination, target)
                _sync_directory(target.parent)
                _sync_directory(archive)
            except (OSError, ValueError):
                raise ValueError('Registration conflict; preserved recovery required') from None
        if target.exists() and _identity(target) == identity:
            _write_json(archive / 'resolved.json', {'status': 'restored'})
            raise ValueError('Registration conflict') from None
        raise ValueError('Registration conflict; preserved recovery required') from None
    if resolve:
        _write_json(archive / 'resolved.json', {'status': 'detached'})
    return destination


def detach(target):
    target = no_links(target)
    with _lock(target):
        preserved = preserve_registration(target)
        return {'status': 'detached', 'preserved': True, 'archive': str(preserved)}


def recover_registration(target, archive):
    """Restore only a complete owned tree, keeping discrepancies unresolved."""
    try:
        target, archive = no_links(target), no_links(archive)
        metadata = metadata_root(target)
        if archive.parent != metadata or not re.fullmatch('archive-[a-f0-9]{32}', archive.name):
            raise ValueError('Registration conflict')
        with _lock(target):
            # Inspect every retained record with the same barrier used by setup.
            _pending(target)
            transaction, status = _archive_record(archive, metadata)
            if transaction['target'] != str(target) or status is not None:
                raise ValueError('Registration conflict')
            record = transaction['receipt']
            preserved = no_links(archive / 'registration')
            identity = transaction['identity']

            def validate(candidate):
                # Check identity on both sides of the complete ownership inventory.
                if _identity(candidate) != identity:
                    raise ValueError('Registration conflict')
                if owned_manifest(candidate, metadata) != record:
                    raise ValueError('Registration conflict')
                if _identity(candidate) != identity:
                    raise ValueError('Registration conflict')

            if target.exists():
                if preserved.exists():
                    raise ValueError('Registration conflict')
                validate(target)
            elif preserved.exists():
                validate(preserved)
                rename_absent(preserved, target)
                _sync_directory(target.parent)
                _sync_directory(archive)
            else:
                raise ValueError('Registration conflict')
            # A same-user edit after the move must not resolve the transaction.
            validate(target)
            _write_json(archive / 'resolved.json', {'status': 'recovered'})
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError('Registration conflict; preserved recovery required') from None
    return {'status': 'recovered', 'preserved': True}


def registration_target(agent, scope, project=None, *, home=None):
    if agent not in ('codex', 'claude') or scope not in ('user', 'project'):
        raise ValueError('Registration selection required')
    if scope == 'project':
        if project is None:
            raise ValueError('Project scope requires --project')
        base = no_links(project)
        if not base.is_dir():
            raise ValueError('Project directory required')
    else:
        if project is not None:
            raise ValueError('User scope does not accept --project')
        base = no_links(Path.home() if home is None else home)
    return no_links(base / ('.agents' if agent == 'codex' else '.claude') / 'skills' / 'vybe-check')


def inspect(target):
    target = no_links(target)
    _assert_settled(target)
    if not target.exists():
        return {'status': 'absent'}
    record = owned_manifest(target)
    return {'status': 'owned', 'version': record['version']}


def _verified_registration(target, metadata):
    """Validate ownership and identity around a complete unmodified tree read."""
    identity = _identity(target)
    before = owned_manifest(target, metadata)
    for name in (*sorted(REQUIRED), OWNER):
        path = no_links(target / name)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Registration conflict')
    after = owned_manifest(target, metadata)
    if before != after or _identity(target) != identity:
        raise ValueError('Registration conflict')
    return before, identity


def update_registration(target):
    """Explicitly publish a new tree, retaining old bytes and failed stages."""
    try:
        target = no_links(target)
        with _lock(target):
            _assert_settled(target)
            metadata = metadata_root(target)
            old, identity = _verified_registration(target, metadata)
            # Validate packaged bytes and the complete staged tree before detach.
            resources = _package_bytes()
            stage, metadata, new = prepared(target, resources=resources)
            expected = {name: hashlib.sha256(data).hexdigest() for name, data in resources.items()}
            staged, staged_identity = _verified_registration(stage, metadata)
            if staged != new or new['files'] != expected:
                raise ValueError('Registration conflict')
            if _verified_registration(target, metadata) != (old, identity):
                raise ValueError('Registration conflict')
            prior = preserve_registration(target, resolve=False, restore_on_failure=False)
            archive = prior.parent
            if _verified_registration(prior, metadata) != (old, identity):
                raise ValueError('Registration conflict')
            if _verified_registration(stage, metadata) != (new, staged_identity):
                raise ValueError('Registration conflict')
            rename_absent(stage, target)
            _sync_directory(target.parent); _sync_directory(metadata)
            if _verified_registration(target, metadata) != (new, staged_identity):
                raise ValueError('Registration conflict')
            if _verified_registration(prior, metadata) != (old, identity):
                raise ValueError('Registration conflict')
            _write_json(archive / 'resolved.json', {'status': 'detached'})
            return {'status': 'updated', 'version': new['version'], 'prior_preserved': True,
                    'archive': str(archive), 'transaction_id': archive.name.removeprefix('archive-')}
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError('Update conflict; preserved recovery required') from None


def recover_transaction(target, transaction_id):
    """Select a saved interrupted transaction only under derived metadata."""
    if not isinstance(transaction_id, str) or not re.fullmatch('[a-f0-9]{32}', transaction_id):
        raise ValueError('Registration conflict; preserved recovery required')
    target = no_links(target)
    return recover_registration(target, metadata_root(target) / ('archive-' + transaction_id))
