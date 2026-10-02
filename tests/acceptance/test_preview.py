"""Explicit local study acceptance with controlled fixtures only."""
import json
from pathlib import Path


def test_cli_capability_without_configuration_is_safe(tmp_path, capsys):
    from vybe_check.cli import main
    result = main(['--root', str(tmp_path / 'state'), 'preview', 'capability'])
    assert result == 0
    assert json.loads(capsys.readouterr().out) == {'available': False, 'reason': 'Local study unavailable'}

import hashlib
import http.client
import importlib.util
import os
import queue
import runpy
import subprocess


def test_capability(tmp_path):
    from tools.acceptance_runtime import installed_guard
    from vybe_check.local_preview import ComfyPreview
    installed_guard()
    assert ComfyPreview(tmp_path / 'unconfigured').capability()['available'] is False
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import study_gate
    pending_gate(study_gate,'DoD-48')


def test_no_automatic_preview(tmp_path, monkeypatch):
    from tools.acceptance_runtime import environment, session
    from vybe_check.local_preview import ComfyPreview
    environment(tmp_path,monkeypatch)
    calls=[]
    monkeypatch.setattr(ComfyPreview,'generate',lambda *a,**kw:calls.append((a,kw)))
    store,state=session(tmp_path)
    state=store.apply(state['id'],state['revision'],'add_image_version',{'prompt':'A blue ceramic rim'})
    from vybe_check.export import agreed_export
    assert agreed_export(state)['version'] == 2 and calls == []


def test_versioned_outputs():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import study_gate
    pending_gate(study_gate,'DoD-51')


def test_promote_generated(tmp_path):
    from tools.acceptance_runtime import session,image
    store,state=session(tmp_path)
    picture=image(tmp_path)
    state=store.apply(state['id'],state['revision'],'record_preview',{'path':str(picture),'prompt_version':1,'model':'Transport control','workflow':'Synthetic transport only'})
    identifier=state['previews'][0]['id']
    state=store.apply(state['id'],state['revision'],'promote_preview',{'preview_id':identifier})
    assert state['previews'][0]['provenance']=='generated'
    assert identifier in str(state['visual_locks'])
import sys
import threading
from urllib.parse import urlsplit

import pytest


def _source_guard():
    import vybe_check
    import vybe_check.cli
    import vybe_check.workshop
    root = Path(__file__).resolve().parents[2]
    assert all(Path(m.__file__).resolve().is_relative_to(root / 'src')
               for m in (vybe_check, vybe_check.cli, vybe_check.workshop))
    return root


def _fixture_module():
    root = _source_guard()
    return runpy.run_path(str(root / 'tests/unit/test_local_transport.py'))


def _http(origin, route, body=None):
    target = urlsplit(origin)
    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=5)
    try:
        connection.request('GET' if body is None else 'POST', route,
            body=None if body is None else json.dumps(body),
            headers={} if body is None else {'Origin': origin, 'Content-Type':'application/json'})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


