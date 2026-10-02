"""Source authoring evidence only; no real provider or native calls."""
import copy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import threading
import time
import pytest


def test_no_jev_baseline(tmp_path, monkeypatch, capsys):
    from test_native_store import test_default_create_refine_export_never_constructs_adapter
    j = judge()
    monkeypatch.setattr(j,'send_once',lambda *a:pytest.fail('Unrequested judge transport'))
    test_default_create_refine_export_never_constructs_adapter(tmp_path,monkeypatch,capsys)


def test_payload_minimization():
    test_exact_anonymous_request_and_fixed_questions()
    test_local_identity_deny_tokens_never_serialise()
    for value in ('identity-pack/notes','/example/reference.png','name@example.invalid','sk-'+'a'*24,'data:image/png;base64,abcd'):
        test_unsafe_input_refused_before_any_store_or_transport(value)


def test_consent_cost_gate(tmp_path, monkeypatch):
    for number, reason in enumerate(('real-pricing','missing-approval','low-ceiling','expired')):
        child = tmp_path/('case-'+str(number));child.mkdir()
        with monkeypatch.context() as patch:
            test_refusal_has_zero_key_and_transport_calls(child,patch,reason)


def test_numeric_validation():
    test_selected_maximum_ties_and_independent_confidence_positive_controls()
    for bad in (True,float('nan'),float('inf'),-.01,1.01):
        test_confidence_and_probabilities_are_finite_nonboolean(bad)
    for bad in ('unknown-label','extra-id','bad-type'):
        test_complete_choice_contract(bad)


def judge():
    assert importlib.util.find_spec('vybe_check.judge') is not None, 'Task 8 judge is not authored'
    from vybe_check import judge
    return judge


def anonymous(purpose='model'):
    return {'constraints': ['Soft light', 'Keep blue glaze'],
            'options': {'option_1': 'Warm light', 'option_2': 'Cool light'} if purpose == 'model' else {'option_1': 'Add rim light'},
            'purpose': purpose, 'source_image_version': 1}


def answer():
    return {'pick': {'type': 'choice', 'choice': 'option_1', 'confidence': .81,
                     'probabilities': {'option_1': .6, 'option_2': .4}}}


def questions():
    return {'pick': {'type': 'choice', 'criteria': {'option_1': 'Warm light', 'option_2': 'Cool light'}}}


def synthetic_bounds(monkeypatch, j):
    # This is an injected trusted test fixture, not operator-provided pricing.
    bounds = j.BillingBounds('https://example.invalid/synthetic-billing', '2030-01-01',
        1893542400, 8192, 256, Decimal('.042'), Decimal('0'), Decimal('.01'))
    monkeypatch.setattr(j, '_primary_bounds', lambda route: bounds)
    return bounds


def consent(receipt):
    return {name: copy.deepcopy(receipt[name]) for name in ('receipt_id', 'receipt_sha256', 'route', 'model',
        'payload_sha256', 'source_image_version', 'pricing_url', 'pricing_date', 'max_input_tokens',
        'max_output_tokens', 'input_usd_per_million', 'output_usd_per_million', 'request_fees_usd',
        'total_upper_bound_usd', 'expires_at', 'call_limit')} | {'approved': True, 'max_usd': receipt['total_upper_bound_usd']}


def local_session(tmp_path):
    from vybe_check.workshop import SessionStore
    store = SessionStore(tmp_path / 'explicit-state')
    s = store.create()
    s = store.apply(s['id'], 0, 'direct_image', {'brief': {'outcome': 'Clay study', 'subject_action': 'Hold bowl',
        'visual_priority': 'Hands', 'frame': 'Close portrait', 'light': 'Window light'},
        'prompt': 'Clay in hands', 'locks': ['Blue glaze'], 'settings': {'seed': 9}})
    return store, s


class Keys:
    def __init__(self, value='invented-test-value'): self.calls = []; self.value = value
    def read(self, route): self.calls.append(route); return self.value


