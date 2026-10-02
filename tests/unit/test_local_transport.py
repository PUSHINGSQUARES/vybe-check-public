"""Local transport controls use synthetic, decoded images, never models."""
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

import pytest
from PIL import Image

GRAPH = {
 '1': {'class_type':'CheckpointLoaderSimple','inputs':{'ckpt_name':'fixture.safetensors'}},
 '2': {'class_type':'CLIPTextEncode','inputs':{'text':'An invented still-life study','clip':['1',1]}},
 '3': {'class_type':'CLIPTextEncode','inputs':{'text':'','clip':['1',1]}},
 '4': {'class_type':'EmptyLatentImage','inputs':{'width':512,'height':768,'batch_size':1}},
 '5': {'class_type':'KSampler','inputs':{'seed':234,'steps':20,'cfg':7,'sampler_name':'euler','scheduler':'normal','denoise':1,'model':['1',0],'positive':['2',0],'negative':['3',0],'latent_image':['4',0]}},
 '6': {'class_type':'VAEDecode','inputs':{'samples':['5',0],'vae':['1',2]}},
 '7': {'class_type':'SaveImage','inputs':{'images':['6',0],'filename_prefix':'vybe-study'}}}

def definitions():
    numeric = {'seed': ['INT', {'min':0,'max':2**64-1}], 'steps':['INT',{'min':1,'max':10000,'step':1}],
        'cfg':['FLOAT',{'min':0,'max':100,'step':0.1}], 'denoise':['FLOAT',{'min':0,'max':1,'step':0.01}],
        'width':['INT',{'min':16,'max':16384,'step':8}], 'height':['INT',{'min':16,'max':16384,'step':8}],
        'batch_size':['INT',{'min':1,'max':4096,'step':1}]}
    types={'ckpt_name':[['fixture.safetensors']], 'text':['STRING',{}], 'clip':['CLIP'], 'model':['MODEL'],
        'positive':['CONDITIONING'], 'negative':['CONDITIONING'], 'latent_image':['LATENT'],
        'samples':['LATENT'], 'vae':['VAE'], 'images':['IMAGE'], 'filename_prefix':['STRING',{}],
        'sampler_name':[['euler','heun']], 'scheduler':[['normal','simple']]}
    outputs={'CheckpointLoaderSimple':['MODEL','CLIP','VAE'],'CLIPTextEncode':['CONDITIONING'],
        'EmptyLatentImage':['LATENT'],'KSampler':['LATENT'],'VAEDecode':['IMAGE'],'SaveImage':['IMAGE']}
    result={}
    for node in GRAPH.values():
        cls=node['class_type']
        result[cls]={'input':{'required':{k:copy.deepcopy(numeric.get(k,types.get(k))) for k in node['inputs']}},
            'output':outputs[cls], 'python_module':'nodes','output_node':cls=='SaveImage'}
    result['SaveImage']['input']['hidden']={'prompt':'PROMPT','extra_pnginfo':'EXTRA_PNGINFO'}
    return result

def picture(fmt='PNG'):
    image=Image.new('RGB',(13,9));image.putdata([(x*13,y*21,(x+y)*7) for y in range(9) for x in range(13)])
    out=BytesIO();image.save(out,format=fmt);return out.getvalue()

class Fixture:
    def __init__(self):
        self.info=definitions(); self.raw=picture();self.posts=[];self.gets=[];self.change=None
        self.output_change=None;self.history_change=None;self.redirect=False;self.pending=False;self.drip=False;self.info_hook=None;self.submitted={'prompt_id':'job-1','number':0}
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def answer(self,value,raw=False):
                data=value if raw else json.dumps(value).encode();self.send_response(200);self.end_headers()
                if raw and owner.drip:
                    for byte in data:
                        try:self.wfile.write(bytes([byte]));self.wfile.flush();time.sleep(0.02)
                        except OSError:break
                else:self.wfile.write(data)
            def do_GET(self):
                owner.gets.append(self.path)
                if owner.redirect:
                    self.send_response(302);self.send_header('Location','http://192.0.2.1:99/object_info');self.end_headers();return
                if self.path=='/object_info':
                    if owner.info_hook:owner.info_hook()
                    self.answer(owner.info)
                elif self.path.startswith('/history/'):
                    if owner.pending:self.answer({});return
                    prefix=owner.posts[-1]['prompt']['7']['inputs']['filename_prefix']
                    record={'filename':prefix+'_00001_.png','subfolder':'','type':'output'}
                    if owner.output_change:owner.output_change(record)
                    job={'outputs':{'7':{'images':[record]}},'status':{'completed':True,'status_str':'success'}}
                    if owner.history_change:owner.history_change(job)
                    self.answer({'job-1':job})
                elif self.path.startswith('/view?'):self.answer(owner.raw,True)
                else:self.send_error(404)
            def do_POST(self):
                owner.posts.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                if owner.change:owner.change()
                self.answer(owner.submitted)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join(4);assert not self.thread.is_alive()
    def configure(self,root):
        root.mkdir(exist_ok=True)
        (root/'comfyui.json').write_text(json.dumps({'base_url':self.url,'workflow':GRAPH,'prompt_node':'2','checkpoint':'fixture.safetensors'}))

@pytest.fixture
def backend():
    value=Fixture()
    try:yield value
    finally:value.close()

def adapter(root):
    from vybe_check.local_preview import ComfyPreview
    return ComfyPreview(root)

