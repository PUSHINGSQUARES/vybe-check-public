"""Advice events preserve creative state and never establish provider acceptance."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess


def test_locked_store_baseline(tmp_path, monkeypatch):
    from tools.acceptance_runtime import environment, session
    if os.environ.get('VYBE_AUTHORING_ONLY') != '1':
        from tools.verify_host import native_unavailable_gate
        native_unavailable_gate()
    from vybe_check import credentials as c
    from vybe_check import judge as j
    environment(tmp_path,monkeypatch)
    monkeypatch.setattr(c,'native_backend',lambda:(_ for _ in ()).throw(c.StoreUnavailable()))
    with pytest.raises(c.StoreUnavailable): c.Credentials().read('typesafe')
    store,state = session(tmp_path)
    prior = state['image_versions'][0]
    state = store.apply(state['id'],state['revision'],'add_image_version',{'prompt':'A closer blue rim'})
    assert store.read(state['id'])['image_versions'][0] == prior
    assert len(state['image_versions']) == 2


def test_judge_failure_baseline(tmp_path, monkeypatch):
    from test_judge import test_failure_and_weak_signals_never_mutate_creative_state
    for index,kind in enumerate(('wrong-model','malformed-answer','key-error')):
        child=tmp_path/('case-'+str(index));child.mkdir()
        with monkeypatch.context() as patch:
            test_failure_and_weak_signals_never_mutate_creative_state(child,patch,kind)


def test_offline_core(tmp_path, monkeypatch):
    import socket
    from tools.acceptance_runtime import environment, session
    from vybe_check.export import agreed_export
    environment(tmp_path,monkeypatch)
    def forbidden(*a,**kw): pytest.fail('Offline core attempted network egress')
    monkeypatch.setattr(socket,'create_connection',forbidden)
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    store,state=session(tmp_path)
    state=store.apply(state['id'],state['revision'],'draft_edit',{'text':'A blue rim under soft light'})
    state=store.apply(state['id'],state['revision'],'accept_draft',{'draft_id':state['drafts'][-1]['id']})
    assert agreed_export(store.read(state['id']))['version'] == 2
    assert len(state['image_versions']) == 2 and state['video_versions'] == []
import sys
import pytest


def modules():
    assert importlib.util.find_spec('vybe_check.judge') is not None, 'Task 8 advice seam missing'
    from vybe_check import judge
    from vybe_check.workshop import SessionStore
    return judge, SessionStore


def session(tmp_path):
    j,Store=modules();store=Store(tmp_path/'state');s=store.create()
    s=store.apply(s['id'],0,'direct_image',{'brief':{'outcome':'Clay study','subject_action':'Hold bowl','visual_priority':'Hands','frame':'Close portrait','light':'Window light'},'prompt':'Clay','locks':['Blue glaze'],'settings':{'seed':42}})
    return j,store,s


def record():
    return {'source_image_version':1,'route':'typesafe','model':'jev-1.13.0','payload_sha256':'a'*64,
        'questions':{'pick':{'type':'choice','criteria':{'option_1':'Warm','option_2':'Cool'}}},
        'answers':{'pick':{'type':'choice','choice':'option_1','confidence':.9,'probabilities':{'option_1':.7,'option_2':.3},'prose':'Discard provider prose'}}}


def test_transport_free_advice_allowlist_and_creative_byte_identity(tmp_path,monkeypatch):
    j,store,s=session(tmp_path)
    from vybe_check import credentials
    monkeypatch.setattr(credentials,'Credentials',lambda:pytest.fail('Record accessed key'))
    monkeypatch.setattr(j,'send_once',lambda *a:pytest.fail('Record sent'))
    registry=store._registry_path(s['id']).read_bytes();before=copy.deepcopy(s)
    after=store.apply(s['id'],s['revision'],'record_advice',record())
    assert {k:v for k,v in after.items() if k not in ('revision','advice')}=={k:v for k,v in before.items() if k!='revision'}
    assert store._registry_path(s['id']).read_bytes()==registry
    assert set(after['advice'][0])=={'source_image_version','route','model','payload_sha256','answers','status'}
    assert 'prose' not in json.dumps(after) and 'questions' not in after['advice'][0]
    for key in ('image_versions','video_versions','locks','visual_locks'):
        assert hashlib.sha256(json.dumps(after[key],sort_keys=True).encode()).digest()==hashlib.sha256(json.dumps(before[key],sort_keys=True).encode()).digest()


@pytest.mark.parametrize('change',[{'source_image_version':True},{'source_image_version':99},{'route':'other'},{'model':'other'},
    {'payload_sha256':'a'*63},{'extra':'Hidden'},{'questions':{'other':{'type':'noul'}}},
    {'questions':{'pick':{'type':'choice','criteria':{'person':'Warm','option_2':'Cool'}}}},
    {'questions':{'relevance':{'type':'noul','instructions':'Persist this'},'contradiction':{'type':'noul'}}}])
def test_invalid_record_is_nonmutating(tmp_path,change):
    j,store,s=session(tmp_path);before=store._session_path(s['id']).read_bytes()
    with pytest.raises(ValueError):store.apply(s['id'],s['revision'],'record_advice',record()|change)
    assert store._session_path(s['id']).read_bytes()==before


def test_source_cli_quote_and_run_fail_closed_in_fresh_child(tmp_path):
    j,_=modules(); source=Path(j.__file__).resolve().parents[1];home=tmp_path/'home';home.mkdir()
    env={**os.environ,**{k:str(home) for k in ('HOME','USERPROFILE','LOCALAPPDATA','XDG_DATA_HOME')},'VYBE_CHECK_ROOT':str(tmp_path/'env-state'),'PYTHONPATH':str(source),'PYTHONDONTWRITEBYTECODE':'1'}
    anonymous={'constraints':['Blue glaze'],'options':{'option_1':'Warm','option_2':'Cool'},'purpose':'model','source_image_version':1}
    data=tmp_path/'anonymous.json'
    with data.open('x') as f:json.dump(anonymous,f)
    command=[sys.executable,'-B','-m','vybe_check','--root',str(tmp_path/'explicit-cli'),'judge','quote','--route','typesafe','--input-file',str(data)]
    child=subprocess.run(command,env=env,capture_output=True,text=True,timeout=10)
    assert child.returncode==0 and json.loads(child.stdout)['status']=='unavailable'
    assert json.loads(child.stdout)['reason']=='billing_unbounded'
    assert not (tmp_path/'explicit-cli').exists()
    approval=tmp_path/'approval.json';receipt=tmp_path/'receipt.json'
    for file in (approval,receipt):
        with file.open('x') as f:json.dump({},f)
    command=[sys.executable,'-B','-m','vybe_check','--root',str(tmp_path/'explicit-cli'),'judge','run','--route','typesafe','--input-file',str(data),'--receipt-file',str(receipt),'--approval-file',str(approval),'--session','a'*32,'--revision','0']
    child=subprocess.run(command,env=env,capture_output=True,text=True,timeout=10)
    assert child.returncode==2 and 'billing_unbounded' in child.stdout and not (tmp_path/'explicit-cli').exists()


def test_cli_quote_document_round_trip_with_synthetic_authority(tmp_path,monkeypatch,capsys):
    j,store,s=session(tmp_path)
    from decimal import Decimal
    from vybe_check.cli import main
    from vybe_check import credentials
    monkeypatch.setattr(j.time,'time',lambda:1893456000)
    monkeypatch.setattr(j,'_primary_bounds',lambda route:j.BillingBounds('https://example.invalid/synthetic','2030-01-01',1893542400,8192,256,Decimal('.042'),Decimal('0'),Decimal('.01')))
    class Keys:
        def read(self,route):assert route=='typesafe';return 'invented-test-key'
    monkeypatch.setattr(credentials,'Credentials',Keys)
    calls=[]
    def send(endpoint,key,body):
        calls.append(body)
        return {'model':'jev-1.13.0','answers':record()['answers']}
    monkeypatch.setattr(j,'send_once',send)
    data=tmp_path/'anonymous.json'
    with data.open('x') as f:json.dump({'constraints':['Blue glaze'],'options':{'option_1':'Warm','option_2':'Cool'},'purpose':'model','source_image_version':1},f)
    assert main(['--root',str(store.root),'judge','quote','--route','typesafe','--input-file',str(data)])==0
    document=json.loads(capsys.readouterr().out)
    assert document['status']=='quoted' and document['receipt']['model']=='jev-1.13.0'
    assert calls==[]
    receipt=tmp_path/'receipt.json'
    with receipt.open('x') as f:json.dump(document,f)
    approval=tmp_path/'approval.json'
    with approval.open('x') as f:json.dump(document['receipt']|{'approved':True,'max_usd':document['receipt']['total_upper_bound_usd']},f)
    assert main(['--root',str(store.root),'judge','run','--route','typesafe','--input-file',str(data),'--receipt-file',str(receipt),'--approval-file',str(approval),'--session',s['id'],'--revision',str(s['revision'])])==0
    assert json.loads(capsys.readouterr().out)['status']=='advisory'
    assert len(calls)==1 and calls[0].decode()==document['outbound_utf8']