def controlled_reply(request, route='typesafe'):
    return {'model': 'jev-1.13.0' if route == 'typesafe' else 'typesafe/jev-1.13-20260917',
        'answers': answer(), 'usage': {'input_tokens': 42, 'output_tokens': 12}, 'prose': 'Never persist provider prose'}


def test_exact_anonymous_request_and_fixed_questions():
    j = judge(); raw = anonymous(); prepared = j.prepare_request(raw, 'typesafe')
    wire = json.loads(prepared.body)
    assert wire == {'model': 'jev-1.13.0', 'state': json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(',', ':')),
        'questions': {'pick': {'type': 'choice', 'instructions': j.PICK_INSTRUCTIONS, 'criteria': raw['options']}}}
    assert prepared.body == json.dumps(wire, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    raw['options']['option_1'] = 'Changed after preparation'
    assert b'Changed after preparation' not in prepared.body
    addition = json.loads(j.prepare_request(anonymous('addition'), 'openrouter').body)
    assert addition['model'] == 'typesafe/jev-1.13'
    assert addition['questions'] == {'relevance': {'type': 'noul', 'instructions': j.RELEVANCE_INSTRUCTIONS},
        'contradiction': {'type': 'noul', 'instructions': j.CONTRADICTION_INSTRUCTIONS}}


@pytest.mark.parametrize('text', ['/Users/example/reference.png', 'C:\\private\\image.png', 'identity-pack/notes',
    'https://example.invalid/asset', 'data:image/png;base64,abcd', 'A'*100,
    'secret=synthetic-value', 'sk-'+'a'*24, '/image.png', 'folder/image.png', 'blob:invented', 'name@example.invalid'])
def test_unsafe_input_refused_before_any_store_or_transport(text):
    j = judge(); raw = anonymous(); raw['constraints'] = [text]
    with pytest.raises(ValueError, match='Anonymous decision input'):
        j.prepare_request(raw, 'typesafe')


@pytest.mark.parametrize('change', [{'title': 'Invented person'}, {'questions': {'arbitrary': {}}},
    {'constraints': [True]}, {'source_image_version': True}, {'purpose': 'other'}, {'options': {'Actual model': 'Fast'}}])
def test_extra_or_invalid_input_fields(change):
    with pytest.raises(ValueError): judge().prepare_request(anonymous() | change, 'typesafe')


def test_local_identity_deny_tokens_never_serialise():
    j = judge(); data = anonymous(); data['constraints'].append('Invented Person')
    with pytest.raises(ValueError): j.prepare_request(data, 'typesafe', deny_tokens=['Invented Person'])
    safe = j.prepare_request(anonymous(), 'typesafe', deny_tokens=['Invented Person'])
    assert b'Invented Person' not in safe.body and 'Invented Person' not in repr(safe)
    with pytest.raises(ValueError): j.prepare_request(anonymous(), 'typesafe', deny_tokens=[''])


def test_serialised_utf8_bound_is_on_complete_request():
    j = judge(); data = anonymous(); data['constraints'] = ['☀ ' * 100]
    assert len(j.prepare_request(data, 'typesafe').body) < 24576
    data['constraints'] = ['☀ ' * 7000]
    with pytest.raises(ValueError): j.prepare_request(data, 'typesafe')


@pytest.mark.parametrize('bad', [True, float('nan'), float('inf'), -.01, 1.01, None, '0.8', 2**4000])
def test_confidence_and_probabilities_are_finite_nonboolean(bad):
    j=judge(); a=answer(); a['pick']['confidence']=bad
    with pytest.raises(ValueError): j.validate_answers(a, questions())
    a=answer(); a['pick']['probabilities']['option_1']=bad
    with pytest.raises(ValueError): j.validate_answers(a, questions())
    with pytest.raises(ValueError): j.validate_answers({'relevance': {'type':'noul','noul':bad}}, {'relevance':{'type':'noul'}})


@pytest.mark.parametrize('alteration', ['missing-map','partial-map','extra-map','bad-sum','wrong-winner','unknown-label','missing-id','extra-id','bad-type'])
def test_complete_choice_contract(alteration):
    j=judge(); a=answer()
    if alteration=='missing-map': a['pick'].pop('probabilities')
    if alteration=='partial-map': a['pick']['probabilities'].pop('option_2')
    if alteration=='extra-map': a['pick']['probabilities']['other']=0
    if alteration=='bad-sum': a['pick']['probabilities']['option_2']=.3
    if alteration=='wrong-winner': a['pick']['choice']='option_2'
    if alteration=='unknown-label': a['pick']['choice']='other'
    if alteration=='missing-id': a={}
    if alteration=='extra-id': a['other']={'type':'noul','noul':.5}
    if alteration=='bad-type': a['pick']['type']='noul'
    with pytest.raises(ValueError): j.validate_answers(a,questions())


def test_selected_maximum_ties_and_independent_confidence_positive_controls():
    j=judge(); a=answer(); a['pick']['ignored-prose']='Never save'; clean=j.validate_answers(a,questions())
    assert clean==answer() and clean['pick']['confidence'] != clean['pick']['probabilities']['option_1']
    a['pick'].update(choice='option_2',probabilities={'option_1':.5,'option_2':.5})
    assert j.validate_answers(a,questions())['pick']['choice']=='option_2'
    assert j.validate_answers({'relevance':{'type':'noul','noul':.7}}, {'relevance':{'type':'noul'}})=={'relevance':{'type':'noul','noul':.7}}


@pytest.mark.parametrize('route,actual', [('typesafe','jev-1.13.0'),('openrouter','typesafe/jev-1.13-20260917')])
def test_exact_requested_actual_route_mapping(route,actual):
    j=judge(); p=j.prepare_request(anonymous(),route)
    assert j.validate_response({'model':actual,'answers':answer()},p)==answer()
    for bad in ['jev-1.13', 'typesafe/jev-1.13', 'jev-1.14.0', 'other', None, []]:
        with pytest.raises(ValueError): j.validate_response({'model':bad,'answers':answer()},p)


def test_real_quote_unavailable_without_billing_bounds(monkeypatch):
    j=judge()
    from vybe_check import credentials
    monkeypatch.setattr(credentials,'Credentials',lambda:pytest.fail('Quote accessed credentials'))
    monkeypatch.setattr(j,'send_once',lambda *a:pytest.fail('Quote sent'))
    for route in ('typesafe','openrouter'):
        assert j.quote(j.prepare_request(anonymous(),route)) == {'status':'unavailable','reason':'billing_unbounded'}


def test_synthetic_receipt_binds_exact_bytes_and_decimal_bound(monkeypatch):
    j=judge(); synthetic_bounds(monkeypatch,j); p=j.prepare_request(anonymous(),'typesafe'); q=j.quote(p,now=1893456000)
    assert q['total_upper_bound_usd']=='0.010344064'
    assert q['call_limit']==1 and q['source_image_version']==1 and q['model']=='jev-1.13.0'
    import hashlib
    assert q['payload_sha256']==hashlib.sha256(p.body).hexdigest()
    assert q['expires_at']==1893456300 and q['pricing_date']=='2030-01-01'
    assert 'constraints' not in q and 'options' not in q and 'state' not in q


@pytest.mark.parametrize('refusal', ['real-pricing','missing-approval','changed-body','changed-version','expired','low-ceiling','forged-total','mismatched-model','extra-approval','old-price','invalid-approval-type'])
def test_refusal_has_zero_key_and_transport_calls(tmp_path,monkeypatch,refusal):
    j=judge(); synthetic_bounds(monkeypatch,j); store,s=local_session(tmp_path);p=j.prepare_request(anonymous(),'typesafe')
    q=j.quote(p,now=1893456000);a=consent(q);now=1893456001;keys=Keys();calls=[];before=store._session_path(s['id']).read_bytes()
    if refusal=='real-pricing': monkeypatch.setattr(j,'_primary_bounds',lambda route:None)
    if refusal=='missing-approval': a=None
    if refusal=='changed-body': p=j.prepare_request(anonymous()|{'constraints':['Hard light']},'typesafe')
    if refusal=='changed-version': p=j.prepare_request(anonymous()|{'source_image_version':2},'typesafe')
    if refusal=='expired': now=q['expires_at']
    if refusal=='low-ceiling': a['max_usd']='0.001'
    if refusal=='forged-total': q['total_upper_bound_usd']='0';a=consent(q)
    if refusal=='mismatched-model': a['model']='other'
    if refusal=='extra-approval': a['unknown']='other'
    if refusal=='old-price': monkeypatch.setattr(j,'_primary_bounds',lambda route:j.BillingBounds('https://example.invalid/old','2029-01-01',1893456000,8192,256,Decimal('.042'),Decimal('0'),Decimal('.01')))
    if refusal=='invalid-approval-type': a['approved']=1
    result=j.run_advice(p,q,a,store,s['id'],s['revision'],credentials=keys,transport=lambda *args:calls.append(args),now=now)
    assert result['status']=='unavailable' and keys.calls==[] and calls==[]
    assert store._session_path(s['id']).read_bytes()==before
    assert not list(store.root.glob('*.attempt'))


def test_timeout_consumes_attempt_no_retry_no_state_change(tmp_path,monkeypatch):
    j=judge();synthetic_bounds(monkeypatch,j);store,s=local_session(tmp_path);p=j.prepare_request(anonymous(),'typesafe');q=j.quote(p,now=1893456000);keys=Keys();calls=[]
    before=store._session_path(s['id']).read_bytes()
    def timeout(endpoint,key,raw): calls.append((endpoint,raw));raise TimeoutError('Untrusted detail')
    assert j.run_advice(p,q,consent(q),store,s['id'],s['revision'],credentials=keys,transport=timeout,now=1893456001)=={'status':'unavailable','reason':'transport_timeout'}
    assert j.run_advice(p,q,consent(q),store,s['id'],s['revision'],credentials=keys,transport=timeout,now=1893456001)['reason']=='attempt_spent'
    assert len(calls)==1 and keys.calls==['typesafe'] and calls[0][1]==p.body
    assert store._session_path(s['id']).read_bytes()==before


def test_concurrent_reuse_reserves_before_key_once(tmp_path,monkeypatch):
    j=judge();synthetic_bounds(monkeypatch,j);store,s=local_session(tmp_path);p=j.prepare_request(anonymous(),'typesafe');q=j.quote(p,now=1893456000);keys=Keys();calls=[];results=[];barrier=threading.Barrier(2)
    def send(endpoint,key,body): calls.append(body);time.sleep(.1);return controlled_reply(p)
    def run():
        barrier.wait(timeout=3)
        results.append(j.run_advice(p,q,consent(q),store,s['id'],s['revision'],credentials=keys,transport=send,now=1893456001))
    threads=[threading.Thread(target=run) for _ in range(2)]
    for t in threads:t.start()
    for t in threads:t.join(timeout=6)
    assert not any(t.is_alive() for t in threads)
    assert len(calls)==1 and keys.calls==['typesafe'] and len(results)==2
    assert sorted(r['status'] for r in results)==['advisory','unavailable']


def test_actual_key_substring_blocks_send_and_is_not_in_errors(tmp_path,monkeypatch,capsys):
    import secrets
    j=judge();synthetic_bounds(monkeypatch,j);store,s=local_session(tmp_path);data=anonymous();secret=secrets.token_hex(8);data['constraints']=[secret+' warm']
    p=j.prepare_request(data,'typesafe');q=j.quote(p,now=1893456000);keys=Keys(secret);calls=[]
    result=j.run_advice(p,q,consent(q),store,s['id'],s['revision'],credentials=keys,transport=lambda *a:calls.append(a),now=1893456001)
    assert result=={'status':'unavailable','reason':'credential_in_payload'} and calls==[]
    assert secret not in repr(result)+capsys.readouterr().out+capsys.readouterr().err
    assert all(secret.encode() not in f.read_bytes() for f in store.root.rglob('*') if f.is_file())


def test_transport_exact_bytes_fixed_tls_timeout_bounded_read(monkeypatch):
    j=judge();p=j.prepare_request(anonymous(),'typesafe');calls=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,n):calls.append(('read',n));return json.dumps(controlled_reply(p)).encode()
    class Opener:
        def open(self,request,timeout):
            calls.append((request.full_url,request.data,request.get_method(),timeout,request.get_header('Authorization')));return Response()
    monkeypatch.setattr(j,'build_opener',lambda handler:Opener())
    assert j.send_once(j.ENDPOINTS['typesafe'],'invented-key',p.body)['answers']==answer()
    assert calls==[(j.ENDPOINTS['typesafe'],p.body,'POST',5,'Bearer invented-key'),('read',128001)]
    assert j.NoRedirect().redirect_request(None,None,302,'Moved',{},'https://elsewhere.invalid') is None
    with pytest.raises(ValueError):j.send_once('http://example.invalid','invented-key',p.body)
    with pytest.raises(ValueError):j.send_once(j.ENDPOINTS['typesafe'],'invented-key',b'x'*24577)