def agreed(root):
    from vybe_check.workshop import SessionStore
    store=SessionStore(root);state=store.create('Invented ceramic study')
    state=store.apply(state['id'],0,'direct_image',{'brief':{'outcome':'Ceramic light','subject_action':'Bowl turns','visual_priority':'Blue rim','frame':'Close view','light':'Soft reflected light'},'shots':[
        {'id':'rim','title':'Rim','prompt':'Blue rim under soft light'},
        {'id':'base','title':'Base','prompt':'Ceramic base in shade'}]})
    return store,state

@pytest.mark.parametrize('url', ['http://localhost:1','https://127.0.0.1:1','http://127.0.0.1',
 'http://127.1:80','http://2130706433:80','http://127.0.0.1:0','http://127.0.0.1:65536',
 'http://user@127.0.0.1:80','http://127.0.0.1:80/a','http://127.0.0.1:80?x','http://127.0.0.1:80#x',
 'http://::1:80','http://[::ffff:127.0.0.1]:80','http://127.0.0.1:80\\evil',' http://127.0.0.1:80'])
def test_origin_rejections(url):
    from vybe_check.local_preview import loopback_origin
    with pytest.raises(ValueError):loopback_origin(url)

@pytest.mark.parametrize('url',['http://127.0.0.1:8188','http://127.0.0.2:8188/','http://[::1]:8188'])
def test_numeric_origins(url):
    from vybe_check.local_preview import loopback_origin
    assert loopback_origin(url)==url.rstrip('/')

def test_live_capability_and_proxy_independence(tmp_path,backend,monkeypatch):
    backend.configure(tmp_path);monkeypatch.setenv('http_proxy','http://192.0.2.1:99');monkeypatch.setenv('HTTP_PROXY','http://192.0.2.1:99')
    cap=adapter(tmp_path).capability()
    assert cap['available'] and cap['wholly_local'];assert cap['model']=='fixture.safetensors'
    assert cap['reference_modes']==['Text'];assert len(cap['workflow_digest'])==64;assert not backend.posts

@pytest.mark.parametrize('change',[
 lambda x:x['CheckpointLoaderSimple']['input']['required']['ckpt_name'].__setitem__(0,['other']),
 lambda x:x['SaveImage'].__setitem__('python_module','custom_nodes.fake'),
 lambda x:x['SaveImage'].__setitem__('API_NODE',True),
 lambda x:x['CLIPTextEncode']['output'].__setitem__(0,'IMAGE'),
 lambda x:x['CheckpointLoaderSimple']['output'].__setitem__(1,'MODEL'),
 lambda x:x['EmptyLatentImage']['input']['required']['width'][1].__setitem__('max',256),
 lambda x:x['EmptyLatentImage']['input']['required']['width'][1].__setitem__('step',7),
 lambda x:x['KSampler']['input']['required']['steps'][1].__setitem__('min',21),
 lambda x:x['KSampler']['input']['required']['sampler_name'].__setitem__(0,['heun']),
 lambda x:x['KSampler']['input']['required']['scheduler'].__setitem__(0,['simple']),
 lambda x:x['SaveImage']['input']['required'].__setitem__('paid_token',['STRING']),
 lambda x:x['SaveImage']['input']['required'].__setitem__('images',['LATENT']),
])
def test_live_shape_refuses_malformed_definitions(tmp_path,backend,change):
    backend.configure(tmp_path);change(backend.info)
    assert adapter(tmp_path).capability()=={'available':False,'reason':'Local study unavailable'};assert not backend.posts

@pytest.mark.parametrize('change',[
 lambda g:g.__setitem__('8',copy.deepcopy(g['7'])),
 lambda g:g['7']['inputs'].__setitem__('extra_data',{}),
 lambda g:g['2']['inputs'].__setitem__('clip',['1',0]),
 lambda g:g['7'].__setitem__('class_type','CustomSave'),
 lambda g:g['4']['inputs'].__setitem__('batch_size',2),
 lambda g:g['4']['inputs'].__setitem__('width',513),
 lambda g:g['5']['inputs'].__setitem__('steps',True),
 lambda g:g['3']['inputs'].__setitem__('text','Arbitrary negative'),
])
def test_configuration_graph_refusals(tmp_path,backend,change):
    backend.configure(tmp_path);p=tmp_path/'comfyui.json';config=json.loads(p.read_text());change(config['workflow']);p.write_text(json.dumps(config))
    assert not adapter(tmp_path).capability()['available'];assert not backend.posts

def test_redirect_is_not_followed(tmp_path,backend):
    backend.configure(tmp_path);backend.redirect=True
    assert not adapter(tmp_path).capability()['available'];assert backend.gets==['/object_info']

