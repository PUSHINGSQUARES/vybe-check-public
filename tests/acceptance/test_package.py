from importlib.resources import files
from pathlib import Path
import tomllib

import vybe_check


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def test_public_resources():
    root = files('vybe_check')
    assert root.joinpath('skill/SKILL.md').is_file()
    assert root.joinpath('studio/index.html').is_file()
    assert not root.joinpath('generation.py').is_file()


def test_extracted_runtime_resources():
    root = files('vybe_check')
    for name in (
        'workshop.py',
        'cli.py',
        'studio/server.py',
        'studio/index.html',
        'studio/app.css',
        'studio/app.js',
    ):
        assert root.joinpath(name).is_file(), name


def test_private_runtime_modules_are_absent():
    root = files('vybe_check')
    for name in (
        'generation.py',
        'requests.py',
        'provider_cli.py',
        'models.py',
        'creative.py',
        'jev.py',
        'secure_store.py',
    ):
        assert not root.joinpath(name).is_file(), name


def test_package_version_matches_metadata():
    metadata_path = SOURCE_ROOT / 'pyproject.toml'
    assert metadata_path.is_file()
    metadata = tomllib.loads(metadata_path.read_text(encoding='utf-8'))
    assert metadata['project']['name'] == 'vybe-check'
    assert metadata['project']['version'] == vybe_check.__version__
    assert metadata['project']['scripts']['vybe-check'] == 'vybe_check.cli:main'


def test_package_entry_modules_exist():
    root = files('vybe_check')
    assert root.joinpath('__init__.py').is_file()
    assert root.joinpath('__main__.py').is_file()


def test_manifest_selects_only_public_input_types(tmp_path, monkeypatch):
    from setuptools.command.egg_info import FileList

    manifest_path = SOURCE_ROOT / 'MANIFEST.in'
    assert manifest_path.is_file()
    allowed = {
        'LICENSE',
        'THIRD_PARTY_NOTICES.md',
        'README.md',
        'CHANGELOG.md',
        'pyproject.toml',
        'MANIFEST.in',
        'src/vybe_check/__init__.py',
        'src/vybe_check/studio/server.py',
        'src/vybe_check/skill/SKILL.md',
        'src/vybe_check/skill/references/prompts.md',
        'src/vybe_check/studio/index.html',
        'src/vybe_check/studio/app.css',
        'src/vybe_check/studio/app.js',
        'src/vybe_check/examples/workshop.json',
        'tests/acceptance/test_package.py',
        'tools/check_package.py',
        'tools/check_package.sh',
        'docs/package.md',
        'examples/comfy-core.json',
        'src/vybe_check/examples/ceramic-reference.png',
    }
    forbidden = {
        'coordination-plan.md',
        '.cache/session.md',
        'private/source-map.json',
        'evidence/receipt.json',
        '.venv/src/runtime.py',
        'build/lib/vybe_check/workshop.py',
        'dist/vybe-check.whl',
        'src/vybe_check/generation.py',
        'src/vybe_check/secure_store.py',
        'src/vybe_check/__pycache__/cached.py',
        'src/vybe_check/studio/._app.js',
        'src/vybe_check/studio/.DS_Store',
        'src/vybe_check/studio/secret.key',
        'tests/.venv/runtime.py',
        'tools/__pycache__/cached.py',
        'tools/native_keys/password.py',
        'docs/private/coordination.md',
        'docs/evidence/receipt.md',
        'docs/._package.md',
        '.env',
        'unlisted.json',
    }
    for name in allowed | forbidden:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Fixture\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    inventory = FileList()
    inventory.allfiles = sorted(allowed | forbidden)
    inventory.files = list(inventory.allfiles)
    for raw_line in manifest_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.partition('#')[0].strip()
        if line:
            inventory.process_template_line(line)
    assert set(inventory.files) == allowed


