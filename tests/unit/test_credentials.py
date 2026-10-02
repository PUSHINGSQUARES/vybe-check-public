"""Credential boundaries; all stores here are synthetic."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest


def credentials():
    assert importlib.util.find_spec('vybe_check.credentials') is not None, 'Native credential module is missing'
    from vybe_check import credentials
    return credentials


class MemoryStore:
    def __init__(self):
        self.values = {}
        self.calls = []
    def get_password(self, service, account):
        self.calls.append(('read', service, account))
        return self.values.get((service, account))
    def add_password(self, service, account, value):
        self.calls.append(('add', service, account))
        if (service, account) in self.values:
            raise credentials().CredentialConflict()
        self.values[service, account] = value


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    c = credentials()
    for name in ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'XDG_DATA_HOME'):
        monkeypatch.setenv(name, str(tmp_path / 'home'))
    monkeypatch.setenv('VYBE_CHECK_ROOT', str(tmp_path / 'session'))
    monkeypatch.delenv('PYTHON_KEYRING_BACKEND', raising=False)
    backend = MemoryStore()
    monkeypatch.setattr(c, 'native_backend', lambda: backend)
    return c, backend


def test_module_exists_and_construction_is_lazy(monkeypatch):
    c = credentials()
    def forbidden():
        pytest.fail('Native store constructed without explicit use')
    monkeypatch.setattr(c, 'native_backend', forbidden)
    c.Credentials()


@pytest.mark.parametrize('configured', ['keyring.backends.null.Keyring', 'keyrings.alt.file.PlaintextKeyring', 'example.ThirdParty', ''])
def test_configured_backend_refuses_even_empty(monkeypatch, configured):
    c = credentials()
    monkeypatch.setenv('PYTHON_KEYRING_BACKEND', configured)
    with pytest.raises(c.StoreUnavailable, match='Native store unavailable'):
        c.native_backend()


def test_create_readback_and_fixed_namespace(synthetic):
    c, backend = synthetic
    owner = c.Credentials()
    owner.store_new('typesafe', 'Synthetic internal value')
    assert owner.read('typesafe') == 'Synthetic internal value'
    assert backend.calls == [('read', 'vybe-check', 'typesafe'), ('add', 'vybe-check', 'typesafe'), ('read', 'vybe-check', 'typesafe'), ('read', 'vybe-check', 'typesafe')]
    with pytest.raises(c.CredentialConflict):
        owner.store_new('typesafe', 'Another value')
    assert backend.values[('vybe-check', 'typesafe')] == 'Synthetic internal value'
    assert sum(call[0] == 'add' for call in backend.calls) == 1


@pytest.mark.parametrize('account', ['other', '../typesafe', None, [], ''])
def test_account_validation_precedes_store_access(synthetic, account):
    c, backend = synthetic
    with pytest.raises(ValueError, match='Unknown credential account'):
        c.Credentials().read(account)
    with pytest.raises(ValueError, match='Unknown credential account'):
        c.Credentials().store_new(account, 'Internal')
    assert backend.calls == []


@pytest.mark.parametrize('value', [None, '', '   ', 42])
def test_empty_validation_precedes_store_access(synthetic, value):
    c, backend = synthetic
    with pytest.raises(ValueError, match='Empty credential'):
        c.Credentials().store_new('typesafe', value)
    assert backend.calls == []


@pytest.mark.parametrize('operation', ['read', 'create', 'readback'])
def test_errors_are_sanitised_without_exception_chain(synthetic, operation):
    c, backend = synthetic
    canary = 'sk-invented-native-canary-987654321'
    reads = []
    def read(*args):
        reads.append(True)
        if operation == 'read' or (operation == 'readback' and len(reads) > 1):
            raise RuntimeError(canary)
        return None
    def add(*args):
        if operation == 'create':
            raise RuntimeError(canary)
    backend.get_password, backend.add_password = read, add
    with pytest.raises(c.StoreUnavailable) as failure:
        c.Credentials().store_new('typesafe', canary)
    assert str(failure.value) == 'Native store unavailable'
    assert failure.value.__cause__ is None and failure.value.__context__ is None
    assert canary not in repr(failure.value)


def test_external_insert_is_preserved_without_retry(synthetic):
    c, backend = synthetic
    inserted = 'External internal value'
    def insert(service, account, value):
        backend.values[service, account] = inserted
        raise c.CredentialConflict()
    backend.add_password = insert
    with pytest.raises(c.CredentialConflict):
        c.Credentials().store_new('typesafe', 'Proposed value')
    assert backend.values[('vybe-check', 'typesafe')] == inserted


def test_linked_lock_root_refuses_without_store_access(synthetic, tmp_path):
    c, backend = synthetic
    home = tmp_path / 'home'
    home.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (home / '.vybe-check-security').symlink_to(outside, target_is_directory=True)
    with pytest.raises(c.StoreUnavailable):
        c.Credentials().store_new('typesafe', 'Internal')
    assert backend.calls == [] and list(outside.iterdir()) == []


def test_macos_add_uses_binary_data_and_no_destructive_setter(monkeypatch):
    c = credentials()
    import ctypes
    calls = []
    class Framework:
        def CFDataCreate(self, allocator, pointer, length):
            calls.append(('data', ctypes.string_at(pointer, length)))
            return 11
        def CFRelease(self, item):
            calls.append(('release', item))
    api = SimpleNamespace(_found=Framework(), k_=lambda name: name,
        create_query=lambda **kwargs: calls.append(('query', kwargs)) or 12,
        SecItemAdd=lambda query, result: calls.append(('add', query, result)) or 0,
        find_generic_password=lambda *a, **kw: None)
    monkeypatch.setattr(c, '_macos_api', lambda: api)
    native = c.MacOSKeychain()
    native.add_password('acceptance', 'invented', 'éInternal')
    assert calls[0] == ('data', 'éInternal'.encode())
    assert calls[1][1]['kSecValueData'].value == 11
    assert calls[2] == ('add', 12, None)
    assert ('release', 12) in calls and ('release', 11) in calls
    api.SecItemAdd = lambda *a: -25299
    with pytest.raises(c.CredentialConflict):
        native.add_password('acceptance', 'invented', 'Another value')


def test_secret_service_locked_refusal_and_replace_false(monkeypatch):
    c = credentials()
    calls = []
    class Collection:
        locked = False
        connection = SimpleNamespace(close=lambda: calls.append('close'))
        def is_locked(self): return self.locked
        def search_items(self, attributes): return []
        def create_item(self, label, attributes, value, replace):
            calls.append(('create', attributes, value, replace))
    collection = Collection()
    api = SimpleNamespace(dbus_init=lambda: collection.connection, get_default_collection=lambda bus: collection)
    monkeypatch.setattr(c, '_secret_service_api', lambda: api)
    native = c.LinuxSecretService()
    native.add_password('acceptance', 'invented', 'Internal')
    assert calls[0] == ('create', {'service': 'acceptance', 'username': 'invented'}, b'Internal', False)
    collection.locked = True
    with pytest.raises(c.StoreUnavailable): native.get_password('acceptance', 'invented')
    assert len([x for x in calls if isinstance(x, tuple)]) == 1


def test_windows_passwordvault_explicit_add_and_missing_code(monkeypatch):
    c = credentials()
    calls = []
    class Vault:
        def retrieve(self, service, account):
            error = OSError('Internal failure')
            error.winerror = 1168
            raise error
        def add(self, credential): calls.append(credential)
    monkeypatch.setattr(c, '_windows_api', lambda: (Vault, lambda *args: args))
    native = c.WindowsLocker()
    assert native.get_password('acceptance', 'invented') is None
    native.add_password('acceptance', 'invented', 'Internal')
    assert calls == [('acceptance', 'invented', 'Internal')]
    def denied(*a): raise OSError('Denied')
    native.vault.retrieve = denied
    with pytest.raises(OSError): native.get_password('acceptance', 'invented')


def test_terminal_setup_and_presence_only(synthetic, monkeypatch, capsys):
    c, backend = synthetic
    from vybe_check.cli import main
    import getpass
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        monkeypatch.setattr(stream, 'isatty', lambda: True)
    canary = 'sk-invented-terminal-canary-123456789'
    calls = []
    monkeypatch.setattr(getpass, 'getpass', lambda *a, **kw: calls.append(True) or canary)
    assert main(['key', 'setup', '--route', 'typesafe']) == 0
    assert main(['key', 'status']) == 0
    assert main(['key', 'setup', '--route', 'typesafe']) == 2
    output = capsys.readouterr()
    concealed = canary not in output.out + output.err
    assert concealed, 'Rejected argument was echoed'
    assert 'typesafe: present' in output.out and 'openrouter: missing' in output.out
    assert 'Credential already exists' in output.err and calls == [True, True]


def test_nonterminal_setup_refuses_before_prompt_or_backend(monkeypatch, capsys):
    c = credentials()
    from vybe_check.cli import main
    import getpass
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)
    monkeypatch.setattr(getpass, 'getpass', lambda *a, **kw: pytest.fail('Prompted without terminal'))
    monkeypatch.setattr(c, 'native_backend', lambda: pytest.fail('Constructed without terminal'))
    assert main(['key', 'setup', '--route', 'typesafe']) == 2
    assert 'visible terminal' in capsys.readouterr().err


def test_status_locked_is_unavailable_not_missing(synthetic, capsys):
    c, backend = synthetic
    from vybe_check.cli import main
    def denied(*a): raise RuntimeError('sk-invented-error-canary-123456789')
    backend.get_password = denied
    assert main(['key', 'status']) == 2
    output = capsys.readouterr()
    assert output.out == 'typesafe: unavailable\nopenrouter: unavailable\n'
    assert output.err == ''


@pytest.mark.parametrize('system, selected', [('Darwin', 'MacOSKeychain'), ('Linux', 'LinuxSecretService'), ('Windows', 'WindowsLocker')])
def test_explicit_platform_selection_only(monkeypatch, system, selected):
    c = credentials()
    monkeypatch.delenv('PYTHON_KEYRING_BACKEND', raising=False)
    monkeypatch.setattr(c.platform, 'system', lambda: system)
    expected = object()
    for name in ('MacOSKeychain', 'LinuxSecretService', 'WindowsLocker'):
        monkeypatch.setattr(c, name, (lambda: expected) if name == selected else (lambda: pytest.fail('Wrong platform selected')))
    assert c.native_backend() is expected


def test_windows_external_insertion_before_add_is_preserved(monkeypatch):
    c = credentials()
    inserted = object()
    calls = []
    class Vault:
        def retrieve(self, *args):
            calls.append('read')
            return SimpleNamespace(retrieve_password=lambda: None, password=inserted)
        def add(self, credential): pytest.fail('Existing external item was passed to Add')
    monkeypatch.setattr(c, '_windows_api', lambda: (Vault, lambda *args: args))
    native = c.WindowsLocker()
    with pytest.raises(c.CredentialConflict):
        native.add_password('acceptance', 'invented', 'Proposed')
    assert calls == ['read']


def test_secret_service_external_insertion_between_checks_is_preserved(monkeypatch):
    c = credentials()
    values = []
    external = object()
    class Collection:
        connection = SimpleNamespace(close=lambda: None)
        def is_locked(self): return False
        def search_items(self, attributes): return []
        def create_item(self, label, attributes, value, replace):
            values.append(external)
            assert replace is False
            values.append(value)
    collection = Collection()
    api = SimpleNamespace(dbus_init=lambda: collection.connection, get_default_collection=lambda connection: collection)
    monkeypatch.setattr(c, '_secret_service_api', lambda: api)
    c.LinuxSecretService().add_password('acceptance', 'invented', 'Proposed')
    assert values[0] is external and len(values) == 2


def test_secret_arguments_rejected_without_echo(capsys):
    credentials()
    from vybe_check.cli import main
    canary = 'sk-invented-argument-canary-987654321'
    with pytest.raises(SystemExit) as outcome:
        main(['key', 'setup', '--route', 'typesafe', '--key', canary])
    assert outcome.value.code == 2
    output = capsys.readouterr()
    concealed = canary not in output.out + output.err
    assert concealed, 'Rejected argument was echoed'


def test_cancelled_terminal_prompt_is_sanitised(synthetic, monkeypatch, capsys):
    c, backend = synthetic
    from vybe_check.cli import main
    import getpass
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        monkeypatch.setattr(stream, 'isatty', lambda: True)
    def cancel(*a, **kw): raise EOFError('sk-invented-prompt-canary-123456789')
    monkeypatch.setattr(getpass, 'getpass', cancel)
    assert main(['key', 'setup', '--route', 'typesafe']) == 2
    assert capsys.readouterr().err == 'Native store unavailable\n'
    assert backend.calls == []


def _synthetic_tty(value=''):
    import io
    class TTY(io.StringIO):
        reads = 0
        def isatty(self): return True
        def fileno(self): return 0
        def readline(self, *args, **kwargs):
            self.reads += 1
            return super().readline(*args, **kwargs)
    return TTY(value)


@pytest.mark.parametrize('echo_failure', ['tcgetattr', 'tcsetattr'])
def test_actual_stdlib_fallback_refuses_before_input_or_credentials(tmp_path, monkeypatch, echo_failure):
    c = credentials()
    from vybe_check.cli import main
    import getpass
    import secrets
    import warnings
    value = secrets.token_urlsafe(32)
    stdin = _synthetic_tty(value + '\n')
    stdout, stderr = _synthetic_tty(), _synthetic_tty()
    calls = {'construct': 0, 'store': 0}
    class Sink:
        def __init__(self): calls['construct'] += 1
        def store_new(self, account, candidate): calls['store'] += 1
    monkeypatch.setattr(c, 'Credentials', Sink)
    monkeypatch.setattr(getpass, 'getpass', getpass.unix_getpass)
    monkeypatch.setattr(getpass.os, 'open', lambda *a, **kw: (_ for _ in ()).throw(OSError('Synthetic terminal unavailable')))
    attrs = [0, 0, 0, getpass.termios.ECHO | getpass.termios.ICANON, 0, 0, []]
    def fail(*args): raise getpass.termios.error('Synthetic echo control unavailable')
    monkeypatch.setattr(getpass.termios, 'tcgetattr', fail if echo_failure == 'tcgetattr' else lambda *a: attrs[:])
    monkeypatch.setattr(getpass.termios, 'tcsetattr', fail if echo_failure == 'tcsetattr' else lambda *a: None)
    for name, stream in [('stdin', stdin), ('stdout', stdout), ('stderr', stderr)]:
        monkeypatch.setattr(sys, name, stream)
    saved = list(warnings.filters)
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter('always', getpass.GetPassWarning)
        warnings.simplefilter('error', UserWarning)
        warnings.simplefilter('always', getpass.GetPassWarning)
        before = list(warnings.filters)
        status = main(['--root', str(tmp_path / 'session'), 'key', 'setup', '--route', 'typesafe'])
        observed = {'exit': status, 'input_reads': stdin.reads, **calls,
            'fixed_output': stdout.getvalue() == '' and stderr.getvalue() == 'Native store unavailable\n',
            'secret_concealed': value not in stdout.getvalue() + stderr.getvalue(),
            'filters_restored': warnings.filters == before,
            'fallback_warning_exposed': bool(seen)}
        warnings.warn('Synthetic outside-call control', getpass.GetPassWarning)
        outside_warning_restored = len(seen) == 1
        with pytest.raises(UserWarning):
            warnings.warn('Synthetic unrelated warning', UserWarning)
    restored = warnings.filters == saved
    assert observed == {'exit': 2, 'input_reads': 0, 'construct': 0, 'store': 0,
        'fixed_output': True, 'secret_concealed': True, 'filters_restored': True,
        'fallback_warning_exposed': False}
    assert restored and outside_warning_restored


def test_actual_stdlib_hidden_input_succeeds_and_restores_terminal_and_warnings(tmp_path, monkeypatch):
    c = credentials()
    from vybe_check.cli import main
    import getpass
    import secrets
    import warnings
    value = secrets.token_urlsafe(32)
    stdin = _synthetic_tty(value + '\n')
    stdout, stderr = _synthetic_tty(), _synthetic_tty()
    calls = {'construct': 0, 'store': 0, 'value_equal': False}
    class Sink:
        def __init__(self): calls['construct'] += 1
        def store_new(self, account, candidate):
            calls['store'] += 1
            calls['value_equal'] = candidate == value and account == 'typesafe'
    monkeypatch.setattr(c, 'Credentials', Sink)
    monkeypatch.setattr(getpass, 'getpass', getpass.unix_getpass)
    monkeypatch.setattr(getpass.os, 'open', lambda *a, **kw: (_ for _ in ()).throw(OSError('Synthetic direct terminal unavailable')))
    attrs = [0, 0, 0, getpass.termios.ECHO | getpass.termios.ICANON, 0, 0, []]
    settings = []
    monkeypatch.setattr(getpass.termios, 'tcgetattr', lambda *a: attrs[:])
    monkeypatch.setattr(getpass.termios, 'tcsetattr', lambda fd, flags, attributes: settings.append(attributes[:]))
    for name, stream in [('stdin', stdin), ('stdout', stdout), ('stderr', stderr)]:
        monkeypatch.setattr(sys, name, stream)
    saved = list(warnings.filters)
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter('always', getpass.GetPassWarning)
        before = list(warnings.filters)
        status = main(['--root', str(tmp_path / 'session'), 'key', 'setup', '--route', 'typesafe'])
        observed = {'exit': status, 'input_reads': stdin.reads, **calls,
            'hidden_then_restored': len(settings) == 2 and not(settings[0][3] & getpass.termios.ECHO) and settings[1] == attrs,
            'secret_concealed': value not in stdout.getvalue() + stderr.getvalue(),
            'success_output': stdout.getvalue() == 'Credential stored\n',
            'filters_restored': warnings.filters == before, 'no_warnings': not seen}
    assert observed == {'exit': 0, 'input_reads': 1, 'construct': 1, 'store': 1,
        'value_equal': True, 'hidden_then_restored': True, 'secret_concealed': True,
        'success_output': True, 'filters_restored': True, 'no_warnings': True}
    assert warnings.filters == saved