@pytest.fixture
def cli_board(tmp_path, request):
    source = _source_guard()
    helper = _fixture_module()
    fixture = helper['Fixture']()
    root = tmp_path / 'state'
    fixture.configure(root)
    store, state = helper['agreed'](root)
    home = tmp_path / 'child-home';home.mkdir()
    child_tmp=tmp_path/'child-tmp';child_tmp.mkdir()
    env = {k:os.environ[k] for k in ('PATH',) if k in os.environ}
    env.update({k:str(home) for k in ('HOME','USERPROFILE','LOCALAPPDATA','XDG_DATA_HOME')})
    env.update(TMPDIR=str(child_tmp), PYTHONPATH=str(source / 'src'), PYTHONDONTWRITEBYTECODE='1', VYBE_CHECK_ROOT=str(tmp_path/'unused-state'))
    command = [sys.executable, '-B', '-m', 'vybe_check', '--root',str(root),
               'board','--session',state['id'],'--port','0']
    if getattr(request, 'param', 'local') == 'local':command.append('--local-studies')
    record = {'argv':command,'cwd':str(source),'environment':env,'roots':{'state':str(root),'home':str(home)},
              'source':{name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in
              ('src/vybe_check/cli.py','src/vybe_check/local_preview.py','src/vybe_check/studio/server.py')}}
    # Reserve logs and initial record before launching the owned process.
    with (tmp_path/'board-launch.json').open('x') as out:json.dump(record,out,indent=2)
    stderr_path=tmp_path/'board-stderr.log';stdout_path=tmp_path/'board-stdout.log'
    errors=stderr_path.open('xb');output=stdout_path.open('xb')
    process=None;reader=None
    try:
        process=subprocess.Popen(command,cwd=source,env=env,stdout=subprocess.PIPE,stderr=errors)
        lines=queue.Queue()
        def read_line():
            line=process.stdout.readline();output.write(line);output.flush();lines.put(line)
        reader=threading.Thread(target=read_line);reader.start()
        line=lines.get(timeout=8);reader.join(2)
        assert not reader.is_alive();url=line.decode().strip();origin=url.split('/?')[0]
        assert urlsplit(origin).hostname=='127.0.0.1' and urlsplit(origin).port!=8765
        yield {'fixture':fixture,'store':store,'state':state,'origin':origin,'url':url,'root':root,'evidence':tmp_path}
    finally:
        if process is not None:
            if process.poll() is None:process.terminate()
            try:remaining,_=process.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill();remaining,_=process.communicate(timeout=4)
            output.write(remaining);output.flush()
            record.update(pid=process.pid,terminal_poll=process.poll(),returncode=process.returncode)
            assert process.poll() is not None
        if reader is not None:reader.join(2)
        errors.close();output.close();fixture.close()
        record['logs']={str(p):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size}
                        for p in (stdout_path,stderr_path)}
        with (tmp_path/'board-terminal.json').open('x') as out:json.dump(record,out,indent=2)


def test_real_source_cli_board_explicit_study(cli_board):
    value=cli_board;backend=value['fixture'];store=value['store'];state=value['state'];origin=value['origin']
    status,raw=_http(origin,'/api/capability');cap=json.loads(raw)
    assert status==200 and cap['available'] and cap['wholly_local'];assert cap['reference_modes']==['Text']
    assert not backend.posts
    request={'session_id':state['id'],'expected_revision':state['revision'],'nonce':store.nonce_for(state['id']),
             'prompt_version':1,'shot_id':'base'}
    status,raw=_http(origin,'/api/preview',{**request,'nonce':'synthetic-invalid'})
    assert status==403 and not backend.posts
    status,raw=_http(origin,'/api/preview',request);result=json.loads(raw)
    assert status==200 and len(backend.posts)==1;preview=result['previews'][-1]
    assert preview['prompt_version']==1 and preview['shot_id']=='base' and preview['provenance']=='generated'
    assert backend.posts[0]['prompt']['2']['inputs']['text']=='Ceramic base in shade'
    status,raw=_http(origin,preview['url']);assert status==200 and raw==backend.raw
    assert store.resolve_media(state['id'],preview['id']).read_bytes()==raw
    assert not (Path(value['evidence'])/'unused-state').exists()


def test_board_stale_completed_study_reconciles(cli_board):
    value=cli_board;backend=value['fixture'];store=value['store'];state=value['state'];origin=value['origin']
    saved={}
    def advance():
        newer=store.apply(state['id'],state['revision'],'draft_edit',{'target':'image','text':'Newer rim draft','shot_id':'rim'})
        saved['bytes']=(store.root/'sessions'/f"{state['id']}.json").read_bytes()
        saved['revision']=newer['revision']
    backend.change=advance
    status,raw=_http(origin,'/api/preview',{'session_id':state['id'],'expected_revision':state['revision'],
        'nonce':store.nonce_for(state['id']),'prompt_version':1,'shot_id':'rim'})
    result=json.loads(raw)
    assert status==409, (status,result)
    assert result=={'status':'unregistered','error':'Generation completed after the session changed. The file is preserved and not registered; reconcile it explicitly.'}
    assert (store.root/'sessions'/f"{state['id']}.json").read_bytes()==saved['bytes']
    paths=list((store.root/'media').rglob('look-study.png'));assert len(paths)==1 and paths[0].read_bytes()==backend.raw
    assert store.read(state['id'])['previews']==[] and len(backend.posts)==1


