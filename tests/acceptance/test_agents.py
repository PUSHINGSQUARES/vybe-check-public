"""Minimal human-reviewed native outcomes, without conversation transcripts."""
from tools.acceptance_runtime import pending_gate
from tools.verify_host import agent_gate


def test_codex_discovery():
    pending_gate(agent_gate, agent='codex')


def test_claude_discovery():
    pending_gate(agent_gate, agent='claude')


def test_empty_brief():
    pending_gate(agent_gate, scenario='empty_brief')


def test_one_question():
    pending_gate(agent_gate, scenario='one_question')


def test_complete_brief():
    pending_gate(agent_gate, scenario='complete_brief')


def test_image_only():
    pending_gate(agent_gate, scenario='image_only')


def test_model_advice():
    pending_gate(agent_gate, scenario='model_advice')
