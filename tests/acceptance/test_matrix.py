"""The complete native install matrix cannot close from source fixtures."""
from tools.acceptance_runtime import pending_gate
from tools.verify_host import matrix_gate


def test_python_matrix():
    pending_gate(matrix_gate)
