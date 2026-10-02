"""Explicit installed acceptance operations. Source controls never close release gates."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import subprocess
import sys
import time
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).absolute().parent.parent))

from tools import verify_host as v

BACKENDS = {'Darwin':'macos-keychain','Windows':'windows-credential-locker','Linux':'linux-secret-service'}
IDENTITIES = {'macOS Keychain':'macos-keychain','Windows PasswordVault / Credential Locker':'windows-credential-locker','Linux Secret Service':'linux-secret-service'}
_CACHE = {}
_OPERATION_INDEX = None
_RECORD_OUT = None


def scope(native):
    from tools.acceptance_runtime import installed_guard
    return native if os.environ.get('VYBE_AUTHORING_ONLY') != '1' and installed_guard() == 'INSTALLED RUNTIME' else 'authoring-synthetic'


def installed():
    from tools.acceptance_runtime import installed_guard
    v.require(installed_guard() == 'INSTALLED RUNTIME', 'Authoring source cannot execute installed acceptance operations')


def copy_regular(source, target):
    raw = v.regular_bytes(source)
    target = Path(target);target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:stream.write(raw)
    return target


def agent_packets(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    prompts={
        'empty_brief':'Use Vybe-Check. Invent two concepts for an image of a ceramic vessel. The brief is empty. Keep every version unagreed until I agree.',
        'one_question':'Use Vybe-Check. Refine a ceramic vessel image. Ask at most one clarification question in each turn.',
        'complete_brief':'Use Vybe-Check. Create and agree an image prompt for a green ceramic bowl on grey linen, lit from the left. I explicitly agree this complete brief. Do not ask redundant agreement questions.',
        'image_only':'Use Vybe-Check. Agree a still image of a green ceramic bowl. Keep the session image-only. Do not create video versions.',
        'draft_refinement':'Use Vybe-Check. Refine the latest draft of a ceramic bowl by changing its glaze to blue. Save a new version and preserve all earlier bytes.',
        'video_modes':'Use Vybe-Check. From an agreed ceramic bowl image, create preserve, evolve, and multishot video versions with explicit anchors, locks, and ordered durations adding to the total.',
        'model_advice':'Use Vybe-Check. Advise on a suitable image input model using a dated official source. State uncertainty. Do not request a provider call or spend.',
        'unavailable_optional':'Use Vybe-Check. Refine a ceramic bowl image with optional judgement and preview unavailable. Continue the baseline refinement without a provider or model call.'}
    rows={}
    for name,prompt in prompts.items():
        path=out/(name+'.txt')
        with path.open('x',encoding='utf-8') as stream:stream.write(prompt+'\nSave outcome artifacts in this isolated workshop. Do not retain conversation transcripts.\n')
        rows[name]={'prompt':str(path),'sha256':hashlib.sha256(v.regular_bytes(path)).hexdigest()}
    return rows


def execute_interactive(argv,cwd,env,out):
    installed()
    v.require(sys.stdin.isatty() and sys.stdout.isatty(), 'A visible interactive terminal is required')
    v.require(isinstance(argv,list) and argv and all(isinstance(x,str) for x in argv), 'Explicit interactive argv required')
    v.require(not set(argv)&{'-p','--print','--output-format','exec'}, 'Headless or paid agent mode refused')
    roots=[Path(env.get(k,'')).absolute() for k in v.ROOT_KEYS]
    v.require(len(set(roots))==6 and all(env.get(k) for k in v.ROOT_KEYS), 'Six isolated roots required')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    executable=Path(argv[0]);before=v.bytes_digest(v.regular_bytes(executable))
    v.save_json(out/'launch.json',{'argv':argv,'cwd':str(Path(cwd).absolute()),'root_environment':{k:env[k] for k in v.ROOT_KEYS},'executable':before,'conversation_transcript':None})
    start=time.monotonic();child=subprocess.Popen(argv,cwd=cwd,env=env)
    initial=child.poll()
    try:code=child.wait(timeout=3600)
    except subprocess.TimeoutExpired:
        child.terminate();code=child.wait(timeout=10)
        v.save_json(out/'terminal.json',{'pid':child.pid,'initial_poll':initial,'wait':code,'final_poll':child.poll(),'timed_out':True})
        raise ValueError('Interactive session exceeded the bounded observation') from None
    terminal={'pid':child.pid,'initial_poll':initial,'wait':code,'final_poll':child.poll(),'elapsed_seconds':time.monotonic()-start,'timed_out':False,'conversation_transcript':None}
    v.save_json(out/'terminal.json',terminal)
    v.require(code==0 and before==v.bytes_digest(v.regular_bytes(executable)), 'Interactive executable failed or changed')
    return terminal


def sentinel_roundtrip(backend,operation=None):
    namespace='vybe-check-acceptance-'+uuid.uuid4().hex
    account='synthetic-'+uuid.uuid4().hex;value=secrets.token_urlsafe(32)
    backend.add_password(namespace,account,value)
    equal=backend.get_password(namespace,account)==value
    duplicate=False
    try:backend.add_password(namespace,account,'Invented duplicate')
    except Exception:duplicate=backend.get_password(namespace,account)==value
    v.require(equal and duplicate,'Native store round trip or duplicate preservation failed')
    if operation is not None:operation()
    after=backend.get_password(namespace,account)==value
    v.require(after,'Same sentinel was not consumable after operation')
    return {'scope':scope('actual-native-store-probe') if type(backend).__module__=='vybe_check.credentials' else 'authoring-synthetic',
        'system':platform.system(),'namespace':namespace,'backend':IDENTITIES.get(backend.identity,backend.identity),
        'equal':equal,'available':True,'duplicate_preserved':duplicate,'consumed_after_operation':after,'secret_logged':False}


def unavailable_sequence(read,baseline,service):
    v.require(service.get('state') in ('explicitly-locked','explicitly-unavailable'),'Permission denial is not service absence')
    from vybe_check.credentials import StoreUnavailable
    refused=False
    try:read()
    except StoreUnavailable:refused=True
    v.require(refused,'Actual native read did not refuse')
    from vybe_check import judge
    calls=[];original=judge.send_once
    def refuse_provider(*args,**kwargs):
        calls.append('attempt');raise ValueError('Unavailable control attempted provider transport')
    judge.send_once=refuse_provider
    try:refined=baseline()
    finally:judge.send_once=original
    v.require(refined is True and not calls,'Unavailable store blocked baseline or attempted provider transport')
    return {'scope':service.get('scope'),'system':platform.system(),'native_read_refused':True,'baseline_refined':True,'provider_calls':0,'store_state':service['state']}


def lifecycle_sequence(read_before,operation,read_after):
    before=read_before();operation();after=read_after()
    v.require(before==after,'Creative state changed across package operation')
    return {'before':before,'after':after}


def capability_controls(out,config):
    from vybe_check.local_preview import ComfyPreview
    from tools.acceptance_runtime import session
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    calls=[];generation=[]
    class Observed(ComfyPreview):
        def _request(self,origin,path,*args,**kwargs):
            body=args[0] if args else kwargs.get('body')
            calls.append({'path':path,'method':'POST' if body is not None else 'GET'})
            if body is not None:
                generation.append(path)
                raise ValueError('Capability control attempted generation')
            return super()._request(origin,path,*args,**kwargs)
    answers={}
    for name in ('unavailable','unsupported_core','missing_checkpoint'):
        work=out/name;work.mkdir();store,state=session(work)
        owner=Observed(store.root)
        # Baseline editing never invokes the transport.
        before=len(calls)
        state=store.apply(state['id'],state['revision'],'add_image_version',{'prompt':'A ceramic bowl with a green glaze'})
        v.require(len(calls)==before,'Automatic local request occurred')
        if name!='unavailable' and config is None:
            answers[name+'_refused']=False;continue
        if name!='unavailable':
            value=json.loads(json.dumps(config));workflow=value['workflow']
            if name=='unsupported_core':next(iter(workflow.values()))['class_type']='InventedUnsupportedAcceptanceNode'
            else:
                value['checkpoint']='invented-absent-'+uuid.uuid4().hex+'.safetensors'
                for node in workflow.values():
                    if node['class_type']=='CheckpointLoaderSimple':node['inputs']['ckpt_name']=value['checkpoint']
            v.save_json(store.root/'comfyui.json',value)
        refused=False
        try:owner.generate(store,state['id'],state['revision'],state['selected_image_version'])
        except Exception:refused=True
        answers[name+'_refused']=refused
    v.require(not generation,'Capability refusal crossed generation boundary')
    row={'scope':scope('actual-local-capability-controls'),'generation_calls':len(generation),'automatic_requests':0,'requests':calls,**answers}
    v.save_json(out/'controls.json',row)
    return row


def provider_record(candidate,route,request,approval,cost,reply,answers,consumer,out,root):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    refs={}
    for name,path in (('request',request),('approval',approval),('cost_receipt',cost)):
        refs[name]=v.file_reference(copy_regular(path,out/(name+'.json')),root)
    usage=reply.get('usage',{})
    sanitised={'model':reply.get('model'),'provider':reply.get('provider') if isinstance(reply.get('provider'),str) and len(reply['provider'])<=80 else None,
        'usage':{k:usage[k] for k in ('input_tokens','output_tokens') if isinstance(usage,dict) and type(usage.get(k)) is int and 0<=usage[k]<=1000000000},'answers':answers}
    v.save_json(out/'response.json',sanitised);refs['response']=v.file_reference(out/'response.json',root)
    approved=v.json_bytes(v.regular_bytes(approval));quoted=v.json_bytes(v.regular_bytes(cost))
    row={'kind':'provider','scope':scope('native-provider-observed') if consumer.get('backend') in BACKENDS.values() else 'authoring-synthetic',
        'candidate':candidate,'route':route,'native_backend':consumer['backend'],'call_count':consumer['calls'],'retry_count':0,'fallback_count':0,
        'transport_outcome':'validated-response','requested_model':{'typesafe':'jev-1.13.0','openrouter':'typesafe/jev-1.13'}[route],
        'actual_model':sanitised['model'],'actual_provider':sanitised['provider'],'provider_observation':'Reported by response' if sanitised['provider'] else 'Not reported by response',
        'usage':sanitised['usage'],'usage_observation':'Reported by response' if sanitised['usage'] else 'Not reported by response',
        'synthetic_decision_only':True,'answers':answers,'maximum_cost':approved.get('max_usd'),'quoted_total':quoted.get('total_upper_bound_usd'),
        'primary_source_url':quoted.get('pricing_url'),'rate_checked_date':quoted.get('pricing_date'),'original_response_sha256':hashlib.sha256(json.dumps(reply,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
        **refs,**{name+'_sha256':ref['sha256'] for name,ref in refs.items()},'final_release_criteria':'OPEN'}
    v.save_json(out/'record.json',row);return row


def bind_runtime_freeze(cwd,candidate,source,reviewed,members,root,out):
    v.require(hashlib.sha256(v.bound_bytes(source,root)).hexdigest()==candidate['source_sha256'],'Wrong frozen source artifact')
    inventory=v.json_bytes(v.bound_bytes(reviewed,root))
    v.require(inventory.get('source_sha256')==candidate['source_sha256'] and isinstance(inventory.get('files'),dict),'Unreviewed frozen source inventory')
    files={name:v.bytes_digest(v.regular_bytes(Path(cwd)/name)) for name in sorted(members)}
    v.require(all(inventory['files'].get(name)==facts for name,facts in files.items()),'Missing or swapped frozen source origin')
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    v.save_json(out/'frozen-source-inventory.json',{'source_sha256':candidate['source_sha256'],'files':files,'reviewed_inventory':reviewed,'source_artifact':source})
    return v.file_reference(out/'frozen-source-inventory.json',root)


def execution_plan(path,digest):
    v.require(path and v.HEX.fullmatch(digest or ''),'Independently reviewed execution plan and digest required')
    path=Path(path).absolute()
    try:raw=v.regular_bytes(path)
    except OSError:raise ValueError('Reviewed execution plan is unavailable') from None
    v.require(hashlib.sha256(raw).hexdigest()==digest,'Modified execution plan refused')
    plan=v.json_bytes(raw);root=path.parent
    v.require(plan.get('schema')==1 and plan.get('scope')=='final-native-execution-plan','Source or simulated plan refused')
    candidate=plan.get('candidate')
    v.require(isinstance(candidate,dict) and set(candidate)=={'version','source_sha256','wheel_sha256','sdist_sha256'} and candidate['version']=='0.1.0rc1','Exact final candidate tuple required')
    for name in ('source','wheel','sdist'):
        v.require(hashlib.sha256(v.bound_bytes(plan.get(name),root)).hexdigest()==candidate[name+'_sha256'],'Wrong candidate artifact')
    freeze=v.json_bytes(v.bound_bytes(plan.get('frozen_source_inventory'),root))
    v.require(freeze.get('source_sha256')==candidate['source_sha256'] and freeze.get('files'),'Independent frozen inventory required')
    v.require(isinstance(plan.get('operations'),list),'Explicit operations required')
    return plan,root


class Context:
    def __init__(self,plan,root,operation):
        self.plan=plan;self.root=root;self.operation=operation;self.candidate=plan['candidate']
        if operation['kind']=='installed-cell':
            v.require(not os.environ.get('PYTHONPATH') and not os.environ.get('VYBE_AUTHORING_ONLY'),'Source cannot install an acceptance cell')
        else:installed()
        v.require(operation.get('system')==platform.system(),'Operation requires another native host')
        self.out=root/'runs'/uuid.uuid4().hex;self.out.mkdir(parents=True,exist_ok=False)
        self.env=v.isolated_environment(self.out/'environment')
        self.cwd=self.out/'project';self.cwd.mkdir()
        self.python=str(Path(operation.get('interpreter',sys.executable)).absolute())
        self.wheel=root/plan['wheel']['path']
        freeze=v.json_bytes(v.bound_bytes(plan['frozen_source_inventory'],root))
        tool_root=Path(__file__).absolute().parent.parent
        for member in ('tools/acceptance_producers.py','tools/verify_host.py','tools/acceptance_runtime.py'):
            v.require(freeze['files'].get(member)==v.bytes_digest(v.regular_bytes(tool_root/member)), 'Unreviewed producer origin')
        self.producer_origins={m:freeze['files'][m] for m in ('tools/acceptance_producers.py','tools/verify_host.py','tools/acceptance_runtime.py')}
        # Mutating pip commands require an independently provisioned disposable venv.
        info=self.command([self.python,'-B','-c','import json,sys;print(json.dumps({"prefix":sys.prefix,"base":sys.base_prefix,"executable":sys.executable}))'],'interpreter')
        self.prefix=Path(v.json_bytes(v.regular_bytes(self.out/'interpreter/stdout.log'))['prefix']).absolute()
        owned=Path(operation.get('environment_owner','')).absolute()
        facts=v.json_bytes(v.regular_bytes(self.out/'interpreter/stdout.log'))
        v.require(owned.is_relative_to(root) and self.prefix.is_relative_to(owned) and facts['prefix']!=facts['base'],'Owned disposable installed environment required')
        v.require(facts['executable']==self.python,'Interpreter origin changed')
        if operation['kind']!='installed-cell':
            wheel=self.wheel;version=self.candidate['version']
            if operation.get('criterion')=='DoD-12':
                prior=operation.get('prior_wheel');v.bound_bytes(prior,root)
                wheel=root/prior['path'];version=operation.get('prior_version')
                v.require(version and version!=self.candidate['version'],'Reviewed prior runtime required')
            observed=v.observe_installed(self.python,self.cwd,self.out/'pre-operation',self.env,version,wheel)
            v.save_json(self.out/'pre-operation/observation.json',observed)
    def command(self,argv,name,artifact=None):
        result=v.command_receipt(argv,self.cwd,self.out/name,env=self.env,artifact=artifact)
        v.require(result['exit_code']==0 and not result['timed_out'],'Required operation failed: '+name)
        return v.file_reference(self.out/name/'receipt.json',self.root)
    def cli(self,name,*args):return self.command([self.python,'-B','-m','vybe_check','--root',self.env['VYBE_CHECK_ROOT'],*args],name)
    def installed_observation(self,name):
        observed=v.observe_installed(self.python,self.cwd,self.out/name,self.env,self.candidate['version'],self.wheel)
        v.save_json(self.out/name/'observation.json',observed)
        return observed,v.file_reference(self.out/name/'observation.json',self.root)
    def save(self,name,row):
        row['producer_origins']=self.producer_origins
        row['producer_system']=platform.system()
        v.save_json(self.out/name,row);return row


def installed_cell(context):
    c=context
    install=c.command([c.python,'-B','-m','pip','install','--no-index','--force-reinstall','--no-deps',str(c.wheel)],'install',artifact=c.wheel)
    observed,ref=c.installed_observation('observe')
    launch=c.cli('launch','--help')
    row={'kind':'installed-cell','scope':'native-observed','candidate':c.candidate,'system':platform.system(),
        'observation':ref,'observation_command':v.file_reference(c.out/'observe/receipt.json',c.root),
        'wheel_reference':c.plan['wheel'],'installed_artifact':c.plan['wheel'],'install_command':install,'launch_command':launch,'environment_location':observed['prefix']}
    v.validate_cell(row,c.candidate,c.root);return c.save('record.json',row)


def agent_installation(context):
    from vybe_check.install import registration_target,inventory,_package_bytes
    c=context;op=c.operation;agent=op.get('agent');managed=op.get('managed_scope')
    v.require(agent in ('codex','claude') and managed in ('user','project'),'Explicit agent and registration scope required')
    v.require(isinstance(op.get('interactive_arguments'),list) and all(isinstance(x,str) for x in op['interactive_arguments']), 'Reviewed interactive argument array required')
    persistence=op.get('persistence_review',{})
    v.require(persistence.get('reviewer') and persistence.get('notes') and persistence.get('official_source_url','').startswith('https://') and persistence.get('conversation_transcripts')=='Disabled', 'Reviewed native no-transcript configuration required')
    v.require(persistence.get('observation_kind')=='human-reviewed-outcome' and persistence.get('verified_version')==op.get('agent_version') and persistence.get('verified_arguments')==op['interactive_arguments'], 'Native persistence configuration has not been verified for this version')
    configuration=op.get('agent_configuration')
    v.require(configuration, 'Bound native no-transcript configuration required')
    configuration_raw=v.bound_bytes(configuration,c.root)
    v.require(persistence.get('configuration_sha256')==hashlib.sha256(configuration_raw).hexdigest(), 'Changed native persistence configuration')
    location={'codex':'.codex/config.toml','claude':'.claude/settings.json'}[agent]
    configured=copy_regular(c.root/configuration['path'],Path(c.env['HOME'])/location)
    v.require(v.regular_bytes(configured)==configuration_raw, 'Native configuration was not installed exactly')
    executable=Path(op.get('agent_executable','')).absolute()
    v.require(v.bytes_digest(v.regular_bytes(executable))==op.get('agent_executable_digest'),'Reviewed native executable bytes required')
    version=c.command([str(executable),'--version'],'agent-version')
    version_raw=v.regular_bytes(c.out/'agent-version/stdout.log');text=version_raw.decode().strip()
    v.require(text and op.get('agent_version')==text,'Exact reviewed native agent version changed')
    v.require(v.regular_bytes(configured)==configuration_raw, 'Native configuration changed during version observation')
    registration=c.cli('register','install','--agent',agent,'--scope',managed,*(['--project',str(c.cwd)] if managed=='project' else []))
    target=registration_target(agent,managed,c.cwd,home=Path(c.env['HOME']))
    files=inventory(target);canonical={name:hashlib.sha256(raw).hexdigest() for name,raw in _package_bytes().items()}
    v.require(files==canonical,'Installed registration differs from canonical bytes')
    v.save_json(c.out/'registration.json',{'scope':'observed-registration-files','path':str(target),'files':files})
    packets=agent_packets(c.out/'prompts');reviews={}
    for name,packet in packets.items():
        prompt=v.regular_bytes(packet['prompt']).decode()
        v.require(v.regular_bytes(configured)==configuration_raw, 'Native no-transcript configuration changed before launch')
        execute_interactive([str(executable),*op['interactive_arguments'],prompt],c.cwd,c.env,c.out/('interactive-'+name))
        print('Review the outcome for '+name+'. Enter the absolute path to outcome notes only:',flush=True)
        review=Path(input().strip())
        outcome=v.json_bytes(v.regular_bytes(review));v.validate_scenario(name,outcome)
        v.require(outcome.get('conversation_transcript') is None,'Transcripts are refused')
        saved=copy_regular(review,c.out/(name+'-review.json'))
        outcome['provenance']={'input':v.file_reference(packet['prompt'],c.root), 'review':v.file_reference(saved,c.root), 'version_log':v.file_reference(c.out/'agent-version/stdout.log',c.root)}
        v.validate_agent_results(name,outcome,c.root)
        # Retain independent copies of the exact creative bytes used in review.
        # Input packets, review notes, and executable logs are never results.
        for index,result in enumerate(outcome['results']):
            artifact=result['artifact']
            retained=copy_regular(c.root/artifact['path'],c.out/('result-'+name+'-'+str(index)+'.json'))
            result['artifact']=v.file_reference(retained,c.root)
        v.validate_agent_results(name,outcome,c.root)
        outcome.pop('artifacts',None)
        reviews[name]=outcome
    print('Enter the absolute path to reviewed native discovery outcome notes:',flush=True)
    discovery=v.json_bytes(v.regular_bytes(Path(input().strip())))
    v.require(discovery.get('agent_version')==text and discovery.get('loaded_registration')==str(target) and discovery.get('observation_kind')=='human-reviewed-outcome' and discovery.get('reviewer') and discovery.get('notes'),'Actual discovery review required')
    v.save_json(c.out/'discovery.json',discovery)
    return c.save('record.json',{'kind':'agent-installation','scope':'native-agent-observed','candidate':c.candidate,
        'agent':agent,'system':platform.system(),'agent_version':text,'agent_executable':str(executable),'agent_executable_digest':op['agent_executable_digest'],
        'version_output':v.file_reference(c.out/'agent-version/stdout.log',c.root),'version_command':version,'managed_scope':managed,'isolated_scope':str(target),
        'discovery_method':'native-agent-managed-registration','registration_receipt':registration,'saved_registration':v.file_reference(c.out/'registration.json',c.root),
        'canonical_skill_files':canonical,'discovery_review':v.file_reference(c.out/'discovery.json',c.root),'scenarios':reviews,'persistence_review':persistence,'interactive_arguments':op['interactive_arguments']})


def _native():
    installed()
    from vybe_check.credentials import native_backend
    backend=native_backend()
    v.require(type(backend).__module__=='vybe_check.credentials' and IDENTITIES.get(backend.identity)==BACKENDS[platform.system()],'Actual host native adapter required')
    return backend


def native_store(context):
    c=context;criterion=c.operation.get('criterion','DoD-11');commands=[]
    operation=None
    if criterion=='DoD-11.1':
        c.cli('register','install','--agent','codex','--scope','project','--project',str(c.cwd))
        operation=lambda:commands.append(c.cli('unregister','unregister','--agent','codex','--scope','project','--project',str(c.cwd)))
    elif criterion=='DoD-11.2':
        c.cli('register','install','--agent','codex','--scope','project','--project',str(c.cwd))
        def remove():
            commands.append(c.cli('unregister','unregister','--agent','codex','--scope','project','--project',str(c.cwd)))
            commands.append(c.command([c.python,'-B','-m','pip','uninstall','-y','vybe-check'],'pip-uninstall'))
        operation=remove
    v.require(c.python==sys.executable,'Native sentinel and operation must share the installed interpreter')
    result=sentinel_roundtrip(_native(),operation)
    v.require(result['scope']=='actual-native-store-probe','Synthetic native result refused')
    v.save_json(c.out/'probe.json',result)
    return c.save('record.json',{'kind':'native-store','scope':'native-store-observed','candidate':c.candidate,'system':platform.system(),
        'criterion':criterion,'namespace':result['namespace'],'backend':result['backend'],'store_version':platform.platform(),
        'outcomes':{'stored':True,'consumed_equal':result['equal'],'duplicate_preserved':result['duplicate_preserved'],'secret_logged':False},
        'service_unlocked':True,'access_outcome':'observed-access','consumed_after_operation':result['consumed_after_operation'],
        'operation':{'DoD-11.1':'unregister','DoD-11.2':'pip-uninstall'}.get(criterion),'commands':commands,'sanitised_probe':v.file_reference(c.out/'probe.json',c.root)})


def linux_service_state():
    installed();v.require(platform.system()=='Linux','Linux service observation required')
    import secretstorage
    try:
        connection=secretstorage.dbus_init()
        collection=secretstorage.get_default_collection(connection)
        return {'state':'explicitly-locked' if collection.is_locked() else 'available','scope':'actual-native-store-unavailable-probe','system':'Linux'}
    except secretstorage.exceptions.SecretServiceNotAvailableException:
        return {'state':'explicitly-unavailable','scope':'actual-native-store-unavailable-probe','system':'Linux'}
    # Permission and other errors deliberately propagate, never proving absence.


def _linux_unavailable_read():
    installed();v.require(platform.system()=='Linux','Linux unavailable read required')
    # Import and construct at this explicit seam so missing dependencies and
    # unexpected setup errors cannot be hidden by generic backend discovery.
    from secretstorage.exceptions import SecretServiceNotAvailableException
    from vybe_check.credentials import LinuxSecretService, StoreUnavailable
    try:
        backend=LinuxSecretService()
        return backend.get_password('vybe-check-acceptance-'+uuid.uuid4().hex,'Invented unavailable read')
    except SecretServiceNotAvailableException:
        raise StoreUnavailable() from None


def native_unavailable(context):
    from tools.acceptance_runtime import session
    c=context;v.require(c.python==sys.executable,'Native unavailable consumer must share installed interpreter')
    ref=c.command([c.python,'-B',str(Path(__file__).absolute()),'service-state'],'service-state')
    service=v.json_bytes(v.regular_bytes(c.out/'service-state/stdout.log'))
    service_again=linux_service_state()
    v.require(service_again==service, 'Native service state changed before the read')
    def read():return _linux_unavailable_read()
    def baseline():
        store,state=session(c.out/'baseline')
        state=store.apply(state['id'],state['revision'],'add_image_version',{'prompt':'A blue ceramic bowl on grey linen'})
        v.save_json(c.out/'baseline.json',state)
        return state['image_versions'][-1]['version']>1
    result=unavailable_sequence(read,baseline,service);v.save_json(c.out/'probe.json',result)
    return c.save('record.json',{'kind':'native-unavailable','scope':'native-unavailable-observed','candidate':c.candidate,'system':platform.system(),'store_state':service['state'],
        'service_state_command':ref,'sanitised_probe':v.file_reference(c.out/'probe.json',c.root)})


def installed_lifecycle(context):
    from tools.acceptance_runtime import registered
    from vybe_check.install import registration_target
    c=context;criterion=c.operation.get('criterion');commands=[]
    v.require(c.python==sys.executable,'Lifecycle fixtures must use the observed installed interpreter')
    v.require(criterion in ('DoD-9.3','DoD-10.2','DoD-12'),'Unsupported lifecycle operation')
    store,state,_=registered(c.out/'creative')
    retained=copy_regular(Path(v.__file__).absolute(),c.out/'retained-verify.py')
    def verify(label):
        output=c.out/(label+'.json')
        receipt=c.command([c.python,'-B',str(retained),'retained-state','--root',str(store.root),'--out',str(output)],label+'-command')
        return v.json_bytes(v.regular_bytes(output)),receipt
    before,before_cmd=verify('before-data');commands.append(before_cmd)
    c.cli('register-owned','install','--agent','codex','--scope','project','--project',str(c.cwd))
    modified_project=c.out/'modified-project';modified_project.mkdir()
    c.cli('register-modified','install','--agent','codex','--scope','project','--project',str(modified_project))
    modified=registration_target('codex','project',modified_project)/'SKILL.md'
    with modified.open('ab') as stream:stream.write(b'\nInvented local modification.\n')
    unrelated=c.cwd/'unrelated.txt';unrelated.write_bytes(b'Invented unrelated data')
    mb=v.bytes_digest(v.regular_bytes(modified));ub=v.bytes_digest(v.regular_bytes(unrelated))
    owned=registration_target('codex','project',c.cwd)
    version_code='import importlib.metadata,json;print(json.dumps({"version":importlib.metadata.version("vybe-check")}))'
    commands.append(c.command([c.python,'-B','-c',version_code],'before-version'))
    old=v.json_bytes(v.regular_bytes(c.out/'before-version/stdout.log'))['version']
    def operation():
        if criterion=='DoD-12':
            v.require(old!=c.candidate['version'],'Update needs an independently provisioned prior version')
            commands.append(c.command([c.python,'-B','-m','pip','install','--no-index','--upgrade',str(c.wheel)],'pip-update',artifact=c.wheel))
            commands.append(c.cli('update-registration','update-registration','--agent','codex','--scope','project','--project',str(c.cwd)))
            return
        commands.append(c.cli('detach-owned','unregister','--agent','codex','--scope','project','--project',str(c.cwd)))
        commands.append(c.command([c.python,'-B','-m','pip','uninstall','-y','vybe-check'],'pip-uninstall'))
    lifecycle_sequence(lambda:before,operation,lambda:verify('after-data')[0])
    after=v.json_bytes(v.regular_bytes(c.out/'after-data.json'))
    row={'kind':'installed-lifecycle','scope':'installed-lifecycle-observed','candidate':c.candidate,'criterion':criterion,'system':platform.system(),
        'commands':commands,'before_data':v.file_reference(c.out/'before-data.json',c.root),'after_data':v.file_reference(c.out/'after-data.json',c.root),
        'retained_verifier_code':v.file_reference(retained,c.root),'retained_verifier_origin':str(retained),'retained_verifier_command':v.file_reference(c.out/'after-data-command/receipt.json',c.root),
        'unrelated_before':ub,'unrelated_after':v.bytes_digest(v.regular_bytes(unrelated)),'modified_before':mb,'modified_after':v.bytes_digest(v.regular_bytes(modified)),
        'owned_detached':not owned.exists(),'prior_versions_readable':before==after,'old_runtime_version':old}
    if criterion=='DoD-12':
        commands.append(c.command([c.python,'-B','-c',version_code],'after-version'))
        row['new_runtime_version']=v.json_bytes(v.regular_bytes(c.out/'after-version/stdout.log'))['version']
        c.installed_observation('new-observation')
    else:
        code="import importlib.util,json;print(json.dumps({'package_absent':importlib.util.find_spec('vybe_check') is None}))"
        row['package_absence_command']=c.command([c.python,'-B','-c',code],'package-absence')
        v.require(v.json_bytes(v.regular_bytes(c.out/'package-absence/stdout.log'))=={'package_absent':True},'Package still imports after uninstall')
    return c.save('record.json',row)


def provider(context):
    from vybe_check import judge,credentials
    from vybe_check.workshop import SessionStore
    c=context;op=c.operation;route=op.get('route')
    v.require(route in ('typesafe','openrouter') and op.get('approval') and op.get('cost_receipt') and op.get('anonymous_input'),'Explicit independent provider inputs required')
    anonymous=v.json_bytes(v.bound_bytes(op['anonymous_input'],c.root))
    request=judge.prepare_request(anonymous,route)
    approval=v.json_bytes(v.bound_bytes(op['approval'],c.root));cost=v.json_bytes(v.bound_bytes(op['cost_receipt'],c.root))
    reason=judge.verify_consent(request,cost,approval)
    v.require(reason is None,'Provider consent refused: '+str(reason))
    # Preserve billing_unbounded before any credential access. No price override.
    state_root=Path(op['state_root']).absolute()
    v.require(state_root.is_relative_to(c.root),'Isolated provider state required')
    store=SessionStore(state_root);state=store.read(op['session'])
    backend=_native();consumptions=[];responses=[]
    class Consumer:
        def read(self,account):
            value=credentials.Credentials().read(account)
            consumptions.append({'route':account,'backend':IDENTITIES[backend.identity]})
            return value
    def transport(endpoint,key,body):
        v.require(not responses,'Retry or fallback refused')
        item={'attempt':1};responses.append(item)
        reply=judge.send_once(endpoint,key,body)
        item['reply']=reply;item['answers']=judge.validate_response(reply,request)
        return reply
    with (c.out/'request.json').open('xb') as stream:stream.write(request.body)
    result=judge.run_advice(request,cost,approval,store,state['id'],state['revision'],credentials=Consumer(),transport=transport)
    v.save_json(c.out/'attempt.json',{'status':result['status'],'consumed_attempts':len(responses),'native_consumptions':consumptions,'retry_count':0,'fallback_count':0})
    v.require(len(responses)==1 and len(consumptions)==1 and 'answers' in responses[0],'No single validated native provider response')
    return provider_record(c.candidate,route,c.out/'request.json',c.root/op['approval']['path'],c.root/op['cost_receipt']['path'],responses[0]['reply'],responses[0]['answers'],
        {'backend':consumptions[0]['backend'],'calls':len(responses)},c.out/'provider',c.root)


def local_study(context):
    c=context;op=c.operation
    config=v.json_bytes(v.regular_bytes(Path(op['state_root'])/'comfyui.json'))
    v.require(Path(op['state_root']).absolute().is_relative_to(c.root),'Owned local study data required')
    study_out=c.out/'studies'
    prior_root=os.environ['VYBE_CHECK_ROOT']
    os.environ['VYBE_CHECK_ROOT']=str(c.root)
    try:
        v.produce_studies(['--root',op['state_root'],'--session',op['session'],'--version',str(op['version']),'--checkpoint',op['checkpoint'],
            '--out',str(study_out),'--approval',op.get('approval','')])
    finally:os.environ['VYBE_CHECK_ROOT']=prior_root
    row=v.json_bytes(v.regular_bytes(study_out/'study.json'));row['candidate']=c.candidate
    # Rebase automatically produced image references into the plan evidence root.
    for study in row['studies']:
        for key in ('image','board_response'):
            study[key]=v.file_reference(study_out.parent/study[key]['path'],c.root)
    row['capability_controls']=v.file_reference(study_out.parent/row['capability_controls']['path'],c.root)
    v.save_json(c.out/'pending-study.json',row)
    print('Review the two displayed studies and enter an outcome-only visual review file path:',flush=True)
    review_path=Path(input().strip());review=v.json_bytes(v.regular_bytes(review_path))
    expected={study['id']:study['image']['sha256'] for study in row['studies']}
    v.require(review.get('candidate')==c.candidate and review.get('images')==expected and review.get('observation_kind')=='human-reviewed-outcome' and review.get('reviewer') and review.get('notes') and review.get('visual_confirmation')=='Both registered studies displayed','Separate actual visual review required')
    copy_regular(review_path,c.out/'visual-review.json');row['visual_review']=v.file_reference(c.out/'visual-review.json',c.root)
    row['visual_confirmation']=review['visual_confirmation']
    return c.save('record.json',row)


PRODUCERS={'installed-cell':installed_cell,'agent-installation':agent_installation,'native-store':native_store,
    'native-unavailable':native_unavailable,'installed-lifecycle':installed_lifecycle,'provider':provider,'local-study':local_study}


def operation_child(plan,root,index):
    """One native operation per disposable interpreter; no terminal transcript capture."""
    op=plan['operations'][index]
    interpreter=str(Path(op['interpreter']).absolute())
    if op.get('criterion') in ('DoD-11.2','DoD-9.3','DoD-10.2','DoD-12'):
        v.require(interpreter!=sys.executable,'Package mutation requires a separate disposable interpreter')
    out=root/'operation-children'/uuid.uuid4().hex;out.mkdir(parents=True,exist_ok=False)
    env=v.isolated_environment(out/'environment')
    env['VYBE_ACCEPTANCE_PLAN']=os.environ['VYBE_ACCEPTANCE_PLAN'];env['VYBE_ACCEPTANCE_PLAN_SHA256']=os.environ['VYBE_ACCEPTANCE_PLAN_SHA256']
    for key in ('VYBE_LAYOUT_BROWSER_EXECUTABLE',):
        if os.environ.get(key):env[key]=os.environ[key]
    result_path=out/'result.json'
    argv=[interpreter,'-B',str(Path(__file__).absolute()),'--plan',env['VYBE_ACCEPTANCE_PLAN'],'--plan-sha256',env['VYBE_ACCEPTANCE_PLAN_SHA256'],
        '--kind',op['kind'],'--operation-index',str(index),'--record-out',str(result_path)]
    v.save_json(out/'launch.json',{'argv':argv,'cwd':str(Path(__file__).absolute().parent.parent),'root_environment':{k:env[k] for k in v.ROOT_KEYS},'conversation_transcript':None})
    process=subprocess.Popen(argv,cwd=Path(__file__).absolute().parent.parent,env=env)
    initial=process.poll()
    try:code=process.wait(timeout=14400)
    except subprocess.TimeoutExpired:
        process.terminate();code=process.wait(timeout=10)
        v.save_json(out/'terminal.json',{'pid':process.pid,'initial_poll':initial,'wait_return':code,'final_poll':process.poll(),'timed_out':True})
        raise ValueError('Bounded native operation timed out') from None
    v.save_json(out/'terminal.json',{'pid':process.pid,'initial_poll':initial,'wait_return':code,'final_poll':process.poll(),'timed_out':False})
    v.require(code==0,'Native producer child failed; retain its observations')
    reference=v.json_bytes(v.regular_bytes(result_path))
    row=v.json_bytes(v.bound_bytes(reference,root))
    v.require(row.get('candidate')==plan['candidate'] and row.get('scope')!='authoring-synthetic','Child returned wrong candidate or synthetic evidence')
    row['_record_reference']=reference
    return row


def execute_required(kind,route=None):
    plan,root=execution_plan(os.environ.get('VYBE_ACCEPTANCE_PLAN'),os.environ.get('VYBE_ACCEPTANCE_PLAN_SHA256'))
    v.require(kind in PRODUCERS,'Unknown required producer')
    if _OPERATION_INDEX is not None and kind=='installed-cell':
        v.require(not os.environ.get('PYTHONPATH') and not os.environ.get('VYBE_AUTHORING_ONLY'),'Source cannot install an acceptance cell')
    else:installed()
    records=[]
    for reference in plan.get('records',[]):
        row=v.json_bytes(v.bound_bytes(reference,root))
        v.require(row.get('candidate')==plan['candidate'] and row.get('scope') not in (None,'authoring-synthetic','simulated'),'Prior record belongs to another candidate')
        records.append(row)
    for index,op in enumerate(plan['operations']):
        if op.get('kind')!=kind or op.get('system')!=platform.system() or (route and op.get('route')!=route) or (_OPERATION_INDEX is not None and index!=_OPERATION_INDEX):continue
        key=(os.environ['VYBE_ACCEPTANCE_PLAN_SHA256'],index)
        if key not in _CACHE:
            if _OPERATION_INDEX is None:
                row=operation_child(plan,root,index)
            else:
                context=Context(plan,root,op)
                previous={k:os.environ.get(k) for k in v.ROOT_KEYS}
                os.environ.update({k:context.env[k] for k in v.ROOT_KEYS})
                try:row=PRODUCERS[kind](context)
                finally:
                    for k,value in previous.items():
                        if value is None:os.environ.pop(k,None)
                        else:os.environ[k]=value
                context.save('completed-record.json',row)
                row['_record_reference']=v.file_reference(context.out/'completed-record.json',root)
            v.require(row.get('candidate')==plan['candidate'] and row.get('scope')!='authoring-synthetic','Producer did not observe native candidate')
            _CACHE[key]=row
        records.append(_CACHE[key])
    if _RECORD_OUT is not None:
        completed=[r['_record_reference'] for r in records if '_record_reference' in r]
        v.require(len(completed)==1,'One operation child record required')
        v.save_json(_RECORD_OUT,completed[0])
    selected=[row for row in records if row.get('kind')==kind and (route is None or row.get('route')==route)]
    v.require(selected,'Missing executable operation or independently bound native record')
    destination=root
    references=list(plan.get('records',[]))+[r['_record_reference'] for r in records if '_record_reference' in r]
    manifest={'schema':1,'scope':'final-native-release','candidate':plan['candidate'],'source':plan['source'],'wheel':plan['wheel'],'sdist':plan['sdist'],
        'frozen_source_inventory':plan['frozen_source_inventory'],'records':references,'execution_plan_sha256':os.environ['VYBE_ACCEPTANCE_PLAN_SHA256'],'final_release_criteria':'OPEN'}
    path=destination/('produced-manifest-'+uuid.uuid4().hex+'.json');v.save_json(path,manifest)
    print(json.dumps({'reviewable_manifest':str(path),'sha256':hashlib.sha256(v.regular_bytes(path)).hexdigest(),'size':len(v.regular_bytes(path))}),flush=True)
    return plan,selected,root


def main(argv=None):
    global _OPERATION_INDEX,_RECORD_OUT
    argv=sys.argv[1:] if argv is None else argv
    if argv==['service-state']:
        print(json.dumps(linux_service_state(),sort_keys=True));return 0
    parser=argparse.ArgumentParser(description='Execute explicitly reviewed native acceptance operations')
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--plan-sha256',required=True)
    parser.add_argument('--kind',choices=tuple(PRODUCERS),required=True);parser.add_argument('--route',choices=('typesafe','openrouter'))
    parser.add_argument('--operation-index',type=int);parser.add_argument('--record-out',type=Path)
    args=parser.parse_args(argv)
    v.require((args.operation_index is None)==(args.record_out is None),'Child index/output must be paired')
    _OPERATION_INDEX=args.operation_index;_RECORD_OUT=args.record_out
    if args.record_out is not None:
        v.require(args.record_out.absolute().is_relative_to(args.plan.absolute().parent),'Child result must be inside owned evidence root')
    os.environ['VYBE_ACCEPTANCE_PLAN']=str(args.plan.absolute());os.environ['VYBE_ACCEPTANCE_PLAN_SHA256']=args.plan_sha256
    _,records,_=execute_required(args.kind,args.route)
    print(json.dumps({'produced_records':len(records),'final_release_criteria':'OPEN'}));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError):
        print('Acceptance producer refused; retained evidence contains sanitised observations.',file=sys.stderr)
        raise SystemExit(2)
