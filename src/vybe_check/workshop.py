"""Local, versioned state for the Vybe-Check creative conversation."""

from __future__ import annotations

import copy
import math
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import stat
from typing import Any
from uuid import uuid4

import portalocker

from .config import data_root
from .privacy import clean as _clean

MEDIA_TYPES = {'.jpeg': 'image/jpeg', '.jpg': 'image/jpeg', '.png': 'image/png',
               '.webp': 'image/webp', '.mp4': 'video/mp4', '.mov': 'video/quicktime'}
MEDIA_SUFFIXES = set(MEDIA_TYPES)
MAX_MEDIA_BYTES = 64 * 1024 * 1024
MAX_STATE_BYTES = 4 * 1024 * 1024


def _regular_stat(value):
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise OSError('Local file unavailable')


def _check_file(path, descriptor):
    opened, current = os.fstat(descriptor), path.lstat()
    _regular_stat(opened)
    _regular_stat(current)
    if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
        raise OSError('Local file unavailable')
    for parent in path.parents:
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise OSError('Local directory unavailable')
    return opened


def _open_regular(path, *, create=False):
    """Open without blocking on a FIFO and validate the actual descriptor.

    POSIX opens each directory through an anchored, no-follow descriptor.
    Other platforms use link checks before and after the descriptor open;
    native filesystem guarantees remain a separate acceptance gate.
    """
    path = Path(path)
    if '..' in path.parts:
        raise OSError('Local file unavailable')
    path = path.absolute()
    for parent in path.parents:
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise OSError('Local directory unavailable')
    try:
        _regular_stat(path.lstat())
    except FileNotFoundError:
        if not create:
            raise
    flags = (os.O_RDWR | os.O_CREAT | os.O_APPEND) if create else os.O_RDONLY
    flags |= getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    descriptor = None
    directory = None
    try:
        if os.name == 'posix':
            directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
            directory = os.open(path.anchor, directory_flags)
            for component in path.parts[1:-1]:
                next_directory = os.open(component, directory_flags, dir_fd=directory)
                os.close(directory)
                directory = next_directory
            descriptor = os.open(path.name, flags, 0o600, dir_fd=directory)
        else:
            descriptor = os.open(path, flags, 0o600)
        _check_file(path, descriptor)
        return descriptor
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        raise
    finally:
        if directory is not None:
            os.close(directory)


