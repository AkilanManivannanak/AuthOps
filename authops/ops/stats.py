"""Small-sample statistics for rollout decisions.

Pilot numbers are small (8 runs on a portal, 24 denials in a backtest), so every
comparison the ops report makes carries an interval or a p-value. All exact or
resampling methods, no normal approximations that break at n=8.
"""
from __future__ import annotations

import math
import random
from typing import Sequence


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k/n (well-behaved at 0/n and n/n)."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for the 2x2 table [[a, b], [c, d]]."""
    r1, r2, c1, n = a + b, c + d, a + c, a + b + c + d

    def pr(x):
        return math.comb(r1, x) * math.comb(r2, c1 - x) / math.comb(n, c1)

    p0 = pr(a)
    lo, hi = max(0, c1 - r2), min(r1, c1)
    return min(1.0, sum(pr(x) for x in range(lo, hi + 1) if pr(x) <= p0 * (1 + 1e-9)))


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Paired comparison: items right under A only vs right under B only (exact binomial)."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def bootstrap_diff(a: Sequence[float], b: Sequence[float], iters: int = 4000,
                   seed: int = 0, groups: Sequence[str] | None = None) -> tuple[float, float, float]:
    """Paired bootstrap CI for mean(a) - mean(b). With `groups`, resamples whole groups
    (e.g. documents), because fields on one page are not independent."""
    rng = random.Random(seed)
    idx = list(range(len(a)))
    if groups is None:
        units = [[i] for i in idx]
    else:
        by: dict[str, list[int]] = {}
        for i, g in zip(idx, groups):
            by.setdefault(g, []).append(i)
        units = list(by.values())
    diff = sum(a[i] - b[i] for i in idx) / len(idx)
    draws = []
    for _ in range(iters):
        pick = [i for _ in units for i in rng.choice(units)]
        draws.append(sum(a[i] - b[i] for i in pick) / len(pick))
    draws.sort()
    return diff, draws[int(0.025 * iters)], draws[int(0.975 * iters) - 1]


def fmt_ci(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({100 * k / n:.0f}%, 95% CI {100 * lo:.0f}-{100 * hi:.0f}%)" if n else "0/0"