def test_packaged_examples_are_complete_and_exclusive(tmp_path):
    import json
    from importlib.util import find_spec
    assert find_spec("vybe_check.resource_copy") is not None, "Packaged resource copy is missing"
    from vybe_check.resource_copy import copy_examples
    from vybe_check.workshop import SessionStore
    from vybe_check.export import agreed_export
    destination = tmp_path / 'examples'
    result = copy_examples(destination)
    assert result['status'] == 'copied'
    assert set(result['files']) == {p.name for p in destination.iterdir()}
    assert {'ceramic-image.json', 'kite-image.json', 'kite-preserve.json', 'kite-evolve.json', 'kite-multishot.json', 'ceramic-reference.png', 'kite-reference.png', 'comfy-core.json'} == set(result['files'])
    store = SessionStore(tmp_path / 'state')
    for scenario in ('ceramic', 'kite'):
        state = store.create(scenario)
        payload = json.loads((destination / (scenario + '-image.json')).read_text())
        assert {p['kind'] for p in payload['provenance']} == {'supplied', 'inferred', 'proposed'}
        state = store.apply(state['id'], 0, 'direct_image', payload)
        assert agreed_export(state, 'image', 1)['prompt'] == state['image_versions'][0]['prompt']
        assert state['image_versions'][0]['prompt'].startswith(payload['prompt'])
        assert all(lock in state['image_versions'][0]['prompt'] for lock in payload['locks'])
        reference = destination / (scenario + '-reference.png')
        state = store.apply(state['id'], state['revision'], 'register_reference', {'path': str(reference), 'label': scenario.capitalize() + ' generic reference', 'role': 'Colour and geometry', 'source_kind': 'supplied_reference'})
        assert state['references'][-1]['label'] == scenario.capitalize() + ' generic reference'
        import threading
        from urllib.request import urlopen
        from vybe_check.studio.server import create_server
        server = create_server(0, root=store.root, store=store, active_id=state['id'])
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            url = 'http://127.0.0.1:' + str(server.server_port) + '/media/' + state['id'] + '/' + state['references'][-1]['id']
            with urlopen(url, timeout=5) as response:
                assert response.headers['Content-Type'] == 'image/png'
                assert response.read() == reference.read_bytes()
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
            assert not thread.is_alive()

        from PIL import Image
        with Image.open(reference) as decoded:
            decoded.load()
            assert decoded.format == 'PNG' and decoded.size == (32, 24)
            assert len(set(decoded.tobytes()[i:i+3] for i in range(0, len(decoded.tobytes()), 3))) > 1

        if scenario == 'kite':
            for mode in ('preserve', 'evolve', 'multishot'):
                video = json.loads((destination / ('kite-' + mode + '.json')).read_text())
                state = store.apply(state['id'], state['revision'], 'add_video_version', video)
                assert state['video_versions'][-1]['duration'] == 15
                assert state['video_versions'][-1]['mode'] == mode
    before = {p.name: p.read_bytes() for p in destination.iterdir()}
    import pytest
    with pytest.raises(ValueError, match='exists'):
        copy_examples(destination)
    assert before == {p.name: p.read_bytes() for p in destination.iterdir()}