def test_transport_untrusted_failures_are_fixed_without_exception_chain(monkeypatch):
    j=judge();p=j.prepare_request(anonymous(),'typesafe');marker='Invented private detail'
    class Opener:
        def open(self,*a,**kw):raise RuntimeError(marker)
    monkeypatch.setattr(j,'build_opener',lambda handler:Opener())
    with pytest.raises(j.TransportUnavailable) as caught:j.send_once(j.ENDPOINTS['typesafe'],'invented-key',p.body)
    assert marker not in str(caught.value) and caught.value.__context__ is None and caught.value.__cause__ is None


def test_gate_checks_fixed_wire_text_and_wrapped_binary():
    j=judge()
    with pytest.raises(ValueError):j.prepare_request(anonymous(),'typesafe',deny_tokens=['Select'])
    data=anonymous();data['constraints']=['a'*32+'\n'+'a'*32]
    with pytest.raises(ValueError):j.prepare_request(data,'typesafe')


def test_transport_rejects_noncanonical_body_without_opening(monkeypatch):
    j=judge();p=j.prepare_request(anonymous(),'typesafe')
    monkeypatch.setattr(j,'build_opener',lambda *a:pytest.fail('Opened for unsafe wire body'))
    body=json.loads(p.body);body['questions']['pick']['instructions']='User-changed question'
    with pytest.raises(ValueError):j.send_once(j.ENDPOINTS['typesafe'],'invented-key',json.dumps(body).encode())


