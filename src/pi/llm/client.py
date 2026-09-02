"""OpenRouter LLM client. JSON-mode structured output, no instructor.

ponytail: the openai SDK + `response_format={"type":"json_object"}` + a pydantic
`model_validate_json` covers structured output in ~10 lines. instructor/tool-calling
is a dep we don't need for one cheap model. Add it in Stage 2 if a non-OpenAI model
needs coaxing. Sync calls — the slice has no concurrency to preserve.
"""
from __future__ import annotations

import os
import uuid
from time import perf_counter
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from .. import constants
from ..deps import ToolUnavailable
from ..trace.events import LLMCall

T = TypeVar("T", bound=BaseModel)


class LLM:
    def __init__(self, cache=None, trace=None):
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise ToolUnavailable("OPENROUTER_API_KEY")
        self._client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)
        self.cache = cache
        self.trace = trace

    def complete(self, tier: str, prompt: str, response_model: Type[T], *, phase: str | None = None) -> T:
        model = constants.TASK_MODELS[tier][0]
        schema = response_model.model_json_schema()
        cache_key = f"{tier}:{prompt}"

        if self.cache is not None:
            hit = self.cache.get_llm(model, cache_key)
            if hit is not None:
                return response_model.model_validate(hit)

        system = ("Respond with ONLY a JSON object matching this schema (no prose):\n"
                  + str(schema))
        t0 = perf_counter()
        resp = self._client.chat.completions.create(
            model=model, temperature=constants.TEMPERATURE,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            extra_body={"usage": {"include": True}},
        )
        obj = response_model.model_validate_json(resp.choices[0].message.content)

        usage = getattr(resp, "usage", None)
        if self.trace is not None:
            eid = uuid.uuid4().hex[:16]
            reasoning = getattr(obj, "reasoning", None)
            ref = self.trace.write_reasoning(eid, reasoning) if reasoning else None
            self.trace.emit(LLMCall(
                event_id=eid, model=model, tier=tier, phase=phase,
                usage={"in": getattr(usage, "prompt_tokens", 0),
                       "out": getattr(usage, "completion_tokens", 0)} if usage else {},
                cost_usd=float(getattr(usage, "cost", 0) or 0),
                latency_ms=(perf_counter() - t0) * 1000, reasoning_ref=ref,
            ))

        if self.cache is not None:
            self.cache.set_llm(model, cache_key, obj.model_dump(mode="json"))
        return obj