@pytest.mark.parametrize('fmt',['PNG','JPEG','WEBP'])
def test_two_requests_preserve_first_and_generated_registry(tmp_path,backend,fmt):
    backend.configure(tmp_path);backend.raw=picture(fmt);store,state=agreed(tmp_path)
    owner=adapter(tmp_path);first=owner.generate(store,state['id'],state['revision'],1,'rim')
    one=first['previews'][-1];path=store.resolve_media(state['id'],one['id']);before=path.read_bytes()
    second=owner.generate(store,state['id'],first['revision'],1,'rim');two=second['previews'][-1]
    assert one['provenance']=='generated' and one['id']!=two['id'];assert path.read_bytes()==before
    assert path!=store.resolve_media(state['id'],two['id']);assert path.is_relative_to(tmp_path/'media')
    assert len(backend.posts)==2 and all(set(p)=={'prompt'} for p in backend.posts)
    for post in backend.posts:
        graph=post['prompt'];assert graph['2']['inputs']['text']=='Blue rim under soft light'
        original=copy.deepcopy(graph)
        for node,key in [('2','text'),('5','seed'),('7','filename_prefix')]:original[node]['inputs'][key]=GRAPH[node]['inputs'][key]
        assert original==GRAPH
    assert backend.posts[0]['prompt']['7']['inputs']['filename_prefix']!=backend.posts[1]['prompt']['7']['inputs']['filename_prefix']
    promoted=store.apply(state['id'],second['revision'],'promote_preview',{'preview_id':two['id']})
    assert promoted['visual_locks']==[two['id']]

@pytest.mark.parametrize('version,shot,revision',[(99,'rim',1),(1,'unknown',1),(1,None,1),(1,'rim',0),(True,'rim',1)])
def test_explicit_current_agreed_request_only(tmp_path,backend,version,shot,revision):
    backend.configure(tmp_path);store,state=agreed(tmp_path)
    with pytest.raises((ValueError,RuntimeError)):adapter(tmp_path).generate(store,state['id'],revision,version,shot)
    assert not backend.posts

def test_stale_completion_preserved_unregistered(tmp_path,backend):
    backend.configure(tmp_path);store,state=agreed(tmp_path)
    backend.change=lambda:store.apply(state['id'],state['revision'],'draft_edit',{'target':'image','text':'New draft','shot_id':'rim'})
    result=adapter(tmp_path).generate(store,state['id'],state['revision'],1,'rim')
    assert result['status']=='unregistered';assert result['reason']=='Session changed; reconcile this study explicitly'
    assert Path(result['path']).read_bytes()==backend.raw;assert store.read(state['id'])['previews']==[];assert len(backend.posts)==1

@pytest.mark.parametrize('raw',[b'',b'not an image',picture()[:-15]])
def test_invalid_output_bytes_never_register(tmp_path,backend,raw):
    backend.configure(tmp_path);backend.raw=raw;store,state=agreed(tmp_path)
    with pytest.raises(RuntimeError):adapter(tmp_path).generate(store,state['id'],1,1,'rim')
    assert store.read(state['id'])['previews']==[];assert len(backend.posts)==1

@pytest.mark.parametrize('change',[
 lambda r:r.__setitem__('filename','../escape.png'),lambda r:r.__setitem__('filename','other.png'),
 lambda r:r.__setitem__('subfolder','../escape'),lambda r:r.__setitem__('type','input'),
 lambda r:r.__setitem__('filename','http://192.0.2.1:99/a.png'),lambda r:r.__setitem__('extra','bad'),
])
def test_output_record_confined(tmp_path,backend,change):
    backend.configure(tmp_path);backend.output_change=change;store,state=agreed(tmp_path)
    with pytest.raises(RuntimeError):adapter(tmp_path).generate(store,state['id'],1,1,'rim')
    assert not any(x.startswith('/view') for x in backend.gets);assert not store.read(state['id'])['previews']

@pytest.mark.parametrize('change',[
 lambda j:j['outputs'].__setitem__('8',j['outputs'].pop('7')),
 lambda j:j['outputs']['7']['images'].append(j['outputs']['7']['images'][0]),
 lambda j:j['status'].__setitem__('status_str','error')])
def test_exact_job_save_record(tmp_path,backend,change):
    backend.configure(tmp_path);backend.history_change=change;store,state=agreed(tmp_path)
    with pytest.raises(RuntimeError):adapter(tmp_path).generate(store,state['id'],1,1,'rim')
    assert not any(x.startswith('/view') for x in backend.gets)

def test_bounded_polling_no_resubmit(tmp_path,backend,monkeypatch):
    import vybe_check.local_preview as module
    backend.configure(tmp_path);backend.pending=True;store,state=agreed(tmp_path)
    monkeypatch.setattr(module,'POLL_SECONDS',0.05)
    with pytest.raises(RuntimeError):adapter(tmp_path).generate(store,state['id'],1,1,'rim')
    assert len(backend.posts)==1

def test_image_decoder_rejects_bomb_warnings(tmp_path,monkeypatch):
    from vybe_check.local_preview import save_study
    monkeypatch.setattr(Image,'MAX_IMAGE_PIXELS',80)
    with pytest.raises(ValueError):save_study(picture(),tmp_path,'0'*32,1)
    assert list(tmp_path.iterdir())==[]

def test_image_decoder_size_limit(tmp_path):
    from vybe_check.local_preview import save_study
    with pytest.raises(ValueError):save_study(b'x'*(64*1024*1024+1),tmp_path,'0'*32,1)
    assert list(tmp_path.iterdir())==[]


def test_per_request_deadline_rejects_trickling_bytes(tmp_path,backend):
    backend.configure(tmp_path);backend.drip=True
    start=time.monotonic()
    with pytest.raises((ValueError,OSError)):
        adapter(tmp_path)._request(backend.url,'/view?synthetic=1',timeout=0.1,limit=1024)
    assert time.monotonic()-start<0.5


