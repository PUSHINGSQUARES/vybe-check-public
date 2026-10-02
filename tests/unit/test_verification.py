"""Synthetic controls for verification mechanics, never release evidence."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def runner():
    path = ROOT / 'tools/verify_host.py'
    assert path.is_file(), 'Host runner and strict receipt aggregation are missing'
    spec = importlib.util.spec_from_file_location('verification_control', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def isolated(tmp_path):
    env = dict(os.environ)
    for key in ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'XDG_DATA_HOME', 'VYBE_CHECK_ROOT', 'TMPDIR'):
        path = tmp_path / key.lower()
        path.mkdir()
        env[key] = str(path)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


def test_runner_observes_actual_command_and_refuses_reuse(tmp_path):
    tool = runner()
    env = isolated(tmp_path)
    out = tmp_path / 'command'
    argv = [sys.executable, '-B', '-c', 'import sys; print("Observed output"); print("Observed error", file=sys.stderr); sys.exit(7)']
    receipt = tool.command_receipt(argv, tmp_path, out, env=env, timeout=10)
    assert receipt['exit_code'] == 7
    assert receipt['timed_out'] is False
    assert receipt['pid'] > 0 and receipt['wait_return'] == receipt['final_poll'] == 7
    assert receipt['argv'] == argv and receipt['system'] == __import__('platform').system()
    assert (out / 'stdout.log').read_bytes() == b'Observed output\n'
    assert (out / 'stderr.log').read_bytes() == b'Observed error\n'
    assert receipt['stdout_sha256'] == hashlib.sha256(b'Observed output\n').hexdigest()
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    with pytest.raises((ValueError, FileExistsError)):
        tool.command_receipt(argv, tmp_path, out, env=env, timeout=10)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before


def test_runner_timeout_retains_partial_bytes_and_no_retry(tmp_path):
    tool = runner()
    out = tmp_path / 'timeout'
    receipt = tool.command_receipt([sys.executable, '-B', '-c', 'import time; print("Before timeout", flush=True); time.sleep(10)'], tmp_path, out, env=isolated(tmp_path), timeout=3)
    assert receipt['timed_out'] is True
    assert receipt['exit_code'] != 0 and receipt['final_poll'] is not None
    assert (out / 'stdout.log').read_bytes() == b'Before timeout\n'
    assert receipt['attempt_count'] == 1


@pytest.mark.parametrize('argv', ['echo Unbounded', [], ['python', '-m', 'vybe_check', 'key', 'setup'], ['python', '-m', 'vybe_check', 'judge', 'run']])
def test_generic_capture_refuses_unsafe_or_secret_commands(tmp_path, argv):
    tool = runner()
    with pytest.raises(ValueError):
        tool.command_receipt(argv, tmp_path, tmp_path / 'refused', env=isolated(tmp_path), timeout=5)
    assert not (tmp_path / 'refused').exists()


def test_contract_exact_active_ids_and_named_probes():
    tool = runner()
    contract = tool.load_contract(ROOT / 'tools/acceptance_contract.json')
    assert len(contract) == 75
    assert len({row['id'] for row in contract}) == 75
    assert len({row['nodeid'] for row in contract}) == 75
    assert not {'DoD-9', 'DoD-10', 'DoD-11', 'DoD-33', 'DoD-64'} & {r['id'] for r in contract}
    for row in contract:
        path, name = row['nodeid'].split('::')
        import ast
        tree = ast.parse((ROOT / path).read_text())
        assert any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name for node in tree.body), row
        assert row['hosts'] and row['mode']


def test_contract_refuses_duplicate_missing_and_renumbered(tmp_path):
    tool = runner()
    original = json.loads((ROOT / 'tools/acceptance_contract.json').read_text())
    for index, changed in enumerate((original[:-1], original + [original[0]], [{**r, 'id': 'DoD-70'} if r['id'] == 'DoD-69' else r for r in original])):
        path = tmp_path / (str(index) + '.json')
        path.write_text(json.dumps(changed))
        with pytest.raises(ValueError): tool.load_contract(path)


def test_missing_matrix_and_fixture_evidence_cannot_pass():
    tool = runner()
    with pytest.raises(ValueError, match='Missing'):
        tool.validate_matrix([], {'version': '0.1.0rc1'})
    forged = {'kind': 'installed-cell', 'scope': 'authoring-synthetic', 'system': 'Darwin', 'python': '3.11.1', 'status': 'PASS'}
    with pytest.raises(ValueError):
        tool.validate_matrix([forged] * 12, {'version': '0.1.0rc1'})


def test_junit_exact_nodes_refuses_skip_omission_and_unexpected(tmp_path):
    tool = runner()
    node = 'tests/acceptance/test_state.py::test_prompt_history'
    clean = '<testsuites><testsuite><testcase classname="tests.acceptance.test_state" name="test_prompt_history"/></testsuite></testsuites>'
    assert tool.junit_nodes(clean.encode(), [node]) == [node]
    for changed in (clean.replace('/>', '><skipped/></testcase>'), clean.replace('test_prompt_history', 'test_other'), '<testsuites/>'):
        with pytest.raises(ValueError): tool.junit_nodes(changed.encode(), [node])


def test_receipt_reference_refuses_tamper_and_links(tmp_path):
    tool = runner()
    raw = tmp_path / 'result.json'; raw.write_text('{"scope":"authoring-synthetic"}')
    reference = tool.file_reference(raw, tmp_path)
    assert tool.bound_bytes(reference, tmp_path) == raw.read_bytes()
    raw.write_text('{"scope":"forged"}')
    with pytest.raises(ValueError): tool.bound_bytes(reference, tmp_path)
    link = tmp_path / 'linked'; link.symlink_to(raw)
    with pytest.raises(ValueError): tool.file_reference(link, tmp_path)


@pytest.mark.parametrize('changed', [
    {'implementation':'PyPy'}, {'version':'different'}, {'module_origin':'/invented/source/__init__.py'},
    {'python':'3.10.1'}, {'system':'Invented'}, {'package_files':{}}, {'dependencies':[]},
    {'scope':'authoring-synthetic'}, {'environment':{'PYTHONPATH':'/invented/source'}},
])
def test_observation_refuses_wrong_origin_version_or_incomplete(changed):
    tool = runner()
    observation = {'scope':'installed', 'system':'Darwin', 'implementation':'CPython', 'python':'3.11.1',
        'version':'0.1.0rc1', 'prefix':'/invented/env', 'module_origin':'/invented/env/site/vybe_check/__init__.py',
        'dependencies':[{'name':'Pillow','version':'12.0.0'}],
        'environment':{}, 'package_files':{'vybe_check/__init__.py':{'size':3,'sha256':hashlib.sha256(b'abc').hexdigest()}}}
    tool.validate_observation(observation, '0.1.0rc1', {'vybe_check/__init__.py':{'size':3,'sha256':hashlib.sha256(b'abc').hexdigest()}})
    with pytest.raises(ValueError):
        tool.validate_observation({**observation, **changed}, '0.1.0rc1', observation['package_files'])


def test_agent_and_provider_fixture_or_boolean_claims_are_refused():
    tool = runner()
    for record in ({}, {'scope':'authoring-synthetic','status':'PASS'}, {'scope':'native','passed':True}):
        with pytest.raises(ValueError): tool.validate_agents([record], {}, None)
        with pytest.raises(ValueError): tool.validate_provider(record, 'typesafe')


def test_actual_phase_receipts_refuse_skip_failure_or_omission():
    tool=runner(); node='tests/acceptance/test_state.py::test_prompt_history'
    rows=[{'nodeid':node,'when':when,'outcome':'passed'} for when in ('setup','call','teardown')]
    clean={'scope':'actual-pytest-phases','exit_code':0,'phases':rows}
    assert tool.validate_phases(json.dumps(clean).encode(),[node])['exit_code']==0
    for changed in ({**clean,'scope':'authoring-synthetic'}, {**clean,'phases':rows[:-1]},
                    {**clean,'phases':rows+[rows[0]]}, {**clean,'exit_code':1},
                    {**clean,'phases':[{**r,'outcome':'skipped'} if r['when']=='call' else r for r in rows]}):
        with pytest.raises(ValueError):tool.validate_phases(json.dumps(changed).encode(),[node])


def test_contract_mapping_cannot_be_swapped_between_active_ids(tmp_path):
    tool=runner(); rows=json.loads((ROOT/'tools/acceptance_contract.json').read_text())
    rows[0]['id'],rows[1]['id']=rows[1]['id'],rows[0]['id']
    target=tmp_path/'swapped.json';target.write_text(json.dumps(rows))
    with pytest.raises(ValueError):tool.load_contract(target)


def test_unknown_or_incomplete_agent_scenarios_refuse():
    tool=runner()
    for name,outcome in (('invented',{}),('video_modes',{'observation_kind':'human-reviewed-outcome','reviewer':'Invented reviewer','notes':'Invented control','invented_input':True,'facts':{'preserve':{}}})):
        with pytest.raises(ValueError):tool.validate_scenario(name,outcome)


def test_final_aggregation_without_reviewed_evidence_fails(monkeypatch):
    tool=runner();monkeypatch.delenv('VYBE_ACCEPTANCE_MANIFEST',raising=False)
    monkeypatch.delenv('VYBE_ACCEPTANCE_MANIFEST_SHA256',raising=False)
    with pytest.raises(ValueError,match='Missing'):tool.aggregate_release()


def test_retained_verifier_observes_media_and_saved_versions(tmp_path):
    from tools.acceptance_runtime import registered
    store,state,picture=registered(tmp_path)
    tool=runner(); observed=tool.retained_state(store.root)
    assert observed['scope']=='retained-state-observed' and len(observed['state_files'])==2
    assert observed['media'] and next(iter(observed['media'].values()))['sha256']==hashlib.sha256(picture.read_bytes()).hexdigest()
    before=observed['state_files']
    assert tool.retained_state(store.root)['state_files']==before
    picture.write_bytes(b'Changed synthetic media')
    assert tool.retained_state(store.root)['media'] != observed['media']


def agent_validator_control(tmp_path,monkeypatch):
    """Isolate result reachability in complete synthetic host records."""
    tool=runner();candidate={'synthetic':True};rows=[]
    monkeypatch.setattr(tool,'validate_command',lambda *a:None)
    # Native command/discovery and unrelated scenario fact boundaries are replaced.
    # Result reads, byte hashes, provenance separation, and validator calls are real.
    monkeypatch.setattr(tool,'validate_scenario',lambda *a:None)
    for system in tool.SYSTEMS:
        for agent in ('codex','claude'):
            dest=tmp_path/(system+'-'+agent);dest.mkdir();version='Synthetic boundary'
            (dest/'stdout.log').write_text(version)
            tool.save_json(dest/'version.json',{'argv':['never-executed','--version']})
            tool.save_json(dest/'registration.json',{'system':system,'argv':['never-executed','-B','-m','vybe_check','install',agent,'project']})
            tool.save_json(dest/'saved.json',{'scope':'observed-registration-files','path':'Synthetic registration','files':{'SKILL.md':'synthetic'}})
            tool.save_json(dest/'discovery.json',{'observation_kind':'human-reviewed-outcome','agent_version':version,'loaded_registration':'Synthetic registration','reviewer':'Synthetic reviewer','notes':'Synthetic boundary'})
            tool.save_json(dest/'notes.json',{'observation_kind':'human-reviewed-outcome','notes':'Outcome only'})
            ref=lambda name:tool.file_reference(dest/name,tmp_path)
            outcome={'artifacts':[ref('notes.json'),ref('stdout.log')],'facts':{},'provenance':{'input':ref('stdout.log'),'review':ref('notes.json'),'version_log':ref('stdout.log')}}
            rows.append({'scope':'native-agent-observed','candidate':candidate,'agent':agent,'system':system,'agent_version':version,
                'agent_executable':'never-executed','managed_scope':'project','isolated_scope':'Synthetic registration',
                'version_output':ref('stdout.log'),'version_command':ref('version.json'),'registration_receipt':ref('registration.json'),
                'saved_registration':ref('saved.json'),'canonical_skill_files':{'SKILL.md':'synthetic'},'discovery_review':ref('discovery.json'),
                'discovery_method':'native-agent-managed-registration','scenarios':{name:copy.deepcopy(outcome) for name in tool.SCENARIOS}})
    return tool,candidate,rows


def test_agent_validator_requires_creative_result_separately(tmp_path,monkeypatch):
    tool,candidate,rows=agent_validator_control(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='result|artifact'):tool.validate_agents(rows,candidate,tmp_path)


def test_agent_validator_reaches_result_check_for_every_scenario(tmp_path,monkeypatch):
    tool,candidate,rows=agent_validator_control(tmp_path,monkeypatch);visited=[]
    def observe(name,outcome,root):visited.append(name)
    monkeypatch.setattr(tool,'validate_agent_results',observe)
    assert len(tool.validate_agents(rows,candidate,tmp_path))==6
    assert visited==list(tool.SCENARIOS)*6


@pytest.mark.parametrize('mode',['missing_binding','hash','wrong_kind','prompt','reviewed_id','facts'])
def test_agent_result_negative_bindings(tmp_path,monkeypatch,mode):
    import runpy
    controls=runpy.run_path(str(ROOT/'tests/unit/test_acceptance_producers.py'))
    p,c,_,_=controls['agent_artifact_control'](tmp_path,monkeypatch)
    from tools import verify_host as v
    row=p.agent_installation(c);outcome=row['scenarios']['image_only'];result=outcome['results'][0]
    if mode=='missing_binding':result['fact_bindings'].pop()
    elif mode=='hash':outcome['reviewed_result_sha256']=['a'*64]
    elif mode=='wrong_kind':result['kind']='prompt'
    elif mode=='prompt':result['prompt_pointers']=['/title/missing']
    elif mode=='reviewed_id':result['reviewed_versions']=['Different',1]
    else:outcome['facts']['agreed_images']=2
    with pytest.raises(ValueError):v.validate_agent_results('image_only',outcome,tmp_path)


@pytest.mark.parametrize('name', ['empty_brief','one_question','complete_brief','image_only','draft_refinement','video_modes','model_advice','unavailable_optional'])
def test_agent_result_eight_scenario_contracts(tmp_path,name):
    """Generic creative-export schema only, never native scenario evidence."""
    tool=runner()
    facts={
        'empty_brief':{'proposed_concepts':1,'alternates':1,'agreed_versions':0},
        'one_question':{'questions_per_turn':[1]},
        'complete_brief':{'image_versions':1,'redundant_agreement_questions':0},
        'image_only':{'agreed_images':1,'video_versions':0},
        'draft_refinement':{'new_version_id':'v2','prior_version_id':'v1'},
        'video_modes':{mode:{'duration':5,'anchor_id':'v1','locks':['Blue glaze'],'durations':[5]} for mode in ('preserve','evolve','multishot')},
        'model_advice':{'input_mode':'image','official_source_url':'https://example.invalid/official','checked_date':'2026-10-02','uncertainty':'Schema control only'},
        'unavailable_optional':{'image_refinements':1,'unavailable_optional':'both'},
    }[name]
    payload={'id':'v1','prompt':'An invented blue bowl with a visible rim','creative':copy.deepcopy(facts)}
    result_path=tmp_path/'result.json';tool.save_json(result_path,payload)
    ref=tool.file_reference(result_path,tmp_path)
    required={
        'empty_brief':['proposed_concepts','alternates','agreed_versions'], 'one_question':[],
        'complete_brief':['image_versions'], 'image_only':['agreed_images','video_versions'],
        'video_modes':[mode+'/'+field for mode in ('preserve','evolve','multishot') for field in ('duration','anchor_id','locks','durations')],
        'model_advice':list(facts), 'unavailable_optional':['image_refinements'], 'draft_refinement':[],
    }[name]
    result={'kind':'session' if name=='image_only' else 'version' if name in ('video_modes','draft_refinement') else 'prompt',
        'artifact':ref,'prompt_pointers':['/prompt'],'version_pointers':['/id'],'reviewed_versions':['v1'],
        'fact_bindings':[{'fact':fact,'operation':'value','pointer':'/creative/'+fact} for fact in required]}
    results=[result]
    if name=='draft_refinement':
        facts.update(prior_before_sha256=ref['sha256'],prior_after_sha256=ref['sha256'])
        result['fact_bindings']=[{'fact':'prior_version_id','operation':'value','pointer':'/id'},
            {'fact':'prior_before_sha256','operation':'bytes_sha256'},{'fact':'prior_after_sha256','operation':'bytes_sha256'}]
        new=tmp_path/'new-version.json';tool.save_json(new,{'id':'v2','prompt':'An evolved blue bowl with a narrow rim'})
        results.append({'kind':'version','artifact':tool.file_reference(new,tmp_path),'prompt_pointers':['/prompt'],
            'version_pointers':['/id'],'reviewed_versions':['v2'],'fact_bindings':[{'fact':'new_version_id','operation':'value','pointer':'/id'}]})
    outcome={'observation_kind':'human-reviewed-outcome','reviewer':'Synthetic reviewer','notes':'Generic schema control',
        'invented_input':True,'conversation_transcript':None,'facts':facts,'results':results,
        'reviewed_result_sha256':[item['artifact']['sha256'] for item in results]}
    input_path=tmp_path/'input.txt';input_path.write_text('Invented instructions')
    log=tmp_path/'version.log';log.write_text('Synthetic executable version')
    review=tmp_path/'review.json';tool.save_json(review,outcome)
    outcome['provenance']={'input':tool.file_reference(input_path,tmp_path),'review':tool.file_reference(review,tmp_path),'version_log':tool.file_reference(log,tmp_path)}
    assert tool.validate_agent_results(name,outcome,tmp_path)==results
    # Rebind the altered bytes so this checks review/identifier consistency,
    # rather than relying only on an old reference detecting hash tampering.
    changed=tmp_path/'changed-result.json';tool.save_json(changed,{**payload,'id':'Different'})
    altered=copy.deepcopy(outcome);altered['results'][0]['artifact']=tool.file_reference(changed,tmp_path)
    altered['reviewed_result_sha256'][0]=altered['results'][0]['artifact']['sha256']
    with pytest.raises(ValueError):tool.validate_agent_results(name,altered,tmp_path)
