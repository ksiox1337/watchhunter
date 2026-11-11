"""Send up to N listings the live rules would send: triage -> verdict -> deal gate + taste.

Usage:  .venv/bin/python scripts/good_session.py [N]

Same pool as label_session (env LABEL_* options apply), but instead of a random
spread it keeps only what passes Jev triage, the photo verdict, MIN_SCORE /
recommendation and the taste threshold (no exploration picks). Cards carry the
usual feedback buttons, so your taps measure the precision of the live bot.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from label_session import gather_kleinanzeigen, gather_pool

from watchhunter.application.ports.notifier import NotificationPayload
from watchhunter.application.services.deal_evaluator import DealEvaluator
from watchhunter.config.settings import Settings
from watchhunter.container import build_container
from watchhunter.learning import preference as pref


async def main(n: int) -> None:
    s = Settings()
    c = await build_container(s)
    try:
        pool = await gather_pool(c, s) + await gather_kleinanzeigen(c, s, pages=4)
        pool = [x for x in pool if not await c.repository.was_ever_notified(x.external_id)]
        verdicts = await c.analyzer.triage_many(pool)
        todo = [x for x, v in zip(pool, verdicts, strict=True) if v.interesting]
        print(f"pool {len(pool)} -> triage passed {len(todo)}")
        analyzer = getattr(c.analyzer, "_evaluator", c.analyzer)
        analyzer._card_min = 101  # verdict only
        taste = pref.load(Path("data/preference.joblib"))
        gate = DealEvaluator(min_score=s.min_score, min_profit_eur=None, taste_threshold=s.taste_threshold)
        sem = asyncio.Semaphore(6)

        async def run(lst):
            async with sem:
                try:
                    ev = await analyzer.evaluate(lst)
                except Exception as exc:
                    print("eval failed", lst.external_id, str(exc)[:80])
                    return None
                if taste is not None:
                    ev = ev.model_copy(update={"taste": taste.predict(lst, ev), "explore": False})
                return (lst, ev) if gate.is_promising(ev) else None

        good = [r for r in await asyncio.gather(*(run(x) for x in todo)) if r]
        good.sort(key=lambda r: -(r[1].taste or 0))
        good = good[:n]
        print(f"good {len(good)}")
        await c.notifier._client.send_message(  # type: ignore[attr-defined]
            text=f"<b>Лучшее по мнению бота: {len(good)} лотов</b>\n👍 · 💸 · 👎 · 💰 — как обычно"
        )
        for lst, ev in good:
            ev = ev.model_copy(update={"raw_response": {**ev.raw_response, "labeling": True}})
            lid = await c.repository.upsert_listing(lst)
            eid = await c.repository.save_evaluation(lid, ev)
            try:
                await c.notifier.send(NotificationPayload(listing=lst, evaluation=ev, evaluation_id=eid))
                await c.repository.mark_notified(eid)
            except Exception as exc:
                print("send failed", lst.external_id, str(exc)[:80])
            await asyncio.sleep(1.2)
        print(f"done: {len(good)} sent")
    finally:
        await c.aclose()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 200))