def test_refine_and_copy_do_not_generate(tmp_path,backend):
    from vybe_check.export import agreed_export
    backend.configure(tmp_path);store,state=agreed(tmp_path)
    state=store.apply(state['id'],state['revision'],'draft_edit',{'target':'image','shot_id':'rim','text':'Alternative rim'})
    result=agreed_export(state,'image',1)
    assert result and backend.posts==[] and backend.gets==[]


def test_state_changes_during_capability_refuse_before_submission(tmp_path,backend):
    backend.configure(tmp_path);store,state=agreed(tmp_path)
    def advance():
        backend.info_hook=None
        store.apply(state['id'],state['revision'],'draft_edit',{'target':'image','shot_id':'rim','text':'Alternative rim'})
    backend.info_hook=advance
    with pytest.raises(RuntimeError):adapter(tmp_path).generate(store,state['id'],state['revision'],1,'rim')
    assert backend.posts==[] and store.read(state['id'])['previews']==[]


def test_live_capability_changes_refuse_before_submission(tmp_path,backend):
    backend.configure(tmp_path);store,state=agreed(tmp_path);calls=[]
    def change():
        calls.append(1)
        if len(calls)==2:backend.info['KSampler']['display_name']='Changed live declaration'
    backend.info_hook=change
    with pytest.raises(RuntimeError):adapter(tmp_path).generate(store,state['id'],1,1,'rim')
    assert backend.posts==[]


@pytest.mark.parametrize('reply',[{'prompt_id':'../other'}, {'prompt_id':'job-1','node_errors':{'7':'bad'}}, {}])
def test_submission_failure_is_never_retried(tmp_path,backend,reply):
    backend.configure(tmp_path);backend.submitted=reply;store,state=agreed(tmp_path)
    with pytest.raises(RuntimeError):adapter(tmp_path).generate(store,state['id'],1,1,'rim')
    assert len(backend.posts)==1 and store.read(state['id'])['previews']==[]


def test_example_matches_shipped_template():
    from vybe_check.local_preview import CORE_WORKFLOW
    assert json.loads((Path(__file__).resolve().parents[2]/'examples/comfy-core.json').read_text())==CORE_WORKFLOW


def test_live_seed_bounds_control_fresh_seed(tmp_path,backend):
    backend.configure(tmp_path);backend.info['KSampler']['input']['required']['seed'][1]={'min':0,'max':256,'step':2}
    store,state=agreed(tmp_path);result=adapter(tmp_path).generate(store,state['id'],1,1,'rim')
    seed=backend.posts[0]['prompt']['5']['inputs']['seed']
    assert 0<=seed<=256 and seed%2==0 and result['previews']


import hashlib,os,stat
from pathlib import Path
from io import BytesIO
import pytest
from PIL import Image

