"""Triage with TypeSafe Jev (a decision model), evaluation delegated to another analyzer.

Jev answers typed questions about one `state` instead of generating text.
Triage is a yes/no decision, so it maps onto Jev's `noul` question type
(probability 0..1 that a statement is true):

  state     = the collector's buying criteria (identical on every call)
  questions = one noul per listing: "this listing is worth a photo-based
              look", with the listing's title/description in `instructions`

All questions of a request are answered in parallel against the same state,
so one HTTP call triages a whole batch. API: https://docs.typesafe.ai
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from watchhunter.application.ports.analyzer import AnalyzerPort, TriageResult
from watchhunter.config.logging import get_logger
from watchhunter.costs.budget import BudgetGuard
from watchhunter.domain.evaluation import WatchEvaluation
from watchhunter.domain.exceptions import BudgetExhaustedError
from watchhunter.domain.models import Listing
from watchhunter.infrastructure.http.client import HttpClient
from watchhunter.infrastructure.llm.prompts import (
    TRIAGE_DESCRIPTION_CHARS,
    TRIAGE_INSTRUCTION,
)
from watchhunter.infrastructure.ratelimit.limiter import RateLimiter

log = get_logger(__name__)

# The noul statement. One condition only (the docs warn that two conditions
# in one noul weaken the value); the criteria live in `state`.
_STATEMENT = (
    "This eBay/Kleinanzeigen listing matches the collector's 'interesting' "
    "criteria in the state and deserves a deeper photo-based analysis."
)

# Jev's state is the criteria only; the JSON-output line of the LLM prompt is meaningless here.
_STATE = TRIAGE_INSTRUCTION.split("Output STRICT JSON")[0].strip()


class JevTriageAnalyzer(AnalyzerPort):
    def __init__(
        self,
        *,
        api_key: str,
        http: HttpClient,
        evaluator: AnalyzerPort,
        rate_limiter: RateLimiter,
        model: str = "jev-latest",
        base_url: str = "https://api.typesafe.ai/v1/systemone",
        threshold: float = 0.3,
        batch_size: int = 25,
        budget: BudgetGuard | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._http = http
        self._evaluator = evaluator  # evaluation + fallback triage
        self._rate = rate_limiter
        self._model = model
        self._url = base_url
        self._threshold = threshold
        self._batch_size = max(1, batch_size)
        self._budget = budget
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)

    async def evaluate(self, listing: Listing) -> WatchEvaluation:
        return await self._evaluator.evaluate(listing)

    async def triage(self, listing: Listing) -> TriageResult:
        return (await self.triage_many([listing]))[0]

    async def triage_many(self, listings: list[Listing]) -> list[TriageResult]:
        chunks = [
            listings[i : i + self._batch_size]
            for i in range(0, len(listings), self._batch_size)
        ]
        results = await asyncio.gather(*(self._triage_chunk(c) for c in chunks))
        return [r for chunk in results for r in chunk]

    async def _triage_chunk(self, chunk: list[Listing]) -> list[TriageResult]:
        questions = {
            f"l{i}": {
                "type": "noul",
                "instructions": {
                    "statement": _STATEMENT,
                    "listing": {
                        "title": lst.title,
                        "description": (lst.description or "")[:TRIAGE_DESCRIPTION_CHARS],
                    },
                },
            }
            for i, lst in enumerate(chunk)
        }
        try:
            if self._budget is not None:
                est_in = (len(_STATE) + sum(len(lst.title) + 200 for lst in chunk)) // 4
                await self._budget.check(
                    model=self._model, est_input_tokens=est_in, est_output_tokens=0
                )
            async with self._rate:
                body = await self._post(
                    {"state": _STATE, "model": self._model, "questions": questions}
                )
        except BudgetExhaustedError:
            return [TriageResult(False, "budget_exhausted") for _ in chunk]
        except Exception as exc:
            log.warning("jev.triage_failed", size=len(chunk), error=str(exc)[:200])
            return await self._evaluator.triage_many(chunk)

        usage = body.get("usage") or {}
        if self._budget is not None and usage:
            await self._budget.record(
                model=str(body.get("model") or self._model),
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
            )

        answers: dict[str, Any] = body.get("answers") or {}
        out: list[TriageResult] = []
        missing: list[int] = []
        for i in range(len(chunk)):
            value = (answers.get(f"l{i}") or {}).get("noul")
            if not isinstance(value, int | float):
                missing.append(i)
                out.append(TriageResult(True, "jev_missing"))
                continue
            out.append(
                TriageResult(
                    interesting=float(value) >= self._threshold,
                    reason=f"jev p={float(value):.2f}",
                )
            )
        if missing:
            log.info("jev.missing_answers", missing=len(missing), size=len(chunk))
            redo = await self._evaluator.triage_many([chunk[i] for i in missing])
            for i, res in zip(missing, redo, strict=True):
                out[i] = res
        return out

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        delay = 1.5
        for attempt in range(3):
            async with self._http.session.post(
                self._url, json=payload, headers=headers, timeout=self._timeout
            ) as resp:
                if resp.status == 200:
                    return await resp.json()  # type: ignore[no-any-return]
                text = (await resp.text())[:300]
                if resp.status in (408, 409, 429) or resp.status >= 500:
                    if attempt < 2:
                        await asyncio.sleep(delay * (attempt + 1))
                        continue
                raise RuntimeError(f"Jev HTTP {resp.status}: {text}")
        raise RuntimeError("Jev retries exhausted")