@pytest.mark.parametrize('kind',['oversize','malformed','duplicate','redirect','wrapped-timeout'])
def test_transport_bounded_failure_controls(monkeypatch,kind):
    from urllib.error import HTTPError, URLError
    j=judge();p=j.prepare_request(anonymous(),'typesafe');opened=[];reads=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,n):
            reads.append(n)
            if kind=='oversize':return b'x'*128001
            if kind=='duplicate':return b'{"model":"other","model":"jev-1.13.0"}'
            return b'not-json'
    class Opener:
        def open(self,request,timeout):
            opened.append(request.full_url)
            if kind=='redirect':raise HTTPError(request.full_url,302,'Untrusted detail',{},None)
            if kind=='wrapped-timeout':raise URLError(TimeoutError('Untrusted detail'))
            return Response()
    monkeypatch.setattr(j,'build_opener',lambda *a:Opener())
    with pytest.raises(j.TransportUnavailable) as caught:j.send_once(j.ENDPOINTS['typesafe'],'invented-key',p.body)
    assert len(opened)==1 and reads in ([],[128001])
    assert caught.value.__context__ is None and 'Untrusted detail' not in str(caught.value)
    if kind=='oversize':assert caught.value.reason=='response_too_large'
    if kind=='wrapped-timeout':assert caught.value.reason=='transport_timeout'