def _tree_inventory(root):
 entries={'.':{'mode':root.lstat().st_mode,'mtime_ns':root.lstat().st_mtime_ns,'size':root.lstat().st_size}}
 for p in sorted(root.rglob('*')):
  s=p.lstat();entry={'mode':s.st_mode,'mtime_ns':s.st_mtime_ns,'size':s.st_size}
  if stat.S_ISLNK(s.st_mode):entry['target']=os.readlink(p)
  elif stat.S_ISREG(s.st_mode):entry['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
  entries[str(p.relative_to(root))]=entry
 return entries

def raw():
 out=BytesIO();Image.new('RGB',(3,2),(37,83,149)).save(out,format='PNG');return out.getvalue()

@pytest.mark.parametrize('location',['session','previews'])
def test_linked_descendant_preserves_complete_outside_inventory(tmp_path,location):
 from vybe_check.local_preview import save_study
 import vybe_check.local_preview as module
 origin=Path(os.environ.get('TASK09_TEST_ORIGIN',str(Path(__file__).resolve().parents[2])))
 assert Path(module.__file__).resolve()==origin/'src/vybe_check/local_preview.py'
 media=tmp_path/'media';media.mkdir();outside=tmp_path/'outside';outside.mkdir()
 nested=outside/'original';nested.mkdir();sentinel=nested/'sentinel.bin';sentinel.write_bytes(b'Invented unchanged sentinel')
 sid='0'*32
 link=media/sid
 if location=='previews':link.mkdir();link=link/'previews'
 link.symlink_to(outside,target_is_directory=True)
 before=_tree_inventory(outside);saved_link=os.readlink(link)
 with pytest.raises(ValueError):save_study(raw(),media,sid,1)
 after=_tree_inventory(outside)
 assert after==before,{'outside_before':before,'outside_after':after}
 assert sentinel.read_bytes()==b'Invented unchanged sentinel' and os.readlink(link)==saved_link


@pytest.mark.parametrize('location',['session','previews'])
def test_link_substitution_cannot_redirect_owned_directory_writes(tmp_path,monkeypatch,location):
    import vybe_check.local_preview as module
    media=tmp_path/'media';session=media/('0'*32);previews=session/'previews';previews.mkdir(parents=True)
    original=previews/'original.bin';original.write_bytes(b'Previous image bytes stay here')
    outside=tmp_path/'outside';outside.mkdir();sentinel=outside/'sentinel.bin';sentinel.write_bytes(b'Unchanged outside sentinel')
    before=_tree_inventory(outside);real_mkdir=module._mkdir_owned;swaps=[]
    def substitute(name,mode=0o777,*,dir_fd=None):
        if str(name).startswith('v001-') and not swaps:
            victim=session if location=='session' else previews
            retained=media/'retained-session' if location=='session' else session/'retained-previews'
            victim.rename(retained);victim.symlink_to(outside,target_is_directory=True)
            swaps.append(retained)
        return real_mkdir(name,mode,dir_fd=dir_fd)
    monkeypatch.setattr(module,'_mkdir_owned',substitute)
    with pytest.raises(ValueError):module.save_study(raw(),media,'0'*32,1)
    assert swaps and _tree_inventory(outside)==before
    assert sentinel.read_bytes()==b'Unchanged outside sentinel'
    previous=swaps[0]/'previews/original.bin' if location=='session' else swaps[0]/'original.bin'
    assert previous.read_bytes()==b'Previous image bytes stay here'
    victim=media/('0'*32) if location=='session' else session/'previews'
    assert victim.is_symlink() and os.readlink(victim)==str(outside)


def test_owned_fresh_media_creation_and_collision_preserve_first(tmp_path,monkeypatch):
    import vybe_check.local_preview as module
    from datetime import datetime,timezone
    from types import SimpleNamespace
    fixed=datetime(2026,1,2,tzinfo=timezone.utc)
    monkeypatch.setattr(module,'datetime',SimpleNamespace(now=lambda _:fixed))
    monkeypatch.setattr(module,'uuid4',lambda:SimpleNamespace(hex='f'*32))
    media=tmp_path/'fresh/parent/media';first=module.save_study(raw(),media,'0'*32,1)
    before=_tree_inventory(media)
    with pytest.raises(ValueError):module.save_study(raw(),media,'0'*32,1)
    assert _tree_inventory(media)==before and first.read_bytes()==raw()
    with Image.open(first) as decoded:
        decoded.load();assert decoded.size==(3,2) and decoded.getpixel((0,0))==(37,83,149)
    monkeypatch.setattr(module,'uuid4',lambda:SimpleNamespace(hex='e'*32))
    second=module.save_study(raw(),media,'0'*32,1)
    assert first!=second and first.read_bytes()==raw() and second.read_bytes()==raw()


def test_missing_no_follow_primitives_fail_before_mutation(tmp_path,monkeypatch):
    import vybe_check.local_preview as module
    store,state=agreed(tmp_path);preview=adapter(tmp_path);requests=[]
    monkeypatch.setattr(preview,'_request',lambda *args,**kwargs:requests.append((args,kwargs)))
    monkeypatch.setattr(module.os,'O_NOFOLLOW',0)
    before=_tree_inventory(tmp_path)
    with pytest.raises(ValueError):module.save_study(raw(),tmp_path/'media','0'*32,1)
    assert preview.capability()=={'available':False,'reason':'Local study unavailable'}
    with pytest.raises(RuntimeError,match='Local study unavailable'):preview.generate(store,state['id'],1,1,'rim')
    assert requests==[] and _tree_inventory(tmp_path)==before


class ControlledWindows:
    """Controlled handle model over fresh POSIX fixtures, never native Windows."""
    def __init__(self, root):
        self.root=root;self.handles={};self.calls=[];self.next=100;self.fail=None;self.hook=None
    def drive(self, anchor):
        self.calls.append(('drive',anchor));return 3
    def path(self, name):
        from pathlib import PureWindowsPath
        return self.root.joinpath(*PureWindowsPath(str(name)).parts[1:])
    def open(self,parent,name,*,create=False,directory=True):
        self.calls.append(('open',parent,name,create,directory))
        if self.fail=='open':raise ValueError('Controlled open refusal')
        if self.hook:self.hook(self,parent,name,create,directory)
        path=self.root if parent is None else self.handles[parent]['path']/name
        parent_fd=None if parent is None else self.handles[parent]['fd']
        fd=None
        if create:
            if directory:
                os.mkdir(name,dir_fd=parent_fd);fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent_fd)
            else:fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent_fd)
        elif path.is_symlink():pass
        else:fd=os.open(str(path) if parent is None else name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent_fd)
        if not path.exists() and not path.is_symlink():
            if fd is not None:os.close(fd)
            raise FileNotFoundError()
        self.next+=1;h=self.next
        # Keep the acquired identity independent of later path substitutions.
        s=path.lstat();self.handles[h]={'path':path,'identity':(s.st_dev,s.st_ino),'directory':directory,'fd':fd}
        return h
    def info(self,h):
        self.calls.append(('info',h));v=self.handles[h];p=v['path'];s=p.lstat()
        flags=0x400 if p.is_symlink() else 0x10 if p.is_dir() else 0x80
        index=s.st_ino
        if self.fail=='identity':index=0
        return flags,1 if p.is_symlink() else 0,s.st_dev,index,chr(92)*2+'?'+chr(92)+'C:'+chr(92)+str(p.relative_to(self.root)).replace('/',chr(92)).rstrip('.')
    def write(self,h,raw):
        self.calls.append(('write',h,len(raw)))
        if self.fail=='write':raise ValueError('Controlled write refusal')
        os.write(self.handles[h]['fd'],raw);os.fsync(self.handles[h]['fd'])
    def close(self,h):
        self.calls.append(('close',h));assert h in self.handles
        fd=self.handles[h]['fd']
        if fd is not None:os.close(fd)
        del self.handles[h]