def test_actual_board_control_and_decode(cli_board):
    assert importlib.util.find_spec('playwright') is not None
    from playwright.sync_api import sync_playwright, expect
    value=cli_board;origin=value['origin']
    with sync_playwright() as playwright:
        options={'headless':True}
        executable=os.environ.get('VYBE_LAYOUT_BROWSER_EXECUTABLE')
        if executable:options['executable_path']=executable
        browser=playwright.chromium.launch(**options)
        context=browser.new_context()
        context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==urlsplit(origin).netloc else route.abort())
        try:
            page=context.new_page();page.set_default_timeout(5000);page.goto(value['url'])
            page.locator('#tab-references').click()
            expect(page.locator('#request-preview')).to_be_visible()
            assert len(value['fixture'].posts)==0
            page.locator('#request-preview').click()
            image=page.locator('#preview-grid img');expect(image).to_be_visible()
            assert image.evaluate('(img) => img.complete && img.naturalWidth === 13 && img.naturalHeight === 9')
            assert len(value['fixture'].posts)==1
            screenshot=value['evidence']/'controlled-board.png'
            assert not screenshot.exists();page.screenshot(path=str(screenshot))
            observation={'synthetic':True,'model_generation':False,'post_count':1,
                'image_dimensions':[13,9],'screenshot':str(screenshot),'sha256':hashlib.sha256(screenshot.read_bytes()).hexdigest()}
            with (value['evidence']/'controlled-board.json').open('x') as out:json.dump(observation,out,indent=2)
        finally:context.close();browser.close()


def test_default_commands_do_not_import_adapter(tmp_path):
    source=_source_guard();home=tmp_path/'home';home.mkdir()
    env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'PYTHONPATH':str(source/'src'),'PYTHONDONTWRITEBYTECODE':'1',
         'VYBE_CHECK_ROOT':str(tmp_path/'unused')}
    env.update({k:str(home) for k in ('HOME','USERPROFILE','LOCALAPPDATA','XDG_DATA_HOME')})
    code="import importlib.util,sys; assert importlib.util.find_spec('vybe_check.local_preview') is not None; from vybe_check.cli import main; main(['--root',sys.argv[1],'new']); assert 'vybe_check.local_preview' not in sys.modules"
    argv=[sys.executable,'-B','-c',code,str(tmp_path/'state')]
    with (tmp_path/'default-command-launch.json').open('x') as out:json.dump({'argv':argv,'cwd':str(source),'env':env},out)
    with (tmp_path/'default-command-stdout.log').open('xb') as out,(tmp_path/'default-command-stderr.log').open('xb') as err:
        child=subprocess.Popen(argv,cwd=source,env=env,stdout=out,stderr=err)
        child.wait(timeout=8);assert child.returncode==0 and child.poll()==0
    with (tmp_path/'default-command-terminal.json').open('x') as out:json.dump({'pid':child.pid,'returncode':child.returncode,'terminal_poll':child.poll()},out)


