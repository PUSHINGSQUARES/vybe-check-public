"""Resolve the local workshop data directory once for every entry point."""

import os
import platform
from pathlib import Path


def data_root(explicit=None, *, system=None, env=None, home=None):
    env = os.environ if env is None else env
    home = Path.home() if home is None else Path(home)
    system = platform.system() if system is None else system
    value = explicit or env.get('VYBE_CHECK_ROOT')
    if value:
        return Path(value).expanduser().resolve()
    if system == 'Darwin':
        return home / 'Library' / 'Application Support' / 'vybe-check'
    if system == 'Windows':
        return Path(env.get('LOCALAPPDATA') or home / 'AppData' / 'Local') / 'vybe-check'
    xdg = env.get('XDG_DATA_HOME')
    if xdg and not Path(xdg).is_absolute():
        raise ValueError('XDG_DATA_HOME must be absolute')
    return Path(xdg or home / '.local' / 'share') / 'vybe-check'