def controlled_windows(tmp_path,monkeypatch):
    import types
    import vybe_check.local_preview as module
    api=ControlledWindows(tmp_path)
    fake=types.SimpleNamespace(**vars(module.os));fake.name='nt';monkeypatch.setattr(module,'os',fake)
    monkeypatch.setattr(module,'_windows_bindings',lambda:api)
    original=module._windows_parts
    def parts(root):
        text=str(root).replace('\\','/')
        prefix=str(tmp_path)
        if text.startswith(prefix+'/'):root='C:/'+text[len(prefix)+1:]
        return original(root)
    monkeypatch.setattr(module,'_windows_parts',parts)
    monkeypatch.setattr(module,'Path',lambda value:api.path(value) if str(value).startswith('C:') else Path(value))
    return module,api


def test_controlled_windows_fresh_decode_and_exclusive_collision(tmp_path,monkeypatch):
    from datetime import datetime,timezone
    from types import SimpleNamespace
    module,api=controlled_windows(tmp_path,monkeypatch)
    monkeypatch.setattr(module,'datetime',SimpleNamespace(now=lambda _:datetime(2026,1,2,tzinfo=timezone.utc)))
    monkeypatch.setattr(module,'uuid4',lambda:SimpleNamespace(hex='f'*32))
    first=module.save_study(raw(),'C:/media','0'*32,1);before=_tree_inventory(tmp_path)
    assert first.read_bytes()==raw() and api.handles=={}
    with Image.open(first) as image:image.load();assert image.size==(3,2) and image.getpixel((0,0))==(37,83,149)
    with pytest.raises((ValueError,OSError)):module.save_study(raw(),'C:/media','0'*32,1)
    assert _tree_inventory(tmp_path)==before and first.read_bytes()==raw() and api.handles=={}
    assert any(c[0]=='open' and c[3] and not c[4] for c in api.calls)


@pytest.mark.parametrize('location',['media','session','previews'])
def test_controlled_windows_links_preserve_outside_inventory(tmp_path,monkeypatch,location):
    outside=tmp_path/'outside';outside.mkdir();(outside/'sentinel').write_bytes(b'Outside unchanged')
    target=tmp_path/'media'
    if location!='media':target.mkdir();target/='0'*32
    if location=='previews':target.mkdir();target/='previews'
    target.symlink_to(outside,target_is_directory=True);before=_tree_inventory(outside)
    module,api=controlled_windows(tmp_path,monkeypatch)
    with pytest.raises(ValueError):module.save_study(raw(),'C:/media','0'*32,1)
    assert _tree_inventory(outside)==before and target.is_symlink() and api.handles=={}
    assert not any(c[0]=='open' and c[3] for c in api.calls)


def test_controlled_windows_substitution_refuses_before_child_creation(tmp_path,monkeypatch):
    previews=tmp_path/'media'/('0'*32)/'previews';previews.mkdir(parents=True);(previews/'original').write_bytes(b'Previous preserved')
    outside=tmp_path/'outside';outside.mkdir();(outside/'sentinel').write_bytes(b'Outside preserved');before=_tree_inventory(outside)
    module,api=controlled_windows(tmp_path,monkeypatch);original=api.info;swaps=[]
    def info(h):
        if api.handles[h]['path']==previews and not swaps:
            retained=previews.parent/'retained';previews.rename(retained);previews.symlink_to(outside,target_is_directory=True);swaps.append(retained)
        return original(h)
    monkeypatch.setattr(api,'info',info)
    with pytest.raises(ValueError):module.save_study(raw(),'C:/media','0'*32,1)
    assert swaps and _tree_inventory(outside)==before and (swaps[0]/'original').read_bytes()==b'Previous preserved' and api.handles=={}


@pytest.mark.parametrize('failure',['open','identity'])
def test_controlled_windows_safety_failure_has_zero_transport_and_mutation(tmp_path,monkeypatch,failure):
    store,state=agreed(tmp_path);module,api=controlled_windows(tmp_path,monkeypatch);api.fail=failure
    preview=adapter(tmp_path);requests=[];monkeypatch.setattr(preview,'_request',lambda *a,**k:requests.append((a,k)))
    before=_tree_inventory(tmp_path)
    assert preview.capability()=={'available':False,'reason':'Local study unavailable'}
    with pytest.raises(RuntimeError):preview.generate(store,state['id'],1,1,'rim')
    assert requests==[] and _tree_inventory(tmp_path)==before and api.handles=={}


@pytest.mark.parametrize('root',['//server/share/media','C:relative','C:/media/../outside','C:/CON','C:/media:stream','C:/trailing.'])
def test_controlled_windows_rejects_invalid_root_without_native_mutation(tmp_path,monkeypatch,root):
    module,api=controlled_windows(tmp_path,monkeypatch);before=_tree_inventory(tmp_path)
    with pytest.raises(ValueError):module.save_study(raw(),root,'0'*32,1)
    assert _tree_inventory(tmp_path)==before and api.calls==[]


def test_posix_writer_never_binds_windows_api(tmp_path,monkeypatch):
    import vybe_check.local_preview as module
    monkeypatch.setattr(module,'_windows_bindings',lambda:pytest.fail('Unexpected native binding'))
    first=module.save_study(raw(),tmp_path/'media','0'*32,1);assert first.read_bytes()==raw()