@pytest.mark.parametrize('kind',['weak-choice','weak-relevance','contradiction','wrong-model','malformed-answer','key-error','stale-revision'])
def test_failure_and_weak_signals_never_mutate_creative_state(tmp_path,monkeypatch,kind):
    j=judge();synthetic_bounds(monkeypatch,j);store,s=local_session(tmp_path)
    p=j.prepare_request(anonymous('addition' if kind in ('weak-relevance','contradiction') else 'model'),'openrouter')
    q=j.quote(p,now=1893456000);keys=Keys();calls=[];before=store._session_path(s['id']).read_bytes()
    result=controlled_reply(p,'openrouter')
    if kind=='weak-choice':result['answers']['pick']['confidence']=.2
    if kind in ('weak-relevance','contradiction'):
        result['answers']={'relevance':{'type':'noul','noul':.2 if kind=='weak-relevance' else .9},'contradiction':{'type':'noul','noul':.8 if kind=='contradiction' else .1}}
    if kind=='wrong-model':result['model']='other'
    if kind=='malformed-answer':result['answers']['pick']['probabilities']={}
    if kind=='key-error':
        def broken(route):keys.calls.append(route);raise RuntimeError('Private value')
        keys.read=broken
    def send(endpoint,key,body):calls.append((endpoint,body));return result
    outcome=j.run_advice(p,q,consent(q),store,s['id'],s['revision']-1 if kind=='stale-revision' else s['revision'],credentials=keys,transport=send,now=1893456001)
    assert outcome['status'] in ('weak','unavailable') and 'answers' not in outcome
    assert store._session_path(s['id']).read_bytes()==before
    assert len(calls)==(0 if kind in ('key-error','stale-revision') else 1)
    if calls:assert calls==[(j.ENDPOINTS['openrouter'],p.body)]


