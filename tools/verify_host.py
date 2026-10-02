"""Observed host execution and strict, independently bound release evidence.

Explicit reviewed plans dispatch separate installed producers. Receipt hashes
must be reviewed independently; a JSON label cannot establish a native outcome.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import re
import stat
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile

CONTRACT_SHA256 = 'ffd11f8557613f27ae5bd7ab157b6261127ec45474d91e46b661d542e9849dd3'
SYSTEMS = ('Darwin', 'Windows', 'Linux')
PYTHONS = ('3.11', '3.12', '3.13', '3.14')
ROOT_KEYS = ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'XDG_DATA_HOME', 'VYBE_CHECK_ROOT', 'TMPDIR')
SCENARIOS = ('empty_brief', 'one_question', 'complete_brief', 'image_only', 'draft_refinement', 'video_modes', 'model_advice', 'unavailable_optional')
HEX = re.compile(r'[0-9a-f]{64}\Z')
ACTIVE_IDS = frozenset(['DoD-' + str(n) for n in range(1, 70) if n not in (9, 10, 11, 33, 64)] +
    ['DoD-' + suffix for suffix in ('9.1', '9.2', '9.3', '10.1', '10.2', '11.1', '11.2', '33.1', '33.2', '64.1', '64.2')])


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular_bytes(path):
    """Read a single stable regular file without following links or specials."""
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        s = parent.lstat()
        require(not stat.S_ISLNK(s.st_mode) and not (getattr(s, 'st_file_attributes', 0) & 0x400), 'Linked evidence refused')
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), 'Regular evidence required')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        require(stat.S_ISREG(opened.st_mode) and (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino), 'Evidence changed before read')
        raw = stream.read()
        after = os.fstat(stream.fileno())
    require((opened.st_size, opened.st_mtime_ns) == (after.st_size, after.st_mtime_ns) and len(raw) == after.st_size, 'Evidence changed during read')
    return raw


def bytes_digest(raw):
    return {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def file_reference(path, root):
    root = Path(root).absolute()
    path = Path(path).absolute()
    require(path.is_relative_to(root), 'Evidence escapes its root')
    return {'path': path.relative_to(root).as_posix(), **bytes_digest(regular_bytes(path))}


def bound_bytes(reference, root):
    require(isinstance(reference, dict) and set(reference) == {'path', 'size', 'sha256'}, 'Incomplete file binding')
    name = reference['path']
    require(isinstance(name, str) and '\\' not in name and not PurePosixPath(name).is_absolute() and all(p not in ('', '.', '..') for p in name.split('/')), 'Unsafe evidence path')
    raw = regular_bytes(Path(root) / name)
    require(bytes_digest(raw) == {k: reference[k] for k in ('size', 'sha256')}, 'Evidence hash or size mismatch')
    return raw


def json_bytes(raw):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out, 'Duplicate JSON key')
            out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def save_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def isolated_environment(root, inherited=None):
    """Create six distinct roots. Do not inherit source or provider variables."""
    root = Path(root).absolute()
    root.mkdir(exist_ok=False)
    env = {k: v for k, v in (inherited or os.environ).items() if k in ('PATH', 'SystemRoot', 'WINDIR', 'COMSPEC', 'LANG', 'LC_ALL')}
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
    for key in ROOT_KEYS:
        path = root / key.lower()
        path.mkdir()
        env[key] = str(path)
    return env


def command_receipt(argv, cwd, out, *, env, timeout=900, artifact=None):
    """Capture a bounded, ordinary command once. Sensitive probes are separate."""
    require(isinstance(argv, (tuple, list)) and argv and all(isinstance(a, str) and a and '\x00' not in a for a in argv), 'Argument array required')
    require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 900, 'Bounded timeout required')
    require(not {'key', 'judge', '--provider-probe', '--native-probe', 'local-study'} & set(argv), 'Dedicated sanitised probe required')
    require(all(env.get(k) and Path(env[k]).is_absolute() for k in ROOT_KEYS), 'Explicit isolated roots required')
    require(len({str(Path(env[k]).absolute()) for k in ROOT_KEYS}) == 6, 'Distinct root directories required')
    for key in ROOT_KEYS:
        path = Path(env[key])
        require(path.is_dir() and not path.is_symlink(), 'Regular isolated root required')
        require(all(not parent.is_symlink() for parent in path.parents), 'Linked isolated root refused')
    require(env.get('PYTHONDONTWRITEBYTECODE') == '1', 'Bytecode must be disabled')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    artifact_binding = {}
    if artifact is not None:
        artifact_path = str(Path(artifact).absolute())
        require(artifact_path in argv, 'Artifact must be an explicit command argument')
        artifact_binding = {'installed_artifact_path': artifact_path, 'installed_artifact_sha256': hashlib.sha256(regular_bytes(artifact)).hexdigest()}
    started = time.time()
    process = subprocess.Popen(list(argv), cwd=cwd, env=env, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    initial_poll = process.poll()
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        stdout, stderr = process.communicate(timeout=10)
    waited = process.wait(timeout=10)
    for name, raw in (('stdout.log', stdout), ('stderr.log', stderr)):
        with (out / name).open('xb') as stream:
            stream.write(raw)
    record = {'schema': 1, 'argv': list(argv), 'cwd': str(Path(cwd).absolute()), 'attempt_count': 1,
        'pid': process.pid, 'initial_poll': initial_poll, 'wait_return': waited, 'final_poll': process.poll(),
        'exit_code': process.returncode, 'timed_out': timed_out, 'started_at': started, 'finished_at': time.time(),
        'os': platform.platform(), 'system': platform.system(), 'python': platform.python_version(),
        'implementation': platform.python_implementation(), 'executable': sys.executable,
        'stdout_sha256': hashlib.sha256(stdout).hexdigest(), 'stderr_sha256': hashlib.sha256(stderr).hexdigest(),
        'stdout_size': len(stdout), 'stderr_size': len(stderr), 'root_environment': {k: env[k] for k in ROOT_KEYS}, **artifact_binding}
    save_json(out / 'receipt.json', record)
    return record


def load_contract(path=None):
    contract = json_bytes(regular_bytes(path or Path(__file__).with_name('acceptance_contract.json')))
    require(isinstance(contract, list) and len(contract) == 75, 'Exactly 75 active criteria required')
    require({r.get('id') for r in contract} == ACTIVE_IDS, 'Missing, obsolete, or renumbered criterion')
    require(len({r.get('nodeid') for r in contract}) == 75, 'Duplicate probe')
    for row in contract:
        require(set(row) == {'id', 'nodeid', 'type', 'hosts', 'mode'}, 'Typed generic contract required')
        require(re.fullmatch(r'tests/acceptance/test_[a-z_]+\.py::test_[a-z0-9_]+', row['nodeid']) is not None, 'Invalid probe node')
        require(isinstance(row['hosts'], list) and row['hosts'] and set(row['hosts']) <= set(SYSTEMS), 'Host classification required')
        require(row['mode'] in ('installed-runtime', 'installed-platform', 'installed-matrix', 'native-agent', 'native-store', 'local-study', 'live-provider', 'final-artifact'), 'Mode classification required')
    require(hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == CONTRACT_SHA256, 'Probe mapping or classification changed')
    return contract


def junit_nodes(raw, expected):
    """Require exact executed cases, including absence of skipped prerequisites."""
    root = ET.fromstring(raw)
    nodes = []
    for case in root.iter('testcase'):
        require(not any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped')), 'Failed or skipped required probe')
        module = case.attrib.get('classname', '').replace('.', '/') + '.py'
        nodes.append(module + '::' + case.attrib.get('name', ''))
    require(nodes and len(nodes) == len(set(nodes)) and set(nodes) == set(expected), 'Missing, duplicated, or unexpected executed node')
    require(all(s.attrib.get('errors', '0') == '0' and s.attrib.get('failures', '0') == '0' and s.attrib.get('skipped', '0') == '0' for s in root.iter('testsuite')), 'Incomplete test suite')
    return nodes


def wheel_inventory(path):
    result = {}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), 'Duplicate wheel members')
        for member in archive.infolist():
            require(not stat.S_ISLNK(member.external_attr >> 16), 'Linked wheel member')
            require(not member.filename.startswith('/') and '..' not in PurePosixPath(member.filename).parts, 'Unsafe wheel member')
            if member.filename.startswith('vybe_check/') and not member.is_dir():
                result[member.filename] = bytes_digest(archive.read(member))
    require(result, 'Package files missing from wheel')
    return result


def validate_observation(record, version, wheel_files):
    require(isinstance(record, dict) and record.get('scope') == 'installed', 'Installed observation required')
    require(record.get('system') in SYSTEMS and record.get('implementation') == 'CPython', 'Actual supported interpreter required')
    require(isinstance(record.get('python'), str) and re.fullmatch(r'3\.(11|12|13|14)\.[0-9]+', record['python']), 'Unsupported Python patch version')
    require(record.get('version') == version, 'Wrong installed package version')
    require(isinstance(record.get('environment'), dict) and not record['environment'].get('PYTHONPATH'), 'Source origin refused')
    path_type = PureWindowsPath if record['system'] == 'Windows' else PurePosixPath
    prefix = path_type(record.get('prefix', ''))
    origin = path_type(record.get('module_origin', ''))
    require(prefix.is_absolute() and origin.is_absolute() and origin.is_relative_to(prefix) and origin.name == '__init__.py', 'Installed origin outside clean environment')
    dependencies = record.get('dependencies')
    require(isinstance(dependencies, list) and dependencies and all(isinstance(d, dict) and d.get('name') and d.get('version') for d in dependencies), 'Exact dependencies required')
    require(record.get('package_files') == wheel_files and wheel_files, 'Installed bytes differ from wheel')


OBSERVE = '''import sys,os,json,platform,hashlib
from pathlib import Path
from importlib.metadata import distribution,distributions
import vybe_check
d=distribution("vybe-check"); origin=Path(vybe_check.__file__).resolve(); prefix=Path(sys.prefix).resolve()
assert origin.is_relative_to(prefix)
members={}
for f in d.files or ():
    if str(f).replace("\\\\","/").startswith("vybe_check/") and "__pycache__" not in str(f):
        p=Path(d.locate_file(f));assert p.is_file() and not p.is_symlink();raw=p.read_bytes()
        members[str(f).replace("\\\\","/")]={"size":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
print(json.dumps({"scope":"installed","system":platform.system(),"platform":platform.platform(),
"implementation":platform.python_implementation(),"python":platform.python_version(),"executable":sys.executable,
"prefix":str(prefix),"module_origin":str(origin),"version":d.version,"package_files":members,
"dependencies":sorted([{"name":x.metadata["Name"],"version":x.version} for x in distributions()],key=lambda x:x["name"]),
"environment":{"PYTHONPATH":os.environ.get("PYTHONPATH")}}))
'''


def observe_installed(interpreter, cwd, out, env, version, wheel):
    require('PYTHONPATH' not in env and 'VYBE_AUTHORING_ONLY' not in env, 'Clean installed environment required')
    record = command_receipt([str(interpreter), '-B', '-c', OBSERVE], cwd, out, env=env)
    require(record['exit_code'] == 0 and not record['timed_out'], 'Installed observation failed')
    observation = json_bytes(regular_bytes(Path(out) / 'stdout.log'))
    validate_observation(observation, version, wheel_inventory(wheel))
    return observation


def validate_command(record, root, expected_argv=None):
    require(isinstance(record, dict) and record.get('attempt_count') == 1, 'Observed command required')
    require(type(record.get('exit_code')) is int and record['exit_code'] == 0 and record.get('timed_out') is False, 'Command failed or timed out')
    require(type(record.get('pid')) is int and record['pid'] > 0 and record.get('wait_return') == 0 and record.get('final_poll') == 0, 'Terminal process observation required')
    require(isinstance(record.get('argv'), list) and record['argv'] and all(isinstance(a, str) for a in record['argv']), 'Observed argument array required')
    if expected_argv is not None:
        require(record['argv'] == expected_argv, 'Wrong command origin')
    require(type(record.get('started_at')) in (int, float) and type(record.get('finished_at')) in (int, float) and record['finished_at'] >= record['started_at'], 'Command timing required')
    for stream in ('stdout', 'stderr'):
        raw = regular_bytes(Path(root) / (stream + '.log'))
        require(bytes_digest(raw) == {'sha256': record.get(stream + '_sha256'), 'size': record.get(stream + '_size')}, 'Command log mismatch')


def validate_cell(cell, candidate, root):
    require(isinstance(cell, dict) and cell.get('kind') == 'installed-cell' and cell.get('scope') == 'native-observed', 'Native installed cell required')
    require(cell.get('candidate') == candidate, 'Stale or mismatched candidate')
    require(root is not None, 'Independent evidence root required')
    observation_ref = cell.get('observation')
    observation = json_bytes(bound_bytes(observation_ref, root))
    wheel_path = cell.get('wheel_reference')
    wheel_raw = bound_bytes(wheel_path, root)
    require(hashlib.sha256(wheel_raw).hexdigest() == candidate.get('wheel_sha256'), 'Wrong wheel artifact')
    validate_observation(observation, candidate['version'], wheel_inventory(Path(root) / wheel_path['path']))
    command = json_bytes(bound_bytes(cell.get('observation_command'), root))
    command_root = Path(root) / PurePosixPath(cell['observation_command']['path']).parent
    validate_command(command, command_root)
    require(command['argv'][1:] == ['-B', '-c', OBSERVE], 'Observation command was simulated')
    require(json_bytes(regular_bytes(command_root / 'stdout.log')) == observation, 'Observation is not actual command output')
    launch = json_bytes(bound_bytes(cell.get('launch_command'), root))
    launch_root = Path(root) / PurePosixPath(cell['launch_command']['path']).parent
    validate_command(launch, launch_root)
    require(launch['argv'][0] == observation['executable'] and launch['argv'][1:4] == ['-B', '-m', 'vybe_check'] and '--root' in launch['argv'] and '--help' in launch['argv'], 'Actual installed CLI launch required')
    install = json_bytes(bound_bytes(cell.get('install_command'), root))
    install_root = Path(root) / PurePosixPath(cell['install_command']['path']).parent
    validate_command(install, install_root)
    require(install['argv'][0] == observation['executable'] and install['argv'][1:5] == ['-B', '-m', 'pip', 'install'] and '--editable' not in install['argv'] and '-e' not in install['argv'], 'Real wheel installation required')
    require(install.get('installed_artifact_sha256') == candidate['wheel_sha256'], 'Install receipt lacks recomputable wheel binding')
    installed_artifact = bound_bytes(cell.get('installed_artifact'), root)
    require(hashlib.sha256(installed_artifact).hexdigest() == candidate['wheel_sha256'] and install.get('installed_artifact_path') in install['argv'], 'Install command used a different artifact')
    require(command['argv'][0] == observation['executable'] and command.get('system') == observation['system'], 'Observation host or executable mismatch')
    require(cell.get('environment_location') == observation['prefix'], 'Wrong environment location')
    return observation


def validate_matrix(cells, candidate, root=None):
    require(isinstance(cells, list) and len(cells) == 12, 'Missing twelve-cell matrix')
    observed = []
    for cell in cells:
        fact = validate_cell(cell, candidate, root)
        observed.append((fact['system'], '.'.join(fact['python'].split('.')[:2])))
    require(len(set(observed)) == 12 and set(observed) == {(s, p) for s in SYSTEMS for p in PYTHONS}, 'Missing or repeated native matrix cell')
    return observed


def _nonempty_text(value, maximum=4000):
    return isinstance(value, str) and 0 < len(value.strip()) <= maximum


def validate_scenario(name, observation):
    require(name in SCENARIOS and isinstance(observation, dict), 'Unknown agent scenario')
    require(observation.get('observation_kind') == 'human-reviewed-outcome' and _nonempty_text(observation.get('reviewer')) and _nonempty_text(observation.get('notes')), 'Reviewed outcome notes required')
    require(observation.get('invented_input') is True and observation.get('conversation_transcript') is None, 'Invented outcome-only scenario required')
    values = observation.get('facts')
    require(isinstance(values, dict), 'Outcome facts required')
    integer = lambda key: type(values.get(key)) is int and values[key] >= 0
    if name == 'empty_brief':
        require(integer('proposed_concepts') and values['proposed_concepts'] >= 1 and integer('alternates') and values['alternates'] >= 1 and values.get('agreed_versions') == 0, 'Empty brief outcome failed')
    elif name == 'one_question':
        turns = values.get('questions_per_turn')
        require(isinstance(turns, list) and turns and all(type(v) is int and 0 <= v <= 1 for v in turns), 'Clarification outcome failed')
    elif name == 'complete_brief':
        require(integer('image_versions') and values['image_versions'] >= 1 and values.get('redundant_agreement_questions') == 0, 'Complete brief outcome failed')
    elif name == 'image_only':
        require(integer('agreed_images') and values['agreed_images'] >= 1 and values.get('video_versions') == 0, 'Image-only outcome failed')
    elif name == 'draft_refinement':
        require(values.get('new_version_id') != values.get('prior_version_id') and _nonempty_text(str(values.get('new_version_id', ''))) and HEX.fullmatch(values.get('prior_before_sha256', '')) and values['prior_before_sha256'] == values.get('prior_after_sha256'), 'Draft lineage outcome failed')
    elif name == 'video_modes':
        require(set(values) >= {'preserve', 'evolve', 'multishot'}, 'All video modes required')
        for mode in ('preserve', 'evolve', 'multishot'):
            v = values[mode]
            require(isinstance(v, dict) and type(v.get('duration')) is int and 1 <= v['duration'] <= 60 and _nonempty_text(v.get('anchor_id')) and v.get('locks'), 'Video continuity outcome failed')
            parts = v.get('durations')
            require(isinstance(parts, list) and parts and all(type(d) is int and d > 0 for d in parts) and sum(parts) == v['duration'], 'Ordered duration outcome failed')
    elif name == 'model_advice':
        require(_nonempty_text(values.get('input_mode')) and values.get('official_source_url', '').startswith('https://') and re.fullmatch(r'\d{4}-\d{2}-\d{2}', values.get('checked_date', '')) and _nonempty_text(values.get('uncertainty')), 'Dated official model advice required')
    else:
        require(integer('image_refinements') and values['image_refinements'] >= 1 and values.get('unavailable_optional') in ('judge', 'preview', 'both'), 'Unavailable optional workflow outcome failed')


def result_pointer(document, pointer):
    """Resolve an explicit JSON pointer without evaluating operator code."""
    require(isinstance(pointer, str) and (pointer == '' or pointer.startswith('/')), 'Result JSON pointer required')
    value = document
    try:
        for token in pointer.split('/')[1:] if pointer else []:
            token = token.replace('~1', '/').replace('~0', '~')
            value = value[int(token)] if isinstance(value, list) and token.isdecimal() else value[token]
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError('Result pointer does not identify retained bytes') from None
    return value


def validate_agent_results(name, outcome, root):
    """Bind outcome observations to creative results, separately from provenance."""
    validate_scenario(name, outcome)
    provenance = outcome.get('provenance')
    require(isinstance(provenance, dict) and set(provenance) == {'input', 'review', 'version_log'}, 'Input, review, and log provenance required')
    provenance_raw = [bound_bytes(ref, root) for ref in provenance.values()]
    results = outcome.get('results')
    require(isinstance(results, list) and results, 'Saved creative result artifacts required')
    review = json_bytes(provenance_raw[1])
    require(isinstance(review, dict) and all(review.get(key) == outcome.get(key) for key in ('observation_kind', 'reviewer', 'notes', 'invented_input', 'conversation_transcript', 'facts', 'reviewed_result_sha256')), 'Saved review differs from scenario observations')
    reviewed_results = review.get('results')
    require(isinstance(reviewed_results, list) and len(reviewed_results) == len(results), 'Saved review lacks creative result bindings')
    for reviewed, retained in zip(reviewed_results, results):
        require(isinstance(reviewed, dict) and isinstance(retained, dict), 'Result descriptors required')
        # Retention may relocate bytes; their reviewed digest and selectors remain.
        require({k: value for k, value in reviewed.items() if k != 'artifact'} == {k: value for k, value in retained.items() if k != 'artifact'}, 'Saved creative review selectors changed')
        require(isinstance(reviewed.get('artifact'), dict) and isinstance(retained.get('artifact'), dict) and all(reviewed['artifact'].get(key) == retained['artifact'].get(key) for key in ('size', 'sha256')), 'Retained result differs from reviewed artifact')
    required_kind = {'image_only': 'session', 'draft_refinement': 'version', 'video_modes': 'version'}.get(name)
    required_facts = {
        'empty_brief': {'proposed_concepts', 'alternates', 'agreed_versions'},
        'one_question': set(), 'complete_brief': {'image_versions'},
        'image_only': {'agreed_images', 'video_versions'},
        'draft_refinement': {'new_version_id', 'prior_version_id', 'prior_before_sha256', 'prior_after_sha256'},
        'video_modes': {mode + '/' + field for mode in ('preserve', 'evolve', 'multishot') for field in ('duration', 'anchor_id', 'locks', 'durations')},
        'model_advice': {'input_mode', 'official_source_url', 'checked_date', 'uncertainty'},
        'unavailable_optional': {'image_refinements'},
    }[name]
    covered = set(); kinds = set(); hashes = []; fact_artifacts = {}
    for result in results:
        require(isinstance(result, dict) and result.get('kind') in ('prompt', 'version', 'session'), 'Creative prompt, version, or session result required')
        raw = bound_bytes(result.get('artifact'), root)
        require(raw and raw not in provenance_raw, 'Provenance cannot replace a creative result artifact')
        document = json_bytes(raw)
        require(isinstance(document, dict) and 'observation_kind' not in document and document.get('conversation_transcript') is None, 'Outcome notes or transcripts cannot replace creative results')
        prompts = result.get('prompt_pointers')
        require(isinstance(prompts, list) and prompts and all(_nonempty_text(result_pointer(document, pointer), 100000) for pointer in prompts), 'Retained creative prompt text required')
        identifiers = result.get('version_pointers', [])
        require(isinstance(identifiers, list), 'Result version pointers required')
        if result['kind'] in ('version', 'session'):
            require(identifiers, 'Retained version or session identifier required')
        actual_ids = [result_pointer(document, pointer) for pointer in identifiers]
        require(all((type(value) is int and value > 0) or _nonempty_text(value) for value in actual_ids), 'Invalid retained creative identifier')
        require(result.get('reviewed_versions') == actual_ids, 'Reviewed result identifiers differ from retained bytes')
        bindings = result.get('fact_bindings')
        require(isinstance(bindings, list), 'Explicit result fact bindings required')
        for binding in bindings:
            require(isinstance(binding, dict) and binding.get('fact') in required_facts and binding.get('operation') in ('value', 'length', 'bytes_sha256'), 'Unknown creative result fact binding')
            fact = binding['fact']; require(fact not in covered, 'Duplicate creative fact binding')
            if name == 'draft_refinement':
                if fact in ('prior_before_sha256', 'prior_after_sha256'):
                    require(binding['operation'] == 'bytes_sha256', 'Prior version hashes must bind actual retained bytes')
                else:
                    require(binding['operation'] == 'value' and binding.get('pointer') in identifiers, 'Refinement identifiers must bind actual saved versions')
            if binding['operation'] == 'bytes_sha256':
                actual = hashlib.sha256(raw).hexdigest()
            else:
                actual = result_pointer(document, binding.get('pointer'))
                if binding['operation'] == 'length':
                    require(isinstance(actual, list), 'Creative collection required for count binding')
                    actual = len(actual)
            expected = result_pointer(outcome['facts'], '/' + fact)
            require(type(actual) is type(expected) and actual == expected, 'Reviewed creative fact differs from retained result bytes')
            covered.add(fact); fact_artifacts[fact] = hashlib.sha256(raw).hexdigest()
        kinds.add(result['kind']); hashes.append(hashlib.sha256(raw).hexdigest())
    require(required_kind is None or required_kind in kinds, 'Scenario requires its resulting session or version artifact')
    require(covered == required_facts, 'Missing scenario creative fact bindings')
    if name == 'draft_refinement':
        require(fact_artifacts['prior_version_id'] == fact_artifacts['prior_before_sha256'] == fact_artifacts['prior_after_sha256'] and fact_artifacts['new_version_id'] != fact_artifacts['prior_version_id'], 'Prior hashes must identify the retained prior version, separately from the new version')
    require(outcome.get('reviewed_result_sha256') == hashes, 'Reviewed result hashes differ from retained bytes')
    return results


def validate_agents(records, candidate, root, agent=None, scenario=None):
    require(isinstance(records, list) and len(records) == 6, 'Missing six native agent installations')
    keys = []
    for record in records:
        require(isinstance(record, dict) and record.get('scope') == 'native-agent-observed' and record.get('candidate') == candidate, 'Wrong or synthetic agent evidence')
        require(record.get('agent') in ('codex', 'claude') and record.get('system') in SYSTEMS, 'Native agent host required')
        require(_nonempty_text(record.get('agent_version')) and record.get('managed_scope') in ('user', 'project') and _nonempty_text(record.get('isolated_scope')), 'Exact managed agent installation required')
        require(root is not None, 'Independent agent evidence root required')
        version_raw = bound_bytes(record.get('version_output'), root)
        require(record['agent_version'].encode() in version_raw, 'Version output mismatch')
        command = json_bytes(bound_bytes(record.get('version_command'), root))
        validate_command(command, Path(root) / PurePosixPath(record['version_command']['path']).parent)
        require(command['argv'][1:] == ['--version'] and command['argv'][0] == record.get('agent_executable') and _nonempty_text(record.get('agent_executable')), 'Actual native executable version required')
        require(regular_bytes(Path(root) / PurePosixPath(record['version_command']['path']).parent / 'stdout.log') == version_raw, 'Version bytes were not observed executable output')
        require(record.get('discovery_method') == 'native-agent-managed-registration', 'Static or fake discovery refused')
        require(set(record.get('scenarios', {})) == set(SCENARIOS), 'Missing or unknown agent scenario')
        registration = json_bytes(bound_bytes(record.get('registration_receipt'), root))
        validate_command(registration, Path(root) / PurePosixPath(record['registration_receipt']['path']).parent)
        require(registration['system'] == record['system'] and registration['argv'][1:4] == ['-B', '-m', 'vybe_check'] and 'install' in registration['argv'] and record['agent'] in registration['argv'] and record['managed_scope'] in registration['argv'], 'Actual explicit managed registration required')
        saved = json_bytes(bound_bytes(record.get('saved_registration'), root))
        require(saved.get('scope') == 'observed-registration-files' and saved.get('path') == record['isolated_scope'] and isinstance(saved.get('files'), dict) and saved['files'], 'Saved managed registration bytes required')
        require(saved['files'] == record.get('canonical_skill_files'), 'Managed skill differs from frozen canonical resources')
        discovery = json_bytes(bound_bytes(record.get('discovery_review'), root))
        require(discovery.get('observation_kind') == 'human-reviewed-outcome' and discovery.get('agent_version') == record['agent_version'] and discovery.get('loaded_registration') == record['isolated_scope'] and _nonempty_text(discovery.get('reviewer')) and _nonempty_text(discovery.get('notes')), 'Native skill discovery outcome not reviewed')
        for name, outcome in record['scenarios'].items():
            validate_agent_results(name, outcome, root)
        keys.append((record['agent'], record['system']))
    require(len(set(keys)) == 6 and set(keys) == {(a, s) for a in ('codex', 'claude') for s in SYSTEMS}, 'Missing or repeated agent installation')
    require(agent is None or agent in ('codex', 'claude'), 'Unknown agent')
    require(scenario is None or scenario in SCENARIOS, 'Unknown scenario')
    return keys


def validate_provider(record, route):
    """Only a dedicated sanitised actual provider consumer may write this record."""
    require(isinstance(record, dict) and record.get('scope') == 'native-provider-observed' and record.get('route') == route and route in ('typesafe', 'openrouter'), 'Real independent route evidence required')
    require(record.get('call_count') == 1 and type(record['call_count']) is int and record.get('retry_count') == 0 and record.get('fallback_count') == 0, 'Exactly one authorised attempt required')
    require(record.get('transport_outcome') == 'validated-response' and record.get('native_backend') in ('macos-keychain', 'windows-credential-locker', 'linux-secret-service'), 'Validated native consumer required')
    require(_nonempty_text(record.get('requested_model')) and _nonempty_text(record.get('actual_model')), 'Actual reported model required')
    require(_nonempty_text(record.get('actual_provider')) or (record.get('actual_provider') is None and record.get('provider_observation') == 'Not reported by response'), 'Provider reporting or explicit observed absence required')
    models = {'typesafe': ('jev-1.13.0', 'jev-1.13.0'), 'openrouter': ('typesafe/jev-1.13', 'typesafe/jev-1.13-20260917')}
    require(record['requested_model'] == models[route][0] and record['actual_model'] in models[route], 'Wrong route or response model')
    for key in ('request_sha256', 'response_sha256', 'approval_sha256', 'cost_receipt_sha256'):
        require(isinstance(record.get(key), str) and HEX.fullmatch(record[key]), 'Incomplete provider binding')
    require(record.get('synthetic_decision_only') is True and record.get('raw_body') is None and record.get('secret') is None, 'Sanitised decision-only receipt required')
    ceiling = record.get('maximum_cost')
    require(isinstance(ceiling, str) and re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', ceiling) and float(ceiling) > 0 and record.get('quoted_total') is not None and 0 <= float(record['quoted_total']) <= float(ceiling), 'Approved conservative cost bound required')
    require(record.get('primary_source_url', '').startswith('https://') and re.fullmatch(r'\d{4}-\d{2}-\d{2}', record.get('rate_checked_date', '')), 'Dated primary-source rate required')
    answers = record.get('answers')
    require(isinstance(answers, dict) and answers, 'Typed answers required')
    for name, answer in answers.items():
        require(re.fullmatch(r'[a-z][a-z0-9_]{0,63}', name) is not None and isinstance(answer, dict), 'Invalid question')
        if answer.get('type') == 'choice':
            require(answer.get('choice') in ('option_1', 'option_2'), 'Unknown choice')
            probs = answer.get('probabilities')
            require(isinstance(probs, dict) and set(probs) == {'option_1', 'option_2'}, 'Choice probabilities required')
            nums = list(probs.values()) + [answer.get('confidence')]
            require(all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in nums) and abs(sum(probs.values()) - 1) <= 0.000001, 'Invalid choice probabilities')
            require(probs[answer['choice']] == max(probs.values()), 'Choice does not match probabilities')
        elif answer.get('type') == 'noul':
            value = answer.get('noul')
            require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1, 'Invalid numeric answer')
        else:
            raise ValueError('Unknown typed answer')


def load_bundle():
    """Read independently reviewed receipt bindings, never infer trust from PASS."""
    name = os.environ.get('VYBE_ACCEPTANCE_MANIFEST')
    expected = os.environ.get('VYBE_ACCEPTANCE_MANIFEST_SHA256', '')
    require(name and HEX.fullmatch(expected), 'Missing independently reviewed evidence manifest and digest')
    path = Path(name).absolute()
    raw = regular_bytes(path)
    require(hashlib.sha256(raw).hexdigest() == expected, 'Unreviewed or modified evidence manifest')
    manifest = json_bytes(raw)
    require(isinstance(manifest, dict) and manifest.get('schema') == 1 and manifest.get('scope') == 'final-native-release', 'Authoring or simulated manifest refused')
    root = path.parent
    candidate = manifest.get('candidate')
    require(isinstance(candidate, dict) and set(candidate) == {'version', 'source_sha256', 'wheel_sha256', 'sdist_sha256'}, 'Exact artifact tuple required')
    for kind in ('source', 'wheel', 'sdist'):
        actual = hashlib.sha256(bound_bytes(manifest.get(kind), root)).hexdigest()
        require(actual == candidate[kind + '_sha256'], 'Wrong final artifact binding')
    require(candidate['version'] == '0.1.0rc1', 'Wrong candidate version')
    records = []
    for ref in manifest.get('records', []):
        record = json_bytes(bound_bytes(ref, root))
        require(isinstance(record, dict) and record.get('candidate') == candidate and record.get('scope') not in (None, 'authoring-synthetic', 'authoring', 'simulated'), 'Synthetic, stale, or wrong artifact receipt')
        records.append(record)
    require(records, 'Missing required receipts')
    return manifest, records, root


def required_records(kind, *, route=None):
    if os.environ.get('VYBE_ACCEPTANCE_PLAN'):
        from tools.acceptance_producers import execute_required
        return execute_required(kind, route)
    manifest, records, root = load_bundle()
    found = [r for r in records if r.get('kind') == kind and (route is None or r.get('route') == route)]
    require(found, 'Missing required ' + kind + ' evidence')
    return manifest, found, root


def matrix_gate(system=None):
    manifest, records, root = required_records('installed-cell')
    validate_matrix(records, manifest['candidate'], root)
    require(system is None or system in SYSTEMS, 'Unknown system')


def agent_gate(agent=None, scenario=None):
    manifest, records, root = required_records('agent-installation')
    validate_agents(records, manifest['candidate'], root, agent=agent, scenario=scenario)


def native_gate(criterion, system=None):
    manifest, records, root = required_records('native-store')
    required_systems = (system,) if system else SYSTEMS
    for host in required_systems:
        matches = [r for r in records if r.get('system') == host and r.get('criterion') == criterion]
        require(len(matches) == 1, 'Missing or duplicated native credential host')
        record = matches[0]
        require(record.get('scope') == 'native-store-observed' and record.get('namespace', '').startswith('vybe-check-acceptance-') and re.fullmatch(r'vybe-check-acceptance-[0-9a-f]{32}', record['namespace']), 'Unique synthetic native namespace required')
        expected = {'Darwin':'macos-keychain', 'Windows':'windows-credential-locker', 'Linux':'linux-secret-service'}[host]
        require(record.get('backend') == expected and _nonempty_text(record.get('store_version')), 'Actual explicit native backend required')
        outcomes = record.get('outcomes')
        require(outcomes == {'stored': True, 'consumed_equal': True, 'duplicate_preserved': True, 'secret_logged': False}, 'Native internal round trip failed')
        require(record.get('service_unlocked') is True and record.get('access_outcome') == 'observed-access', 'Host access is not evidence of absence')
        if criterion in ('DoD-11.1', 'DoD-11.2'):
            require(record.get('consumed_after_operation') is True and record.get('operation') == ('unregister' if criterion == 'DoD-11.1' else 'pip-uninstall'), 'Native preservation not observed')
        if criterion in ('DoD-11.1', 'DoD-11.2'):
            commands = record.get('commands')
            require(isinstance(commands, list) and commands, 'Actual preservation operation commands required')
            observed = []
            for reference in commands:
                command = json_bytes(bound_bytes(reference, root))
                validate_command(command, Path(root)/PurePosixPath(reference['path']).parent)
                require(command['system'] == host, 'Preservation operation host differs')
                observed.append(command['argv'])
            require(any(a[1:4] == ['-B','-m','vybe_check'] and 'unregister' in a for a in observed), 'Actual unregister was not executed')
            if criterion == 'DoD-11.2':
                require(any(a[1:5] == ['-B','-m','pip','uninstall'] and 'vybe-check' in a for a in observed), 'Actual pip uninstall was not executed')
        if host == 'Linux':
            native_unavailable_gate('Linux')
        evidence = json_bytes(bound_bytes(record.get('sanitised_probe'), root))
        require(evidence.get('scope') == 'actual-native-store-probe' and evidence.get('system') == host and evidence.get('namespace') == record['namespace'], 'Wrong or simulated native probe origin')
        require(evidence.get('backend') == expected and evidence.get('equal') is True and evidence.get('available') is True and evidence.get('duplicate_preserved') is True, 'Actual sanitised probe output required')



def native_unavailable_gate(system=None):
    host = system or platform.system()
    _, records, root = required_records('native-unavailable')
    found = [r for r in records if r.get('system') == host]
    require(len(found) == 1, 'Missing separate native-store unavailable observation')
    row = found[0]
    require(row.get('scope') == 'native-unavailable-observed' and row.get('store_state') in ('explicitly-locked', 'explicitly-unavailable'), 'Denied host access is not an unavailable-service observation')
    command = json_bytes(bound_bytes(row.get('service_state_command'), root))
    command_root = Path(root) / PurePosixPath(row['service_state_command']['path']).parent
    validate_command(command, command_root)
    require(command['system'] == host, 'Unavailable-service host mismatch')
    observed = json_bytes(bound_bytes(row.get('sanitised_probe'), root))
    require(observed.get('scope') == 'actual-native-store-unavailable-probe' and observed.get('system') == host and observed.get('native_read_refused') is True and observed.get('provider_calls') == 0 and observed.get('baseline_refined') is True, 'Actual unavailable native consumer and usable baseline required')

def provider_gate(route):
    manifest, records, root = required_records('provider', route=route)
    require(len(records) == 1, 'Independent one-route receipt required')
    record = records[0]
    validate_provider(record, route)
    for key, digest in (('request', 'request_sha256'), ('response', 'response_sha256'), ('approval', 'approval_sha256'), ('cost_receipt', 'cost_receipt_sha256')):
        raw = bound_bytes(record.get(key), root)
        require(hashlib.sha256(raw).hexdigest() == record[digest], 'Provider evidence binding mismatch')


def study_gate(criterion):
    _, records, root = required_records('local-study')
    require(len(records) == 1, 'One complete study record required')
    record = records[0]
    require(record.get('scope') == 'local-checkpoint-observed' and record.get('core_version') and record.get('backend_version') and HEX.fullmatch(record.get('checkpoint_sha256', '')), 'Actual local checkpoint versions required')
    require(record.get('workflow') == 'approved-core' and record.get('wholly_local') is True and record.get('visual_confirmation') == 'Both registered studies displayed', 'Actual board display confirmation required')
    studies = record.get('studies')
    require(isinstance(studies, list) and len(studies) == 2 and len({s.get('id') for s in studies}) == 2, 'Two distinct study outputs required')
    from io import BytesIO
    from PIL import Image
    names = []
    for study in studies:
        image = bound_bytes(study.get('image'), root)
        response = bound_bytes(study.get('board_response'), root)
        require(image == response and image, 'Board bytes differ from generated file')
        with Image.open(BytesIO(image)) as decoded:
            decoded.load()
            require(decoded.width > 0 and decoded.height > 0, 'Undecoded study file')
        require(study.get('browser_natural_width', 0) > 0 and _nonempty_text(study.get('registered_media_id')), 'Browser image decode not observed')
        names.append(study['image']['path'])
    require(len(set(names)) == 2 and record.get('first_before_sha256') == record.get('first_after_sha256') == studies[0]['image']['sha256'], 'Earlier study output changed')
    require(criterion in ('DoD-48', 'DoD-50', 'DoD-51'), 'Unknown study criterion')
    if criterion == 'DoD-48':
        controls = json_bytes(bound_bytes(record.get('capability_controls'), root))
        require(controls.get('scope') == 'actual-local-capability-controls' and controls.get('unsupported_core_refused') is True and controls.get('missing_checkpoint_refused') is True and controls.get('unavailable_refused') is True and controls.get('generation_calls') == 0, 'Local capability refusal observations required')
    return record, root


def final_gate(criterion):
    """Later scan/history tooling must supply matching recomputable proof."""
    manifest, records, root = required_records('final-artifact')
    rows = [r for r in records if r.get('criterion') == criterion]
    require(len(rows) == 1, 'Missing or duplicated final artifact criterion')
    row = rows[0]
    require(row.get('scope') == 'final-artifact-observed' and row.get('completed') is True and row.get('unresolved_findings') == [], 'Final artifact gate incomplete')
    require(_nonempty_text(row.get('reviewer')) and row.get('observations'), 'Independent final observations required')
    for reference in row['observations']:
        require(bound_bytes(reference, root), 'Empty final observation')
    if criterion == 'DoD-69':
        review = json_bytes(bound_bytes(row.get('quickstart_review'), root))
        require(review.get('observation_kind') == 'human-reviewed-outcome' and review.get('candidate') == manifest['candidate'] and review.get('newcomer_completed') is True and _nonempty_text(review.get('notes')) and _nonempty_text(review.get('reviewer')), 'Actual newcomer quickstart outcome required')
        return
    # Tasks which author the actual history and scan tools complete their typed
    # verification here. An unimplemented validator cannot close a criterion.
    raise ValueError('Pending final history, scan, and publication-tool verification')



def validate_phases(raw, expected):
    receipt = json_bytes(raw)
    require(receipt.get('scope') == 'actual-pytest-phases' and receipt.get('exit_code') == 0, 'Actual successful pytest phase receipt required')
    rows = receipt.get('phases')
    require(isinstance(rows, list) and len(rows) == 3 * len(expected), 'Incomplete executed phases')
    require({r.get('nodeid') for r in rows} == set(expected), 'Wrong or missing executed probe')
    for node in expected:
        parts = [r for r in rows if r.get('nodeid') == node]
        require(len(parts) == 3 and {r.get('when') for r in parts} == {'setup', 'call', 'teardown'} and all(r.get('outcome') == 'passed' for r in parts), 'Skipped or incomplete required phase')
    return receipt


def run_probes(interpreter, cwd, out, env, observation, candidate, wheel, evidence_root):
    """Run exact named probes once; native prerequisites remain explicit gates."""
    require(not env.get('PYTHONPATH') and 'VYBE_AUTHORING_ONLY' not in env, 'Source fixture cannot run final probes')
    cwd = Path(cwd).absolute()
    out = Path(out).absolute()
    out.mkdir(exist_ok=False)
    rows = [r for r in load_contract() if observation['system'] in r['hosts']]
    nodes = [r['nodeid'] for r in rows]
    source_members = {'tools/verify_host.py', 'tools/acceptance_contract.json', 'tools/acceptance_runtime.py', 'tools/pytest_receipts.py', 'tools/acceptance_producers.py'} | {n.split('::')[0] for n in nodes}
    manifest, _, manifest_root = load_bundle()
    require(manifest['candidate'] == candidate, 'Runtime candidate tuple differs from reviewed artifacts')
    from tools.acceptance_producers import bind_runtime_freeze
    frozen = bind_runtime_freeze(cwd, candidate, manifest['source'], manifest.get('frozen_source_inventory'), source_members, manifest_root, out)
    # Rebase the producer output into this runtime evidence root.
    frozen = file_reference(Path(manifest_root) / frozen['path'], evidence_root)
    origins = {name: bytes_digest(regular_bytes(cwd / name)) for name in sorted(source_members)}
    require((cwd / 'tools/verify_host.py').absolute() == Path(__file__).absolute(), 'Host runner origin differs from probe source')
    save_json(out / 'observation.json', observation)
    with (out / 'candidate.whl').open('xb') as stream:
        stream.write(regular_bytes(wheel))
    observed_env = dict(env)
    observed_env['VYBE_LAYOUT_EVIDENCE_DIR'] = str(out / 'browser-evidence')
    observed_env['VYBE_PYTEST_RECEIPT'] = str(out / 'phases.json')
    argv = [str(interpreter), '-B', '-m', 'pytest', '-q', '-ra', '-p', 'no:cacheprovider', '-p', 'tools.pytest_receipts',
        '--junitxml=' + str(out / 'junit.xml'), '--basetemp=' + str(out / 'temporary'), *nodes]
    command = command_receipt(argv, cwd, out / 'command', env=observed_env)
    save_json(out / 'probe-origins.json', origins)
    # Failed output remains intact and cannot produce a successful receipt.
    require(command['exit_code'] == 0 and not command['timed_out'], 'Required host probes failed')
    junit_nodes(regular_bytes(out / 'junit.xml'), nodes)
    validate_phases(regular_bytes(out / 'phases.json'), nodes)
    save_json(out / 'runtime.json', {'schema': 1, 'kind': 'installed-runtime', 'scope': 'native-runtime-observed',
        'candidate': candidate, 'observation': file_reference(out / 'observation.json', evidence_root),
        'wheel_reference': file_reference(out / 'candidate.whl', evidence_root), 'nodes': nodes,
        'command': file_reference(out / 'command/receipt.json', evidence_root),
        'junit': file_reference(out / 'junit.xml', evidence_root), 'phases': file_reference(out / 'phases.json', evidence_root),
        'probe_origins': file_reference(out / 'probe-origins.json', evidence_root), 'frozen_source_inventory': frozen, 'final_release_criteria': 'OPEN'})


def validate_runtime(records, candidate, root):
    """Aggregate actual executed nodes on each native host, never fixture PASS."""
    require(isinstance(records, list) and len(records) == 3, 'Missing three installed runtime host runs')
    hosts = []
    for record in records:
        require(record.get('kind') == 'installed-runtime' and record.get('scope') == 'native-runtime-observed' and record.get('candidate') == candidate, 'Wrong native runtime receipt')
        observation = json_bytes(bound_bytes(record.get('observation'), root))
        wheel = record.get('wheel_reference')
        require(hashlib.sha256(bound_bytes(wheel, root)).hexdigest() == candidate['wheel_sha256'], 'Runtime wheel differs')
        validate_observation(observation, candidate['version'], wheel_inventory(Path(root) / wheel['path']))
        host = observation['system']
        expected = [r['nodeid'] for r in load_contract() if host in r['hosts']]
        require(record.get('nodes') == expected, 'Host node set incomplete or reordered')
        command = json_bytes(bound_bytes(record.get('command'), root))
        validate_command(command, Path(root) / PurePosixPath(record['command']['path']).parent)
        require(command['system'] == host and command['argv'][:4] == [observation['executable'], '-B', '-m', 'pytest'] and command['argv'][-len(expected):] == expected, 'Wrong runtime command or native host')
        junit_nodes(bound_bytes(record.get('junit'), root), expected)
        validate_phases(bound_bytes(record.get('phases'), root), expected)
        origins = json_bytes(bound_bytes(record.get('probe_origins'), root))
        require(origins and all(isinstance(v, dict) and HEX.fullmatch(v.get('sha256', '')) for v in origins.values()), 'Test and tool origins missing')
        # Bind runtime tests back to the same source freeze independently.
        frozen = json_bytes(bound_bytes(record.get('frozen_source_inventory'), root))
        require(frozen.get('source_sha256') == candidate['source_sha256'] and isinstance(frozen.get('files'), dict), 'Independent frozen source inventory required')
        require(all(frozen['files'].get(name) == value for name, value in origins.items()), 'Probe source differs from frozen source inventory')
        hosts.append(host)
    require(set(hosts) == set(SYSTEMS), 'Missing or repeated runtime host')
    return hosts


def retained_state(root):
    """Read saved state with this retained stdlib verifier after pip removal."""
    root = Path(root).absolute()
    require(root.is_dir() and not root.is_symlink(), 'Regular retained state root required')
    files = {}
    sessions = {}
    for folder in ('sessions', 'registry'):
        directory = root / folder
        require(directory.is_dir() and not directory.is_symlink(), 'Saved state directory missing')
        for path in sorted(directory.iterdir()):
            raw = regular_bytes(path)
            value = json_bytes(raw)
            require(path.suffix == '.json' and re.fullmatch(r'[0-9a-f]{32}', path.stem) and isinstance(value, dict), 'Unsupported retained schema')
            files[folder + '/' + path.name] = bytes_digest(raw)
            if folder == 'sessions':
                require(value.get('schema_version') == 1 and value.get('id') == path.stem and isinstance(value.get('image_versions'), list) and isinstance(value.get('video_versions'), list), 'Incompatible retained state')
                sessions[path.stem] = value
    require(sessions, 'No retained session')
    require({p.stem for p in (root / 'registry').iterdir()} == set(sessions), 'Incomplete retained registry')
    # Registry paths are read only and bind the original registered media bytes.
    media = {}
    for path in sorted((root / 'registry').iterdir()):
        registry = json_bytes(regular_bytes(path))
        for identifier, entry in registry.get('media', {}).items():
            require(isinstance(entry, dict) and entry.get('path'), 'Unsupported retained media entry')
            media[path.stem + '/' + identifier] = bytes_digest(regular_bytes(entry['path']))
    return {'scope':'retained-state-observed', 'schema_version':1, 'state_files':files, 'media':media,
        'system':platform.system(), 'python':platform.python_version(), 'verifier_sha256':hashlib.sha256(regular_bytes(__file__)).hexdigest()}


def retained_main(argv):
    parser = argparse.ArgumentParser(description='Read compatible retained state after package removal')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    record = retained_state(args.root)
    save_json(args.out, record)
    print(json.dumps({'scope':record['scope'], 'state_files':len(record['state_files']), 'media':len(record['media']), 'verifier_sha256':record['verifier_sha256']}))
    return 0


def produce_studies(argv):
    """Explicit installed checkpoint execution; visual review remains separate."""
    parser = argparse.ArgumentParser(description='Produce two explicitly approved local checkpoint studies')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--version', type=int, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--approval', required=True)
    args = parser.parse_args(argv)
    require(args.approval == 'Two real local studies explicitly approved', 'Explicit study authorisation required')
    from tools.acceptance_runtime import installed_guard, board
    require(installed_guard() == 'INSTALLED RUNTIME', 'Source fixtures cannot produce live model evidence')
    require(args.root.absolute().is_relative_to(Path(os.environ['VYBE_CHECK_ROOT']).absolute()), 'Owned isolated study root required')
    from tools.acceptance_producers import execution_plan, capability_controls, scope
    plan, plan_root = execution_plan(os.environ.get('VYBE_ACCEPTANCE_PLAN'), os.environ.get('VYBE_ACCEPTANCE_PLAN_SHA256'))
    candidate = plan['candidate']
    args.out.mkdir(parents=True, exist_ok=False)
    controls = capability_controls(args.out/'capability-controls', json_bytes(regular_bytes(args.root/'comfyui.json')))
    require(all(controls.get(k) is True for k in ('unsupported_core_refused','missing_checkpoint_refused','unavailable_refused')) and controls['generation_calls']==0, 'Incomplete local capability controls')
    from vybe_check.local_preview import ComfyPreview
    from vybe_check.workshop import SessionStore
    owner=ComfyPreview(args.root);store=SessionStore(args.root)
    capability,origin,_,_=owner._snapshot()
    checkpoint=bytes_digest(regular_bytes(args.checkpoint))
    require(args.checkpoint.name == capability['model'], 'Wrong actual checkpoint file')
    stats=json_bytes(owner._request(origin,'/system_stats'))
    system=stats.get('system',{})
    core_version=system.get('comfyui_version')
    backend_version=system.get('pytorch_version')
    require(_nonempty_text(core_version) and _nonempty_text(backend_version), 'Actual core/backend versions unavailable')
    save_json(args.out/'system-stats.json',stats)
    first=owner.generate(store,args.session,store.read(args.session)['revision'],args.version)
    one=first['previews'][-1];one_raw=regular_bytes(store.resolve_media(args.session,one['id']))
    second=owner.generate(store,args.session,first['revision'],args.version)
    two=second['previews'][-1]
    require(one['id'] != two['id'] and regular_bytes(store.resolve_media(args.session,one['id'])) == one_raw, 'Generated version identity or preservation failed')
    studies=[]
    from urllib.request import urlopen
    from PIL import Image
    from io import BytesIO
    from playwright.sync_api import sync_playwright
    with board(store,second) as (_,board_origin), sync_playwright() as engine:
        options={'headless':True}
        if os.environ.get('VYBE_LAYOUT_BROWSER_EXECUTABLE'):
            options['executable_path']=os.environ['VYBE_LAYOUT_BROWSER_EXECUTABLE']
        browser=engine.chromium.launch(**options)
        try:
            page=browser.new_page();page.goto(board_origin,wait_until='networkidle')
            page.locator('#tab-references').click()
            for index,item in enumerate((one,two),1):
                raw=regular_bytes(store.resolve_media(args.session,item['id']))
                with urlopen(board_origin+'/media/'+args.session+'/'+item['id'],timeout=5) as response:
                    received=response.read(len(raw)+1)
                require(raw == received, 'Board bytes differ from generated output')
                with Image.open(BytesIO(raw)) as decoded:
                    decoded.load();require(decoded.width*decoded.height>0, 'Generated image decode failed')
                image=page.locator('img[src$="'+item['id']+'"]');image.wait_for(state='visible')
                width=image.evaluate('(image) => image.complete ? image.naturalWidth : 0')
                require(width>0,'Browser decode failed')
                for suffix,data in (('image',raw),('board',received)):
                    with (args.out/(str(index)+'-'+suffix+'.bin')).open('xb') as output:output.write(data)
                studies.append({'id':item['id'],'registered_media_id':item['id'],'browser_natural_width':width,
                    'image':file_reference(args.out/(str(index)+'-image.bin'),args.out.parent),
                    'board_response':file_reference(args.out/(str(index)+'-board.bin'),args.out.parent)})
            page.screenshot(path=str(args.out/'board.png'),full_page=True)
        finally:browser.close()
    save_json(args.out/'study.json',{'kind':'local-study','scope':scope('local-checkpoint-observed'),'candidate':candidate,'capability_controls':file_reference(args.out/'capability-controls/controls.json',args.out.parent),'session_id':args.session,
        'state_root':str(args.root.absolute()), 'isolated_parent':str(Path(os.environ['VYBE_CHECK_ROOT']).absolute()),
        'checkpoint_file':str(args.checkpoint.absolute()), 'system':platform.system(),'python':platform.python_version(),'core_version':core_version,'backend_version':backend_version,
        'checkpoint_sha256':checkpoint['sha256'],'workflow':'approved-core','workflow_digest':capability['workflow_digest'],
        'wholly_local':True,'studies':studies,'first_before_sha256':hashlib.sha256(one_raw).hexdigest(),
        'first_after_sha256':hashlib.sha256(regular_bytes(store.resolve_media(args.session,one['id']))).hexdigest(),
        'visual_confirmation':None,'final_release_criteria':'OPEN'})
    return 0


def aggregate_release():
    manifest, records, root = load_bundle()
    candidate = manifest['candidate']
    validate_matrix([r for r in records if r.get('kind') == 'installed-cell'], candidate, root)
    validate_agents([r for r in records if r.get('kind') == 'agent-installation'], candidate, root)
    validate_runtime([r for r in records if r.get('kind') == 'installed-runtime'], candidate, root)
    for criterion, host in (('DoD-43', 'Darwin'), ('DoD-44', 'Windows'), ('DoD-45', 'Linux')):
        native_gate(criterion, host)
    for criterion in ('DoD-11.1', 'DoD-11.2'):
        native_gate(criterion)
    for route in ('typesafe', 'openrouter'):
        provider_gate(route)
    for criterion in ('DoD-48', 'DoD-50', 'DoD-51'):
        study_gate(criterion)
    from tools.acceptance_runtime import lifecycle_gate
    for criterion in ('DoD-9.3', 'DoD-10.2', 'DoD-12'):
        lifecycle_gate(criterion)
    for row in load_contract():
        if row['mode'] == 'final-artifact':
            final_gate(row['id'])
    return {'scope':'complete-native-release-evidence','criteria':len(load_contract()),'candidate':candidate}

def main(argv=None):
    actual = sys.argv[1:] if argv is None else list(argv)
    if actual == ['aggregate']:
        print(json.dumps(aggregate_release(), sort_keys=True))
        return 0
    if actual and actual[0] == 'execute-plan':
        from tools.acceptance_producers import main as execute_plan
        return execute_plan(actual[1:])
    if actual and actual[0] == 'local-study':
        return produce_studies(actual[1:])
    if actual and actual[0] == 'retained-state':
        return retained_main(actual[1:])
    parser = argparse.ArgumentParser(description='Observe an already installed candidate without changing it')
    parser.add_argument('--interpreter', required=True)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cwd', type=Path, required=True)
    parser.add_argument('--run-probes', action='store_true', help='Run the exact host contract in the installed environment')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--manifest-sha256')
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=False)
    env = isolated_environment(args.out / 'environment')
    observation = observe_installed(args.interpreter, args.cwd, args.out / 'observation', env, args.version, args.wheel)
    launch = command_receipt([args.interpreter, '-B', '-m', 'vybe_check', '--root', env['VYBE_CHECK_ROOT'], '--help'], args.cwd, args.out / 'launch', env=env)
    require(launch['exit_code'] == 0 and not launch['timed_out'], 'Installed launch failed')
    if args.run_probes:
        require(args.manifest and HEX.fullmatch(args.manifest_sha256 or ''), 'Reviewed evidence bundle required for native probes')
        env['VYBE_ACCEPTANCE_MANIFEST'] = str(args.manifest.absolute())
        env['VYBE_ACCEPTANCE_MANIFEST_SHA256'] = args.manifest_sha256
        os.environ['VYBE_ACCEPTANCE_MANIFEST'] = env['VYBE_ACCEPTANCE_MANIFEST']
        os.environ['VYBE_ACCEPTANCE_MANIFEST_SHA256'] = args.manifest_sha256
        manifest, _, _ = load_bundle()
        require(manifest['candidate']['version'] == args.version and manifest['candidate']['wheel_sha256'] == hashlib.sha256(regular_bytes(args.wheel)).hexdigest(), 'Observed candidate differs from reviewed bundle')
        run_probes(args.interpreter, args.cwd, args.out / 'probes', env, observation, manifest['candidate'], args.wheel, args.out.parent)
    save_json(args.out / 'observed-host.json', {'observation': observation, 'wheel': bytes_digest(regular_bytes(args.wheel)), 'launch': launch, 'final_release_criteria':'OPEN'})
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print('Host verification refused: ' + str(error), file=sys.stderr)
        raise SystemExit(2)
