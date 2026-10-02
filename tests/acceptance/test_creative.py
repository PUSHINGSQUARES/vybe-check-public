import pytest
from vybe_check.workshop import SessionStore


def test_provenance(tmp_path):
    from tools.acceptance_runtime import session, image
    store, state = session(tmp_path)
    path = image(tmp_path)
    state = store.apply(state['id'], state['revision'], 'record_preview', {'path':str(path), 'prompt_version':1, 'model':'Transport control only', 'workflow':'Synthetic transport'})
    state = store.apply(state['id'], state['revision'], 'promote_preview', {'preview_id':state['previews'][0]['id']})
    reopened = store.read(state['id'])
    assert {p['kind'] for p in reopened['image_versions'][0]['provenance']} == {'supplied','inferred','proposed'}
    assert reopened['previews'][0]['provenance'] == 'generated'
    assert reopened['previews'][0]['id'] in str(reopened['visual_locks'])

def test_lock_conflict(tmp_path):
    store = SessionStore(tmp_path / 'state')
    s = store.create()
    s = store.apply(s['id'], 0, 'propose_brief', {
        'brief': {'outcome': 'Ceramic portrait', 'subject_action': 'Potter holds a bowl', 'visual_priority': 'Hands'},
        'open_choices': ['Front light or silhouette'],
    })
    with pytest.raises(ValueError, match='unresolved'):
        store.apply(s['id'], s['revision'], 'agree_brief', {})

import copy
import hashlib
import json
import os
import subprocess
import sys
import portalocker

BRIEF = {'outcome': 'Ceramic portrait', 'subject_action': 'Potter holds a bowl', 'visual_priority': 'Hands', 'frame': 'Close portrait', 'light': 'Window light'}
SETTINGS = {'aspect_ratio': '3:4', 'resolution': '1080p', 'seed': 42}

def direct(store, **extra):
    s = store.create()
    return store.apply(s['id'], 0, 'direct_image', {'brief': BRIEF, 'prompt': 'Potter and bowl', 'locks': ['Blue glaze'], 'settings': SETTINGS, 'provenance': [{'text': 'Bowl', 'kind': 'supplied', 'source': 'Conversation'}], **extra})

def event(store, s, action, payload):
    return store.apply(s['id'], s['revision'], action, payload)

@pytest.mark.parametrize('payload', [{'unknown': 1}, {'settings': {'seed': True}}, {'settings': {'aspect_ratio': '0:4'}}, {'settings': {'aspect_ratio': '1000:1'}}, {'settings': {'style_strength': float('nan')}}, {'provenance': [{'text': 'Bowl', 'kind': 'supplied', 'extra': 1}]}, {'locks': 'Blue'}, {'shots': [{'id': 'one', 'title': 'One', 'prompt': 'Clay', 'unexpected': 1}]}])
def test_invalid_payload_before_lock_and_nonmutation(tmp_path, payload):
    store=SessionStore(tmp_path/'state'); s=direct(store)
    before=store._session_path(s['id']).read_bytes()
    with portalocker.Lock(str(store.root/'.write.lock'), mode='a', timeout=1):
        with pytest.raises(ValueError):
            event(store,s,'direct_image',payload)
    assert store._session_path(s['id']).read_bytes()==before

def test_explicit_resolution_then_agreement(tmp_path):
    store=SessionStore(tmp_path/'state'); s=store.create()
    s=event(store,s,'propose_brief',{'brief': BRIEF,'open_choices':['Light direction'],'locks':['Blue glaze']})
    s=event(store,s,'resolve_choices',{'resolution':'Use window light','locks':['Blue glaze','Window light']})
    assert s['provenance'][-1]['kind']=='supplied'
    s=event(store,s,'agree_brief',{})
    assert s['brief_status']=='agreed' and not s['open_choices']

def test_draft_guard(tmp_path):
    store=SessionStore(tmp_path/'state'); s=store.create()
    s=event(store,s,'draft_edit',{'text':'Window light'})
    before=store.read(s['id'])
    with pytest.raises(ValueError,match='agreed'):
        event(store,s,'accept_draft',{'draft_id':s['drafts'][0]['id']})
    assert store.read(s['id'])==before