def test_live_study():
    from tools.acceptance_runtime import installed_guard
    if os.environ.get('VYBE_AUTHORING_ONLY') == '1':
        pytest.skip('PENDING real local checkpoint and browser study; authoring only')
    installed_guard()
    from tools.verify_host import study_gate, bound_bytes, regular_bytes
    record, evidence_root = study_gate('DoD-50')
    from vybe_check.local_preview import ComfyPreview
    from vybe_check.workshop import SessionStore
    from tools.acceptance_runtime import board
    root=Path(record['state_root']).absolute()
    assert root.is_relative_to(Path(record['isolated_parent']).absolute())
    store=SessionStore(root); state=store.read(record['session_id'])
    capability=ComfyPreview(root).capability()
    assert capability['available'] and capability['workflow_digest'] == record['workflow_digest']
    assert hashlib.sha256(regular_bytes(record['checkpoint_file'])).hexdigest() == record['checkpoint_sha256']
    selected=[]
    for observed in record['studies']:
        item=next(p for p in state['previews'] if p['id']==observed['id'])
        assert item['workflow'] == record['workflow_digest'] and item['model'] == capability['model']
        assert regular_bytes(store.resolve_media(state['id'],item['id'])) == bound_bytes(observed['image'],evidence_root)
        selected.append(item)
    assert len(selected)==2
    from playwright.sync_api import sync_playwright
    with board(store,state) as (_,origin), sync_playwright() as engine:
        options={'headless':True}
        if os.environ.get('VYBE_LAYOUT_BROWSER_EXECUTABLE'):
            options['executable_path']=os.environ['VYBE_LAYOUT_BROWSER_EXECUTABLE']
        browser=engine.chromium.launch(**options)
        try:
            page=browser.new_page();page.goto(origin,wait_until='networkidle')
            page.locator('#tab-references').click()
            for item,observed in zip(selected,record['studies']):
                status,raw=_http(origin,f"/media/{state['id']}/{item['id']}")
                assert status==200 and raw==bound_bytes(observed['board_response'],evidence_root)
                picture=page.locator('img[src$="'+item['id']+'"]')
                assert picture.count()==1
                picture.wait_for(state='visible')
                assert picture.evaluate('(image) => image.complete && image.naturalWidth > 0')
        finally:
            browser.close()


@pytest.mark.parametrize('cli_board',['default'],indirect=True)
def test_explicit_studies_refuse_unproven_existing_listener(cli_board):
    value=cli_board;source=_source_guard();store=value['store'];identifier=value['state']['id']
    origin=value['origin'];folder=value['evidence']
    status,raw=_http(origin,'/api/capability');assert status==200 and not json.loads(raw)['available']
    before={str(p.relative_to(store.root)):p.read_bytes() for p in store.root.rglob('*.json')}
    launch=json.loads((folder/'board-launch.json').read_text());env=launch['environment']
    argv=[sys.executable,'-B','-m','vybe_check','--root',str(store.root),'board','--session',identifier,
          '--port',str(urlsplit(origin).port),'--local-studies']
    with (folder/'reuse-launch.json').open('x') as out:json.dump({'argv':argv,'environment':env,'cwd':str(source)},out,indent=2)
    with (folder/'reuse-stdout.log').open('xb') as out,(folder/'reuse-stderr.log').open('xb') as err:
        child=subprocess.Popen(argv,cwd=source,env=env,stdout=out,stderr=err)
        try:child.wait(timeout=8)
        finally:
            if child.poll() is None:child.terminate();child.wait(timeout=4)
            with (folder/'reuse-terminal.json').open('x') as record:json.dump({'pid':child.pid,'returncode':child.returncode,'terminal_poll':child.poll(),'argv':argv},record)
    observed={'exit':child.returncode,'stdout':(folder/'reuse-stdout.log').read_text(),
              'stderr':(folder/'reuse-stderr.log').read_text()}
    assert observed['exit']==2, observed
    assert '--port' in observed['stderr'] and observed['stdout']==''
    status,raw=_http(origin,'/api/capability');assert status==200 and not json.loads(raw)['available']
    assert before=={str(p.relative_to(store.root)):p.read_bytes() for p in store.root.rglob('*.json')}
    assert value['fixture'].posts==[] and value['fixture'].gets==[]


_RECONCILE_FAILURES = ('missing-base-url', 'config-list', 'config-null', 'config-invalid-json',
                       'base-url-type', 'backend-list', 'backend-null', 'backend-node-type',
                       'backend-disconnect', 'changed-checkpoint')


