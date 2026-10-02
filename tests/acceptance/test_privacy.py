import pytest


def test_raw_path_exclusion(tmp_path):
    import json
    from tools.acceptance_runtime import registered, board, http
    from vybe_check.export import agreed_export
    store, state, picture = registered(tmp_path)
    canary = str(picture).encode()
    with board(store, state) as (_, origin):
        code, body, _ = http(origin, '/api/session?id=' + state['id'])
        assert code == 200 and canary not in body
    assert canary not in json.dumps(agreed_export(state)).encode()


def test_secret_exclusion(tmp_path, monkeypatch, capsys):
    from test_native_store import test_secret_canary_absent_from_cli_state_http_export_and_child_arguments
    test_secret_canary_absent_from_cli_state_http_export_and_child_arguments(tmp_path, monkeypatch, capsys)
from vybe_check.workshop import _clean

@pytest.mark.parametrize('canary',[r'C:\Example\sample.png',r'\\example-server\pictures\sample.png','file:///example/sample.png','/example/images/sample.png','sk-inventedcanary123456789','token=InventedCanary123456'])
def test_nested_canaries(canary):
    result=_clean({'settings':{canary:[canary]},'prompt':'Ceramic bowl'})
    assert canary not in repr(result)
    assert result['prompt']=='Ceramic bowl'

def test_creative_prose_positive_controls():
    prose='A potter named Rowan holds a red/blue bowl at f/2.8. https://example.org/look'
    assert _clean(prose)==prose

@pytest.mark.parametrize('path',[r'C:\Example\folder',r'\\example-server\folder','file:///example/folder','/example/folder/'])
def test_ambiguous_directory_refusal(path):
    with pytest.raises(ValueError): _clean(path)


@pytest.mark.parametrize('text', [
    'é' * 32768,
    '景' * 32768,
    'é' * 32768 + ' red/blue at f/2.8',
    '景' * 32768 + '.png / Colour study',
    '/' + 'é' * 32768 + '.png',
], ids=['Accented', 'CJK', 'Slash prose', 'Suffix before slash', 'Single slash'])
def test_long_unicode_is_preserved_within_bounded_child(tmp_path, text):
    import hashlib
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    from vybe_check import privacy

    source = Path(privacy.__file__).resolve().parents[1]
    home = tmp_path / 'home'
    home.mkdir()
    payload = tmp_path / 'input.json'
    payload.write_text(json.dumps(text), encoding='utf-8')
    env = {**os.environ, 'PYTHONPATH': str(source),
           'PYTHONDONTWRITEBYTECODE': '1',
           'VYBE_CHECK_ROOT': str(tmp_path / 'state'),
           **{key: str(home) for key in
              ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'XDG_DATA_HOME')}}
    code = """import hashlib, json, pathlib, sys
from vybe_check import privacy
assert pathlib.Path(privacy.__file__).resolve().parent.parent == pathlib.Path(sys.argv[2])
text = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
result = privacy.clean(text)
print(hashlib.sha256(result.encode('utf-8')).hexdigest())
"""
    result = subprocess.run([sys.executable, '-B', '-c', code, str(payload), str(source)],
                            env=env, capture_output=True, text=True, timeout=2)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == hashlib.sha256(text.encode('utf-8')).hexdigest()


def test_unicode_save_keeps_text_and_refusals_keep_revision(tmp_path):
    from vybe_check.workshop import MAX_STATE_BYTES, SessionStore

    text = 'é景' * 16384 + ' red/blue at f/2.8'
    store = SessionStore(tmp_path / 'state')
    session = store.create(text)
    assert session['title'] == text
    session = store.apply(session['id'], 0, 'direct_image', {
        'brief': {'outcome': 'Ceramic portrait', 'subject_action': 'Potter holds a bowl',
                  'visual_priority': 'Hands', 'frame': 'Close portrait', 'light': 'Window light'},
        'prompt': text,
    })
    assert session['image_versions'][0]['prompt'] == text
    assert session['revision'] == 1
    path = store._session_path(session['id'])
    before = path.read_bytes()
    for prompt, error in [('/example/folder/', 'ambiguous local path'),
                          ('景' * MAX_STATE_BYTES, 'Local file too large')]:
        with pytest.raises(ValueError, match=error):
            store.apply(session['id'], 1, 'add_image_version', {'prompt': prompt})
        assert path.read_bytes() == before
        assert store.read(session['id'])['revision'] == 1
    with pytest.raises(ValueError, match='revision'):
        store.apply(session['id'], 0, 'add_image_version', {'prompt': text})
    assert path.read_bytes() == before


@pytest.mark.parametrize('text, expected', [
    ('éé/x.PNG', True),
    ('/a:é/x.png', False),
    ('/a:éé/x.png', True),
    ('/a:İıſK/x.png', False),
    ('e\u0301/x.png', True),
    ('a/x.pngé', False),
    ('a/x.png\u0301', True),
    ('a/x.png_', False),
    ('a/x.png!', True),
    ('a//x.png', False),
    ('a/b/x.JpEg', True),
    ('a/.png', False),
    ('https://example.org/look', False),
    ('red/blue at f/2.8', False),
])
def test_relative_file_detection_keeps_boundaries(text, expected):
    from vybe_check.privacy import _has_relative_file_path
    assert _has_relative_file_path(text) is expected


@pytest.mark.parametrize('text', ['é' * 32768 + '/x.PNG', '景' * 32768 + '/x.md'])
def test_long_unicode_relative_file_is_refused(text):
    with pytest.raises(ValueError, match='ambiguous local path'):
        _clean(text)