def test_old_draft_retains_base_settings_and_provenance(tmp_path):
    store=SessionStore(tmp_path/'state'); s=direct(store)
    first=copy.deepcopy(s['image_versions'][0])
    s=event(store,s,'draft_edit',{'text':'Potter lifts the bowl'})
    draft=s['drafts'][0]
    s=event(store,s,'add_image_version',{'prompt':'Potter turns','settings':{'seed':99}})
    s=event(store,s,'accept_draft',{'draft_id':draft['id']})
    assert s['image_versions'][0]==first
    new=s['image_versions'][-1]
    assert new['source_image_version']==1 and new['settings']==SETTINGS
    assert new['provenance']==first['provenance']

def test_series_ids_and_shot_settings_survive_old_draft(tmp_path):
    store=SessionStore(tmp_path/'state')
    s=direct(store,shots=[{'id':'wide','title':'Wide','prompt':'Potter','settings':{'seed':7}}, {'id':'hands','title':'Hands','prompt':'Bowl'}])
    first=copy.deepcopy(s['image_versions'][0])
    s=event(store,s,'draft_edit',{'text':'Close hands','shot_id':'hands'})
    s=event(store,s,'add_image_version',{'shot_id':'wide','prompt':'Wide window','settings':{'seed':9}})
    s=event(store,s,'accept_draft',{'draft_id':s['drafts'][0]['id']})
    assert s['image_versions'][0]==first
    assert [x['id'] for x in s['image_versions'][-1]['shots']]==['wide','hands']
    assert s['image_versions'][-1]['shots'][0]==first['shots'][0]
    assert s['image_versions'][-1]['shots'][1]['settings']==SETTINGS

def test_preview_exact_source_and_generated_promotion(tmp_path):
    store=SessionStore(tmp_path/'state'); s=direct(store)
    picture=tmp_path/'study.png';picture.write_bytes(b'Invented image')
    payload={'path':str(picture),'prompt_version':1,'model':'Local checkpoint','workflow':'Core workflow'}
    before=store._registry_path(s['id']).read_bytes()
    for bad in [{'prompt_version':True},{'prompt_version':99},{'shot_id':'missing'}]:
        with pytest.raises(ValueError): event(store,s,'record_preview',{**payload,**bad})
        assert store._registry_path(s['id']).read_bytes()==before
    s=event(store,s,'record_preview',payload)
    s=event(store,s,'add_image_version',{'prompt':'New direction'})
    s=event(store,s,'promote_preview',{'preview_id':s['previews'][0]['id']})
    assert s['previews'][0]['provenance']=='generated' and s['previews'][0]['prompt_version']==1

def test_cli_source_flow(tmp_path):
    root=tmp_path/'state';home=tmp_path/'home';home.mkdir()
    env={**os.environ,**{k:str(home) for k in ('HOME','USERPROFILE','LOCALAPPDATA','XDG_DATA_HOME')},'VYBE_CHECK_ROOT':str(root),'PYTHONDONTWRITEBYTECODE':'1'}
    def run(*args):
        result=subprocess.run([sys.executable,'-m','vybe_check','--root',str(root),*args],env=env,text=True,capture_output=True,timeout=10)
        assert result.returncode==0,result.stderr
        return json.loads(result.stdout)
    def send(s,action,payload):
        file=tmp_path/'event.json';file.write_text(json.dumps(payload))
        return run('event',s['id'],'--revision',str(s['revision']),'--action',action,'--payload-file',str(file))
    s=run('new')
    s=send(s,'propose_brief',{'brief':BRIEF,'open_choices':['Light']})
    s=send(s,'resolve_choices',{'resolution':'Window light'})
    s=send(s,'agree_brief',{})
    s=send(s,'add_image_version',{'prompt':'Potter','settings':SETTINGS})
    first=copy.deepcopy(s['image_versions'][0])
    assert run('show',s['id'])['image_versions'][0]['settings']==SETTINGS
    assert run('export',s['id'])['settings']==SETTINGS
    s=send(s,'draft_edit',{'text':'Potter lifts bowl'})
    s=send(s,'accept_draft',{'draft_id':s['drafts'][0]['id']})
    assert s['image_versions'][0]==first and s['image_versions'][-1]['settings']==SETTINGS