def test_windows_raw_binding_flags_status_and_owned_handles(monkeypatch):
    import ctypes,types
    import vybe_check.local_preview as module
    calls=[];outcome={'status':0,'information':1,'handle':321};closed=[]
    class Function:
        def __init__(self,fn):self.fn=fn
        def __call__(self,*a):return self.fn(*a)
    def create(output,access,attrs,status,allocation,file_attributes,share,disposition,options,ea,length):
        a=attrs._obj;u=a.ObjectName.contents
        calls.append({'parent':a.RootDirectory,'name':ctypes.wstring_at(u.Buffer),'length':u.Length,'attributes':a.Attributes,'access':access,'share':share,'disposition':disposition,'options':options,'security':a.SecurityDescriptor,'allocation':allocation,'ea':ea,'ea_length':length})
        output._obj.value=outcome['handle'];status._obj.Information=outcome['information'];return outcome['status']
    kernel=types.SimpleNamespace(**{name:Function(lambda *a:1) for name in ['GetDriveTypeW','GetFileType','GetFileInformationByHandle','GetFileInformationByHandleEx','GetFinalPathNameByHandleW','WriteFile','FlushFileBuffers']})
    kernel.CloseHandle=Function(lambda h:closed.append(h.value if hasattr(h,'value') else h) or 1)
    native=types.SimpleNamespace(NtCreateFile=Function(create));loads=[]
    def load(name,**kw):loads.append((name,kw));return native if name=='ntdll.dll' else kernel
    monkeypatch.setattr(ctypes,'WinDLL',load,raising=False)
    api=module._windows_bindings();assert loads==[('kernel32.dll',{'use_last_error':True}),('ntdll.dll',{})]
    owned=api.open(None,'C:'+chr(92));assert owned==321
    first=calls[-1];assert first['parent'] is None and first['name']==chr(92)+'??'+chr(92)+'C:'+chr(92)
    assert first['attributes']==0x40 and first['share']==1 and first['disposition']==1 and first['options']==0x200020
    assert first['access']==0x1000a0 and first['security'] is None and first['ea'] is None
    outcome['information']=2;api.open(owned,'new',create=True)
    created=calls[-1];assert created['parent']==owned and created['name']=='new' and created['disposition']==2 and created['options']==0x21
    api.open(owned,'look-study.png',create=True,directory=False)
    file=calls[-1];assert file['share']==0 and file['disposition']==2 and file['options']==0x200060 and file['access']==0x120196
    outcome.update(status=-1073741772,handle=999)
    with pytest.raises(FileNotFoundError):api.open(owned,'missing')
    assert closed==[]
    outcome.update(status=0,information=3,handle=444)
    with pytest.raises(ValueError):api.open(owned,'unexpected')
    assert closed==[444]
    api.close(owned);assert closed==[444,321]
    assert native.NtCreateFile.restype is ctypes.c_int32 and len(native.NtCreateFile.argtypes)==11
    kernel.GetFileType.fn=lambda h:1
    def information(h,p):
        p._obj.attributes=0x10;p._obj.volume=7;p._obj.index_low=9;return 1
    def tags(h,kind,p,size):
        assert kind==9 and size==8;p._obj[0]=0x10;p._obj[1]=0;return 1
    def final(h,buffer,size,flags):
        assert flags==0;buffer.value=chr(92)*2+'?'+chr(92)+'C:'+chr(92);return len(buffer.value)
    kernel.GetFileInformationByHandle.fn=information;kernel.GetFileInformationByHandleEx.fn=tags;kernel.GetFinalPathNameByHandleW.fn=final
    assert api.info(owned)==(0x10,0,7,9,chr(92)*2+'?'+chr(92)+'C:'+chr(92))
    written=[]
    def write(h,buffer,size,count,overlapped):
        assert h==owned and overlapped is None
        n=min(2,size);written.append(ctypes.string_at(buffer,n));count._obj.value=n;return 1
    kernel.WriteFile.fn=write;api.write(owned,b'abcdef');assert b''.join(written)==b'abcdef'
    kernel.FlushFileBuffers.fn=lambda h:0
    with pytest.raises(ValueError):api.write(owned,b'ghi')
    kernel.GetFileInformationByHandleEx.fn=lambda *a:0
    with pytest.raises(ValueError):api.info(owned)


def test_controlled_windows_actual_adapter_registration(tmp_path,monkeypatch,backend):
    backend.configure(tmp_path);store,state=agreed(tmp_path)
    module,api=controlled_windows(tmp_path,monkeypatch);preview=adapter(tmp_path)
    capability=preview.capability();assert capability['available'] and api.handles=={}
    result=preview.generate(store,state['id'],1,1,'rim')
    assert len(backend.posts)==1 and result['previews'] and api.handles=={}
    generated=result['previews'][-1];path=store.resolve_media(state['id'],generated['id'])
    with Image.open(path) as image:image.load();assert image.size==(13,9) and image.getpixel((1,1))==(13,21,14)
    assert any(c[0]=='write' for c in api.calls)


@pytest.mark.parametrize('location',['session','previews'])
def test_controlled_windows_substitution_during_create_never_redirects(tmp_path,monkeypatch,location):
    session=tmp_path/'media'/('0'*32);previews=session/'previews';previews.mkdir(parents=True);(previews/'original').write_bytes(b'Previous bytes')
    outside=tmp_path/'outside';outside.mkdir();(outside/'sentinel').write_bytes(b'Outside bytes');before=_tree_inventory(outside)
    module,api=controlled_windows(tmp_path,monkeypatch);swaps=[]
    def hook(api,parent,name,create,directory):
        if create and name.startswith('v001-') and not swaps:
            victim=session if location=='session' else previews;retained=victim.parent/'retained'
            victim.rename(retained);victim.symlink_to(outside,target_is_directory=True);swaps.append(retained)
    api.hook=hook
    with pytest.raises((ValueError,OSError)):module.save_study(raw(),'C:/media','0'*32,1)
    assert swaps and _tree_inventory(outside)==before and api.handles=={}
    previous=swaps[0]/'previews/original' if location=='session' else swaps[0]/'original'
    assert previous.read_bytes()==b'Previous bytes'