def test_success_uses_selected_native_account_and_existing_event(tmp_path,monkeypatch):
    j=judge();synthetic_bounds(monkeypatch,j);store,s=local_session(tmp_path)
    from vybe_check import credentials
    keys=Keys();monkeypatch.setattr(credentials,'Credentials',lambda:keys)
    p=j.prepare_request(anonymous(),'openrouter');q=j.quote(p,now=1893456000);calls=[]
    def send(endpoint,key,body):calls.append((endpoint,key,body));return controlled_reply(p,'openrouter')
    result=j.run_advice(p,q,consent(q),store,s['id'],s['revision'],transport=send,now=1893456001)
    assert result['status']=='advisory' and keys.calls==['openrouter']
    assert calls==[(j.ENDPOINTS['openrouter'],keys.value,p.body)]
    after=store.read(s['id']);assert after['image_versions']==s['image_versions'] and after['locks']==s['locks']
    assert after['revision']==s['revision']+1 and after['advice'][0]['model']=='typesafe/jev-1.13'
    assert 'Never persist provider prose' not in json.dumps(after)


def test_one_approval_consumed_across_different_session_roots(tmp_path,monkeypatch):
    j=judge();synthetic_bounds(monkeypatch,j);first,s1=local_session(tmp_path/'first');second,s2=local_session(tmp_path/'second')
    p=j.prepare_request(anonymous(),'typesafe');q=j.quote(p,now=1893456000);keys=Keys();calls=[]
    def send(endpoint,key,body):calls.append(body);return controlled_reply(p)
    assert j.run_advice(p,q,consent(q),first,s1['id'],s1['revision'],credentials=keys,transport=send,now=1893456001)['status']=='advisory'
    result=j.run_advice(p,q,consent(q),second,s2['id'],s2['revision'],credentials=keys,transport=send,now=1893456001)
    assert result=={'status':'unavailable','reason':'attempt_spent'} and len(calls)==1 and len(keys.calls)==1


def test_forged_prepared_request_and_quote_refused(tmp_path,monkeypatch):
    from dataclasses import replace
    j=judge();synthetic_bounds(monkeypatch,j);store,s=local_session(tmp_path);p=j.prepare_request(anonymous(),'typesafe');q=j.quote(p,now=1893456000);keys=Keys();calls=[]
    forged=replace(p,model='other')
    assert j.run_advice(forged,q,consent(q),store,s['id'],s['revision'],credentials=keys,transport=lambda *a:calls.append(a),now=1893456001)['status']=='unavailable'
    assert keys.calls==[] and calls==[]


def test_wrapped_binary_is_independently_rejected():
    j=judge();data=anonymous();data['constraints']=['a'*32+'\n'+'a'*32]
    with pytest.raises(ValueError):j.prepare_request(data,'typesafe')