def test_resource_copy_cli(tmp_path):
    import json, os, subprocess, sys
    target = tmp_path / 'copied'
    root = tmp_path / 'state'
    counter = 0
    def call(*args):
        nonlocal counter
        counter += 1
        child = tmp_path / ('cli-' + str(counter)); child.mkdir()
        env = dict(os.environ)
        keys = ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'XDG_DATA_HOME', 'VYBE_CHECK_ROOT', 'TMPDIR')
        for key in keys:
            directory = child / key.lower(); directory.mkdir(); env[key] = str(directory)
        assert len({env[key] for key in keys}) == 6
        for key in keys:
            assert Path(env[key]).is_dir() and Path(env[key]).is_relative_to(child)
        assert env['PYTHONDONTWRITEBYTECODE'] == '1'
        assert env['PYTHONPATH'].split(os.pathsep)[0] == str(SOURCE_ROOT / 'src')
        from importlib.machinery import PathFinder
        origins = {}
        for name in ('cli', 'workshop', 'credentials', 'local_preview', 'resource_copy'):
            spec = PathFinder.find_spec(name, [str(SOURCE_ROOT / 'src/vybe_check')])
            assert spec and Path(spec.origin).is_relative_to(SOURCE_ROOT / 'src/vybe_check')
            origins[name] = spec.origin
        with (child / 'requested-environment-and-origins.json').open('x') as stream:
            json.dump({'environment': env, 'origins': origins}, stream)
        return subprocess.run([sys.executable, '-B', '-m', 'vybe_check', '--root', str(root), *args], cwd=child, env=env, capture_output=True, text=True, timeout=10)
    result = call('examples', 'copy', '--out', str(target))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['destination'] == str(target.resolve())
    assert not root.exists()
    assert call('examples', 'copy', '--out', str(target)).returncode == 2
    for scenario in ('ceramic', 'kite'):
        created = call('new', '--title', scenario)
        assert created.returncode == 0
        session = json.loads(created.stdout)
        result = call('event', session['id'], '--revision', str(session['revision']), '--action', 'direct_image', '--payload-file', str(target / (scenario + '-image.json')))
        assert result.returncode == 0, result.stderr
        current = json.loads(call('show', session['id']).stdout)
        reference_event = tmp_path / (scenario + '-reference-event.json')
        with reference_event.open('x') as stream:
            json.dump({'path': str(target / (scenario + '-reference.png')), 'label': 'Programmatic generic ' + scenario + ' reference', 'role': 'Colour and geometry only', 'source_kind': 'supplied_reference'}, stream)
        result = call('event', session['id'], '--revision', str(current['revision']), '--action', 'register_reference', '--payload-file', str(reference_event))
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['references'][-1]['label'].startswith('Programmatic generic')
        exported = call('export', session['id'], '--target', 'image', '--version', '1')
        assert exported.returncode == 0 and json.loads(exported.stdout)['target'] == 'image'


def test_public_docs_and_licence_contract():
    for name in ('README.md', 'docs/quickstart.md', 'docs/privacy.md', 'docs/lifecycle.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md'):
        assert (SOURCE_ROOT / name).is_file(), name
    assert 'Copyright (c) 2026 PUSHINGSQUARES' in (SOURCE_ROOT / 'LICENSE').read_text()
    quickstart = (SOURCE_ROOT / 'docs/quickstart.md').read_text()
    for value in ('0.1.0rc1', 'examples copy --out', 'SESSION_ID', '--revision 0', '--port 8766', 'Ctrl+C', 'Windows', 'macOS', 'Linux'):
        assert value in quickstart, value


def test_resource_inventory_refuses_unknown_or_malformed(tmp_path, monkeypatch):
    import pytest
    from vybe_check import resource_copy
    package = tmp_path / 'package'
    examples = package / 'examples'
    examples.mkdir(parents=True)
    for name in resource_copy.EXAMPLE_FILES:
        original = files('vybe_check').joinpath('examples', name)
        (examples / name).write_bytes(original.read_bytes())
    monkeypatch.setattr(resource_copy, 'files', lambda name: package)
    (examples / 'unknown.json').write_text('{}')
    with pytest.raises(ValueError, match='inventory'):
        resource_copy.copy_examples(tmp_path / 'unknown-output')
    assert not (tmp_path / 'unknown-output').exists()
    # Retain the unknown inventory and use a separate malformed inventory.
    other = tmp_path / 'other'; (other / 'examples').mkdir(parents=True)
    for name in resource_copy.EXAMPLE_FILES:
        (other / 'examples' / name).write_bytes(files('vybe_check').joinpath('examples', name).read_bytes())
    (other / 'examples' / 'ceramic-image.json').write_text('[]')
    monkeypatch.setattr(resource_copy, 'files', lambda name: other)
    with pytest.raises(ValueError, match='Malformed'):
        resource_copy.copy_examples(tmp_path / 'malformed-output')
    assert not (tmp_path / 'malformed-output').exists()


