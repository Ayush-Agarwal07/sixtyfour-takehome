"""Gate order: math first; model vetoes a pass, never overrides a fail."""
from __future__ import annotations

from pi.resolve import gate_decision


def test_model_abstain_overrides_math_pass():
    assert gate_decision(True, "ABSTAIN") == "abstain"


def test_model_confirm_cannot_override_math_fail():
    assert gate_decision(False, "CONFIRM") == "continue"


def test_math_pass_and_model_confirm():
    assert gate_decision(True, "CONFIRM") == "confirm"


def test_continue_stays_continue():
    assert gate_decision(True, "CONTINUE") == "continue"
