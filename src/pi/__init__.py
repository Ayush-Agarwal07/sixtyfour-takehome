"""People research agent — freeform target in, provenance-carrying profile out."""
from __future__ import annotations

from .deps import Deps, Tool, ToolUnavailable, traced
from .types import (
    Candidate, Casefile, Claim, Confidence, Evidence, Findings, Output,
    Resolution, Seed, Temporal,
)

__version__ = "0.1.0"

__all__ = [
    "Deps", "Tool", "ToolUnavailable", "traced",
    "Seed", "Candidate", "Claim", "Evidence", "Confidence", "Temporal",
    "Resolution", "Findings", "Output", "Casefile",
    "__version__",
]
