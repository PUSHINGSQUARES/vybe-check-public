"""Explicit later installed-provider probe. Default tests never spend or load keys.

A missing quote, approval, or native route remains pending, never PASS.
This probe is not a native store acceptance substitute.
"""
import json
import pytest


def test_typesafe_live():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import provider_gate
    pending_gate(provider_gate,'typesafe')


def test_openrouter_live():
    from tools.acceptance_runtime import pending_gate
    from tools.verify_host import provider_gate
    pending_gate(provider_gate,'openrouter')


def test_live_probes_are_explicit_and_pending_without_approval():
    assert live_probe([])==2


def live_probe(argv):
    if not argv or argv[0]!='--provider-probe':
        print(json.dumps({'status':'pending','reason':'explicit_provider_probe_required'}))
        return 2
    # Reuse the same gates, never mint consent or enable unknown pricing here.
    from vybe_check.cli import main
    if '--root' not in argv or '--approval-file' not in argv or '--receipt-file' not in argv or '--evidence-file' not in argv:
        print(json.dumps({'status':'pending','reason':'quote_and_approval_required'}))
        return 2
    from importlib.metadata import distribution
    from pathlib import Path
    from vybe_check import judge
    import hashlib
    import time
    # Source PYTHONPATH is not installed/native acceptance.
    try:
        installed = distribution('vybe-check')
        module = Path(judge.__file__).resolve()
        if not any(Path(installed.locate_file(f)).resolve() == module for f in installed.files or ()):
            raise ValueError()
    except Exception:
        print(json.dumps({'status': 'pending', 'reason': 'installed_module_required'}))
        return 2
    args = argv[1:]
    index = args.index('--evidence-file')
    if index + 1 >= len(args):
        return 2
    evidence = Path(args[index + 1])
    args = args[:index] + args[index + 2:]
    from vybe_check import credentials
    original_credentials = credentials.Credentials
    consumptions = []
    class ObservedCredentials:
        def read(self, route):
            value = original_credentials().read(route)
            # Observe the selected actual adapter, without retaining the value.
            consumptions.append({'route':route, 'backend':credentials.native_backend().identity})
            return value
    calls = []
    original = judge.send_once
    def observed(endpoint, key, body):
        item = {'endpoint': endpoint, 'payload_sha256': hashlib.sha256(body).hexdigest(),
                'payload_bytes': len(body), 'call_number': len(calls) + 1}
        calls.append(item)
        start = time.monotonic()
        try:
            reply = original(endpoint, key, body)
            route = next(k for k, value in judge.ENDPOINTS.items() if value == endpoint)
            wire = json.loads(body)
            source = json.loads(wire['state'])['source_image_version']
            request = judge.PreparedRequest(route, judge.MODELS[route], source, body)
            answers = judge.validate_response(reply, request)
            item['answers'] = answers
            item['response_body_sha256'] = hashlib.sha256(json.dumps(reply, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            item['requested_model'] = request.model
            item['actual_model'] = reply['model']
            provider = reply.get('provider')
            item['actual_provider'] = provider if isinstance(provider, str) and len(provider) <= 80 else None
            item['provider_observation'] = 'Reported by response' if item['actual_provider'] else 'Not reported by response'
            # Only bounded typed usage fields, never provider prose or errors.
            usage = reply.get('usage', {})
            item['usage'] = {k: usage[k] for k in ('input_tokens', 'output_tokens')
                if isinstance(usage, dict) and type(usage.get(k)) is int and 0 <= usage[k] <= 1000000000}
            item['status'] = 'validated_response'
            return reply
        except Exception:
            item['status'] = 'unavailable'
            raise judge.TransportUnavailable() from None
        finally:
            item['elapsed_seconds'] = time.monotonic() - start
    # Exclusive output is opened before any possible attempt. Existing evidence
    # is never replaced. This file is a probe receipt, not a release verdict.
    with evidence.open('x', encoding='utf-8') as output:
        judge.send_once = observed
        credentials.Credentials = ObservedCredentials
        try:
            code = main(args)
        finally:
            judge.send_once = original
            credentials.Credentials = original_credentials
            bound_inputs = {}
            for flag in ('--input-file','--approval-file','--receipt-file'):
                if flag in args and args.index(flag) + 1 < len(args):
                    from tools.verify_host import regular_bytes
                    raw = regular_bytes(args[args.index(flag)+1])
                    bound_inputs[flag] = {'sha256':hashlib.sha256(raw).hexdigest(), 'size':len(raw)}
            json.dump({'status': 'pending', 'scope': 'Installed provider probe only',
                       'calls': calls, 'native_consumptions':consumptions, 'input_bindings':bound_inputs,
                       'call_count':len(calls), 'retry_count':0, 'fallback_count':0, 'final_release_criteria': 'OPEN'}, output, indent=2)
    return code



if __name__=='__main__':
    import sys
    raise SystemExit(live_probe(sys.argv[1:]))


def test_provider_probe_without_explicit_evidence_or_consent_stays_pending(tmp_path):
    assert live_probe(['--provider-probe','--root',str(tmp_path/'explicit-state')])==2
    assert not (tmp_path/'explicit-state').exists()
