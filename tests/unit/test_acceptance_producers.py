"""Execution controls are synthetic authoring evidence, never native receipts."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys

import pytest


def producer():
    try:
        return importlib.import_module('tools.acceptance_producers')
    except ImportError:
        pytest.fail('Required Task 12 producer orchestration is absent')


def test_agent_packets_cover_eight_scenarios_and_interactive_no_transcripts(tmp_path):
    p=producer();pack=p.agent_packets(tmp_path/'pack')
    assert set(pack)=={'empty_brief','one_question','complete_brief','image_only','draft_refinement','video_modes','model_advice','unavailable_optional'}
    assert all(Path(x['prompt']).is_file() and x['sha256']==hashlib.sha256(Path(x['prompt']).read_bytes()).hexdigest() for x in pack.values())
    with pytest.raises(ValueError,match='installed|Authoring|source'):
        p.execute_interactive([sys.executable,'-c','print("Never run")'],tmp_path,{},tmp_path/'session')
    assert not (tmp_path/'session').exists()


def test_native_preservation_consumes_same_sentinel_after_actual_operation(tmp_path):
    p=producer();events=[]
    class SyntheticStore:
        identity='Synthetic authoring store'
        values={}
        def get_password(self,service,account):events.append(('get',service,account));return self.values.get((service,account))
        def add_password(self,service,account,value):
            if (service,account) in self.values:raise ValueError('Existing')
            self.values[service,account]=value
    def operation():events.append(('operation',));(tmp_path/'operation-observed').write_bytes(b'Actual local operation control')
    result=p.sentinel_roundtrip(SyntheticStore(),operation)
    assert result['equal'] and result['duplicate_preserved'] and result['consumed_after_operation']
    assert result['scope']=='authoring-synthetic'
    assert events[-2][0]=='operation' and events[-1][0]=='get'
    assert (tmp_path/'operation-observed').is_file()
    assert len({row[1] for row in events if row[0]=='get'})==1
    assert not any(key in result for key in ('secret','account','value'))


@pytest.mark.parametrize("store_state", ["explicitly-locked", "explicitly-unavailable"])
def test_unavailable_control_runs_refusal_baseline_and_no_provider(tmp_path, store_state):
    p=producer();events=[]
    from vybe_check.credentials import StoreUnavailable
    def read():events.append('read');raise StoreUnavailable()
    def baseline():
        from tools.acceptance_runtime import session
        store,state=session(tmp_path);state=store.apply(state['id'],state['revision'],'add_image_version',{'prompt':'A ceramic bowl, with a green glaze'})
        events.append('baseline');return state['image_versions'][-1]['version']>1
    result=p.unavailable_sequence(read,baseline,{'state':store_state,'scope':'authoring-synthetic'})
    assert result['native_read_refused'] and result['baseline_refined'] and result['provider_calls']==0
    assert events==['read','baseline'] and result['scope']=='authoring-synthetic'
    with pytest.raises(ValueError):p.unavailable_sequence(read,baseline,{'state':'permission-denied','scope':'authoring-synthetic'})


def test_lifecycle_orders_actual_retained_verifier_after_operation(tmp_path):
    p=producer();events=[]
    from tools.acceptance_runtime import registered,environment
    from tools.verify_host import command_receipt,retained_state
    store,state,picture=registered(tmp_path)
    env=environment(tmp_path);env['PYTHONPATH']=os.environ['PYTHONPATH']
    def read_state():events.append('state');return retained_state(store.root)
    def op():events.append('operation');(tmp_path/'operation').write_bytes(b'Synthetic pip boundary control')
    def retained():
        events.append('retained');out=tmp_path/'after.json';tool=Path(__file__).resolve().parents[2]/'tools/verify_host.py'
        command_receipt([sys.executable,'-B',str(tool),'retained-state','--root',str(store.root),'--out',str(out)],tmp_path,tmp_path/'verifier-command',env=env)
        return json.loads(out.read_bytes())
    result=p.lifecycle_sequence(read_state,op,retained)
    assert result['before']==result['after'] and events==['state','operation','retained']
    assert result['after']['media'] and (tmp_path/'verifier-command/receipt.json').is_file()


def test_capability_controls_refuse_without_automatic_generation(tmp_path):
    p=producer();from vybe_check.local_preview import ComfyPreview
    result=p.capability_controls(tmp_path/'controls',None)
    assert result['unavailable_refused'] and result['generation_calls']==0 and result['automatic_requests']==0
    assert result['scope']=='authoring-synthetic'
    assert result['unsupported_core_refused'] is False and result['missing_checkpoint_refused'] is False
    assert ComfyPreview(tmp_path/'unconfigured').capability()['available'] is False


def test_provider_builder_binds_original_inputs_and_sanitised_response(tmp_path):
    p=producer();candidate={'version':'0.1.0rc1',**{x+'_sha256':hashlib.sha256(x.encode()).hexdigest() for x in ('source','wheel','sdist')}}
    request=tmp_path/'request.json';request.write_text('{"invented":true}')
    approval=tmp_path/'approval.json';approval.write_text('{"approved":true,"max_usd":"0.01"}')
    cost=tmp_path/'cost.json';cost.write_text('{"total_upper_bound_usd":"0.001","pricing_url":"https://example.invalid/rate","pricing_date":"2026-10-01"}')
    reply={'model':'jev-1.13.0','provider':'Invented control','answers':{'relevance':{'type':'noul','noul':0.4}},'untrusted_prose':'Must not be copied'}
    row=p.provider_record(candidate,'typesafe',request,approval,cost,reply,reply['answers'],{'backend':'Synthetic authoring store','calls':1},tmp_path/'provider',tmp_path)
    assert row['candidate']==candidate and row['scope']=='authoring-synthetic' and row['call_count']==1
    assert row['retry_count']==row['fallback_count']==0
    from tools.verify_host import bound_bytes,validate_provider
    assert b'Must not be copied' not in bound_bytes(row['response'],tmp_path)
    assert row['approval_sha256']==hashlib.sha256(approval.read_bytes()).hexdigest()
    with pytest.raises(ValueError):validate_provider(row,'typesafe')


def test_runtime_freeze_is_produced_from_reviewed_inventory_and_actual_origins(tmp_path):
    p=producer();work=tmp_path/'source';work.mkdir();(work/'probe.py').write_bytes(b'print("Observed")\n')
    source=tmp_path/'source-artifact';source.write_bytes(b'Independent frozen artifact')
    digest=hashlib.sha256(source.read_bytes()).hexdigest();files={'probe.py':{'size':18,'sha256':hashlib.sha256(b'print("Observed")\n').hexdigest()}}
    files['probe.py']['size']=len(b'print("Observed")\n')
    reviewed=tmp_path/'reviewed-freeze.json';reviewed.write_text(json.dumps({'source_sha256':digest,'files':files}))
    from tools.verify_host import file_reference
    row=p.bind_runtime_freeze(work,{'source_sha256':digest},file_reference(source,tmp_path),file_reference(reviewed,tmp_path),['probe.py'],tmp_path,tmp_path/'runtime')
    assert json.loads((tmp_path/row['path']).read_bytes())['files']==files
    (work/'probe.py').write_bytes(b'Swapped origin')
    with pytest.raises(ValueError):p.bind_runtime_freeze(work,{'source_sha256':digest},file_reference(source,tmp_path),file_reference(reviewed,tmp_path),['probe.py'],tmp_path,tmp_path/'refused')
    assert not (tmp_path/'refused/frozen-source-inventory.json').exists()


def test_execution_dispatch_requires_reviewed_plan_before_any_native_action(tmp_path,monkeypatch):
    p=producer();monkeypatch.delenv('VYBE_ACCEPTANCE_PLAN',raising=False);monkeypatch.delenv('VYBE_ACCEPTANCE_PLAN_SHA256',raising=False)
    with pytest.raises(ValueError):p.execute_required('installed-cell')
    assert set(p.PRODUCERS)=={'installed-cell','agent-installation','native-store','native-unavailable','installed-lifecycle','provider','local-study'}
    with pytest.raises(ValueError):p.execution_plan(tmp_path/'invented', '0'*64)


def test_existing_runtime_producer_emits_independent_inventory(tmp_path,monkeypatch):
    """Execute the producer and actual pytest child; source control is labelled."""
    from tools import verify_host as v
    from tools.acceptance_runtime import environment
    root=Path(__file__).resolve().parents[2];node='tests/unit/test_verification.py::test_contract_exact_active_ids_and_named_probes'
    artifact=tmp_path/'source.bin';artifact.write_bytes(b'Independent source control')
    wheel=tmp_path/'candidate.whl';wheel.write_bytes(b'Synthetic wheel binding only')
    candidate={'version':'0.1.0rc1','source_sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'sdist_sha256':hashlib.sha256(b'sdist').hexdigest()}
    members=['tools/verify_host.py','tools/acceptance_contract.json','tools/acceptance_runtime.py','tools/pytest_receipts.py','tests/unit/test_verification.py']
    if (root/'tools/acceptance_producers.py').is_file():members.append('tools/acceptance_producers.py')
    reviewed=tmp_path/'reviewed.json';v.save_json(reviewed,{'source_sha256':candidate['source_sha256'],'files':{x:v.bytes_digest(v.regular_bytes(root/x)) for x in members}})
    manifest={'candidate':candidate,'source':v.file_reference(artifact,tmp_path),'frozen_source_inventory':v.file_reference(reviewed,tmp_path)}
    monkeypatch.setattr(v,'load_contract',lambda:[{'hosts':['Darwin'],'nodeid':node}]);monkeypatch.setattr(v,'load_bundle',lambda:(manifest,[],tmp_path))
    real=v.command_receipt
    def execute(argv,cwd,out,*,env):
        # Run real pytest and the real phase plugin, with an explicit synthetic
        # startup guard only. No pre-created phases or runtime record.
        local=dict(os.environ);local.update(env);local['PYTHONPATH']=str(root/'src')+os.pathsep+os.environ['PYTHONPATH'].split(os.pathsep)[-1]
        local['VYBE_AUTHORING_ONLY']='1'
        code='import sys;sys.path.insert(0,'+repr(str(root))+');from tools import acceptance_runtime as r;r.installed_guard=lambda:"AUTHORING SNAPSHOT";import pytest;raise SystemExit(pytest.main('+repr(argv[4:])+'))'
        row=real([sys.executable,'-B','-c',code],cwd,out,env=local)
        return row
    monkeypatch.setattr(v,'command_receipt',execute)
    env=environment(tmp_path);env.pop('PYTHONPATH',None)
    observation={'system':'Darwin'}
    # Actual phase rows carry synthetic scope and cannot close final acceptance.
    validate=v.validate_phases
    def phases(raw,nodes):
        value=v.json_bytes(raw);assert value['scope']=='authoring-synthetic'
        assert value['exit_code']==0 and len(value['phases'])==3
    monkeypatch.setattr(v,'validate_phases',phases)
    v.run_probes(sys.executable,root,tmp_path/'runtime',env,observation,candidate,wheel,tmp_path)
    row=v.json_bytes((tmp_path/'runtime/runtime.json').read_bytes())
    assert row.get('frozen_source_inventory'), 'Runtime producer omitted independently bound inventory'
    assert v.json_bytes(v.bound_bytes(row['frozen_source_inventory'],tmp_path))['files']=={x:v.bytes_digest(v.regular_bytes(root/x)) for x in members}
    with pytest.raises(ValueError):validate((tmp_path/'runtime/phases.json').read_bytes(),[node])


def test_existing_study_producer_reaches_real_board_tab(tmp_path):
    import ast
    from tools import verify_host as v
    from tools.acceptance_runtime import registered,board
    from playwright.sync_api import sync_playwright
    tree=ast.parse(Path(v.__file__).read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='produce_studies')
    click=next(n for n in ast.walk(function) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='click')
    expression=ast.Expression(click);ast.fix_missing_locations(expression)
    store,state,_=registered(tmp_path)
    with board(store,state) as (_,origin),sync_playwright() as engine:
        browser=engine.chromium.launch(headless=True,executable_path=os.environ['VYBE_LAYOUT_BROWSER_EXECUTABLE'])
        try:
            page=browser.new_page();page.set_default_timeout(1000);page.goto(origin,wait_until='networkidle')
            # Execute the exact selector expression authored by the producer.
            eval(compile(expression,str(v.__file__),'eval'),{'page':page})
            assert page.locator('#tab-references').get_attribute('aria-selected')=='true'
            page.screenshot(path=str(tmp_path/'actual-board-tab.png'))
        finally:browser.close()


def test_existing_study_producer_binds_candidate_and_controls():
    import ast
    from tools import verify_host as v
    tree=ast.parse(Path(v.__file__).read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='produce_studies')
    assert 'candidate' in ast.get_source_segment(Path(v.__file__).read_text(),function), 'Dedicated producer cannot emit candidate-bound record'
    assert 'capability_controls' in ast.get_source_segment(Path(v.__file__).read_text(),function), 'Dedicated producer omits required capability observations'


def test_provider_dependency_refuses_before_native_consumer_or_transport(tmp_path):
    from vybe_check import judge
    from tools.acceptance_runtime import session
    store,state=session(tmp_path)
    request=judge.prepare_request({'purpose':'addition','source_image_version':1,'constraints':['Invented green glaze'],'options':{'option_1':'A blue ceramic rim'}},'typesafe')
    calls=[]
    class Consumer:
        def read(self,route):calls.append('credential');raise AssertionError('Unapproved')
    result=judge.run_advice(request,{}, {},store,state['id'],state['revision'],credentials=Consumer(),transport=lambda *a:calls.append('provider'))
    assert result=={'status':'unavailable','reason':'billing_unbounded'} and calls==[]


def test_actual_capability_producer_uses_get_and_never_generates(tmp_path):
    import runpy
    p=producer();root=Path(__file__).resolve().parents[2]
    module=runpy.run_path(str(root/'tests/unit/test_local_transport.py'));fixture=module['Fixture']()
    try:
        config={'base_url':fixture.url,'workflow':module['GRAPH'],'prompt_node':'2','checkpoint':'fixture.safetensors'}
        row=p.capability_controls(tmp_path/'controls',config)
        assert all(row[k] for k in ('unsupported_core_refused','missing_checkpoint_refused','unavailable_refused'))
        assert row['generation_calls']==0 and row['automatic_requests']==0 and fixture.posts==[]
        assert fixture.gets==['/object_info','/object_info']
        assert row['scope']=='authoring-synthetic'
    finally:fixture.close()


def test_actual_study_producer_outputs_candidate_bound_decoded_transport(tmp_path,monkeypatch):
    import runpy
    from tools import verify_host as v,acceptance_runtime as runtime
    p=producer();root=Path(__file__).resolve().parents[2]
    module=runpy.run_path(str(root/'tests/unit/test_local_transport.py'));fixture=module['Fixture']()
    try:
        store,state=runtime.session(tmp_path);fixture.configure(store.root)
        checkpoint=tmp_path/'fixture.safetensors';checkpoint.write_bytes(b'Synthetic checkpoint control; no model')
        candidate={'version':'0.1.0rc1',**{x+'_sha256':hashlib.sha256(x.encode()).hexdigest() for x in ('source','wheel','sdist')}}
        monkeypatch.setattr(runtime,'installed_guard',lambda:'INSTALLED RUNTIME')
        monkeypatch.setattr(p,'execution_plan',lambda *a:({'candidate':candidate},tmp_path))
        monkeypatch.setenv('VYBE_CHECK_ROOT',str(tmp_path))
        from vybe_check.local_preview import ComfyPreview
        real=ComfyPreview._request
        def observed(self,origin,route,**kwargs):
            if route=='/system_stats':return b'{"system":{"comfyui_version":"Synthetic transport","pytorch_version":"Synthetic transport"}}'
            return real(self,origin,route,**kwargs)
        monkeypatch.setattr(ComfyPreview,'_request',observed)
        out=tmp_path/'produced'
        assert v.produce_studies(['--root',str(store.root),'--session',state['id'],'--version','1','--checkpoint',str(checkpoint),'--out',str(out),'--approval','Two real local studies explicitly approved'])==0
        row=v.json_bytes(v.regular_bytes(out/'study.json'))
        assert row['candidate']==candidate and row['scope']=='authoring-synthetic' and row['visual_confirmation'] is None
        controls=v.json_bytes(v.bound_bytes(row['capability_controls'],tmp_path))
        assert controls['generation_calls']==0 and controls['automatic_requests']==0
        assert len(fixture.posts)==2 and len(row['studies'])==2
        assert row['first_before_sha256']==row['first_after_sha256']
        monkeypatch.setattr(v,'required_records',lambda *a,**kw:({'candidate':candidate},[row],tmp_path))
        with pytest.raises(ValueError):v.study_gate('DoD-48')
        # Schema interoperability only. The actual produced record remains
        # synthetic and final acceptance must refuse it as asserted above.
        schema=json.loads(json.dumps(row));schema['scope']='local-checkpoint-observed';schema['visual_confirmation']='Both registered studies displayed'
        schema_controls=dict(controls,scope='actual-local-capability-controls');v.save_json(out/'schema-controls.json',schema_controls)
        schema['capability_controls']=v.file_reference(out/'schema-controls.json',tmp_path)
        monkeypatch.setattr(v,'required_records',lambda *a,**kw:({'candidate':candidate},[schema],tmp_path))
        assert v.study_gate('DoD-48')[0]['candidate']==candidate
    finally:fixture.close()


def test_provider_produced_sanitised_schema_and_final_synthetic_refusal(tmp_path,monkeypatch):
    p=producer();from tools import verify_host as v
    candidate={'version':'0.1.0rc1',**{x+'_sha256':hashlib.sha256(x.encode()).hexdigest() for x in ('source','wheel','sdist')}}
    for name,value in [('request',{'invented':True}),('approval',{'approved':True,'max_usd':'0.01'}),('cost',{'total_upper_bound_usd':'0.001','pricing_url':'https://example.invalid/authoring-rate','pricing_date':'2026-10-01'})]:v.save_json(tmp_path/(name+'.json'),value)
    reply={'model':'jev-1.13.0','answers':{'relevance':{'type':'noul','noul':0.7}},'untrusted_prose':'Excluded'}
    row=p.provider_record(candidate,'typesafe',tmp_path/'request.json',tmp_path/'approval.json',tmp_path/'cost.json',reply,reply['answers'],{'backend':'Synthetic authoring store','calls':1},tmp_path/'produced',tmp_path)
    monkeypatch.setattr(v,'required_records',lambda *a,**kw:({'candidate':candidate},[row],tmp_path))
    with pytest.raises(ValueError):v.provider_gate('typesafe')
    schema=dict(row,scope='native-provider-observed',native_backend='macos-keychain')
    monkeypatch.setattr(v,'required_records',lambda *a,**kw:({'candidate':candidate},[schema],tmp_path))
    v.provider_gate('typesafe')
    assert row['scope']=='authoring-synthetic' and v.json_bytes(v.bound_bytes(row['response'],tmp_path))['provider'] is None


def test_single_image_generated_output_registers_without_null_shot(tmp_path):
    import runpy
    from tools.acceptance_runtime import session
    from vybe_check.local_preview import ComfyPreview
    root=Path(__file__).resolve().parents[2];module=runpy.run_path(str(root/'tests/unit/test_local_transport.py'));fixture=module['Fixture']()
    try:
        store,state=session(tmp_path);fixture.configure(store.root)
        result=ComfyPreview(store.root).generate(store,state['id'],state['revision'],1)
        assert result.get('previews'), 'Single image generation was silently left unregistered'
        assert result['previews'][-1]['shot_id']=='' and len(fixture.posts)==1
        assert store.resolve_media(state['id'],result['previews'][-1]['id']).is_file()
    finally:fixture.close()


def test_known_carousel_shot_generation_still_registers_explicit_id(tmp_path):
    import runpy
    from vybe_check.local_preview import ComfyPreview
    root=Path(__file__).resolve().parents[2];module=runpy.run_path(str(root/'tests/unit/test_local_transport.py'));fixture=module['Fixture']()
    try:
        store,state=module['agreed'](tmp_path/'state');fixture.configure(store.root)
        result=ComfyPreview(store.root).generate(store,state['id'],state['revision'],1,'rim')
        assert result['previews'][-1]['shot_id']=='rim' and len(fixture.posts)==1
        with pytest.raises(ValueError,match='known shot'):
            ComfyPreview(store.root).generate(store,state['id'],result['revision'],1,'invented-unknown')
        assert len(fixture.posts)==1
    finally:fixture.close()


@pytest.mark.parametrize("error_type", [PermissionError, RuntimeError, ImportError, ValueError])
@pytest.mark.parametrize("store_state", ["explicitly-locked", "explicitly-unavailable"])
def test_unavailable_unexpected_read_error_propagates_before_baseline(tmp_path, monkeypatch, error_type, store_state):
    """Synthetic refusal must not certify denial or a broken consumer as absence."""
    p=producer()
    from vybe_check import judge
    events=[]
    failure=error_type('Synthetic denied or unexpected read')
    def read():events.append('read');raise failure
    def baseline():events.append('baseline');return True
    def provider(*args, **kwargs):events.append('provider');raise AssertionError('No transport authorised')
    monkeypatch.setattr(judge,'send_once',provider)
    with pytest.raises(error_type) as caught:
        p.unavailable_sequence(read,baseline,{'state':store_state,'scope':'authoring-synthetic'})
    assert caught.value is failure and events==['read']
    assert judge.send_once is provider


@pytest.mark.parametrize("condition", ['absent', 'locked', 'denied', 'unexpected', 'missing_dependency', 'invalid', 'changed_state', 'dependency_import_missing', 'constructor_error'])
def test_linux_unavailable_synthetic_native_consumer_seam(tmp_path, monkeypatch, condition):
    """Execute the Linux adapter read and producer with injected API, never D-Bus."""
    import types
    p=producer()
    from vybe_check import credentials, judge
    from tools.acceptance_runtime import environment
    environment(tmp_path,monkeypatch)
    # The optional native library is represented by a synthetic typed module.
    class SyntheticServiceAbsent(Exception):pass
    failure={'denied':PermissionError,'unexpected':RuntimeError,'missing_dependency':ImportError,'invalid':ValueError,'dependency_import_missing':ImportError,'constructor_error':RuntimeError}.get(condition)
    events=[]
    class Connection:
        def close(self):events.append('connection-close')
    class Collection:
        def is_locked(self):return condition=='locked'
        def search_items(self,attributes):raise AssertionError('Refusal must precede item access')
    def dbus_init():
        events.append('native-read')
        if condition=='absent':raise SyntheticServiceAbsent('Synthetic absent service')
        if failure:raise failure('Synthetic read error')
        return Connection()
    exceptions=types.ModuleType('secretstorage.exceptions')
    exceptions.SecretServiceNotAvailableException=SyntheticServiceAbsent
    api=types.ModuleType('secretstorage');api.exceptions=exceptions
    api.dbus_init=dbus_init;api.get_default_collection=lambda connection:Collection()
    monkeypatch.setitem(sys.modules,'secretstorage',api)
    monkeypatch.setitem(sys.modules,'secretstorage.exceptions',exceptions)
    if condition=='dependency_import_missing':monkeypatch.setitem(sys.modules,'secretstorage.exceptions',None)
    def load_api():
        if condition=='constructor_error':raise RuntimeError('Synthetic constructor failure')
        return api
    monkeypatch.setattr(credentials,'_secret_service_api',load_api)
    monkeypatch.setattr(p,'installed',lambda:None)
    monkeypatch.setattr(p.platform,'system',lambda:'Linux')
    def provider(*args,**kwargs):events.append('provider');raise AssertionError('No provider authorised')
    monkeypatch.setattr(judge,'send_once',provider)
    service={'state':'explicitly-locked' if condition=='locked' else 'explicitly-unavailable','scope':'authoring-synthetic','system':'Linux'}
    observed=dict(service,state='available') if condition=='changed_state' else service
    monkeypatch.setattr(p,'linux_service_state',lambda:observed)
    class Context:
        python=sys.executable
        out=tmp_path/'producer'
        root=tmp_path
        candidate={'synthetic':True}
        def command(self,argv,label):
            events.append('service-command')
            dest=self.out/label;dest.mkdir(parents=True)
            (dest/'stdout.log').write_text(json.dumps(service))
            return {'synthetic':True}
        def save(self,name,row):
            events.append('record');(self.out/name).write_text(json.dumps(row));return row
    context=Context()
    if failure or condition=='changed_state':
        with pytest.raises(failure or ValueError):p.native_unavailable(context)
        assert not (context.out/'baseline').exists()
        assert not (context.out/'probe.json').exists() and not (context.out/'record.json').exists()
        assert 'record' not in events and 'provider' not in events
    else:
        row=p.native_unavailable(context)
        probe=json.loads((context.out/'probe.json').read_text())
        assert probe['scope']=='authoring-synthetic' and probe['native_read_refused'] is True
        assert probe['baseline_refined'] is True and probe['provider_calls']==0
        baseline=json.loads((context.out/'baseline.json').read_text())
        assert baseline['image_versions'][-1]['version']>1
        assert events.count('native-read')==1 and events.count('record')==1 and 'provider' not in events
        assert row['store_state']==service['state']
    assert judge.send_once is provider


def agent_artifact_control(tmp_path, monkeypatch, mode='positive'):
    """Real SessionStore creative bytes; native launches and registration replaced."""
    from types import SimpleNamespace
    from tools import verify_host as v
    from tools.acceptance_runtime import session
    from vybe_check import install
    p=producer();out=tmp_path/'produced';out.mkdir();cwd=tmp_path/'project';cwd.mkdir()
    env=v.isolated_environment(tmp_path/'environment')
    for key in v.ROOT_KEYS:monkeypatch.setenv(key,env[key])
    store,state=session(tmp_path/'workshop')
    result_path=store.root/'sessions'/(state['id']+'.json')
    result={'kind':'session','artifact':v.file_reference(result_path,tmp_path),
            'prompt_pointers':['/image_versions/0/prompt'],'version_pointers':['/id','/image_versions/0/version'],
            'reviewed_versions':[state['id'],state['image_versions'][0]['version']],
            'fact_bindings':[{'fact':'agreed_images','operation':'length','pointer':'/image_versions'},
                             {'fact':'video_versions','operation':'length','pointer':'/video_versions'}]}
    outcome={'observation_kind':'human-reviewed-outcome','reviewer':'Synthetic reviewer','notes':'Invented local result observed',
             'invented_input':True,'conversation_transcript':None,'facts':{'agreed_images':1,'video_versions':0},
             'results':[result],'reviewed_result_sha256':[result['artifact']['sha256']]}
    if mode=='missing':outcome.pop('results');outcome.pop('reviewed_result_sha256')
    elif mode=='mismatch':outcome['facts']['agreed_images']=2
    elif mode=='identifier':result['reviewed_versions'][-1]=99
    elif mode=='tamper':result_path.write_bytes(b'{"prompt":"Changed"}')
    elif mode=='input_only':
        packet=tmp_path/'input-packet.json';v.save_json(packet,{'prompt':'Input instructions'})
        result['artifact']=v.file_reference(packet,tmp_path);result['prompt_pointers']=['/prompt'];result['version_pointers']=[]
        result['reviewed_versions']=[];result['kind']='prompt';result['fact_bindings']=[]
        outcome['reviewed_result_sha256']=[result['artifact']['sha256']]
    elif mode=='notes_only':
        note=tmp_path/'notes-result.json';v.save_json(note,dict(outcome,results=[]))
        result['artifact']=v.file_reference(note,tmp_path);outcome['reviewed_result_sha256']=[result['artifact']['sha256']]
    exe=tmp_path/'never-executed-agent';exe.write_bytes(b'Synthetic not executable')
    config=tmp_path/'configuration';config.write_text('Synthetic no-transcript configuration');ref=v.file_reference(config,tmp_path)
    version='Synthetic boundary version';target=tmp_path/'registration'
    op={'agent':'codex','managed_scope':'project','interactive_arguments':[],'agent_version':version,
        'agent_executable':str(exe),'agent_executable_digest':v.bytes_digest(v.regular_bytes(exe)), 'agent_configuration':ref,
        'persistence_review':{'reviewer':'Synthetic reviewer','notes':'Invented configuration', 'official_source_url':'https://example.invalid/config',
        'conversation_transcripts':'Disabled','observation_kind':'human-reviewed-outcome','verified_version':version,'verified_arguments':[],
        'configuration_sha256':ref['sha256']}}
    monkeypatch.setattr(install,'registration_target',lambda *a,**kw:target)
    canonical={'SKILL.md':b'Synthetic registration'}
    monkeypatch.setattr(install,'_package_bytes',lambda:canonical)
    monkeypatch.setattr(install,'inventory',lambda target:{n:hashlib.sha256(raw).hexdigest() for n,raw in canonical.items()})
    monkeypatch.setattr(p,'execute_interactive',lambda *a:None)
    packets=p.agent_packets
    monkeypatch.setattr(p,'agent_packets',lambda path:{'image_only':packets(path)['image_only']})
    def command(argv,label):
        dest=out/label;dest.mkdir();(dest/'stdout.log').write_text(version+'\n')
        v.save_json(dest/'receipt.json',{'argv':argv,'system':'Darwin','synthetic_boundary':True})
        return v.file_reference(dest/'receipt.json',tmp_path)
    def cli(label,*args):return command([sys.executable,'-B','-m','vybe_check',*args],label)
    def save(name,row):v.save_json(out/name,row);return row
    review=tmp_path/'review.json';v.save_json(review,outcome)
    discovery=tmp_path/'discovery.json';v.save_json(discovery,{'agent_version':version,'loaded_registration':str(target),
        'observation_kind':'human-reviewed-outcome','reviewer':'Synthetic reviewer','notes':'Synthetic discovery boundary'})
    answers=iter([str(review),str(discovery)]);monkeypatch.setattr('builtins.input',lambda:next(answers))
    c=SimpleNamespace(out=out,root=tmp_path,cwd=cwd,env=env,operation=op,candidate={'synthetic':True},command=command,cli=cli,save=save)
    return p,c,state,result_path


@pytest.mark.parametrize('mode',['missing','input_only','notes_only','mismatch','identifier','tamper'])
def test_agent_installation_requires_creative_results(tmp_path,monkeypatch,mode):
    p,c,_,_=agent_artifact_control(tmp_path,monkeypatch,mode)
    with pytest.raises(ValueError):p.agent_installation(c)
    assert not (c.out/'record.json').exists()


def test_agent_installation_retains_actual_session_creative_result(tmp_path,monkeypatch):
    from tools import verify_host as v
    p,c,state,path=agent_artifact_control(tmp_path,monkeypatch)
    before=v.regular_bytes(path);row=p.agent_installation(c);outcome=row['scenarios']['image_only']
    v.validate_agent_results('image_only',outcome,tmp_path)
    retained=outcome['results'][0]['artifact']
    assert retained['path'].startswith('produced/result-image_only-')
    assert v.bound_bytes(retained,tmp_path)==before
    assert v.json_bytes(before)['image_versions'][0]['prompt']==state['image_versions'][0]['prompt']
    assert set(outcome['provenance'])=={'input','review','version_log'} and 'artifacts' not in outcome
    path.write_bytes(b'Later original mutation')
    assert v.bound_bytes(retained,tmp_path)==before