def _change_reconciliation_input(value, case):
    backend=value['fixture'];path=value['root']/'comfyui.json'
    config=json.loads(path.read_text())
    if case=='missing-base-url':config.pop('base_url')
    elif case=='config-list':config=[]
    elif case=='config-null':config=None
    elif case=='config-invalid-json':path.write_text('{');return
    elif case=='base-url-type':config['base_url']=[]
    elif case=='backend-list':backend.info=[];return
    elif case=='backend-null':backend.info=None;return
    elif case=='backend-node-type':backend.info['SaveImage']=None;return
    elif case=='backend-disconnect':
        def disconnect():raise ConnectionResetError('Synthetic backend disconnect')
        backend.info_hook=disconnect;return
    elif case=='changed-checkpoint':config['checkpoint']='other.safetensors'
    else:raise AssertionError(case)
    path.write_text(json.dumps(config))


@pytest.mark.parametrize('case',_RECONCILE_FAILURES)
def test_completed_board_failure_preserves_reconciliation(cli_board,case):
    from PIL import Image
    value=cli_board;store=value['store'];state=value['state'];backend=value['fixture']
    paths=[store.root/'sessions'/f"{state['id']}.json",store.root/'registry'/f"{state['id']}.json"]
    before={str(p):p.read_bytes() for p in paths}
    # Configuration changes after submission. Backend changes occur in the
    # final capability request, after the image response and full decoding.
    def change_after_view():
        if any(route.startswith('/view?') for route in backend.gets):
            if case=='backend-disconnect':raise ConnectionResetError('Synthetic backend disconnect')
            _change_reconciliation_input(value,case)
    if case.startswith('backend-'):
        # The hook executes inside the actual final /object_info HTTP handler.
        backend.info_hook=change_after_view
    else:
        backend.change=lambda:_change_reconciliation_input(value,case)
    status,raw=_http(value['origin'],'/api/preview',{'session_id':state['id'],
        'expected_revision':state['revision'],'nonce':store.nonce_for(state['id']),
        'prompt_version':1,'shot_id':'rim'})
    result=json.loads(raw)
    files=list((store.root/'media').rglob('look-study.png'))
    assert len(files)==1 and files[0].read_bytes()==backend.raw
    with Image.open(files[0]) as image:image.load();assert image.size==(13,9)
    assert len(backend.posts)==1 and store.read(state['id'])['previews']==[]
    assert all(p.read_bytes()==before[str(p)] for p in paths)
    observation={'case':case,'http_status':status,'response':result,'posts':len(backend.posts),
        'requests':backend.gets,'decoded_size':[13,9],'saved':{'path':str(files[0]),
        'size':files[0].stat().st_size,'sha256':hashlib.sha256(files[0].read_bytes()).hexdigest()},
        'session_registry_unchanged':True,'registered':False}
    with (value['evidence']/'reconciliation-observation.json').open('x') as out:json.dump(observation,out,indent=2)
    print(json.dumps(observation),flush=True)
    assert status==409,(status,result)
    assert result=={'status':'unregistered','error':'Generation completed after the session changed. The file is preserved and not registered; reconcile it explicitly.'}
    assert 'current' not in result and str(store.root) not in raw.decode()


@pytest.mark.parametrize('case',_RECONCILE_FAILURES)
def test_malformed_board_input_refuses_before_submission(cli_board,case):
    value=cli_board;store=value['store'];state=value['state'];backend=value['fixture']
    paths=[store.root/'sessions'/f"{state['id']}.json",store.root/'registry'/f"{state['id']}.json"]
    before={str(p):p.read_bytes() for p in paths}
    _change_reconciliation_input(value,case)
    status,raw=_http(value['origin'],'/api/preview',{'session_id':state['id'],
        'expected_revision':state['revision'],'nonce':store.nonce_for(state['id']),
        'prompt_version':1,'shot_id':'rim'})
    assert status==409,(status,raw)
    assert json.loads(raw)=={'error':'Local study unavailable'}
    assert backend.posts==[] and not (store.root/'media').exists()
    assert all(p.read_bytes()==before[str(p)] for p in paths) and store.read(state['id'])['previews']==[]
    observation={'case':case,'http_status':status,'response':json.loads(raw),'posts':0,
                 'media_created':False,'session_registry_unchanged':True}
    with (value['evidence']/'pre-submit-observation.json').open('x') as out:json.dump(observation,out,indent=2)
    print(json.dumps(observation),flush=True)
