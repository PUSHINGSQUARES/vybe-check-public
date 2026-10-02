"""Explicit complete backups of readable schema-one state.

Backups contain JSON and an inventory only. They retain media references,
never credentials or media copies. Identity migration writes no live state.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from .config import data_root
from .install import no_links, _sync_directory
from .workshop import (ID_PATTERN, MAX_MEDIA_BYTES, MAX_STATE_BYTES, MEDIA_TYPES,
                       _SafeLock, _read_regular, _brief, _ledger, generation_settings)

ERROR = 'State backup unavailable; original state preserved'
SESSION_FIELDS = {'schema_version', 'id', 'revision', 'title', 'brief_status', 'brief',
                  'provenance', 'locks', 'open_choices', 'references', 'image_versions',
                  'video_versions', 'selected_image_version', 'drafts', 'previews',
                  'visual_locks', 'assets'}


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - set(optional):
        raise ValueError(ERROR)


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(ERROR)


def _text(value, *, nonempty=True):
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise ValueError(ERROR)


def _strings(value):
    if not isinstance(value, list):
        raise ValueError(ERROR)
    for item in value:
        _text(item)


def _identifier(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError(ERROR)


def _unique(items):
    if len(items) != len(set(items)):
        raise ValueError(ERROR)


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(ERROR)
            result[key] = value
        return result
    def constant(value):
        raise ValueError(ERROR)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)



def _provenance(value):
    _ledger(value)
    for entry in value:
        _object(entry, {'text', 'kind', 'source'})
        _text(entry['source'])


def _session(value, identifier):
    _object(value, SESSION_FIELDS, {'advice'})
    if type(value['schema_version']) is not int or value['schema_version'] != 1 or value['id'] != identifier:
        raise ValueError(ERROR)
    _identifier(value['id']); _integer(value['revision']); _text(value['title'], nonempty=False)
    if value['brief_status'] not in ('gathering', 'proposed', 'agreed'):
        raise ValueError(ERROR)
    if value['brief_status'] == 'gathering':
        if value['brief'] != {}:
            raise ValueError(ERROR)
    else:
        _brief(value['brief'])
    _provenance(value['provenance'])
    for name in ('locks', 'open_choices', 'visual_locks'):
        _strings(value[name])
    if value['assets'] != []:
        # No schema-one writer produces assets. Refuse unsupported additions.
        raise ValueError(ERROR)
    for name in ('image_versions', 'video_versions', 'drafts', 'references', 'previews'):
        if not isinstance(value[name], list):
            raise ValueError(ERROR)
    versions = set()
    for number, image in enumerate(value['image_versions'], 1):
        _object(image, {'version', 'source_image_version', 'prompt', 'shots', 'settings', 'locks', 'provenance', 'note'})
        if type(image['version']) is not int or image['version'] != number:
            raise ValueError(ERROR)
        source = image['source_image_version']
        if source is not None and (type(source) is not int or source not in versions):
            raise ValueError(ERROR)
        versions.add(number)
        _text(image['prompt']); _text(image['note'], nonempty=False)
        _strings(image['locks']); _provenance(image['provenance'])
        if not isinstance(image['settings'], dict):
            raise ValueError(ERROR)
        generation_settings(image['settings'])
        if not isinstance(image['shots'], list):
            raise ValueError(ERROR)
        ids = []
        for shot in image['shots']:
            _object(shot, {'id', 'title', 'prompt', 'settings'})
            for key in ('id', 'title', 'prompt'): _text(shot[key])
            if not isinstance(shot['settings'], dict):
                raise ValueError(ERROR)
            generation_settings(shot['settings']); ids.append(shot['id'])
        _unique(ids)
    selected = value['selected_image_version']
    if (selected is not None and (type(selected) is not int or selected not in versions)) or (versions and selected is None):
        raise ValueError(ERROR)
    video_versions = set()
    for number, video in enumerate(value['video_versions'], 1):
        _object(video, {'version', 'source_image_version', 'mode', 'duration', 'motion', 'camera',
                        'prompt', 'locks', 'settings', 'provenance'}, {'source_video_version'})
        if (type(video['version']) is not int or video['version'] != number or
                type(video['source_image_version']) is not int or video['source_image_version'] not in versions or
                video['mode'] not in ('preserve', 'evolve', 'multishot')):
            raise ValueError(ERROR)
        _integer(video['duration'], 1)
        if video['duration'] > 60 or (video['mode'] != 'preserve' and video['duration'] < 3):
            raise ValueError(ERROR)
        if 'source_video_version' in video and (type(video['source_video_version']) is not int or video['source_video_version'] not in video_versions):
            raise ValueError(ERROR)
        video_versions.add(number)
        for key in ('motion', 'camera', 'prompt'): _text(video[key])
        _strings(video['locks']); _provenance(video['provenance'])
        if not isinstance(video['settings'], dict):
            raise ValueError(ERROR)
        generation_settings(video['settings'], video=True)
    draft_ids = []
    for draft in value['drafts']:
        _object(draft, {'id', 'target', 'text', 'status', 'base_revision', 'base_version', 'shot_id'})
        _identifier(draft['id']); draft_ids.append(draft['id']); _text(draft['text']); _text(draft['shot_id'], nonempty=False)
        if draft['status'] not in ('pending', 'accepted') or draft['target'] not in ('image', 'video'):
            raise ValueError(ERROR)
        _integer(draft['base_revision'])
        if draft['base_revision'] > value['revision']:
            raise ValueError(ERROR)
        base = draft['base_version']; allowed = versions if draft['target'] == 'image' else video_versions
        if base is None:
            if draft['target'] != 'image' or draft['shot_id']:
                raise ValueError(ERROR)
        elif type(base) is not int or base not in allowed:
            raise ValueError(ERROR)
        if draft['target'] == 'image' and base is not None:
            shots = value['image_versions'][base - 1]['shots']
            if (shots and draft['shot_id'] not in {s['id'] for s in shots}) or (not shots and draft['shot_id']):
                raise ValueError(ERROR)
    _unique(draft_ids)
    references = []
    for ref in value['references']:
        _object(ref, {'id', 'label', 'role', 'source_kind', 'provenance'})
        _identifier(ref['id']); references.append(ref['id']); _text(ref['label']); _text(ref['role'])
        if ref['source_kind'] not in ('supplied_reference', 'supplied_still', 'supplied_video') or ref['provenance'] != 'supplied':
            raise ValueError(ERROR)
    _unique(references)
    previews = []
    for preview in value['previews']:
        _object(preview, {'id', 'status', 'provenance', 'prompt_version', 'shot_id', 'model', 'workflow',
                          'source_reference_ids', 'sha256', 'limitations'})
        _identifier(preview['id']); previews.append(preview['id'])
        if (preview['status'] not in ('exploratory', 'promoted') or preview['provenance'] != 'generated' or
                type(preview['prompt_version']) is not int or preview['prompt_version'] not in versions):
            raise ValueError(ERROR)
        for key in ('model', 'workflow'): _text(preview[key])
        _text(preview['shot_id'], nonempty=False)
        shots = value['image_versions'][preview['prompt_version'] - 1]['shots']
        if (shots and preview['shot_id'] not in {s['id'] for s in shots}) or (not shots and preview['shot_id']):
            raise ValueError(ERROR)
        _strings(preview['source_reference_ids']); _strings(preview['limitations'])
        if set(preview['source_reference_ids']) - set(references):
            raise ValueError(ERROR)
        if not isinstance(preview['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', preview['sha256']):
            raise ValueError(ERROR)
    _unique(references + previews); _unique(value['visual_locks'])
    promoted = {p['id'] for p in value['previews'] if p['status'] == 'promoted'}
    if set(value['visual_locks']) != promoted:
        raise ValueError(ERROR)
    if 'advice' in value:
        if not isinstance(value['advice'], list): raise ValueError(ERROR)
        for advice in value['advice']:
            _object(advice, {'source_image_version', 'route', 'model', 'payload_sha256', 'answers', 'status'})
            if (type(advice['source_image_version']) is not int or advice['source_image_version'] not in versions or
                    advice['route'] not in ('typesafe', 'openrouter') or advice['status'] != 'advisory' or
                    not isinstance(advice['payload_sha256'], str) or not re.fullmatch('[a-f0-9]{64}', advice['payload_sha256'])):
                raise ValueError(ERROR)
            # Validate the persisted form without importing transport or credentials.
            from .judge import MODELS, validate_answers
            if advice['model'] != MODELS[advice['route']] or not isinstance(advice['answers'], dict):
                raise ValueError(ERROR)
            answers = advice['answers']
            if set(answers) == {'pick'}:
                answer = answers['pick']
                _object(answer, {'type', 'choice', 'confidence', 'probabilities'})
                if answer['type'] != 'choice' or not isinstance(answer['probabilities'], dict):
                    raise ValueError(ERROR)
                questions = {'pick': {'type': 'choice', 'criteria': {label:'Stored criterion' for label in answer['probabilities']}}}
            else:
                for answer in answers.values(): _object(answer, {'type', 'noul'})
                questions = {'relevance': {'type':'noul'}, 'contradiction': {'type':'noul'}}
            if validate_answers(answers, questions) != answers:
                raise ValueError(ERROR)
    return set(references + previews)


def _registry(value, session, identifier):
    _object(value, {'nonce', 'media'}); _text(value['nonce'])
    if not isinstance(value['media'], dict) or set(value['media']) != _session(session, identifier):
        raise ValueError(ERROR)
    for identifier, entry in value['media'].items():
        _identifier(identifier); _object(entry, {'path', 'sha256', 'size', 'mime'})
        _text(entry['path']); path = Path(entry['path'])
        if not path.is_absolute() or '..' in path.parts or path.suffix.lower() not in MEDIA_TYPES:
            raise ValueError(ERROR)
        _integer(entry['size'], 1)
        if entry['mime'] != MEDIA_TYPES[path.suffix.lower()] or entry['size'] > MAX_MEDIA_BYTES:
            raise ValueError(ERROR)
        raw = _read_regular(path, MAX_MEDIA_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if entry['size'] != len(raw) or entry['sha256'] != digest:
            raise ValueError(ERROR)
        for preview in session['previews']:
            if preview['id'] == identifier and preview['sha256'] != digest:
                raise ValueError(ERROR)


def _config(value):
    _object(value, {'base_url', 'workflow', 'prompt_node', 'checkpoint'})
    # Validate stored configuration offline. Live capability remains a separate gate.
    from .local_preview import CORE_WORKFLOW, NUMERIC, loopback_origin
    loopback_origin(value['base_url']); _text(value['checkpoint'])
    if (len(value['checkpoint']) > 240 or any(c in value['checkpoint'] for c in '\\/:\x00\r\n') or
            value['checkpoint'] in ('.', '..') or value['prompt_node'] != '2'):
        raise ValueError(ERROR)
    graph = value['workflow']; _object(graph, set(CORE_WORKFLOW))
    for identifier, template in CORE_WORKFLOW.items():
        node = graph[identifier]; _object(node, {'class_type', 'inputs'})
        if node['class_type'] != template['class_type']: raise ValueError(ERROR)
        _object(node['inputs'], set(template['inputs']))
        for key, item in node['inputs'].items():
            if key in NUMERIC:
                kind, low, high = NUMERIC[key]
                if type(item) not in (int, float) or (kind == 'INT' and type(item) is not int) or not low <= item <= high:
                    raise ValueError(ERROR)
            elif key == 'ckpt_name':
                if item != value['checkpoint']: raise ValueError(ERROR)
            elif key == 'text': _text(item, nonempty=False)
            elif key in ('sampler_name', 'scheduler'): _text(item)
            elif item != template['inputs'][key]: raise ValueError(ERROR)


def _tree_types(folder):
    """Inspect allowed nonsnapshot trees without following links or special files."""
    pending = [folder]
    while pending:
        parent = pending.pop(); no_links(parent)
        if not stat.S_ISDIR(parent.lstat().st_mode): raise ValueError(ERROR)
        for child in parent.iterdir():
            no_links(child); info = child.lstat()
            if stat.S_ISDIR(info.st_mode): pending.append(child)
            elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: raise ValueError(ERROR)


def _snapshot(root):
    no_links(root)
    if not root.is_dir(): raise ValueError(ERROR)
    allowed = {'sessions', 'registry', 'comfyui.json', 'media', 'backups', '.write.lock', '.registry.lock'}
    if {p.name for p in root.iterdir()} - allowed: raise ValueError(ERROR)
    raw, decoded = {}, {}
    for child in root.iterdir():
        no_links(child)
        if child.name in ('media', 'backups'):
            _tree_types(child)
        elif child.name in ('.write.lock', '.registry.lock'):
            _read_regular(child, MAX_STATE_BYTES)
    sets = []
    for name in ('sessions', 'registry'):
        folder = no_links(root / name)
        if not folder.is_dir(): raise ValueError(ERROR)
        identifiers = set()
        for path in sorted(folder.iterdir()):
            if not re.fullmatch('[a-f0-9]{32}\\.json', path.name): raise ValueError(ERROR)
            content = _read_regular(path, MAX_STATE_BYTES)
            relative = path.relative_to(root).as_posix()
            raw[relative] = content; decoded[relative] = _json(content)
            identifiers.add(path.stem)
        sets.append(identifiers)
    if sets[0] != sets[1]: raise ValueError(ERROR)
    for identifier in sets[0]:
        _registry(decoded[f'registry/{identifier}.json'], decoded[f'sessions/{identifier}.json'], identifier)
    config = root / 'comfyui.json'
    if config.exists() or config.is_symlink():
        raw['comfyui.json'] = _read_regular(config, MAX_STATE_BYTES)
        _config(_json(raw['comfyui.json']))
    return raw


def _mkdir(path):
    no_links(path).mkdir(mode=0o700, exist_ok=False)
    _sync_directory(path.parent)


def _write_exclusive(path, data):
    """Anchor exclusive output to a no-follow directory descriptor on POSIX."""
    path = no_links(path)
    directory = None
    try:
        if os.name == 'posix':
            directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            for component in path.parts[1:-1]:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory); directory = child
            fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        else:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os,'O_BINARY',0), 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        if _read_regular(path, max(len(data), MAX_STATE_BYTES)) != data: raise ValueError(ERROR)
        _sync_directory(path.parent)
    finally:
        if directory is not None: os.close(directory)


def _backup_locked(root):
    raw = _snapshot(root)
    backups = no_links(root / 'backups')
    if not backups.exists(): _mkdir(backups)
    folder = backups / ('before-update-' + uuid4().hex); _mkdir(folder)
    for name in ('sessions', 'registry'): _mkdir(folder / name)
    inventory = {}
    for name, content in sorted(raw.items()):
        _write_exclusive(folder / name, content)
        inventory[name] = {'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
    if _snapshot(root) != raw: raise ValueError(ERROR)
    # Check the complete output set before marking a backup readable and complete.
    if _snapshot(folder) != raw: raise ValueError(ERROR)
    for name, content in raw.items():
        if _read_regular(folder/name, MAX_STATE_BYTES) != content: raise ValueError(ERROR)
    manifest = {'schema_version':1, 'complete':True, 'files':inventory,
                'directories':['sessions','registry'], 'media':'Referenced unchanged; not copied'}
    _write_exclusive(folder/'manifest.json', (json.dumps(manifest, indent=2, sort_keys=True)+'\n').encode())
    return {'status':'backed_up', 'schema_version':1, 'backup':str(folder)}


def _root(explicit):
    # Check the supplied spelling before data_root resolves it and hides links.
    spelling = explicit if explicit is not None else os.environ.get('VYBE_CHECK_ROOT')
    if spelling: no_links(Path(spelling).expanduser())
    root = no_links(data_root(explicit))
    if not root.is_dir(): raise ValueError(ERROR)
    return root


def backup_state(root=None):
    try:
        root = _root(root)
        with _SafeLock(str(root/'.write.lock'), mode='a', timeout=5):
            with _SafeLock(str(root/'.registry.lock'), mode='a', timeout=5):
                return _backup_locked(root)
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError(ERROR) from None


def _identity_publication(snapshot):
    """Schema one is already readable. No generation or live file changes."""
    return {**snapshot, 'status':'unchanged'}


def migrate_state(root=None):
    """Back up under the write lock, then preserve schema one byte for byte."""
    try:
        root = _root(root)
        with _SafeLock(str(root/'.write.lock'), mode='a', timeout=5):
            with _SafeLock(str(root/'.registry.lock'), mode='a', timeout=5):
                return _identity_publication(_backup_locked(root))
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError(ERROR) from None
