"""Learned confidence calibration for extracted fields (the trained component).

The abstain-or-submit decision is only as good as the confidence score behind it.
The heuristic score (OCR word confidence x validator penalty) is uncalibrated. This
module trains a small logistic model to predict "this field value is correct" from
signals available at inference time, then compares it with the heuristic on held-out
documents:

  * AUROC: does the score rank correct fields above wrong ones?
  * risk-coverage: at the coverage the heuristic achieves, how many wrong values slip
    through with each score? (wrong-but-answered is the error that reaches a payor)

Human corrections from the Document Lab become new training rows, so the model
improves from the same QA loop that reviewers already run.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass

import numpy as np

FIELDS = ["auth_number", "decision", "patient_name", "patient_dob", "member_id", "cpt_codes",
          "approved_units", "start_date", "end_date", "provider_npi", "icd10_codes",
          "requested_units", "plan_start", "plan_end", "signature_present", "signature_date"]
TEMPLATES = ["a", "b", "c", "tp"]


def features(row: dict, doc_meta: dict) -> list[float]:
    """Signals available at inference time only (no ground truth, no image condition label)."""
    pred = row["pred"]
    filled = pred not in (None, "", [])
    f = [
        float(row["conf"]),
        float(doc_meta.get("ocr_mean_conf", 0.0)) / 100.0,
        1.0 if filled else 0.0,
        float(len(pred)) if isinstance(pred, list) else 0.0,
        float(len(str(pred))) / 20.0 if filled else 0.0,
    ]
    f += [1.0 if row["field"] == k else 0.0 for k in FIELDS]
    f += [1.0 if doc_meta.get("template") == t else 0.0 for t in TEMPLATES]
    return f


@dataclass
class CalibrationReport:
    n_train: int
    n_test: int
    auroc_heuristic: float
    auroc_learned: float
    coverage: float
    silent_error_heuristic: float
    silent_error_learned: float
    precision_heuristic: float
    precision_learned: float

    def as_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def _auroc(scores: np.ndarray, labels: np.ndarray) -> float:
    pos, neg = scores[labels == 1], scores[labels == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    order = np.argsort(np.concatenate([pos, neg]))
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(order) + 1)
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def _at_coverage(scores, labels, coverage):
    k = max(1, int(round(coverage * len(scores))))
    top = np.argsort(-scores)[:k]
    wrong = int((labels[top] == 0).sum())
    return wrong / len(scores), 1 - wrong / k


def train_and_evaluate(rows: list[dict], doc_meta: dict[str, dict], seed: int = 0):
    """rows: evaluate.score(...)['rows'] (fields with a ground-truth value only)."""
    from sklearn.linear_model import LogisticRegression

    rows = [r for r in rows if r["truth"] is not None]
    cases = sorted({r["doc_id"].split("_")[0] for r in rows})
    random.Random(seed).shuffle(cases)
    test_cases = set(cases[: int(len(cases) * 0.4)])
    tr = [r for r in rows if r["doc_id"].split("_")[0] not in test_cases]
    te = [r for r in rows if r["doc_id"].split("_")[0] in test_cases]
    Xtr = np.array([features(r, doc_meta[r["doc_id"]]) for r in tr])
    ytr = np.array([int(r["ok"]) for r in tr])
    Xte = np.array([features(r, doc_meta[r["doc_id"]]) for r in te])
    yte = np.array([int(r["ok"]) for r in te])
    model = LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced").fit(Xtr, ytr)
    learned = model.predict_proba(Xte)[:, 1]
    heuristic = np.array([r["conf"] for r in te])
    answered = np.array([not r["abstained"] for r in te])
    coverage = float(answered.mean())
    se_h, p_h = _at_coverage(heuristic, yte, coverage)
    se_l, p_l = _at_coverage(learned, yte, coverage)
    rep = CalibrationReport(len(tr), len(te), _auroc(heuristic, yte), _auroc(learned, yte), coverage,
                            se_h, se_l, p_h, p_l)
    return model, rep, {"heuristic": heuristic.tolist(), "learned": learned.tolist(), "labels": yte.tolist()}


def risk_coverage_curve(scores, labels, points: int = 21) -> list[dict]:
    scores, labels = np.asarray(scores, float), np.asarray(labels, int)
    out = []
    for c in np.linspace(0.05, 1.0, points):
        se, p = _at_coverage(scores, labels, float(c))
        out.append({"coverage": round(float(c), 3), "silent_error": round(se, 4), "precision": round(p, 4)})
    return out


def save_model(model, path) -> None:
    json.dump({"coef": model.coef_.tolist(), "intercept": model.intercept_.tolist(),
               "fields": FIELDS, "templates": TEMPLATES}, open(path, "w"))


def load_scorer(path):
    m = json.load(open(path))
    w, b = np.array(m["coef"][0]), m["intercept"][0]
    return lambda row, meta: float(1 / (1 + np.exp(-(np.dot(w, features(row, meta)) + b))))
