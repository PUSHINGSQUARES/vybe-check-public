"""Final archive/history probes stay explicitly pending during source authoring."""
import hashlib
import json
import os
from pathlib import Path
import tarfile
import zipfile
import pytest


def test_public_scan():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import final_gate
    pending_gate(final_gate,'DoD-64.1')


def test_scan_gate_red_check():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import final_gate
    pending_gate(final_gate,'DoD-64.2')


def test_operational_review():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import final_gate
    pending_gate(final_gate,'DoD-65')


def test_identity_review():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import final_gate
    pending_gate(final_gate,'DoD-66')


def test_artifact_binding():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import load_bundle, validate_matrix, validate_agents
    def gate():
        manifest,records,root=load_bundle()
        validate_matrix([r for r in records if r.get('kind')=='installed-cell'],manifest['candidate'],root)
        validate_agents([r for r in records if r.get('kind')=='agent-installation'],manifest['candidate'],root)
        kinds={r.get('kind') for r in records}
        assert {'installed-cell','agent-installation','native-store','local-study','provider','installed-lifecycle','final-artifact'} <= kinds
    pending_gate(gate)


def test_support_report():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import matrix_gate, agent_gate, native_gate
    def gate():
        matrix_gate();agent_gate()
        for criterion,system in (('DoD-43','Darwin'),('DoD-44','Windows'),('DoD-45','Linux')):
            native_gate(criterion,system)
    pending_gate(gate)


def test_quickstart(tmp_path):
    from tools.acceptance_runtime import environment, cli, installed_guard, board, http
    from vybe_check.workshop import SessionStore
    installed_guard()
    env = environment(tmp_path)
    copied = tmp_path / 'copied-examples'
    result = cli(tmp_path,env,'examples','copy','--out',str(copied))
    assert result.returncode == 0, result.stderr
    for example in ('ceramic','kite'):
        result = cli(tmp_path,env,'new','--title',example.capitalize() + ' example')
        assert result.returncode == 0, result.stderr
        state = json.loads(result.stdout)
        result = cli(tmp_path,env,'event',state['id'],'--revision','0','--action','direct_image','--payload-file',str(copied/(example+'-image.json')))
        assert result.returncode == 0, result.stderr
        state = json.loads(result.stdout)
        assert state['image_versions'] and state['video_versions'] == []
        store = SessionStore(tmp_path/'state')
        with board(store,state) as (_, origin):
            status,raw,_ = http(origin,'/api/session?id='+state['id'])
            assert status == 200 and json.loads(raw)['id'] == state['id']
        result = cli(tmp_path,env,'export',state['id'],'--target','image','--version','1')
        assert result.returncode == 0 and json.loads(result.stdout)['prompt']
        if example == 'kite':
            for index,mode in enumerate(('preserve','evolve','multishot'),1):
                result=cli(tmp_path,env,'event',state['id'],'--revision',str(state['revision']),'--action','add_video_version','--payload-file',str(copied/('kite-'+mode+'.json')))
                assert result.returncode == 0, result.stderr
                state=json.loads(result.stdout)
                result=cli(tmp_path,env,'export',state['id'],'--target','video','--version',str(index))
                assert result.returncode == 0 and json.loads(result.stdout)['prompt']
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import final_gate
    pending_gate(final_gate,'DoD-69')


def _input(name):
    value = os.environ.get(name)
    if not value:
        if os.environ.get('VYBE_AUTHORING_ONLY') == '1':
            pytest.skip('PENDING final source freeze, history, and exact archive verification; authoring only')
        pytest.fail('Final release evidence required: ' + name)
    path = Path(value).resolve()
    assert path.is_file()
    return path


def test_fresh_history():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import final_gate
    pending_gate(final_gate, 'DoD-62')
    record = json.loads(_input('VYBE_HISTORY_RECEIPT').read_text())
    assert record['status'] == 'PASS'
    assert record['private_ancestry'] is False
    assert record['public_noreply_identity_verified'] is True
    assert record['unexpected_source_members'] == []
    assert record['history_roots'] and record['audited_commits']
    inventory = _input('VYBE_FROZEN_SOURCE_INVENTORY')
    assert record['source_inventory_sha256'] == hashlib.sha256(inventory.read_bytes()).hexdigest()


def test_licence_notices():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import final_gate
    pending_gate(final_gate, 'DoD-63')
    wheel = _input('VYBE_PACKAGE_WHEEL'); sdist = _input('VYBE_PACKAGE_SDIST')
    receipt = json.loads(_input('VYBE_LICENCE_RECEIPT').read_text())
    assert receipt['status'] == 'PASS' and receipt['unknown_licences'] == []
    assert receipt['wheel_sha256'] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert receipt['sdist_sha256'] == hashlib.sha256(sdist.read_bytes()).hexdigest()
    assert receipt['installed_distributions'] and receipt['redistribution_review_complete'] is True
    for distribution in receipt['installed_distributions']:
        assert distribution['name'] and distribution['version'] and distribution['licence_identifier']
        assert distribution['licence_files']
    with zipfile.ZipFile(wheel) as archive:
        wheel_members = {n: archive.read(n) for n in archive.namelist() if not n.endswith('/')}
    with tarfile.open(sdist) as archive:
        assert all(m.isfile() or m.isdir() for m in archive.getmembers()), 'Links or special archive members refused'
        sdist_members = {m.name: archive.extractfile(m).read() for m in archive.getmembers() if m.isfile()}
    for kind, members in (('wheel', wheel_members), ('sdist', sdist_members)):
        recorded = receipt[kind + '_members']
        assert set(recorded) == set(members)
        assert all(recorded[n] == hashlib.sha256(raw).hexdigest() for n, raw in members.items())
        assert any(Path(n).name == 'LICENSE' for n in members)
        assert any(Path(n).name == 'THIRD_PARTY_NOTICES.md' for n in members)
        for required in receipt['required_redistributed_licence_members'][kind]:
            assert required in members and members[required]


def test_notice_metadata_is_preparatory():
    source = Path(__file__).resolve().parents[2]
    text = (source / 'THIRD_PARTY_NOTICES.md').read_text()
    assert 'not the final installed candidate' in text
    assert 'MIT-CMU' in text and 'BSD-3-Clause' in text
    assert 'unknown licences as pending' in text
