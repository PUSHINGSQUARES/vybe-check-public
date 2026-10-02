"""Prompt-only Vybe-Check workshop commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import portalocker

from .workshop import AGENT_ACTIONS, RevisionConflict, SessionStore
from .export import agreed_export


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # Rejected arguments may contain an accidentally pasted credential.
        self.exit(2, 'Vybe-Check command unavailable: invalid arguments\n')


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="vybe-check")
    parser.add_argument("--root", type=Path, default=None, help="Local workshop state directory")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="Create a blank local workshop session")
    new.add_argument("--title", default="Untitled creative session")
    show = sub.add_parser("show", help="Read a workshop session")
    show.add_argument("session_id")
    event = sub.add_parser("event", help="Apply one typed creative event")
    event.add_argument("session_id")
    event.add_argument("--revision", type=int, required=True)
    event.add_argument("--action", required=True, choices=AGENT_ACTIONS)
    event.add_argument("--payload-file", type=Path, required=True)
    export = sub.add_parser('export', help='Export one agreed image or video prompt')
    export.add_argument('session_id')
    export.add_argument('--target', choices=('image', 'video'), default='image')
    export.add_argument('--version', type=int)
    export.add_argument('--out', type=Path)
    board = sub.add_parser('board', help='Open a visible loopback workshop board')
    board.add_argument('--session', help='Show an existing workshop session')
    board.add_argument('--port', type=int, default=8765)
    board.add_argument('--local-studies', action='store_true', help='Enable explicitly requested local studies')
    preview = sub.add_parser('preview', help='Inspect or explicitly request a local look study')
    previews = preview.add_subparsers(dest='preview_command', required=True)
    previews.add_parser('capability', help='Inspect live local study capability')
    run = previews.add_parser('run', help='Request one study from an agreed image version')
    run.add_argument('session_id')
    run.add_argument('--revision', type=int, required=True)
    run.add_argument('--version', type=int, required=True)
    run.add_argument('--shot')
    key = sub.add_parser('key', help='Manage native credentials through the terminal')
    key_sub = key.add_subparsers(dest='key_command', required=True)
    setup = key_sub.add_parser('setup', help='Add a new native credential in a visible terminal')
    setup.add_argument('--route', choices=('typesafe', 'openrouter'), required=True)
    key_sub.add_parser('status', help='Report presence only, never credential values')
    judge = sub.add_parser('judge', help='Inspect anonymous advisory input and explicit spend consent')
    judge_sub = judge.add_subparsers(dest='judge_command', required=True)
    for name in ('quote', 'run'):
        decision = judge_sub.add_parser(name, help='Calculate a local quote' if name == 'quote' else 'Use one explicitly approved attempt')
        decision.add_argument('--route', choices=('typesafe', 'openrouter'), required=True)
        decision.add_argument('--input-file', type=Path, required=True)
        decision.add_argument('--deny-tokens-file', type=Path, help='Local JSON object with an identity tokens list')
        if name == 'run':
            decision.add_argument('--receipt-file', type=Path, required=True)
            decision.add_argument('--approval-file', type=Path, required=True)
            decision.add_argument('--session', required=True)
            decision.add_argument('--revision', type=int, required=True)
    examples = sub.add_parser('examples', help='Copy invented packaged workshop resources')
    example_sub = examples.add_subparsers(dest='examples_command', required=True)
    copy = example_sub.add_parser('copy', help='Copy to a new exclusive folder')
    copy.add_argument('--out', type=Path, required=True)
    sub.add_parser('backup', help='Create an explicit complete private state backup')
    for command in ('install', 'inspect', 'unregister', 'update-registration', 'recover-registration'):
        lifecycle = sub.add_parser(command, formatter_class=argparse.RawTextHelpFormatter, help=f'{command.capitalize()} an explicitly selected skill registration',
            description=('Detach each installed registration with unregister first. Then run '
                         'python -m pip uninstall vybe-check in the environment where it was installed. '
                         'Archives, workshop data, and keys are preserved.'))
        lifecycle.add_argument('--agent', choices=('codex', 'claude'), required=True)
        lifecycle.add_argument('--scope', choices=('user', 'project'), required=True)
        lifecycle.add_argument('--project', type=Path)
        if command == 'recover-registration':
            lifecycle.add_argument('--transaction', required=True, help='Saved transaction ID from the derived registration metadata')
    return parser


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _key_command(args) -> int:
    # Import and construct only for explicit key commands.
    from .credentials import ACCOUNTS, Credentials, CredentialConflict, StoreUnavailable
    if args.key_command == 'setup':
        if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
            print('Credential setup requires a visible terminal', file=sys.stderr)
            return 2
        import getpass
        import warnings
        message = None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                value = getpass.getpass('New credential: ')
            Credentials().store_new(args.route, value)
        except CredentialConflict:
            message = 'Credential already exists; leave it untouched'
        except (Exception, KeyboardInterrupt):
            message = 'Native store unavailable'
        if message is not None:
            print(message, file=sys.stderr)
            return 2
        print('Credential stored')
        return 0
    owner = Credentials()
    unavailable = False
    for account in ACCOUNTS:
        try:
            state = 'present' if owner.read(account) is not None else 'missing'
        except StoreUnavailable:
            state = 'unavailable'
            unavailable = True
        print(f'{account}: {state}')
    return 2 if unavailable else 0


def _judge_command(args) -> int:
    from . import judge
    result = None
    try:
        tokens = ()
        if args.deny_tokens_file is not None:
            local = judge.read_object(args.deny_tokens_file)
            if set(local) != {'tokens'}:
                raise ValueError('Invalid local identity tokens')
            tokens = local['tokens']
        request = judge.prepare_request(judge.read_object(args.input_file), args.route, deny_tokens=tokens)
        if args.judge_command == 'quote':
            result = judge.quote(request)
            # This exact anonymous text is what must be inspected before approval.
            result = ({'status': 'quoted', 'receipt': result, 'outbound_utf8': request.body.decode('utf-8')}
                      if 'receipt_id' in result else {**result, 'outbound_utf8': request.body.decode('utf-8')})
        else:
            receipt = judge.read_object(args.receipt_file)
            if 'receipt' in receipt:
                if (set(receipt) != {'status', 'receipt', 'outbound_utf8'} or receipt['status'] != 'quoted' or
                        receipt['outbound_utf8'] != request.body.decode('utf-8')):
                    raise ValueError('Invalid quote document')
                receipt = receipt['receipt']
            approval = judge.read_object(args.approval_file)
            reason = judge.verify_consent(request, receipt, approval)
            if reason:
                result = {'status': 'unavailable', 'reason': reason}
            elif args.root is None:
                result = {'status': 'unavailable', 'reason': 'explicit_state_root_required'}
            else:
                result = judge.run_advice(request, receipt, approval, SessionStore(args.root), args.session, args.revision)
    except Exception:
        result = {'status': 'unavailable', 'reason': 'invalid_local_input'}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if args.judge_command == 'quote' or result['status'] == 'advisory' else 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == 'key':
        return _key_command(args)
    if args.command == 'judge':
        return _judge_command(args)
    try:
        if args.command == 'examples':
            from .resource_copy import copy_examples
            result = copy_examples(args.out)
        elif args.command == 'backup':
            from .lifecycle import backup_state
            result = backup_state(args.root)
        elif args.command in ('install', 'inspect', 'unregister', 'update-registration', 'recover-registration'):
            from . import install
            target = install.registration_target(args.agent, args.scope, args.project)
            if args.command == 'install':
                result = install.register(target)
            elif args.command == 'inspect':
                result = install.inspect(target)
            elif args.command == 'update-registration':
                result = install.update_registration(target)
            elif args.command == 'recover-registration':
                result = install.recover_transaction(target, args.transaction)
            else:
                result = install.detach(target)
        elif args.command == 'preview':
            from .local_preview import ComfyPreview
            owner = ComfyPreview(args.root)
            result = (owner.capability() if args.preview_command == 'capability' else
                      owner.generate(SessionStore(owner.root), args.session_id, args.revision, args.version, args.shot))
        elif args.command == 'board':
            from .studio.server import run_board
            if args.local_studies:
                from .local_preview import ComfyPreview
                owner = ComfyPreview(args.root)
                return run_board(owner.root, args.session, args.port, preview=owner)
            return run_board(args.root, args.session, args.port)
        elif args.command == "new":
            result = SessionStore(args.root).create(args.title)
        elif args.command == "show":
            result = SessionStore(args.root).read(args.session_id)
        elif args.command == 'export':
            result = agreed_export(SessionStore(args.root).read(args.session_id), args.target, args.version)
            if args.out is not None:
                with args.out.open('x', encoding='utf-8') as stream:
                    stream.write(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
                return 0
        elif args.command == "event":
            result = SessionStore(args.root).apply(
                args.session_id, args.revision, args.action, _read_json(args.payload_file)
            )
    except portalocker.exceptions.LockException:
        print("Vybe-Check workshop unavailable: state is busy; try again", file=sys.stderr)
        return 2
    except OSError:
        print("Vybe-Check workshop unavailable: local state could not be accessed", file=sys.stderr)
        return 2
    except (ValueError, RuntimeError, RevisionConflict) as exc:
        print(f"Vybe-Check workshop request failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
