"""OpenRouter LLM client — async, tiered, cached, traced.

- AsyncOpenAI against OpenRouter (single auth path, D6). Never blocks the loop.
- Structured output: JSON schema in the system prompt; `response_format=json_object`
  only for models that accept it (JSON_MODE_PREFIXES); lenient JSON extraction and
  up to RETRIES["validation"] re-asks with the validation error.
- Reasoning tiers (REASONING_TIERS) send `reasoning: {effort}` and no temperature;
  other tiers send `reasoning: {enabled: False}` explicitly — some models on
  OpenRouter default to thinking on, so omitting the param does not turn it off —
  plus `temperature` and a per-tier `max_tokens` (MAX_TOKENS). Reasoning text is
  stored in the sidecar and referenced from the llm_call event.
- Cost from OpenRouter `usage.cost`, else MODEL_PRICES; accumulated in counters.
- Same-tier secondary model on failure (C15).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from time import perf_counter
from typing import Any, Optional, Type, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from .. import constants
from ..deps import ToolUnavailable
from ..trace.events import LLMCall

T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _extract_json(text: str) -> str:
    text = text.strip()
    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()
    if text.startswith("{") or text.startswith("["):
        return text
    i, j = text.find("{"), text.rfind("}")
    return text[i:j + 1] if i != -1 and j > i else text


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, cache=None, trace=None, counters: dict | None = None, client: Any = None):
        key = os.getenv("OPENROUTER_API_KEY")
        if client is None and not key:
            raise ToolUnavailable("OPENROUTER_API_KEY")
        self._client = client or AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1", api_key=key,
            default_headers={"HTTP-Referer": "https://github.com/people-research-agent",
                             "X-Title": "people-research-agent"})
        self.cache = cache
        self.trace = trace
        self.counters = counters if counters is not None else {}
        self._sem = asyncio.Semaphore(constants.SEMAPHORES["openrouter"])

    async def complete(self, tier: str, prompt: str, response_model: Type[T], *,
                       phase: str | None = None, system: str | None = None) -> T:
        primary, secondary = constants.TASK_MODELS[tier]
        try:
            return await self._complete_with(primary, tier, prompt, response_model, phase=phase, system=system)
        except Exception as e:  # noqa: BLE001
            if not secondary:
                raise
            if self.trace is not None:
                self.trace.emit(LLMCall(event_id=uuid.uuid4().hex[:16], model=primary, tier=tier, phase=phase,
                                        note=f"primary failed, falling back to {secondary}: {type(e).__name__}: {str(e)[:120]}"))
            return await self._complete_with(secondary, tier, prompt, response_model, phase=phase, system=system)

    async def _complete_with(self, model: str, tier: str, prompt: str, response_model: Type[T], *,
                             phase: str | None, system: str | None) -> T:
        schema = json.dumps(response_model.model_json_schema())
        sys_msg = (system + "\n\n" if system else "") + (
            "Respond with ONLY a JSON object matching this JSON schema. No prose, no markdown fences.\n" + schema)
        cache_key = f"{tier}\x00{sys_msg}\x00{prompt}"

        if self.cache is not None:
            hit = self.cache.get_llm(model, cache_key)
            if hit is not None:
                obj = response_model.model_validate(hit)
                self._emit(model, tier, phase, obj, usage=None, latency_ms=0.0, cache_hit=True, reasoning=None)
                return obj

        reasoning_on = tier in constants.REASONING_TIERS
        kwargs: dict[str, Any] = dict(model=model, messages=[
            {"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}],
            max_tokens=constants.MAX_TOKENS.get(tier, 1500))
        extra: dict[str, Any] = {"usage": {"include": True}}
        if reasoning_on:
            extra["reasoning"] = {"effort": constants.REASONING_EFFORT}
        else:
            kwargs["temperature"] = constants.TEMPERATURE
            if model.startswith("anthropic/"):
                # OpenRouter runs Anthropic models with thinking on by default;
                # omitting `reasoning` does not turn it off. (Scoped to this family:
                # the Gemini endpoint used for T3-T5 400s on an explicit
                # `enabled: False` — "Reasoning is mandatory for this endpoint".)
                extra["reasoning"] = {"enabled": False}
        if model.startswith(constants.JSON_MODE_PREFIXES):
            kwargs["response_format"] = {"type": "json_object"}
        kwargs["extra_body"] = extra

        messages = kwargs["messages"]
        last_err: Exception | None = None
        for attempt in range(constants.RETRIES["validation"] + 1):
            t0 = perf_counter()
            resp = await self._call(kwargs)
            latency = (perf_counter() - t0) * 1000
            msg = resp.choices[0].message
            content = msg.content or ""
            reasoning = getattr(msg, "reasoning", None) or (msg.model_extra or {}).get("reasoning")
            try:
                obj = response_model.model_validate_json(_extract_json(content))
            except (ValidationError, ValueError) as e:
                last_err = e
                self._emit(model, tier, phase, None, usage=getattr(resp, "usage", None), latency_ms=latency,
                           cache_hit=False, reasoning=None, note=f"validation retry {attempt + 1}: {str(e)[:160]}")
                messages = messages + [{"role": "assistant", "content": content},
                                       {"role": "user", "content": f"Invalid JSON for the schema: {str(e)[:400]}. "
                                                                   "Return ONLY the corrected JSON object."}]
                kwargs["messages"] = messages
                continue
            finish_reason = getattr(resp.choices[0], "finish_reason", None)
            self._emit(model, tier, phase, obj, usage=getattr(resp, "usage", None), latency_ms=latency,
                       cache_hit=False, reasoning=reasoning,
                       note=f"finish_reason={finish_reason}" if finish_reason and finish_reason != "stop" else None)
            if self.cache is not None:
                self.cache.set_llm(model, cache_key, obj.model_dump(mode="json"))
            return obj
        raise LLMError(f"{model}/{tier}: structured output failed after retries: {last_err}")

    async def _call(self, kwargs: dict[str, Any]) -> Any:
        delay = 2.0
        for attempt in range(constants.RETRIES["rate_limit"] + 1):
            try:
                async with self._sem:
                    return await asyncio.wait_for(self._client.chat.completions.create(**kwargs),
                                                  timeout=constants.LLM_TIMEOUT_S)
            except Exception as e:  # noqa: BLE001
                status = getattr(e, "status_code", None)
                if status in (429, 502, 503) and attempt < constants.RETRIES["rate_limit"]:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                raise

    def _emit(self, model: str, tier: str, phase: str | None, obj: Any, *, usage: Any, latency_ms: float,
              cache_hit: bool, reasoning: Optional[str], note: str | None = None) -> None:
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
        cost = 0.0
        if usage is not None:
            extra = getattr(usage, "model_extra", None) or {}
            cost = float(extra.get("cost") or getattr(usage, "cost", 0) or 0)
            if not cost and model in constants.MODEL_PRICES:
                p = constants.MODEL_PRICES[model]
                cost = (tokens_in * p["in"] + tokens_out * p["out"]) / 1e6
        if not cache_hit:
            self.counters["llm_calls"] = self.counters.get("llm_calls", 0) + 1
            self.counters["usd"] = self.counters.get("usd", 0.0) + cost
        if self.trace is None:
            return
        eid = uuid.uuid4().hex[:16]
        text = reasoning or (getattr(obj, "reasoning", None) if obj is not None else None)
        ref = self.trace.write_reasoning(eid, text) if text else None
        self.trace.emit(LLMCall(event_id=eid, model=model, tier=tier, phase=phase,
                                usage={"in": tokens_in, "out": tokens_out}, cost_usd=cost,
                                latency_ms=latency_ms, cache_hit=cache_hit, reasoning_ref=ref, note=note))
