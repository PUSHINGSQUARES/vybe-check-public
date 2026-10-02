"""Named native wheel probes require all real interpreter cells for the host."""
from tools.acceptance_runtime import pending_gate
from tools.verify_host import matrix_gate


def test_macos_wheel():
    pending_gate(matrix_gate, 'Darwin')


def test_windows_wheel():
    pending_gate(matrix_gate, 'Windows')


def test_linux_wheel():
    pending_gate(matrix_gate, 'Linux')
