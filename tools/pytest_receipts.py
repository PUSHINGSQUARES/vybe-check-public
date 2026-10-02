"""Exclusive actual pytest phase observations for an installed host run."""
import json
import os
from pathlib import Path
import time

ROWS = []


def pytest_sessionstart(session):
    from tools.acceptance_runtime import installed_guard
    installed_guard()


def pytest_runtest_logreport(report):
    ROWS.append({'nodeid':report.nodeid, 'when':report.when, 'outcome':report.outcome,
        'duration':report.duration, 'observed_at':time.time()})


def pytest_sessionfinish(session, exitstatus):
    target = os.environ.get('VYBE_PYTEST_RECEIPT')
    if not target:
        return
    records = {'scope':('authoring-synthetic' if os.environ.get('VYBE_AUTHORING_ONLY') == '1' else 'actual-pytest-phases'), 'exit_code':int(exitstatus), 'phases':ROWS}
    with Path(target).open('x', encoding='utf-8') as stream:
        json.dump(records, stream, indent=2, allow_nan=False)
        stream.write('\n')
