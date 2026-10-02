import copy
import pytest


def _timed_video_probe(tmp_path, mode):
    from tools.acceptance_runtime import session
    store, state = session(tmp_path)
    image = state['image_versions'][0]
    state = store.apply(state['id'], state['revision'], 'add_video_version', {'mode':mode, 'duration':15, 'motion':'Turn bowl slowly', 'camera':'Locked camera'})
    video = store.read(state['id'])['video_versions'][-1]
    assert video['mode'] == mode and video['duration'] == 15
    assert video['source_image_version'] == image['version']
    assert 'Blue glaze' in video['prompt']
    if mode == 'preserve':
        assert 'Single continuous shot, 0 to 15s' in video['prompt']
    else:
        intervals = ['0 to 5s','5 to 10s','10 to 15s']
        assert all(interval in video['prompt'] for interval in intervals)
        assert [video['prompt'].index(interval) for interval in intervals] == sorted(video['prompt'].index(interval) for interval in intervals)
    assert video['locks'] == image['locks']


def test_preserve_mode(tmp_path):
    _timed_video_probe(tmp_path, 'preserve')


def test_evolve_mode(tmp_path):
    _timed_video_probe(tmp_path, 'evolve')


def test_multishot_mode(tmp_path):
    _timed_video_probe(tmp_path, 'multishot')
from vybe_check.workshop import SessionStore
from test_creative import direct,event

@pytest.mark.parametrize('mode',['preserve','evolve','multishot'])
def test_video_modes_anchor_and_settings(tmp_path,mode):
    store=SessionStore(tmp_path/'state');s=direct(store)
    s['locks']=['Changed session lock'];store._write(store._session_path(s['id']),s)
    s=event(store,s,'add_video_version',{'mode':mode,'duration':15,'motion':'Lift the bowl','camera':'Slow push','prompt':'Hold the final gaze','settings':{'sound':'Room tone','fps':24}})
    video=s['video_versions'][0]
    assert video['locks']==['Blue glaze'] and video['source_image_version']==1
    assert video['settings']['sound']=='Room tone' and video['settings']['seed']==42
    assert video['provenance'][0]['kind']=='supplied' and video['provenance'][-1]['kind']=='proposed'
    assert '0 to 15s' in video['prompt'] if mode=='preserve' else all(x in video['prompt'] for x in ['0 to 5s','5 to 10s','10 to 15s'])
    assert 'Additional creative direction: Hold the final gaze' in video['prompt']

@pytest.mark.parametrize('bad',[{'mode':'unknown'},{'duration':True},{'duration':1.5},{'duration':61},{'duration':0},{'mode':'evolve','duration':2},{'settings':{'fps':True}}])
def test_video_validation_custom_prose(tmp_path,bad):
    store=SessionStore(tmp_path/'state');s=direct(store);before=store.read(s['id'])
    with pytest.raises(ValueError):
        event(store,s,'add_video_version',{'mode':'preserve','duration':15,'motion':'Lift','camera':'Push','prompt':'Custom prose',**bad})
    assert store.read(s['id'])==before

def test_video_old_draft_lineage(tmp_path):
    store=SessionStore(tmp_path/'state');s=direct(store)
    payload={'mode':'preserve','motion':'Lift','camera':'Push'}
    s=event(store,s,'add_video_version',payload);first=copy.deepcopy(s['video_versions'][0])
    s=event(store,s,'draft_edit',{'target':'video','text':'Revised prose'})
    s=event(store,s,'add_video_version',{**payload,'mode':'evolve'})
    s=event(store,s,'accept_draft',{'draft_id':s['drafts'][0]['id']})
    assert s['video_versions'][0]==first
    assert s['video_versions'][-1]['source_video_version']==1 and s['video_versions'][-1]['mode']=='preserve'