def _final_package_input(name):
    import os
    import pytest
    value = os.environ.get(name)
    if not value:
        if os.environ.get('VYBE_AUTHORING_ONLY') == '1':
            pytest.skip('PENDING final frozen distributions and clean installed verification; authoring only')
        pytest.fail('Final package input required: ' + name)
    path = Path(value).resolve()
    assert path.is_file()
    assert not path.is_relative_to(SOURCE_ROOT), 'Final artifacts must be outside source'
    return path


def test_paid_generation_excluded():
    import tarfile, zipfile
    from vybe_check.cli import _parser
    wheel = _final_package_input('VYBE_PACKAGE_WHEEL')
    sdist = _final_package_input('VYBE_PACKAGE_SDIST')
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    with tarfile.open(sdist) as archive:
        names += archive.getnames()
    banned = {'generation.py', 'requests.py', 'provider_cli.py', 'models.py', 'creative.py', 'jev.py', 'secure_store.py'}
    assert not any(Path(n).name in banned for n in names)
    assert not any(part in {'private', 'evidence', '.git', '.venv', '__pycache__'} or part.startswith('._') for n in names for part in Path(n).parts)
    choices = next(a.choices for a in _parser()._actions if a.dest == 'command')
    assert not {'submit', 'collect', 'spend', 'provider', 'generate'} & set(choices)


def test_sdist_install(tmp_path):
    import os, subprocess, sys, venv, json
    sdist = _final_package_input('VYBE_PACKAGE_SDIST')
    # Explicit later verification only: real package-manager work, never editable.
    clean = tmp_path / 'clean'; clean.mkdir()
    home = clean / 'home'; home.mkdir()
    env = {'PATH': os.environ.get('PATH', ''), 'PYTHONDONTWRITEBYTECODE': '1'}
    for key in ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'XDG_DATA_HOME', 'VYBE_CHECK_ROOT', 'TMPDIR'):
        directory = clean / key.lower(); directory.mkdir(exist_ok=True); env[key] = str(directory)
    assert 'PYTHONPATH' not in env
    virtual = clean / 'venv'; venv.EnvBuilder(with_pip=True).create(virtual)
    interpreter = virtual / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    wheels = clean / 'wheels'; wheels.mkdir()
    def run(argv):
        result = subprocess.run([str(interpreter), '-B', *argv], cwd=clean, env=env, capture_output=True, text=True, timeout=300)
        print(json.dumps({'argv': argv, 'exit': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}))
        assert result.returncode == 0, result.stderr
        return result
    run(['-m', 'pip', 'wheel', '--no-deps', '--wheel-dir', str(wheels), str(sdist)])
    built = list(wheels.glob('vybe_check-*.whl')); assert len(built) == 1
    run(['-m', 'pip', 'install', str(built[0])])
    origin = run(['-c', 'import json,vybe_check; print(json.dumps(vybe_check.__file__))'])
    assert Path(json.loads(origin.stdout)).resolve().is_relative_to(virtual.resolve())
    run(['-m', 'vybe_check', '--root', str(clean / 'state'), '--help'])
    run(['-m', 'vybe_check', '--root', str(clean / 'state'), 'examples', 'copy', '--out', str(clean / 'examples')])


def test_partial_resource_copy_retains_written_bytes(tmp_path, monkeypatch):
    import pytest
    from vybe_check.resource_copy import copy_examples
    original = Path.open
    target = tmp_path / 'partial'
    def fail_second(path, *args, **kwargs):
        if path == target / 'kite-image.json' and args and args[0] == 'xb':
            raise OSError('Invented write refusal')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', fail_second)
    with pytest.raises(ValueError, match='retained partial'):
        copy_examples(target)
    assert (target / 'ceramic-image.json').read_bytes() == files('vybe_check').joinpath('examples/ceramic-image.json').read_bytes()
    assert not (target / 'kite-image.json').exists()