def _read_regular(path, limit):
    descriptor = _open_regular(path)
    with os.fdopen(descriptor, 'rb') as stream:
        before = _check_file(Path(path).absolute(), stream.fileno())
        if before.st_size > limit:
            raise ValueError('Local file too large')
        data = stream.read(limit + 1)
        after = _check_file(Path(path).absolute(), stream.fileno())
        if (len(data) > limit or len(data) != before.st_size or
                (before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError('Local file changed')
        return data


def _read_state(path):
    value = json.loads(_read_regular(path, MAX_STATE_BYTES))
    if not isinstance(value, dict):
        raise ValueError('Invalid local state')
    return value


def _state_bytes(value):
    """Validate the complete persisted representation against the reader bound."""
    if not isinstance(value, dict):
        raise ValueError('Invalid local state')
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
    if len(data) > MAX_STATE_BYTES:
        raise ValueError('Local file too large')
    return data


class _SafeLock(portalocker.Lock):
    def _get_fh(self):
        return os.fdopen(_open_regular(Path(self.filename), create=True), 'a', encoding='utf-8')

    def _prepare_fh(self, stream):
        _check_file(Path(self.filename), stream.fileno())
        return stream

ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
class RevisionConflict(ValueError):
    """Raised when a stale browser or agent event would overwrite new state."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    return _clean(value.strip())


def _brief(value: Any, *, direct: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("brief must be an object")
    result = _clean(value)
    for required in ("outcome", "subject_action", "visual_priority"):
        _text(result.get(required), required)
    if direct:
        for required in ("frame", "light"):
            _text(result.get(required), required)
    return result


def _video_prompt(image_prompt: str, mode: str, duration: int, motion: str, camera: str, locks: list[str]) -> str:
    boundary = max(1, duration // 3)
    if mode == "preserve":
        plan = (
            f"Single continuous shot, 0 to {duration}s. Begin from the selected still's composition. "
            f"Subject action: {motion}. Camera: {camera}. Keep motion physically plausible and the scene continuous."
        )
    elif mode == "evolve":
        if duration < 3:
            raise ValueError("evolve mode requires at least 3 seconds")
        plan = (
            f"One continuous scene. 0 to {boundary}s: establish the still and its geography. "
            f"{boundary} to {duration-boundary}s: {motion}. "
            f"{duration-boundary} to {duration}s: settle on the changed expression or position. "
            f"Camera: {camera}. Motivate any light change within the same location."
        )
    elif mode == "multishot":
        if duration < 3:
            raise ValueError("multishot mode requires at least 3 seconds")
        plan = (
            f"Shot 1, 0 to {boundary}s: establish the still's subject and location. "
            f"Cut on subject movement to shot 2, {boundary} to {duration-boundary}s: {motion}. "
            f"Cut on subject movement to shot 3, {duration-boundary} to {duration}s: resolve the action consistently with the supplied camera plan. "
            f"Camera plan: {camera}. Hold screen direction, wardrobe, object placement, and light direction across cuts."
        )
    else:
        raise ValueError("mode must be preserve, evolve, or multishot")
    continuity = "; ".join(locks) if locks else "Preserve the selected still's subject, setting, and visual hierarchy"
    return f"Visual anchor: {image_prompt}\n\nDuration: {duration} seconds. {plan}\n\nContinuity locks: {continuity}."


PAYLOAD_FIELDS = {
    'propose_brief': {'brief', 'provenance', 'locks', 'open_choices', 'title'},
    'resolve_choices': {'resolution', 'locks'},
    'agree_brief': set(),
    'direct_image': {'brief', 'provenance', 'locks', 'title', 'prompt', 'shots', 'settings', 'note'},
    'add_image_version': {'prompt', 'shots', 'shot_id', 'settings', 'provenance', 'note'},
    'add_video_version': {'mode', 'duration', 'motion', 'camera', 'prompt', 'provenance', 'settings'},
    'draft_edit': {'target', 'text', 'shot_id', 'base_version'},
    'accept_draft': {'draft_id'},
    'register_reference': {'path', 'label', 'role', 'source_kind'},
    'record_preview': {'path', 'prompt_version', 'shot_id', 'model', 'workflow', 'source_reference_ids', 'limitations'},
    'promote_preview': {'preview_id'},
    'select_image_version': {'version'},
    'record_advice': {'source_image_version', 'route', 'model', 'payload_sha256', 'questions', 'answers'},
}
AGENT_ACTIONS = tuple(sorted(PAYLOAD_FIELDS))

def validated_payload(action, value):
    if not isinstance(action, str) or action not in PAYLOAD_FIELDS or not isinstance(value, dict) or set(value) - PAYLOAD_FIELDS[action]:
        raise ValueError('Invalid event payload')
    result = copy.deepcopy(value)
    for name in ('locks', 'open_choices', 'source_reference_ids', 'limitations'):
        if name in result and (not isinstance(result[name], list) or any(not isinstance(x, str) for x in result[name])):
            raise ValueError('Invalid event list')
        if name in result:
            result[name] = [_text(x, name) for x in result[name]]
    if 'provenance' in result:
        result['provenance'] = _ledger(result['provenance'])
    if 'settings' in result:
        result['settings'] = generation_settings(result['settings'], video=action == 'add_video_version')
    if 'brief' in result:
        result['brief'] = _brief(result['brief'], direct=action == 'direct_image')
    if 'shots' in result:
        shots = result['shots']
        if not isinstance(shots, list) or not shots:
            raise ValueError('Shots must be a nonempty list')
        seen = set()
        for shot in shots:
            if not isinstance(shot, dict) or set(shot) - {'id', 'title', 'prompt', 'settings'}:
                raise ValueError('Invalid shot')
            identifier = _text(shot.get('id'), 'shot ID')
            if identifier in seen:
                raise ValueError('Duplicate shot ID')
            seen.add(identifier)
            _text(shot.get('title'), 'shot title')
            _text(shot.get('prompt'), 'shot prompt')
            generation_settings(shot.get('settings'))
    for name in ('title', 'prompt', 'note', 'resolution', 'text', 'shot_id', 'draft_id', 'label', 'role', 'model', 'workflow', 'preview_id', 'motion', 'camera'):
        if name in result:
            result[name] = _text(result[name], name)
    if action in {'direct_image', 'add_image_version'} and 'shots' not in result:
        _text(result.get('prompt'), 'prompt')
    required_text = {
        'resolve_choices': ('resolution',), 'draft_edit': ('text',),
        'accept_draft': ('draft_id',), 'promote_preview': ('preview_id',),
        'register_reference': ('label', 'role'),
        'record_preview': ('model', 'workflow'),
        'add_video_version': ('motion', 'camera'),
    }
    for name in required_text.get(action, ()):
        _text(result.get(name), name)
    if action in {'propose_brief', 'direct_image'}:
        _brief(result.get('brief'), direct=action == 'direct_image')
    if action in {'register_reference', 'record_preview'}:
        if not isinstance(result.get('path'), str) or not result['path'].strip():
            raise ValueError('Media path must be nonempty text')
    if action == 'select_image_version' and 'version' not in result:
        raise ValueError('An image version is required')
    if action == 'record_preview' and 'prompt_version' not in result:
        raise ValueError('A preview image version is required')
    # Path-bearing media events are validated separately and never copied to creative state.
    for name in ('version', 'prompt_version', 'source_image_version', 'base_version'):
        if name in result and (isinstance(result[name], bool) or not isinstance(result[name], int) or result[name] < 1):
            raise ValueError('Invalid version')
    if action == 'draft_edit' and ('target' in result and (not isinstance(result['target'], str) or result['target'] not in {'image', 'video'})):
        raise ValueError('Invalid draft target')
    if action == 'register_reference' and ('source_kind' in result and (not isinstance(result['source_kind'], str) or result['source_kind'] not in {'supplied_reference', 'supplied_still', 'supplied_video'})):
        raise ValueError('Invalid source kind')
    if action == 'add_video_version':
        mode, duration = result.get('mode'), result.get('duration', 15)
        if not isinstance(mode, str) or mode not in {'preserve', 'evolve', 'multishot'}:
            raise ValueError('Invalid video mode')
        if isinstance(duration, bool) or not isinstance(duration, int) or not 1 <= duration <= 60:
            raise ValueError('Invalid video duration')
        if mode != 'preserve' and duration < 3:
            raise ValueError('A timed sequence needs at least three seconds')
    return result


def _ledger(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError('Provenance must be a list')
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) - {'text', 'kind', 'source'} or not isinstance(item.get('kind'), str) or item.get('kind') not in {'supplied', 'inferred', 'proposed', 'generated'}:
            raise ValueError('Invalid provenance')
        result.append({'text': _text(item.get('text'), 'provenance text'), 'kind': item['kind'],
                       'source': _text(item.get('source', 'Creative conversation'), 'provenance source')})
    return result

def generation_settings(value, video=False):
    if value is None:
        return {}
    text = {'resolution', 'model', 'style_id'}
    counts = {'seed': (0, 2**64 - 1), 'batch_size': (1, 16)}
    allowed = text | set(counts) | {'aspect_ratio', 'style_strength'}
    if video:
        text |= {'sound'}
        counts['fps'] = (1, 120)
        allowed |= {'sound', 'fps'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError('Invalid generation settings')
    result = {}
    for name, item in value.items():
        if name in text:
            result[name] = _text(item, name)
        elif name == 'aspect_ratio':
            if not isinstance(item, str) or not re.fullmatch('[1-9][0-9]{0,2}:[1-9][0-9]{0,2}', item):
                raise ValueError('Invalid aspect ratio')
            result[name] = item
        elif name in counts:
            low, high = counts[name]
            if isinstance(item, bool) or not isinstance(item, int) or not low <= item <= high:
                raise ValueError('Invalid integer setting')
            result[name] = item
        elif isinstance(item, bool) or not isinstance(item, (int, float)) or not 0 <= item <= 1 or not math.isfinite(item):
            raise ValueError('Invalid style strength')
        else:
            result[name] = float(item)
    return result

def image_by_version(session, version):
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError('Unknown image version')
    image = next((x for x in session['image_versions'] if x['version'] == version), None)
    if image is None:
        raise ValueError('Unknown image version')
    return image

def append_image(session, payload, base_version=None):
    selected = base_version if base_version is not None else session['selected_image_version']
    previous = image_by_version(session, selected) if selected is not None else None
    inherited = previous.get('settings', {}) if previous else {}
    settings = generation_settings({**inherited, **generation_settings(payload.get('settings'))})
    locks = list(previous.get('locks', session['locks']) if base_version is not None and previous else session['locks'])
    def locked(text):
        prompt = _text(text, 'prompt')
        missing = [x for x in locks if x not in prompt]
        return prompt + ('\n\nContinuity locks: ' + '; '.join(missing) + '.' if missing else '')
    shots = []
    if 'shots' in payload:
        if not isinstance(payload['shots'], list) or not payload['shots']:
            raise ValueError('Shots must be a nonempty list')
        seen = set()
        for item in payload['shots']:
            if not isinstance(item, dict) or set(item) - {'id', 'title', 'prompt', 'settings'}:
                raise ValueError('Invalid shot')
            identifier = _text(item.get('id'), 'shot ID')
            if identifier in seen:
                raise ValueError('Duplicate shot ID')
            seen.add(identifier)
            shots.append({'id': identifier, 'title': _text(item.get('title'), 'shot title'),
                          'prompt': locked(item.get('prompt')),
                          'settings': generation_settings({**settings, **generation_settings(item.get('settings'))})})
    elif previous and previous.get('shots'):
        if base_version is None and locks != previous.get('locks', session['locks']):
            raise ValueError('Changed continuity locks require an explicit complete series')
        shots = copy.deepcopy(previous['shots'])
        chosen = next((x for x in shots if x['id'] == payload.get('shot_id')), None)
        if chosen is None:
            raise ValueError('A series edit needs a known shot ID or a complete series')
        chosen['prompt'] = locked(payload.get('prompt'))
        chosen['settings'] = generation_settings({**chosen.get('settings', settings), **generation_settings(payload.get('settings'))})
    elif payload.get('shot_id'):
        raise ValueError('Unknown shot ID')
    prompt = shots[0]['prompt'] if shots else locked(payload.get('prompt'))
    lineage = copy.deepcopy(previous.get('provenance', []) if previous else session['provenance'])
    additions = _ledger(session['provenance']) if base_version is None else []
    for item in additions + _ledger(payload.get('provenance')):
        if item not in lineage:
            lineage.append(item)
    record = {'version': len(session['image_versions']) + 1, 'source_image_version': selected,
              'prompt': prompt, 'shots': shots, 'settings': settings, 'locks': locks,
              'provenance': lineage, 'note': _clean(str(payload.get('note', '')))}
    session['image_versions'].append(record)
    session['selected_image_version'] = record['version']


class SessionStore:
    def __init__(self, root: Path | str | None = None):
        self.root = data_root(root)
        for name in ('sessions', 'registry'):
            folder = self.root / name
            folder.mkdir(parents=True, exist_ok=True)
            if not stat.S_ISDIR(folder.lstat().st_mode):
                raise OSError('Local directory unavailable')

    def _session_path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not ID_PATTERN.fullmatch(session_id):
            raise ValueError("unknown session")
        return self.root / "sessions" / f"{session_id}.json"

    def _registry_path(self, session_id: str) -> Path:
        self._session_path(session_id)
        return self.root / "registry" / f"{session_id}.json"

    def _write(self, path: Path, value: dict) -> None:
        """Replace JSON atomically while the caller holds its portable lock.

        POSIX temporary files stay private. Windows privacy relies on the
        user-owned application-data ACL; an explicit root needs suitable ACLs.
        Unix chmod does not establish a Windows ACL.
        """
        for parent in path.parents:
            if not stat.S_ISDIR(parent.lstat().st_mode):
                raise OSError('Local directory unavailable')
        data = _state_bytes(value)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def create(self, title: str = "Untitled creative session") -> dict:
        session_id = uuid4().hex
        session = {
            "schema_version": 1, "id": session_id, "revision": 0,
            "title": _clean(title), "brief_status": "gathering", "brief": {},
            "provenance": [], "locks": [], "open_choices": [], "references": [],
            "image_versions": [], "video_versions": [], "selected_image_version": None,
            "drafts": [], "previews": [], "visual_locks": [],
            "assets": [],
        }
        registry = {"nonce": secrets.token_urlsafe(32), "media": {}}
        _state_bytes(session)
        _state_bytes(registry)
        with _SafeLock(str(self.root / ".write.lock"), mode="a", timeout=5):
            with _SafeLock(str(self.root / ".registry.lock"), mode="a", timeout=5):
                self._write(self._session_path(session_id), session)
                self._write(self._registry_path(session_id), registry)
        return session

    def read(self, session_id: str) -> dict:
        try:
            data = _read_state(self._session_path(session_id))
        except FileNotFoundError as exc:
            raise ValueError("unknown session") from exc
        return data

    def nonce_for(self, session_id: str) -> str:
        try:
            nonce = _read_state(self._registry_path(session_id))['nonce']
            if not isinstance(nonce, str) or not nonce:
                raise ValueError('Invalid local state')
            return nonce
        except FileNotFoundError as exc:
            raise ValueError("unknown session") from exc

    def _registered_media(self, session_id, media_id):
        if not isinstance(media_id, str) or not ID_PATTERN.fullmatch(media_id):
            return None
        try:
            self.read(session_id)
            registry = _read_state(self._registry_path(session_id))
            entry = registry['media'].get(media_id)
            if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
                return None
            path = Path(entry['path'])
            if not path.is_absolute() or '..' in path.parts or path.suffix.lower() not in MEDIA_TYPES:
                return None
            data = _read_regular(path, MAX_MEDIA_BYTES)
            if (not data or type(entry.get('size')) is not int or len(data) != entry['size'] or
                    entry.get('mime') != MEDIA_TYPES[path.suffix.lower()] or
                    not isinstance(entry.get('sha256'), str) or
                    not secrets.compare_digest(hashlib.sha256(data).hexdigest(), entry['sha256'])):
                return None
            return path, data, entry['mime']
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def resolve_media(self, session_id: str, media_id: str) -> Path | None:
        media = self._registered_media(session_id, media_id)
        return media[0] if media is not None else None

    def read_media(self, session_id, media_id):
        """Return the checked bytes, so the HTTP boundary never reopens a path."""
        media = self._registered_media(session_id, media_id)
        return (media[1], media[2]) if media is not None else None

    def _stage_media(self, registry: dict, path: Path) -> str:
        if path.suffix.lower() not in MEDIA_TYPES:
            raise ValueError('Reference must be an existing supported media file')
        data = _read_regular(path, MAX_MEDIA_BYTES)
        if not data:
            raise ValueError('Reference must be nonempty media')
        media_id = uuid4().hex
        registry['media'][media_id] = {'path': str(path.absolute()),
            'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data),
            'mime': MEDIA_TYPES[path.suffix.lower()]}
        return media_id

    def _register_media(self, session_id: str, path: Path) -> str:
        registry_path = self._registry_path(session_id)
        with _SafeLock(str(self.root / '.registry.lock'), mode='a', timeout=5):
            registry = _read_state(registry_path)
            media_id = self._stage_media(registry, path)
            self._write(registry_path, registry)
        return media_id

    def apply(self, session_id: str, expected_revision: int, action: str, payload: dict | None = None) -> dict:
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
            raise ValueError("expected_revision must be an integer")
        payload = validated_payload(action, {} if payload is None else payload)
        with _SafeLock(str(self.root / ".write.lock"), mode="a", timeout=5):
            session = self.read(session_id)
            if session["revision"] != expected_revision:
                raise RevisionConflict("session revision changed")
            if action in {'register_reference', 'record_preview'}:
                with _SafeLock(str(self.root / '.registry.lock'), mode='a', timeout=5):
                    registry = _read_state(self._registry_path(session_id))
                    self._mutate(session, action, payload, registry=registry)
                    session['revision'] += 1
                    # Both prospective records must be readable before either commits.
                    _state_bytes(session)
                    _state_bytes(registry)
                    self._write(self._registry_path(session_id), registry)
                    self._write(self._session_path(session_id), session)
                    return session
            self._mutate(session, action, payload)
            session["revision"] += 1
            self._write(self._session_path(session_id), session)
            return session

    def _mutate(self, session: dict, action: str, payload: dict, *, registry: dict | None = None) -> None:
        if action == "resolve_choices":
            resolution = _text(payload.get('resolution'), 'resolution')
            if not session['open_choices']:
                raise ValueError('No unresolved choices')
            session['provenance'].append({'kind': 'supplied', 'text': resolution, 'source': 'Explicit creative choice'})
            session['locks'] = [_text(x, 'lock') for x in payload.get('locks', session['locks'])]
            session['open_choices'] = []
        elif action == "propose_brief":
            session["brief"] = _brief(payload.get("brief"))
            session["brief_status"] = "proposed"
            session["provenance"] = _ledger(payload.get("provenance"))
            session["locks"] = [_text(item, "lock") for item in payload.get("locks", [])]
            session["open_choices"] = [_text(item, "choice") for item in payload.get("open_choices", [])]
            if payload.get("title"):
                session["title"] = _text(payload["title"], "title")
        elif action == "agree_brief":
            if session["brief_status"] != "proposed":
                raise ValueError("a proposed brief is required")
            if session['open_choices']:
                raise ValueError('unresolved choices')
            session["brief_status"] = "agreed"
        elif action == "direct_image":
            if session["brief_status"] != "gathering":
                raise ValueError("direct image is only for a new session")
            session["brief"] = _brief(payload.get("brief"), direct=True)
            session["brief_status"] = "agreed"
            session["provenance"] = _ledger(payload.get("provenance"))
            session["locks"] = [_text(item, "lock") for item in payload.get("locks", [])]
            if payload.get("title"):
                session["title"] = _text(payload["title"], "title")
            self._append_image(session, payload)
        elif action == "add_image_version":
            if session["brief_status"] != "agreed":
                raise ValueError("an agreed brief is required before a copy-ready prompt")
            self._append_image(session, payload)
        elif action == 'add_video_version':
            if session['brief_status'] != 'agreed':
                raise ValueError('An agreed brief is required')
            image = image_by_version(session, session['selected_image_version'])
            mode, duration = payload.get('mode'), payload.get('duration', 15)
            if not isinstance(mode, str) or mode not in {'preserve', 'evolve', 'multishot'}:
                raise ValueError('Invalid video mode')
            if isinstance(duration, bool) or not isinstance(duration, int) or not 1 <= duration <= 60:
                raise ValueError('Invalid video duration')
            if mode != 'preserve' and duration < 3:
                raise ValueError('A timed sequence needs at least three seconds')
            motion, camera = _text(payload.get('motion'), 'motion'), _text(payload.get('camera'), 'camera')
            locks = copy.deepcopy(image.get('locks', session['locks']))
            settings = generation_settings({**image.get('settings', {}), **generation_settings(payload.get('settings'), video=True)}, video=True)
            prompt = _video_prompt(image['prompt'], mode, duration, motion, camera, locks)
            if payload.get('prompt'):
                prompt += '\n\nAdditional creative direction: ' + _text(payload['prompt'], 'prompt')
            provenance = copy.deepcopy(image.get('provenance', [])) + _ledger(payload.get('provenance'))
            if not payload.get('provenance'):
                provenance.append({'text': motion, 'kind': 'proposed', 'source': 'Motion direction'})
            session['video_versions'].append({'version': len(session['video_versions']) + 1,
                'source_image_version': image['version'], 'mode': mode, 'duration': duration,
                'motion': motion, 'camera': camera, 'prompt': prompt, 'locks': locks,
                'settings': settings, 'provenance': provenance})
        elif action == "draft_edit":
            target = payload.get("target", "image")
            if not isinstance(target, str) or target not in {"image", "video"}:
                raise ValueError("draft target must be image or video")
            if target == 'image':
                base_version = payload['base_version'] if 'base_version' in payload else session['selected_image_version']
                if base_version is None and payload.get('shot_id'):
                    raise ValueError('Unknown shot ID')
                if base_version is not None:
                    image = image_by_version(session, base_version)
                    shots = image.get('shots', [])
                    if shots and payload.get('shot_id') not in {x['id'] for x in shots}:
                        raise ValueError('A series draft needs a known shot ID')
                    if not shots and payload.get('shot_id'):
                        raise ValueError('Unknown shot ID')
            else:
                base_version = payload['base_version'] if 'base_version' in payload else (session['video_versions'][-1]['version'] if session['video_versions'] else None)
                if base_version is None:
                    raise ValueError('No video version to revise')
                if not any(version['version'] == base_version for version in session['video_versions']):
                    raise ValueError('Unknown video version')
            session["drafts"].append({
                "id": uuid4().hex, "target": target,
                "text": _text(payload.get("text"), "draft text"), "status": "pending",
                "base_revision": session["revision"], "base_version": base_version,
                "shot_id": _clean(str(payload.get("shot_id", ""))),
            })
        elif action == 'accept_draft':
            if session['brief_status'] != 'agreed':
                raise ValueError('An agreed brief is required')
            draft = next((x for x in session['drafts'] if x['id'] == payload.get('draft_id') and x['status'] == 'pending'), None)
            if draft is None:
                raise ValueError('Unknown pending draft')
            if draft['target'] == 'image':
                append_image(session, {'prompt': draft['text'], 'shot_id': draft.get('shot_id'),
                                      'note': 'Accepted browser draft'}, draft['base_version'])
            else:
                previous = next((x for x in session['video_versions'] if x['version'] == draft['base_version']), None)
                if previous is None:
                    raise ValueError('Unknown video draft source')
                revised = copy.deepcopy(previous)
                revised.update(version=len(session['video_versions']) + 1,
                               source_video_version=previous['version'], prompt=_text(draft['text'], 'prompt'))
                session['video_versions'].append(revised)
            draft['status'] = 'accepted'
        elif action == "register_reference":
            raw_path = payload.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ValueError("reference path must be nonempty text")
            path = Path(raw_path)
            source_kind = payload.get("source_kind", "supplied_reference")
            if not isinstance(source_kind, str) or source_kind not in {"supplied_reference", "supplied_still", "supplied_video"}:
                raise ValueError("invalid source kind")
            label = _text(payload.get("label"), "reference label")
            role = _text(payload.get("role"), "reference role")
            media_id = self._stage_media(registry, path)
            session["references"].append({
                "id": media_id, "label": label,
                "role": role,
                "source_kind": source_kind,
                "provenance": "supplied",
            })
        elif action == "record_preview":
            raw_path = payload.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ValueError("preview path must be nonempty text")
            path = Path(raw_path)
            source_ids = payload.get("source_reference_ids", [])
            known_ids = {item["id"] for item in session["references"]}
            if not isinstance(source_ids, list) or any(item not in known_ids for item in source_ids):
                raise ValueError("unknown source reference ID")
            image = image_by_version(session, payload.get('prompt_version'))
            shot_id = payload.get('shot_id')
            if image.get('shots'):
                if shot_id not in {x['id'] for x in image['shots']}:
                    raise ValueError('Unknown preview shot ID')
            elif shot_id:
                raise ValueError('Unknown preview shot ID')
            model = _text(payload.get('model'), 'model')
            workflow = _text(payload.get('workflow'), 'workflow')
            media_id = self._stage_media(registry, path)
            digest = registry['media'][media_id]['sha256']
            session["previews"].append({
                "id": media_id, "status": "exploratory", "provenance": "generated",
                "prompt_version": payload.get("prompt_version"),
                "shot_id": _clean(str(payload.get("shot_id") or "")),
                "model": _text(payload.get("model"), "model"),
                "workflow": _text(payload.get("workflow"), "workflow"),
                "source_reference_ids": source_ids,
                "sha256": digest, "limitations": _clean(payload.get("limitations", [])),
            })
        elif action == "promote_preview":
            preview = next((item for item in session["previews"] if item["id"] == payload.get("preview_id")), None)
            if preview is None:
                raise ValueError("unknown preview")
            preview["status"] = "promoted"
            if preview["id"] not in session["visual_locks"]:
                session["visual_locks"].append(preview["id"])
        elif action == "select_image_version":
            version = payload.get("version")
            image_by_version(session, version)
            session["selected_image_version"] = version
        elif action == "record_advice":
            try:
                from .judge import validate_advice
            except ImportError as exc:
                raise ValueError('Advice validation is unavailable until the advice module is installed') from exc
            advice = validate_advice(payload, session)
            session.setdefault('advice', []).append(advice)
        else:
            raise ValueError("unknown workshop action")

    @staticmethod
    def _append_image(session: dict, payload: dict, base_version=None) -> None:
        append_image(session, payload, base_version)