@pytest.mark.parametrize('action,payload',[('draft_edit',{'target':[],'text':'Clay'}),('draft_edit',{'target':{},'text':'Clay'}),('propose_brief',{'brief':BRIEF,'provenance':[{'kind':[],'text':'Clay'}]}),('register_reference',{'path':'invented.png','label':'Clay','role':'Texture','source_kind':[]}),('register_reference',{'path':'invented.png','label':'Clay','role':'Texture','source_kind':{}})])
def test_structured_types_refuse_safely(tmp_path,action,payload):
    store=SessionStore(tmp_path/'state');s=store.create();before=store.read(s['id'])
    with pytest.raises(ValueError):event(store,s,action,payload)
    assert store.read(s['id'])==before

def test_stale_revision_and_advice_unavailable_are_nonmutating(tmp_path):
    store=SessionStore(tmp_path/'state');s=direct(store);before=store.read(s['id'])
    with pytest.raises(ValueError,match='revision'):
        store.apply(s['id'],0,'add_image_version',{'prompt':'New clay'})
    with pytest.raises(ValueError,match='Advice validation is unavailable'):
        event(store,s,'record_advice',{'source_image_version':1,'route':'local','model':'Example','payload_sha256':'a'*64,'questions':['Fit?'],'answers':['Uncertain']})
    assert store.read(s['id'])==before

def test_gathering_draft_allowed_but_unknown_shot_refused(tmp_path):
    store=SessionStore(tmp_path/'state');s=store.create()
    before=store.read(s['id'])
    with pytest.raises(ValueError,match='shot'):
        event(store,s,'draft_edit',{'text':'Clay','shot_id':'missing'})
    assert store.read(s['id'])==before
    s=event(store,s,'draft_edit',{'text':'Draft','target':'image'})
    assert s['revision']==1 and s['drafts'][0]['base_version'] is None

@pytest.mark.parametrize('action,payload',[('resolve_choices',{}),('draft_edit',{}),('select_image_version',{}),('record_preview',{'path':'example.png','prompt_version':1}),('register_reference',{'path':'example.png'}),('add_video_version',{'mode':'preserve'}),('add_image_version',{'prompt':'Clay','settings':{'style_strength':2**4000}})])
def test_required_fields_and_extreme_strength_before_lock(tmp_path,action,payload):
    store=SessionStore(tmp_path/'state');s=direct(store);before=store.read(s['id'])
    with portalocker.Lock(str(store.root/'.write.lock'),mode='a',timeout=1):
        with pytest.raises(ValueError):event(store,s,action,payload)
    assert store.read(s['id'])==before

@pytest.mark.parametrize('action',['add_image_version','direct_image'])
def test_image_prompt_required_before_lock(tmp_path,action):
    store=SessionStore(tmp_path/'state');s=direct(store)
    with portalocker.Lock(str(store.root/'.write.lock'),mode='a',timeout=1):
        with pytest.raises(ValueError):event(store,s,action,{'brief':BRIEF} if action=='direct_image' else {})


def test_reagreed_locks_apply_to_new_images_but_old_drafts_keep_base(tmp_path):
    store=SessionStore(tmp_path/'state');s=direct(store)
    first=json.dumps(s['image_versions'][0],sort_keys=True)
    s=event(store,s,'draft_edit',{'text':'Old blue bowl refinement'})
    draft_id=s['drafts'][0]['id']
    s=event(store,s,'propose_brief',{'brief':BRIEF,'open_choices':['Blue or red']})
    s=event(store,s,'resolve_choices',{'resolution':'Replace blue with red','locks':['Red glaze']})
    s=event(store,s,'agree_brief',{})
    s=event(store,s,'add_image_version',{'prompt':'A red bowl'})
    new=s['image_versions'][-1]
    assert new['locks']==['Red glaze']
    assert 'Red glaze' in new['prompt'] and 'Blue glaze' not in new['prompt']
    second=json.dumps(new,sort_keys=True)
    s=event(store,s,'accept_draft',{'draft_id':draft_id})
    accepted=s['image_versions'][-1]
    assert accepted['locks']==['Blue glaze']
    assert 'Blue glaze' in accepted['prompt'] and 'Red glaze' not in accepted['prompt']
    assert accepted['source_image_version']==1
    assert json.dumps(s['image_versions'][0],sort_keys=True)==first
    assert json.dumps(s['image_versions'][1],sort_keys=True)==second