@pytest.mark.parametrize('bad',[{'mode':[]},{'mode':{}},{'mode':15},{'duration':2**80},{'settings':{'fps':121}},{'settings':{'style_strength':float('inf')}},{'settings':{'batch_size':17}}])
def test_structured_values_refuse_without_state_change(tmp_path,bad):
    store=SessionStore(tmp_path/'state');s=direct(store)
    before={p.name:p.read_bytes() for p in (store.root/'sessions').iterdir()}
    with pytest.raises(ValueError):
        event(store,s,'add_video_version',{'mode':'preserve','motion':'Lift','camera':'Push',**bad})
    assert {p.name:p.read_bytes() for p in (store.root/'sessions').iterdir()}==before


@pytest.mark.parametrize('mode,ending', [(mode, ending) for mode in ('preserve', 'evolve', 'multishot') for ending in ('wide', 'close')], ids=[mode + '-' + ending for mode in ('preserve', 'evolve', 'multishot') for ending in ('wide', 'close')])
def test_supplied_camera_plan_cli(tmp_path, mode, ending):
    import json, os, subprocess, sys
    from pathlib import Path
    from importlib.machinery import PathFinder
    source = Path(__file__).resolve().parents[2]
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
        assert env['PYTHONPATH'].split(os.pathsep)[0] == str(source / 'src')
        origins = {}
        for name in ('cli', 'workshop', 'credentials', 'local_preview', 'resource_copy'):
            spec = PathFinder.find_spec(name, [str(source / 'src/vybe_check')])
            assert spec and Path(spec.origin).is_relative_to(source / 'src/vybe_check')
            origins[name] = spec.origin
        with (child / 'requested-environment-and-origins.json').open('x') as stream:
            json.dump({'environment': env, 'origins': origins}, stream)
        result = subprocess.run([sys.executable, '-B', '-m', 'vybe_check', '--root', str(root), *args], cwd=child, env=env, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    destination = tmp_path / 'examples'
    call('examples', 'copy', '--out', str(destination))
    state = call('new', '--title', 'Kite camera control')
    state = call('event', state['id'], '--revision', str(state['revision']), '--action', 'direct_image', '--payload-file', str(destination / 'kite-image.json'))
    anchor = call('export', state['id'], '--target', 'image', '--version', '1')
    payload = json.loads((destination / ('kite-' + mode + '.json')).read_text())
    if ending == 'close':
        payload['camera'] = 'Wide establishing view, medium fabric view, and close closing view' if mode == 'multishot' else 'Settle into a close closing view'
    elif mode != 'multishot':
        payload['camera'] = 'Settle into a wide closing view'
    sound = 'Requested isolated wind track'
    payload['settings']['sound'] = sound
    payload_path = tmp_path / 'camera-payload.json'
    with payload_path.open('x') as stream: json.dump(payload, stream)
    state = call('event', state['id'], '--revision', str(state['revision']), '--action', 'add_video_version', '--payload-file', str(payload_path))
    exported = call('export', state['id'], '--target', 'video', '--version', '1')
    video = state['video_versions'][-1]
    assert exported['prompt'] == video['prompt']
    assert exported['mode'] == mode and exported['duration'] == 15 and exported['source_image_version'] == 1
    assert anchor['prompt'] in exported['prompt']
    assert exported['locks'] == anchor['locks']
    assert all(record in video['provenance'] for record in payload['provenance'])
    assert exported['prompt'].count(payload['camera']) == 1
    assert exported['settings']['sound'] == sound and sound not in exported['prompt']
    assert exported['settings']['fps'] == payload['settings']['fps']
    if mode == 'preserve':
        assert '0 to 15s' in exported['prompt']
    else:
        assert all(span in exported['prompt'] for span in ('0 to 5s', '5 to 10s', '10 to 15s'))
    if mode == 'multishot':
        assert 'resolve in a closer frame' not in exported['prompt']
        assert 'eyeline or gesture' not in exported['prompt']
        assert 'Cut on subject movement to shot 3' in exported['prompt']
        assert 'resolve the action consistently with the supplied camera plan' in exported['prompt']
