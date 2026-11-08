"""Your taste as a small model, retrained from your Telegram reactions.

Target: "the right watch" = 👍, 💸 (right watch, wrong price) or 💰.
Price is handled separately by MAX_TOTAL_EUR, so 💸 counts as a yes here.

Features: the evaluator's verdict (score, rarity, recommendation, value vs
price), price, source, and the listing title as word/char n-grams (brand,
model words like "data bank", "lcd", "calculator"). Logistic regression with
balanced classes: small, fast, explainable, trains in a second.

The model is saved to data/preference.joblib; the bot loads the newest one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sqlalchemy import select

from watchhunter.domain.evaluation import RarityLevel, WatchEvaluation
from watchhunter.domain.models import BuyingOption, Listing, Marketplace
from watchhunter.infrastructure.persistence.database import Database
from watchhunter.infrastructure.persistence.models import EvaluationRow, FeedbackRow, ListingRow

POSITIVE = {"like", "bought", "pricey"}
MIN_LABELS = 40
MIN_POSITIVES = 8


@dataclass(frozen=True)
class Sample:
    text: str
    numeric: list[float]
    label: int


def featurize(listing: Listing, ev: WatchEvaluation) -> tuple[str, list[float]]:
    price = float(listing.current_price_eur)
    value = float(ev.estimated_market_value_eur or 0)
    numeric = [
        ev.score / 100,
        ev.rarity.rank / 3,
        {"skip": 0.0, "watch": 0.5, "buy": 1.0}.get(ev.recommendation.value, 0.0),
        math.log1p(price) / 7,
        min(price / value, 4.0) / 4 if value > 0 else 1.0,
        1.0 if listing.marketplace == Marketplace.KLEINANZEIGEN else 0.0,
        1.0 if listing.buying_option == BuyingOption.AUCTION else 0.0,
    ]
    text = f"{ev.brand} {ev.model} {listing.title}".lower()
    return text, numeric


@dataclass
class PreferenceModel:
    words: TfidfVectorizer
    chars: TfidfVectorizer
    clf: LogisticRegression
    n: int
    positives: int
    auc: float | None

    def _x(self, texts: list[str], numeric: list[list[float]]) -> Any:
        return hstack(
            [self.words.transform(texts), self.chars.transform(texts), csr_matrix(np.array(numeric))]
        ).tocsr()

    def predict(self, listing: Listing, ev: WatchEvaluation) -> float:
        text, num = featurize(listing, ev)
        return float(self.clf.predict_proba(self._x([text], [num]))[0, 1])

    def top_terms(self, k: int = 8) -> tuple[list[str], list[str]]:
        names = list(self.words.get_feature_names_out())
        coefs = self.clf.coef_[0][: len(names)]
        order = np.argsort(coefs)
        return [names[i] for i in order[::-1][:k]], [names[i] for i in order[:k]]


def _fit(samples: list[Sample]) -> PreferenceModel:
    texts = [s.text for s in samples]
    y = np.array([s.label for s in samples])
    words = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    chars = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4), min_df=3, max_features=3000)
    words.fit(texts)
    chars.fit(texts)
    m = PreferenceModel(words, chars, LogisticRegression(C=0.7, class_weight="balanced", max_iter=2000),
                        len(samples), int(y.sum()), None)
    m.clf.fit(m._x(texts, [s.numeric for s in samples]), y)
    return m


async def load_samples(db: Database) -> list[Sample]:
    async with db.session() as s:
        rows = (await s.execute(
            select(ListingRow, EvaluationRow, FeedbackRow)
            .join(EvaluationRow, EvaluationRow.listing_id == ListingRow.id)
            .join(FeedbackRow, FeedbackRow.evaluation_id == EvaluationRow.id)
            .order_by(FeedbackRow.id)
        )).all()
    from watchhunter.infrastructure.persistence.repository import _row_to_eval, _row_to_listing

    latest: dict[int, tuple[Any, Any, str]] = {}
    for lr, er, fr in rows:  # the last reaction per evaluation wins
        latest[er.id] = (lr, er, fr.action)
    out = []
    for lr, er, action in latest.values():
        lst, ev = _row_to_listing(lr), _row_to_eval(er)
        text, num = featurize(lst, ev)
        out.append(Sample(text, num, int(action in POSITIVE)))
    return out


def train(samples: list[Sample]) -> PreferenceModel | None:
    y = [s.label for s in samples]
    if len(samples) < MIN_LABELS or sum(y) < MIN_POSITIVES:
        return None
    # Honest quality number: cross-validated AUC on held-out folds.
    folds = min(5, sum(y), len(y) - sum(y))
    preds = np.zeros(len(samples))
    for tr, te in StratifiedKFold(folds, shuffle=True, random_state=0).split(np.zeros(len(y)), y):
        m = _fit([samples[i] for i in tr])
        for i in te:
            preds[i] = m.clf.predict_proba(m._x([samples[i].text], [samples[i].numeric]))[0, 1]
    model = _fit(samples)
    model.auc = float(roc_auc_score(y, preds))
    model.cv_preds = preds  # type: ignore[attr-defined]
    return model


def save(model: PreferenceModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)


def load(path: Path) -> PreferenceModel | None:
    try:
        return joblib.load(path) if path.exists() else None
    except Exception:
        return None


def rarity_rank(value: str) -> int:
    return RarityLevel(value).rank
