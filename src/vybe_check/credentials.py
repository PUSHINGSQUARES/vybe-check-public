"""Explicit native credential stores, accessed only on an explicit request.

Setup adds once and never deletes or replaces. The per-user lock serialises
this application's writers, not arbitrary external credential managers.
PasswordVault may roam under the operating system's Microsoft account policy.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import platform
import time

import portalocker

from .install import no_links, _open_regular

SERVICE = 'vybe-check'
ACCOUNTS = ('typesafe', 'openrouter')


class StoreUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Native store unavailable')


class CredentialConflict(ValueError):
    def __init__(self):
        super().__init__('Credential already exists; leave it untouched')


def _macos_api():
    # This imports framework bindings only, never generic keyring discovery.
    from keyring.backends.macOS import api
    api._found.CFDataCreate.restype = ctypes.c_void_p
    api._found.CFDataCreate.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long)
    api._found.CFRelease.argtypes = (ctypes.c_void_p,)
    api._found.CFRelease.restype = None
    return api


class MacOSKeychain:
    identity = 'macOS Keychain'

    def __init__(self):
        self.api = _macos_api()

    def get_password(self, service, account):
        return self.api.find_generic_password(None, service, account, not_found_ok=True)

    def add_password(self, service, account, value):
        api = self.api
        encoded = value.encode('utf-8')
        data = api._found.CFDataCreate(None, encoded, len(encoded))
        if not data:
            raise StoreUnavailable()
        query = None
        try:
            query = api.create_query(kSecClass=api.k_('kSecClassGenericPassword'),
                kSecAttrService=service, kSecAttrAccount=account,
                kSecValueData=ctypes.c_void_p(data))
            if not query:
                raise StoreUnavailable()
            status = api.SecItemAdd(query, None)
            if status == -25299:  # errSecDuplicateItem; no delete, update, or retry.
                raise CredentialConflict()
            if status != 0:
                raise StoreUnavailable()
        finally:
            if query:
                api._found.CFRelease(query)
            api._found.CFRelease(data)


def _secret_service_api():
    import secretstorage
    return secretstorage


class LinuxSecretService:
    identity = 'Linux Secret Service'

    def __init__(self):
        self.api = _secret_service_api()

    @contextmanager
    def _collection(self):
        connection = self.api.dbus_init()
        try:
            collection = self.api.get_default_collection(connection)
            # Locked or denied is unavailable, never interpreted as missing.
            if collection.is_locked():
                raise StoreUnavailable()
            yield collection
        finally:
            connection.close()

    def get_password(self, service, account):
        with self._collection() as collection:
            items = list(collection.search_items({'service': service, 'username': account}))
            if not items:
                return None
            if len(items) != 1 or items[0].is_locked():
                raise StoreUnavailable()
            return items[0].get_secret().decode('utf-8')

    def add_password(self, service, account, value):
        attributes = {'service': service, 'username': account}
        with self._collection() as collection:
            if list(collection.search_items(attributes)):
                raise CredentialConflict()
            # The native API permits parallel external insertions. False preserves
            # those items; ambiguous readback is unavailable, without a retry.
            collection.create_item('Vybe-Check credential', attributes,
                                   value.encode('utf-8'), replace=False)


def _windows_api():
    from winrt.windows.security.credentials import PasswordVault, PasswordCredential
    return PasswordVault, PasswordCredential


class WindowsLocker:
    identity = 'Windows PasswordVault / Credential Locker'

    def __init__(self):
        vault_type, self.credential_type = _windows_api()
        self.vault = vault_type()

    def get_password(self, service, account):
        try:
            credential = self.vault.retrieve(service, account)
        except OSError as exc:
            # These codes still require actual release-host projection evidence.
            if getattr(exc, 'winerror', None) in (-2147023728, 1168):
                return None
            raise
        credential.retrieve_password()
        return credential.password

    def add_password(self, service, account, value):
        # Duplicate semantics require a real Windows acceptance probe. No update,
        # remove, generic Credential Manager backend, or retry is permitted here.
        if self.get_password(service, account) is not None:
            raise CredentialConflict()
        self.vault.add(self.credential_type(service, account, value))


def native_backend():
    if 'PYTHON_KEYRING_BACKEND' in os.environ:
        raise StoreUnavailable()
    backend = None
    try:
        system = platform.system()
        if system == 'Darwin':
            backend = MacOSKeychain()
        elif system == 'Linux':
            backend = LinuxSecretService()
        elif system == 'Windows':
            backend = WindowsLocker()
    except Exception:
        pass
    # Raise outside the handler: even the exception chain contains no secret.
    if backend is None:
        raise StoreUnavailable()
    return backend


@contextmanager
def _setup_lock(account):
    directory = no_links(Path.home() / '.vybe-check-security')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = no_links(directory / (account + '.setup.lock'))
    fd = _open_regular(path, os.O_CREAT | os.O_RDWR, create=True)
    with os.fdopen(fd, 'a', encoding='utf-8') as stream:
        deadline = time.monotonic() + 5
        while True:
            try:
                portalocker.lock(stream, portalocker.LOCK_EX | portalocker.LOCK_NB)
                break
            except portalocker.exceptions.LockException:
                if time.monotonic() >= deadline:
                    raise StoreUnavailable()
                time.sleep(.05)
        try:
            yield
        finally:
            portalocker.unlock(stream)


class Credentials:
    def __init__(self):
        self._backend = None

    @staticmethod
    def _account(account):
        if not isinstance(account, str) or account not in ACCOUNTS:
            raise ValueError('Unknown credential account')

    def _native(self):
        if 'PYTHON_KEYRING_BACKEND' in os.environ:
            raise StoreUnavailable()
        if self._backend is None:
            self._backend = native_backend()
        return self._backend

    def read(self, account):
        self._account(account)
        failed = False
        try:
            value = self._native().get_password(SERVICE, account)
            if value is None or isinstance(value, str):
                return value
            failed = True
        except Exception:
            failed = True
        if failed:
            raise StoreUnavailable()

    def store_new(self, account, value):
        self._account(account)
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Empty credential')
        conflict = False
        failed = False
        try:
            with _setup_lock(account):
                if self.read(account) is not None:
                    raise CredentialConflict()
                self._native().add_password(SERVICE, account, value)
                if self.read(account) != value:
                    raise StoreUnavailable()
        except CredentialConflict:
            conflict = True
        except Exception:
            failed = True
        if conflict:
            raise CredentialConflict()
        if failed:
            raise StoreUnavailable()