def test_two_processes_share_one_portable_reservation(tmp_path,monkeypatch):
    import os
    import subprocess
    import sys
    j=judge();synthetic_bounds(monkeypatch,j);p=j.prepare_request(anonymous(),'typesafe');q=j.quote(p,now=1893456000)
    source=Path(j.__file__).resolve().parents[1];home=tmp_path/'shared-fake-home';home.mkdir();release=tmp_path/'release'
    script=tmp_path/'reserve.py'
    code = """import json,os,pathlib,sys,time
from vybe_check import judge
source=pathlib.Path(os.environ['PYTHONPATH'])
assert pathlib.Path(judge.__file__).resolve()==source/'vybe_check/judge.py'
assert os.environ['PYTHONDONTWRITEBYTECODE']=='1'
receipt,ready,release=sys.argv[1:]
pathlib.Path(ready).touch(exist_ok=False)
deadline=time.monotonic()+5
while not pathlib.Path(release).exists():
    assert time.monotonic()<deadline
    time.sleep(.02)
print(json.dumps({'reserved':judge._reserve(json.loads(receipt))}))
"""
    with script.open('x') as f:f.write(code)
    children=[];launches=[]
    try:
        for index in range(2):
            childroot=tmp_path/('child-'+str(index));childroot.mkdir();ready=childroot/'ready'
            env={**os.environ,**{k:str(home) for k in ('HOME','USERPROFILE','LOCALAPPDATA','XDG_DATA_HOME')},'VYBE_CHECK_ROOT':str(childroot/'explicit-state'),'PYTHONPATH':str(source),'PYTHONDONTWRITEBYTECODE':'1'}
            command=[sys.executable,'-B',str(script),json.dumps({'receipt_id':q['receipt_id'],'receipt_sha256':q['receipt_sha256']}),str(ready),str(release)]
            launches.append({'argv':command,'cwd':str(source.parent),'environment':env})
            children.append(subprocess.Popen(command,cwd=source.parent,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
        deadline=time.monotonic()+5
        while not all((tmp_path/('child-'+str(i))/'ready').exists() for i in range(2)):
            assert time.monotonic()<deadline
            time.sleep(.02)
        release.touch(exist_ok=False)
        values=[]
        for child,launch in zip(children,launches):
            out,err=child.communicate(timeout=7)
            with (tmp_path/('child-result-'+str(child.pid)+'.json')).open('x') as f:
                json.dump({**launch,'pid':child.pid,'exit':child.returncode,'poll':child.poll(),'status':'terminal','stdout':out,'stderr':err},f)
            assert child.returncode==0 and err=='', {'argv':child.args,'exit':child.returncode,'stdout':out,'stderr':err}
            values.append(json.loads(out)['reserved'])
        assert sorted(values)==[False,True]
        markers=list((home/'.vybe-check-security/judge-attempts').glob('*.attempt'))
        assert len(markers)==1 and json.loads(markers[0].read_text())=={'receipt_sha256':q['receipt_sha256'],'status':'spent'}
    finally:
        for child in children:
            if child.poll() is None:child.terminate()
            child.communicate(timeout=7)


def test_reservation_reopens_checked_lock_after_one_leaf_open_missing(tmp_path,monkeypatch):
    import os
    from vybe_check import workshop
    j=judge();home=tmp_path/'home';home.mkdir()
    monkeypatch.setenv('HOME',str(home))
    real=workshop.os.open;opens=[];checks=[];check=workshop._check_file
    def open_leaf(path,flags,*args,**kwargs):
        if path=='.reservation.lock':
            opens.append((flags,kwargs.get('dir_fd')))
            if len(opens)==1:raise FileNotFoundError(2,'Injected recorded boundary',path)
        return real(path,flags,*args,**kwargs)
    def checked(path,fd):checks.append(Path(path).name);return check(path,fd)
    monkeypatch.setattr(workshop.os,'open',open_leaf);monkeypatch.setattr(workshop,'_check_file',checked)
    receipt={'receipt_id':'b'*32,'receipt_sha256':'a'*64}
    assert j._reserve(receipt) is True
    assert len(opens)==2 and all(flags & os.O_NOFOLLOW and fd is not None for flags,fd in opens)
    assert checks.count('.reservation.lock')>=2
    marker=home/'.vybe-check-security/judge-attempts'/('b'*32+'.attempt')
    assert json.loads(marker.read_text())=={'receipt_sha256':'a'*64,'status':'spent'}
    assert j._reserve(receipt) is False


@pytest.mark.parametrize('failure',['permanent-leaf','parent-open','permission','marker-open'])
def test_reservation_primitive_failures_never_reach_key_or_send(tmp_path,monkeypatch,failure):
    from vybe_check import workshop
    j=judge();synthetic_bounds(monkeypatch,j);store,s=local_session(tmp_path)
    home=tmp_path/'home';home.mkdir();monkeypatch.setenv('HOME',str(home))
    p=j.prepare_request(anonymous(),'typesafe');q=j.quote(p,now=1893456000);keys=Keys();calls=[];opens=[]
    before=store._session_path(s['id']).read_bytes();real=workshop.os.open
    def broken(path,flags,*args,**kwargs):
        if path=='.reservation.lock' and failure in ('permanent-leaf','permission'):
            opens.append(path)
            if failure=='permission':raise PermissionError(13,'Injected',path)
            raise FileNotFoundError(2,'Injected recorded boundary',path)
        if path=='judge-attempts' and failure=='parent-open':
            opens.append(path);raise FileNotFoundError(2,'Injected parent boundary',path)
        if str(path).endswith('.attempt') and failure=='marker-open':
            opens.append(path);raise FileNotFoundError(2,'Injected marker boundary',path)
        return real(path,flags,*args,**kwargs)
    monkeypatch.setattr(workshop.os,'open',broken)
    result=j.run_advice(p,q,consent(q),store,s['id'],s['revision'],credentials=keys,transport=lambda *a:calls.append(a),now=1893456001)
    assert result=={'status':'unavailable','reason':'local_state_unavailable'}
    assert keys.calls==[] and calls==[] and store._session_path(s['id']).read_bytes()==before
    assert len(opens)==(2 if failure=='permanent-leaf' else 1)
    assert not list(home.rglob('*.attempt'))


@pytest.mark.parametrize('unsafe',['symlink','hardlink','fifo','parent-link','descriptor-mismatch'])
def test_reservation_retry_rechecks_unsafe_paths_and_preserves_sentinel(tmp_path,monkeypatch,unsafe):
    import os
    from vybe_check import workshop
    j=judge();home=tmp_path/'home';home.mkdir();monkeypatch.setenv('HOME',str(home))
    sentinel=tmp_path/'sentinel';sentinel.write_bytes(b'Unchanged sentinel')
    folder=home/'.vybe-check-security/judge-attempts';lock=folder/'.reservation.lock';real=workshop.os.open;calls=[]
    def altered(path,flags,*args,**kwargs):
        if path=='.reservation.lock':
            calls.append(path)
            if len(calls)==1:
                if unsafe=='symlink':lock.symlink_to(sentinel)
                if unsafe=='hardlink':os.link(sentinel,lock)
                if unsafe=='fifo':os.mkfifo(lock)
                if unsafe=='parent-link':
                    retained=folder.with_name('retained-attempts');folder.rename(retained);folder.symlink_to(tmp_path,target_is_directory=True)
                raise FileNotFoundError(2,'Injected recorded boundary',path)
            if unsafe=='descriptor-mismatch':
                fd=real(sentinel,flags,*args);os.close(real(path,flags,*args,**kwargs))
                return fd
        return real(path,flags,*args,**kwargs)
    monkeypatch.setattr(workshop.os,'open',altered)
    with pytest.raises((OSError,ValueError)):j._reserve({'receipt_id':'c'*32,'receipt_sha256':'a'*64})
    assert sentinel.read_bytes()==b'Unchanged sentinel'
    assert not list(home.rglob('*.attempt'))
    assert len(calls)==(2 if unsafe=='descriptor-mismatch' else 1)
