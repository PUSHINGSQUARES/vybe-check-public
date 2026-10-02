"""Explicit text-only local studies through a validated core workflow."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import http.client
import ipaddress
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import socket
import threading
import time
from urllib.parse import urlencode, urlsplit
from uuid import uuid4
import warnings

from PIL import Image

from .config import data_root
from .workshop import ID_PATTERN, RevisionConflict

MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 40_000_000
POLL_SECONDS = 180
MAX_JSON_BYTES = 4 * 1024 * 1024
LIMITATIONS = ['Text-only study; references do not condition this workflow',
               'Live backend declarations are assertions, not verified node provenance',
               'Identity, object fidelity, and checkpoint compatibility require separate review']
CORE_WORKFLOW = {'1': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': 'selected-local-checkpoint.safetensors'}}, '2': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'An invented still-life study', 'clip': ['1', 1]}}, '3': {'class_type': 'CLIPTextEncode', 'inputs': {'text': '', 'clip': ['1', 1]}}, '4': {'class_type': 'EmptyLatentImage', 'inputs': {'width': 512, 'height': 768, 'batch_size': 1}}, '5': {'class_type': 'KSampler', 'inputs': {'seed': 234, 'steps': 20, 'cfg': 7, 'sampler_name': 'euler', 'scheduler': 'normal', 'denoise': 1, 'model': ['1', 0], 'positive': ['2', 0], 'negative': ['3', 0], 'latent_image': ['4', 0]}}, '6': {'class_type': 'VAEDecode', 'inputs': {'samples': ['5', 0], 'vae': ['1', 2]}}, '7': {'class_type': 'SaveImage', 'inputs': {'images': ['6', 0], 'filename_prefix': 'vybe-study'}}}
OUTPUTS = {'CheckpointLoaderSimple': ['MODEL', 'CLIP', 'VAE'],
           'CLIPTextEncode': ['CONDITIONING'], 'EmptyLatentImage': ['LATENT'],
           'KSampler': ['LATENT'], 'VAEDecode': ['IMAGE']}
NUMERIC = {'width': ('INT', 16, 2048), 'height': ('INT', 16, 2048),
           'batch_size': ('INT', 1, 1), 'seed': ('INT', 0, 2**64 - 1),
           'steps': ('INT', 1, 100), 'cfg': ('FLOAT', 0, 30), 'denoise': ('FLOAT', 0, 1)}
LINK_TYPES = {'clip': 'CLIP', 'model': 'MODEL', 'positive': 'CONDITIONING',
              'negative': 'CONDITIONING', 'latent_image': 'LATENT',
              'samples': 'LATENT', 'vae': 'VAE', 'images': 'IMAGE'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()


def loopback_origin(value):
    if not isinstance(value, str) or any(c.isspace() for c in value) or '\\' in value:
        raise ValueError('Invalid local origin')
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.username is not None or parsed.password is not None or
            parsed.path not in ('', '/') or parsed.query or parsed.fragment or '?' in value or '#' in value):
        raise ValueError('Invalid local origin')
    address = ipaddress.ip_address(parsed.hostname or '')
    if not address.is_loopback or (address.version == 6 and str(address) != '::1'):
        raise ValueError('Invalid local origin')
    port = parsed.port
    if port is None or not 1 <= port <= 65535:
        raise ValueError('Invalid local origin')
    host = f'[{address}]' if address.version == 6 else str(address)
    origin = f'http://{host}:{port}'
    if value.rstrip('/') != origin:
        raise ValueError('Invalid local origin')
    return origin


def _plain_file(path, limit):
    if not stat.S_ISREG(path.lstat().st_mode) or path.is_symlink() or path.stat().st_nlink != 1:
        raise ValueError('Invalid local configuration')
    if path.stat().st_size > limit:
        raise ValueError('Invalid local configuration')
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError('Invalid local configuration')
    return raw


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _numeric(value, key, definition):
    kind, low, high = NUMERIC[key]
    if not _number(value) or (kind == 'INT' and type(value) is not int) or not low <= value <= high:
        raise ValueError('Invalid core value')
    if len(definition) != 2 or definition[0] != kind or not isinstance(definition[1], dict):
        raise ValueError('Invalid core definition')
    bounds = definition[1]
    minimum, maximum, step = bounds.get('min'), bounds.get('max'), bounds.get('step', 1)
    if not all(_number(v) for v in (minimum, maximum, step)) or step <= 0 or minimum > maximum:
        raise ValueError('Invalid core bounds')
    if not minimum <= value <= maximum:
        raise ValueError('Unsupported core value')
    if (Decimal(str(value)) - Decimal(str(minimum))) % Decimal(str(step)) != 0:
        raise ValueError('Unsupported core step')


def validate_workflow(config, info):
    if not isinstance(config, dict) or set(config) != {'base_url', 'workflow', 'prompt_node', 'checkpoint'}:
        raise ValueError('Invalid local configuration')
    origin = loopback_origin(config['base_url'])
    graph = config['workflow']
    checkpoint = config['checkpoint']
    if (not isinstance(checkpoint, str) or not checkpoint or len(checkpoint) > 240 or
            any(c in checkpoint for c in '\\/:\x00\r\n') or checkpoint in ('.', '..')):
        raise ValueError('Invalid checkpoint')
    if config['prompt_node'] != '2' or not isinstance(graph, dict) or set(graph) != set(CORE_WORKFLOW):
        raise ValueError('Unsupported core workflow')
    if not isinstance(info, dict):
        raise ValueError('Invalid live capability')
    for identifier, template in CORE_WORKFLOW.items():
        node = graph[identifier]
        if (not isinstance(node, dict) or set(node) != {'class_type', 'inputs'} or
                node['class_type'] != template['class_type'] or not isinstance(node['inputs'], dict) or
                set(node['inputs']) != set(template['inputs'])):
            raise ValueError('Unsupported core workflow')
        cls = node['class_type']; definition = info.get(cls)
        if (not isinstance(definition, dict) or definition.get('python_module') != 'nodes' or
                definition.get('API_NODE', False) is not False or
                definition.get('output_node') is not (cls == 'SaveImage')):
            raise ValueError('Unsupported node declaration')
        groups = definition.get('input')
        if not isinstance(groups, dict) or set(groups) - {'required', 'optional', 'hidden'}:
            raise ValueError('Invalid node inputs')
        required = groups.get('required')
        if not isinstance(required, dict) or set(required) != set(template['inputs']) or groups.get('optional', {}):
            raise ValueError('Unsupported node inputs')
        hidden = groups.get('hidden', {})
        expected_hidden = {'prompt': 'PROMPT', 'extra_pnginfo': 'EXTRA_PNGINFO'} if cls == 'SaveImage' else {}
        if not isinstance(hidden, dict) or any(expected_hidden.get(k) != v for k,v in hidden.items()):
            raise ValueError('Unsupported hidden inputs')
        outputs = definition.get('output')
        if cls == 'SaveImage':
            if outputs not in ([], ['IMAGE']): raise ValueError('Unsupported core output')
        elif outputs != OUTPUTS[cls]:
            raise ValueError('Unsupported core output')
        for key, value in node['inputs'].items():
            shape = required[key]
            if not isinstance(shape, (list, tuple)) or not shape: raise ValueError('Invalid input declaration')
            expected = template['inputs'][key]
            if key in LINK_TYPES:
                if (value != expected or not isinstance(value, list) or len(value) != 2 or
                        type(value[1]) is not int or shape[0] != LINK_TYPES[key]):
                    raise ValueError('Invalid core link')
                source = graph[value[0]]['class_type']
                if info[source]['output'][value[1]] != LINK_TYPES[key]: raise ValueError('Invalid typed link')
            elif key in NUMERIC:
                _numeric(value, key, shape)
            elif key in ('ckpt_name', 'sampler_name', 'scheduler'):
                if not isinstance(shape[0], list) or not shape[0] or not all(isinstance(x,str) for x in shape[0]) or value not in shape[0]:
                    raise ValueError('Unsupported core choice')
                if key == 'ckpt_name' and value != checkpoint: raise ValueError('Checkpoint mismatch')
            else:
                if shape[0] != 'STRING' or value != expected: raise ValueError('Invalid core text')
    return origin, copy.deepcopy(graph)


def _media_primitives(output_root=None):
    if os.name == 'nt':
        writer = _windows_writer()
        if output_root is not None: writer.preflight(output_root)
        return

    required = (os.open, os.mkdir, os.stat)
    if (os.name != 'posix' or not getattr(os, 'O_DIRECTORY', 0) or
            not getattr(os, 'O_NOFOLLOW', 0) or
            any(function not in os.supports_dir_fd for function in required) or
            os.stat not in os.supports_follow_symlinks):
        raise ValueError('Owned local media directories unavailable')



def _windows_bindings():
    # Bind only when local studies explicitly request Windows media safety.
    import ctypes as c
    kernel = c.WinDLL('kernel32.dll', use_last_error=True)
    native = c.WinDLL('ntdll.dll')
    u32, handle, pointer = c.c_uint32, c.c_void_p, c.c_void_p
    class Unicode(c.Structure):
        _fields_ = [('Length', c.c_uint16), ('MaximumLength', c.c_uint16), ('Buffer', pointer)]
    class Attributes(c.Structure):
        _fields_ = [('Length', u32), ('RootDirectory', handle), ('ObjectName', c.POINTER(Unicode)),
                    ('Attributes', u32), ('SecurityDescriptor', pointer), ('SecurityQualityOfService', pointer)]
    class Status(c.Structure):
        _fields_ = [('Status', pointer), ('Information', c.c_size_t)]
    class Information(c.Structure):
        _fields_ = [('attributes', u32), ('times', u32 * 6), ('volume', u32),
                    ('size_high', u32), ('size_low', u32), ('links', u32),
                    ('index_high', u32), ('index_low', u32)]
    signatures = {
        'GetDriveTypeW': (u32, [c.c_wchar_p]),
        'GetFileType': (u32, [handle]),
        'GetFileInformationByHandle': (c.c_int32, [handle, c.POINTER(Information)]),
        'GetFileInformationByHandleEx': (c.c_int32, [handle, c.c_int32, pointer, u32]),
        'GetFinalPathNameByHandleW': (u32, [handle, c.c_wchar_p, u32, u32]),
        'WriteFile': (c.c_int32, [handle, pointer, u32, c.POINTER(u32), pointer]),
        'FlushFileBuffers': (c.c_int32, [handle]),
        'CloseHandle': (c.c_int32, [handle]),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(kernel, name); function.restype = result; function.argtypes = arguments
    native.NtCreateFile.restype = c.c_int32
    native.NtCreateFile.argtypes = [c.POINTER(handle), u32, c.POINTER(Attributes), c.POINTER(Status),
                                    pointer, u32, u32, u32, u32, pointer, u32]
    class Bindings:
        def drive(self, anchor):
            return kernel.GetDriveTypeW(anchor)
        def open(self, parent, name, *, create=False, directory=True):
            # One relative child has no intermediate name to traverse. Existing
            # leaves open the reparse object itself, then validation rejects it.
            text = name if parent is not None else '\\??\\' + name
            buffer = c.create_unicode_buffer(text)
            length = len(text.encode('utf-16-le'))
            if length > 65532: raise ValueError('Invalid media path')
            string = Unicode(length, length + 2, c.cast(buffer, pointer))
            attributes = Attributes(c.sizeof(Attributes), parent, c.pointer(string), 0x40, None, None)
            output, status = handle(), Status()
            options = 0x20 | (0x1 if create and directory else 0x200000)
            if not directory: options |= 0x40
            access = 0x100000 | 0x80 | (0x20 if directory else 0x2)
            # FILE_GENERIC_WRITE permits flushing only the fresh output file.
            if create and not directory: access |= 0x120116
            result = native.NtCreateFile(c.byref(output), access, c.byref(attributes), c.byref(status),
                                         None, 0x10 if directory else 0x80, 1 if directory else 0,
                                         2 if create else 1, options, None, 0)
            # Only exact synchronous success yields an owned handle. Failure
            # output is unverifiable, so it must never be used or closed.
            if result != 0 or not output.value or output.value == c.c_void_p(-1).value:
                if (result & 0xffffffff) in (0xc0000034, 0xc000003a): raise FileNotFoundError()
                raise ValueError('Native media open unavailable')
            if status.Status or int(status.Information) != (2 if create else 1):
                kernel.CloseHandle(output); raise ValueError('Unexpected native creation')
            return output.value
        def info(self, owned):
            information = Information(); tag = (u32 * 2)(); final = c.create_unicode_buffer(32768)
            if (kernel.GetFileType(owned) != 1 or
                    not kernel.GetFileInformationByHandle(owned, c.byref(information)) or
                    not kernel.GetFileInformationByHandleEx(owned, 9, c.byref(tag), c.sizeof(tag))):
                raise ValueError('Native media identity unavailable')
            length = kernel.GetFinalPathNameByHandleW(owned, final, len(final), 0)
            if length == 0 or length >= len(final): raise ValueError('Native media path unavailable')
            if information.attributes != tag[0]: raise ValueError('Native media attributes changed')
            return (int(tag[0]), int(tag[1]), int(information.volume),
                    (int(information.index_high) << 32) | int(information.index_low), final.value)
        def write(self, owned, raw):
            buffer = c.create_string_buffer(raw); offset = 0
            while offset < len(raw):
                count = u32()
                if not kernel.WriteFile(owned, c.byref(buffer, offset), len(raw)-offset, c.byref(count), None):
                    raise ValueError('Native media write unavailable')
                if not 0 < count.value <= len(raw)-offset: raise ValueError('Invalid native write')
                offset += count.value
            if not kernel.FlushFileBuffers(owned): raise ValueError('Native media flush unavailable')
        def close(self, owned):
            if not kernel.CloseHandle(owned): raise ValueError('Native media close unavailable')
    return Bindings()


def _windows_parts(root):
    from pathlib import PureWindowsPath
    path = PureWindowsPath(str(root))
    if (not re.fullmatch(r'[A-Za-z]:\\', path.anchor) or not path.is_absolute() or
            any(not name or name in {'.', '..'} or name[-1] in '. ' or
                re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or
                re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name)
                for name in path.parts[1:])):
        raise ValueError('Invalid local media path')
    # PureWindowsPath normalises dot components, so reject them in the input too.
    if any(name in {'.','..'} for name in re.split(r'[/\\]', str(root))):
        raise ValueError('Invalid local media path')
    return path, list(path.parts[1:])


class _WindowsMedia:
    def __init__(self, api):
        self.api = api

    def _check(self, owned, expected, directory, volume=None):
        attributes, tag, serial, index, final = self.api.info(owned)
        if (attributes & (0x400 | 0x1000 | 0x40) or tag or bool(attributes & 0x10) != directory or
                not serial or not index or (volume is not None and serial != volume) or
                final.casefold().rstrip('\\') != ('\\\\?\\' + str(expected)).casefold().rstrip('\\')):
            raise ValueError('Invalid native media identity')
        return serial, index

    def _verify(self, chain):
        for owned, expected, directory, identity in chain:
            if self._check(owned, expected, directory, identity[0]) != identity:
                raise ValueError('Native media identity changed')

    def _walk(self, root, owned, chain):
        path, components = _windows_parts(root)
        if self.api.drive(path.anchor) not in (2, 3): raise ValueError('Non-local media drive')
        parent = self.api.open(None, path.anchor)
        owned.append(parent); current = type(path)(path.anchor)
        identity = self._check(parent, current, True); chain.append((parent, current, True, identity))
        count = 0
        for name in components:
            self._verify(chain)
            try: child = self.api.open(parent, name)
            except FileNotFoundError: break
            owned.append(child); current /= name
            identity = self._check(child, current, True, chain[0][3][0])
            chain.append((child, current, True, identity)); parent = child; count += 1
        self._verify(chain)
        return path, components[count:], parent, current

    def _close(self, owned):
        failed = False
        for handle in reversed(owned):
            try: self.api.close(handle)
            except Exception: failed = True
        if failed: raise ValueError('Native media close unavailable')

    def preflight(self, root):
        owned, chain = [], []
        try: self._walk(root, owned, chain)
        finally: self._close(owned)

    def save(self, raw, root, session_id, prompt_version, suffix):
        from pathlib import PureWindowsPath
        path = _windows_parts(root)[0] / session_id / 'previews'
        owned, chain = [], []
        try:
            _, missing, parent, current = self._walk(path, owned, chain)
            # Creation returns the directory handle atomically. No reopen gap.
            fresh = (f'v{prompt_version:03d}-' +
                     datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex)
            for name in [*missing, fresh]:
                self._verify(chain)
                child = self.api.open(parent, name, create=True)
                owned.append(child); current /= name
                identity = self._check(child, current, True, chain[0][3][0])
                chain.append((child, current, True, identity)); parent = child
            self._verify(chain)
            output = self.api.open(parent, 'look-study' + suffix, create=True, directory=False)
            owned.append(output); current /= 'look-study' + suffix
            identity = self._check(output, current, False, chain[0][3][0])
            chain.append((output, current, False, identity)); self._verify(chain)
            self.api.write(output, raw); self._verify(chain)
            return Path(str(current))
        finally: self._close(owned)


def _windows_writer():
    return _WindowsMedia(_windows_bindings())


def _directory_identity(value):
    if not stat.S_ISDIR(value.st_mode):
        raise ValueError('Invalid media directory')
    return value.st_dev, value.st_ino


def _verify_owned_directories(chain):
    for parent, name, child in chain:
        entry = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if _directory_identity(entry) != _directory_identity(os.fstat(child)):
            raise ValueError('Media directory changed')


def _mkdir_owned(name, mode=0o700, *, dir_fd):
    os.mkdir(name, mode=mode, dir_fd=dir_fd)


def _save_owned(raw, root, session_id, prompt_version, suffix):
    _media_primitives()
    if root.anchor != '/' or '..' in root.parts:
        raise ValueError('Invalid media directory')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors = []
    chain = []
    components = [*root.parts[1:], session_id, 'previews']
    try:
        parent = os.open(root.anchor, flags)
        descriptors.append(parent)
        _directory_identity(os.fstat(parent))
        # Inspect every existing descendant before creating any output directory.
        for name in components:
            try:
                child = os.open(name, flags, dir_fd=parent)
            except FileNotFoundError:
                break
            descriptors.append(child)
            chain.append((parent, name, child))
            _verify_owned_directories(chain)
            parent = child
        # Each operation uses an owned descriptor, never a substituted path.
        for name in components[len(chain):]:
            _verify_owned_directories(chain)
            try:
                _mkdir_owned(name, dir_fd=parent)
            except FileExistsError:
                pass
            child = os.open(name, flags, dir_fd=parent)
            descriptors.append(child)
            chain.append((parent, name, child))
            _verify_owned_directories(chain)
            parent = child
        fresh = (f'v{prompt_version:03d}-' +
                 datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex)
        _verify_owned_directories(chain)
        _mkdir_owned(fresh, dir_fd=parent)
        folder = os.open(fresh, flags, dir_fd=parent)
        descriptors.append(folder)
        chain.append((parent, fresh, folder))
        _verify_owned_directories(chain)
        filename = 'look-study' + suffix
        descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=folder)
        with os.fdopen(descriptor, 'wb') as output:
            _verify_owned_directories(chain)
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
            _verify_owned_directories(chain)
        return root / session_id / 'previews' / fresh / filename
    except OSError:
        raise ValueError('Owned local media directory unavailable') from None
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def save_study(raw, output_root, session_id, prompt_version):
    if (not isinstance(raw, bytes) or not raw or len(raw) > MAX_IMAGE_BYTES or
            not isinstance(session_id, str) or not ID_PATTERN.fullmatch(session_id) or
            type(prompt_version) is not int or prompt_version < 1):
        raise ValueError('Invalid study image')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                if (image.format not in {'PNG','JPEG','WEBP'} or image.width * image.height > MAX_PIXELS or
                        getattr(image, 'n_frames', 1) != 1):
                    raise ValueError('Invalid study dimensions')
                image.verify()
            with Image.open(BytesIO(raw)) as image:
                image.load()
                suffix = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}[image.format]
    except Exception:
        raise ValueError('Invalid study image') from None
    if os.name == 'nt':
        try: return _windows_writer().save(raw, output_root, session_id, prompt_version, suffix)
        except Exception: raise ValueError('Owned local media directory unavailable') from None
    return _save_owned(raw, Path(output_root).absolute(), session_id, prompt_version, suffix)


class ComfyPreview:
    def __init__(self, root):
        self.root = data_root(root)

    def _request(self, origin, route, *, body=None, timeout=5, limit=MAX_JSON_BYTES):
        parsed = urlsplit(loopback_origin(origin))
        # http.client does not inherit proxy settings and does not follow redirects.
        budget = min(5, max(0.01, timeout))
        started = time.monotonic()
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=budget)
        timer = None
        response = None
        expired = threading.Event()
        try:
            connection.connect()
            owned_socket = connection.sock
            def expire():
                expired.set()
                try: owned_socket.shutdown(socket.SHUT_RDWR)
                except OSError: pass
            timer = threading.Timer(max(0.001, budget - (time.monotonic()-started)), expire)
            timer.daemon = True
            timer.start()
            payload = None if body is None else json.dumps(body, allow_nan=False).encode('utf-8')
            connection.request('GET' if body is None else 'POST', route, body=payload,
                               headers={} if body is None else {'Content-Type': 'application/json'})
            response = connection.getresponse()
            if response.status != 200: raise ValueError('Local response unavailable')
            raw = response.read(limit + 1)
            if expired.is_set(): raise TimeoutError('Local response timed out')
            if len(raw) > limit: raise ValueError('Local response too large')
            return raw
        finally:
            if timer is not None:
                timer.cancel()
                timer.join(timeout=1)
            if response is not None: response.close()
            connection.close()

    def _snapshot(self, timeout=5):
        _media_primitives(self.root / 'media')
        raw = _plain_file(self.root / 'comfyui.json', MAX_JSON_BYTES)
        config = json.loads(raw)
        origin = loopback_origin(config['base_url'])
        info = json.loads(self._request(origin, '/object_info', timeout=timeout))
        origin, workflow = validate_workflow(config, info)
        capability = {'available': True, 'wholly_local': True, 'backend': 'ComfyUI',
            'model': config['checkpoint'], 'reference_modes': ['Text'], 'limitations': LIMITATIONS.copy(),
            'workflow_digest': digest(workflow), 'capability_digest': digest({'origin':origin,'workflow':workflow,'definitions':info})}
        return capability, origin, workflow, info

    def capability(self):
        try: return self._snapshot()[0]
        except Exception: return {'available': False, 'reason': 'Local study unavailable'}

    def _source(self, store, session_id, revision, version, shot_id):
        if (store.root.resolve() != self.root.resolve() or type(revision) is not int or
                type(version) is not int or version < 1): raise ValueError('Invalid study request')
        state = store.read(session_id)
        if state['revision'] != revision: raise ValueError('Session revision changed')
        if state['brief_status'] != 'agreed': raise ValueError('An agreed image version is required')
        image = next((x for x in state['image_versions'] if x['version'] == version), None)
        if image is None: raise ValueError('Unknown image version')
        shots = image.get('shots', [])
        if shots:
            selected = next((x for x in shots if x['id'] == shot_id), None)
            if selected is None: raise ValueError('A known shot is required')
        else:
            if shot_id is not None: raise ValueError('Unknown shot')
            selected = image
        return selected['prompt'], digest({'version':image,'shot':selected,'shot_id':shot_id})

    def generate(self, store, session_id, expected_revision, prompt_version, shot_id=None):
        text, source_digest = self._source(store,session_id,expected_revision,prompt_version,shot_id)
        try:
            _media_primitives(self.root / 'media' / session_id / 'previews')
            capability, origin, graph, _ = self._snapshot()
            # Recheck both state and live capability immediately before the only submission.
            self._source(store,session_id,expected_revision,prompt_version,shot_id)
            checked, _, _, info = self._snapshot()
            if checked != capability: raise ValueError('Local capability changed')
            graph['2']['inputs']['text'] = text
            bounds = info['KSampler']['input']['required']['seed'][1]
            low, high = max(0, bounds['min']), min(2**64 - 1, bounds['max'])
            step = bounds.get('step', 1)
            if any(type(x) is not int for x in (low, high, step)):
                raise ValueError('Unsupported seed bounds')
            first = low + ((bounds['min'] - low) % step)
            graph['5']['inputs']['seed'] = first + secrets.randbelow((high-first)//step+1) * step
            _numeric(graph['5']['inputs']['seed'], 'seed', info['KSampler']['input']['required']['seed'])
            prefix = 'vybe-study-' + uuid4().hex
            graph['7']['inputs']['filename_prefix'] = prefix
            if self._source(store,session_id,expected_revision,prompt_version,shot_id)[1] != source_digest:
                raise ValueError('Image version changed')
            deadline = time.monotonic() + min(180, POLL_SECONDS)
            submitted = json.loads(self._request(origin,'/prompt',body={'prompt':graph},timeout=min(5,deadline-time.monotonic())))
            job_id = submitted.get('prompt_id')
            if (not isinstance(job_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',job_id) or submitted.get('node_errors')):
                raise ValueError('Invalid submitted job')
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise ValueError('Local study timed out')
                history = json.loads(self._request(origin,'/history/'+job_id,timeout=min(5,remaining)))
                if not isinstance(history,dict): raise ValueError('Invalid history')
                if job_id not in history:
                    if history: raise ValueError('Unexpected job history')
                    time.sleep(min(0.25,max(0,deadline-time.monotonic())));continue
                job = history[job_id]
                if not isinstance(job,dict): raise ValueError('Invalid job history')
                status = job.get('status', {})
                if status.get('status_str') == 'error': raise ValueError('Local study failed')
                if status.get('completed') is not True:
                    time.sleep(min(0.25,max(0,deadline-time.monotonic())));continue
                if status.get('status_str') != 'success' or set(job.get('outputs',{})) != {'7'}:
                    raise ValueError('Unexpected study output')
                images = job['outputs']['7'].get('images')
                if not isinstance(images,list) or len(images)!=1: raise ValueError('Unexpected study output')
                image = images[0]
                if (not isinstance(image,dict) or set(image)!={'filename','subfolder','type'} or
                    image['type']!='output' or image['subfolder']!='' or not isinstance(image['filename'],str) or
                    not re.fullmatch(re.escape(prefix)+r'_[0-9]+_\.(png|jpg|jpeg|webp)',image['filename'])):
                    raise ValueError('Unexpected study record')
                remaining = deadline-time.monotonic()
                if remaining<=0: raise ValueError('Local study timed out')
                raw = self._request(origin,'/view?'+urlencode(image),timeout=min(5,remaining),limit=MAX_IMAGE_BYTES)
                path = save_study(raw,self.root/'media',session_id,prompt_version)
                break
        except Exception:
            raise RuntimeError('Local study unavailable') from None
        result = {'status':'unregistered','reason':'Session changed; reconcile this study explicitly',
                  'path':str(path),'prompt_version':prompt_version,'shot_id':shot_id,
                  'source_digest':source_digest,'workflow_digest':capability['workflow_digest']}
        try:
            _, current_digest = self._source(store,session_id,expected_revision,prompt_version,shot_id)
            current_capability, _, _, _ = self._snapshot()
            if current_digest!=source_digest or current_capability!=capability: return result
            return store.apply(session_id,expected_revision,'record_preview',{'path':str(path),
                'prompt_version':prompt_version,**({'shot_id':shot_id} if shot_id is not None else {}),'model':capability['model'],
                'workflow':capability['workflow_digest'],'source_reference_ids':[],
                'limitations':capability['limitations']})
        except (RevisionConflict,ValueError,OSError,RuntimeError,KeyError,TypeError,http.client.HTTPException):
            return result
