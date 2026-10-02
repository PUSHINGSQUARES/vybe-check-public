import json
import pytest


def test_reference_exclusion(tmp_path):
    import json
    from tools.acceptance_runtime import registered
    from vybe_check.export import agreed_export
    store, state, picture = registered(tmp_path)
    exported = agreed_export(store.read(state['id']))
    raw = json.dumps(exported).encode()
    assert exported['prompt'] == state['image_versions'][0]['prompt']
    assert str(picture).encode() not in raw and picture.read_bytes() not in raw
    assert 'references' not in exported and 'identity_pack' not in exported
from vybe_check.workshop import SessionStore
from vybe_check.export import agreed_export
from vybe_check.cli import main
from test_creative import direct,event

def test_allowlist_selected_version_and_exclusive_output(tmp_path,capsys):
    store=SessionStore(tmp_path/'state');s=direct(store)
    s=event(store,s,'add_image_version',{'prompt':'New image'})
    s['references']=[{'label':'Private reference','contents':'Never export'}]
    result=agreed_export(s,version=1)
    assert set(result)=={'schema_version','target','version','prompt','shots','settings','locks','source_image_version'}
    assert result['version']==1 and result['settings']['seed']==42
    output=tmp_path/'export.json'
    assert main(['--root',str(store.root),'export',s['id'],'--version','1','--out',str(output)])==0
    assert json.loads(output.read_text())==result
    before=output.read_bytes()
    assert main(['--root',str(store.root),'export',s['id'],'--out',str(output)])==2
    assert output.read_bytes()==before

def test_export_refusals_and_nested_cleaning(tmp_path):
    store=SessionStore(tmp_path/'state');s=store.create()
    with pytest.raises(ValueError):agreed_export(s)
    s=direct(store)
    for kwargs in [{'target':'asset'},{'version':99},{'version':True},{'version':0}]:
        with pytest.raises(ValueError):agreed_export(s,**kwargs)
    s['image_versions'][0]['settings']['model']='token=InventedCanary123456'
    assert 'InventedCanary' not in json.dumps(agreed_export(s))

def test_video_export_retains_mode_duration_anchor_and_sound(tmp_path):
    store=SessionStore(tmp_path/'state');s=direct(store)
    s=event(store,s,'add_video_version',{'mode':'evolve','duration':15,'motion':'Lift bowl','camera':'Slow push','settings':{'sound':'Requested room tone'}})
    output=agreed_export(s,'video',1)
    assert output['mode']=='evolve' and output['duration']==15
    assert output['source_image_version']==1 and output['locks']==['Blue glaze']
    assert output['settings']['sound']=='Requested room tone'
    assert set(output)=={'schema_version','target','version','prompt','shots','settings','locks','source_image_version','mode','duration'}