def test_old_draft_locks_survive_explicit_reagreement(tmp_path):
    store=SessionStore(tmp_path/'state');s=direct(store)
    first=copy.deepcopy(s['image_versions'][0])
    s=event(store,s,'draft_edit',{'text':'Old blue bowl refinement'})
    draft_id=s['drafts'][0]['id']
    s=event(store,s,'propose_brief',{'brief':BRIEF,'open_choices':['Blue or red']})
    s=event(store,s,'resolve_choices',{'resolution':'Replace blue with red','locks':['Red glaze']})
    s=event(store,s,'agree_brief',{})
    s=event(store,s,'accept_draft',{'draft_id':draft_id})
    assert s['image_versions'][-1]['locks']==['Blue glaze']
    assert s['image_versions'][-1]['settings']==first['settings']
    assert s['image_versions'][0]==first


def renew_red_agreement(store,s):
    s=event(store,s,'propose_brief',{'brief':BRIEF,'open_choices':['Blue or red'],'provenance':[{'text':'Red direction','kind':'proposed','source':'New conversation'}]})
    s=event(store,s,'resolve_choices',{'resolution':'Use red glaze instead of blue','locks':['Red glaze']})
    return event(store,s,'agree_brief',{})

def test_changed_locks_require_complete_series_without_mutation(tmp_path):
    store=SessionStore(tmp_path/'state')
    s=direct(store,shots=[{'id':'wide','title':'Wide','prompt':'Bowl on shelf'},{'id':'hands','title':'Hands','prompt':'Bowl in hands'}])
    first=copy.deepcopy(s['image_versions'][0]);s=renew_red_agreement(store,s)
    before=store._session_path(s['id']).read_bytes()
    with pytest.raises(ValueError,match='complete series'):
        event(store,s,'add_image_version',{'shot_id':'hands','prompt':'Hands holding red bowl'})
    assert store._session_path(s['id']).read_bytes()==before
    s=event(store,s,'add_image_version',{'shots':[{'id':'wide','title':'Wide','prompt':'Red bowl on shelf'},{'id':'hands','title':'Hands','prompt':'Red bowl in hands'}]})
    assert s['image_versions'][0]==first
    assert s['image_versions'][-1]['locks']==['Red glaze']
    assert all('Red glaze' in shot['prompt'] and 'Blue glaze' not in shot['prompt'] for shot in s['image_versions'][-1]['shots'])

@pytest.mark.parametrize('series',[False,True])
def test_reagreement_provenance_survives_new_image_and_video(tmp_path,series):
    store=SessionStore(tmp_path/'state')
    generated={'text':'Exploratory lighting','kind':'generated','source':'Local study'}
    s=direct(store,provenance=[generated])
    first=copy.deepcopy(s['image_versions'][0]);s=renew_red_agreement(store,s)
    resolution=s['provenance'][-1]
    supplied={'text':'Red bowl held close','kind':'supplied','source':'Refinement'}
    payload={'shots':[{'id':'wide','title':'Wide','prompt':'Red bowl'},{'id':'hands','title':'Hands','prompt':'Hands on red bowl'}]} if series else {'prompt':'Red bowl'}
    s=event(store,s,'add_image_version',{**payload,'provenance':[supplied,resolution] if series else [supplied]})
    lineage=s['image_versions'][-1]['provenance']
    assert resolution in lineage
    assert s['provenance'][0] in lineage
    assert resolution in lineage and lineage.count(resolution)==1
    assert generated in lineage and supplied in lineage
    assert s['image_versions'][0]==first
    s=event(store,s,'add_video_version',{'mode':'preserve','motion':'Lift bowl','camera':'Slow push'})
    assert all(item in s['video_versions'][-1]['provenance'] for item in lineage)


def test_old_series_draft_keeps_named_base_lineage_after_new_agreement(tmp_path):
    store=SessionStore(tmp_path/'state')
    s=direct(store,shots=[{'id':'wide','title':'Wide','prompt':'Bowl on shelf'},{'id':'hands','title':'Hands','prompt':'Bowl in hands'}])
    first=copy.deepcopy(s['image_versions'][0])
    s=event(store,s,'draft_edit',{'target':'image','shot_id':'hands','text':'Closer bowl in hands'})
    draft_id=s['drafts'][0]['id'];s=renew_red_agreement(store,s)
    s=event(store,s,'accept_draft',{'draft_id':draft_id})
    accepted=s['image_versions'][-1]
    assert accepted['locks']==first['locks'] and accepted['provenance']==first['provenance']
    assert accepted['shots'][0]==first['shots'][0]
    assert accepted['source_image_version']==1
    assert s['image_versions'][0]==first