@pytest.mark.parametrize('drive',[0,1,4,5,6])
def test_controlled_windows_remote_or_unknown_drive_refuses(tmp_path,monkeypatch,drive):
    module,api=controlled_windows(tmp_path,monkeypatch);monkeypatch.setattr(api,'drive',lambda _:drive);before=_tree_inventory(tmp_path)
    with pytest.raises(ValueError):module.save_study(raw(),'C:/media','0'*32,1)
    assert api.calls==[] and api.handles=={} and _tree_inventory(tmp_path)==before


def test_controlled_windows_missing_binding_refuses_without_transport(tmp_path,monkeypatch):
    module,api=controlled_windows(tmp_path,monkeypatch);store,state=agreed(tmp_path);preview=adapter(tmp_path);requests=[]
    def unavailable():raise AttributeError('Controlled missing native API')
    monkeypatch.setattr(module,'_windows_bindings',unavailable);monkeypatch.setattr(preview,'_request',lambda *a,**k:requests.append((a,k)))
    before=_tree_inventory(tmp_path)
    assert preview.capability()=={'available':False,'reason':'Local study unavailable'}
    with pytest.raises(RuntimeError):preview.generate(store,state['id'],1,1,'rim')
    assert requests==[] and _tree_inventory(tmp_path)==before


@pytest.mark.parametrize('force_failure',[False,True])
def test_native_flush_independent_write_contract_and_owned_closure(monkeypatch,force_failure):
    import ctypes,types
    import vybe_check.local_preview as module
    origin=Path(os.environ.get('TASK09_TEST_ORIGIN',str(Path(module.__file__).resolve().parents[2])))
    assert Path(module.__file__).resolve()==origin/'src/vybe_check/local_preview.py'
    # Independent oracle from Microsoft FILE_GENERIC_WRITE, not production mask.
    standard_write=0x00020000;write_data=0x2;append_data=0x4;write_ea=0x10;write_attributes=0x100;synchronise=0x100000
    required=standard_write|write_data|append_data|write_ea|write_attributes|synchronise
    rights={};created=[];closed=[];written=[];flush=[];next_handle=[40]
    class Function:
        def __init__(self,fn):self.fn=fn
        def __call__(self,*args):return self.fn(*args)
    def create(output,access,attrs,status,allocation,attributes,share,disposition,options,ea,length):
        a=attrs._obj;name=ctypes.wstring_at(a.ObjectName.contents.Buffer)
        next_handle[0]+=1;h=next_handle[0];rights[h]=access;output._obj.value=h;status._obj.Information=2 if disposition==2 else 1
        created.append({'handle':h,'parent':a.RootDirectory,'name':name,'access':hex(access),'share':share,'disposition':disposition,'options':hex(options)})
        return 0
    def write(h,buffer,size,count,overlapped):
        assert h in rights and rights[h]&write_data and overlapped is None
        n=min(3,size);written.append(ctypes.string_at(buffer,n));count._obj.value=n;return 1
    def flush_file(h):
        sufficient=(rights[h]&required)==required
        flush.append({'handle':h,'required':hex(required),'actual':hex(rights[h]),'sufficient':sufficient,'forced_failure':force_failure})
        return int(sufficient and not force_failure)
    def close(h):
        h=h.value if hasattr(h,'value') else h
        assert h in rights and h not in closed;closed.append(h);return 1
    kernel=types.SimpleNamespace(**{name:Function(lambda *args:1) for name in ['GetDriveTypeW','GetFileType','GetFileInformationByHandle','GetFileInformationByHandleEx','GetFinalPathNameByHandleW']})
    kernel.WriteFile=Function(write);kernel.FlushFileBuffers=Function(flush_file);kernel.CloseHandle=Function(close)
    native=types.SimpleNamespace(NtCreateFile=Function(create))
    monkeypatch.setattr(ctypes,'WinDLL',lambda name,**kwargs:native if name=='ntdll.dll' else kernel,raising=False)
    api=module._windows_bindings();owned=[];error=None;raw=b'Invented complete output bytes'
    try:
        parent=api.open(None,'C:'+chr(92));owned.append(parent)
        file=api.open(parent,'look-study.png',create=True,directory=False);owned.append(file)
        api.write(file,raw)
    except ValueError as failure:error=str(failure)
    finally:
        for h in reversed(owned):api.close(h)
    observation={'created':created,'flush':flush,'closed':closed,'error':error,'bytes_sha256':hashlib.sha256(b''.join(written)).hexdigest(),'bytes_count':len(b''.join(written))}
    print(json.dumps(observation,sort_keys=True))
    assert closed==list(reversed(owned)) and set(closed)==set(rights)
    assert created[0]['access']=='0x1000a0' and created[0]['disposition']==1 and created[0]['share']==1
    assert created[1]['parent']==parent and created[1]['disposition']==2 and created[1]['share']==0 and created[1]['options']=='0x200060'
    assert b''.join(written)==raw and len(flush)==1
    if force_failure:assert error=='Native media flush unavailable'
    else:assert error is None,observation
