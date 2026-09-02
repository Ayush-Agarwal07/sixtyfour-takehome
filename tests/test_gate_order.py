"""Gate order: math first; model vetoes a pass, never overrides a fail."""
from __future__ import annotations

from pi.resolve import gate_decision, math_pass


def test_model_abstain_overrides_math_pass():
    assert gate_decision(True, "ABSTAIN") == "abstain"


def test_model_confirm_cannot_override_math_fail():
    assert gate_decision(False, "CONFIRM") == "continue"


def test_math_pass_and_model_confirm():
    assert gate_decision(True, "confirm") == "confirm"


def test_margin():
    assert math_pass(0.95, 0.20) and not math_pass(0.95, 0.70) and not math_pass(0.80, 0.0)
