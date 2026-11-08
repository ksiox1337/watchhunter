"""Runtime side of the taste model: score each evaluation, retrain on a timer."""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np

from watchhunter.config.logging import get_logger
from watchhunter.domain.evaluation import WatchEvaluation
from watchhunter.domain.models import Listing
from watchhunter.infrastructure.persistence.database import Database
from watchhunter.learning import preference as pref

log = get_logger(__name__)


class TasteService:
    def __init__(
        self,
        *,
        database: Database,
        path: Path,
        threshold: float,
        explore_rate: float,
        report: object = None,  # async (text) -> None, e.g. Telegram send
    ) -> None:
        self._db = database
        self._path = path
        self.threshold = threshold
        self._explore = explore_rate
        self._report = report
        self._model = pref.load(path)
        self._rng = random.Random()

    def score(self, listing: Listing, ev: WatchEvaluation) -> WatchEvaluation:
        if self._model is None:
            return ev
        p = self._model.predict(listing, ev)
        explore = p < self.threshold and self._rng.random() < self._explore
        raw = {**ev.raw_response, "taste": {"p": round(p, 3), "explore": explore}}
        return ev.model_copy(update={"taste": p, "explore": explore, "raw_response": raw})

    async def retrain(self) -> None:
        samples = await pref.load_samples(self._db)
        model = pref.train(samples)
        if model is None:
            log.info("taste.not_enough_labels", n=len(samples))
            return
        old_auc = self._model.auc if self._model else None
        pref.save(model, self._path)
        self._model = model
        y = np.array([s.label for s in samples])
        sel = model.cv_preds >= self.threshold  # type: ignore[attr-defined]
        prec = float(y[sel].mean()) if sel.sum() else 0.0
        likes, dislikes = model.top_terms(6)
        log.info("taste.retrained", n=model.n, positives=model.positives, auc=round(model.auc or 0, 3))
        if self._report:
            change = f" (было {old_auc:.2f})" if old_auc else ""
            await self._report(  # type: ignore[operator]
                "<b>🎓 Модель вкуса дообучилась</b>\n"
                f"Оценок: {model.n}, из них «те самые»: {model.positives}\n"
                f"Качество (AUC): {model.auc:.2f}{change}\n"
                f"При пороге {round(self.threshold * 100)}%: из присланного понравилось бы {prec:.0%}, "
                f"находится {int(y[sel].sum())} из {int(y.sum())}\n"
                f"Тянет к: {', '.join(likes)}\nОтталкивает: {', '.join(dislikes)}"
            )
