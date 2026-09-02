"""Company domain resolution — mocked Serper via respx. No live network calls."""
from __future__ import annotations

import httpx
import respx

from pi.deps import Deps, ToolUnavailable
from pi.tools.company import Company


@respx.mock
async def test_resolve_skips_aggregator_picks_official_domain(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    respx.post("https://google.serper.dev/search").mock(
        return_value=httpx.Response(200, json={
            "organic": [
                {"link": "https://www.linkedin.com/company/ramp", "title": "Ramp | LinkedIn", "snippet": "..."},
                {"link": "https://ramp.com", "title": "Ramp - Corporate Cards", "snippet": "..."},
            ]
        })
    )

    async with httpx.AsyncClient() as client:
        company = Company(Deps(http=client))
        result = await company.resolve("Ramp")

    assert result is not None
    assert result["name"] == "Ramp"
    assert result["domain"] == "ramp.com"
    assert "linkedin.com" not in result["aliases"]


@respx.mock
async def test_missing_key_raises_tool_unavailable(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)

    async with httpx.AsyncClient() as client:
        company = Company(Deps(http=client))
        try:
            await company.resolve("Ramp")
        except ToolUnavailable:
            pass
        else:
            raise AssertionError("expected ToolUnavailable")
