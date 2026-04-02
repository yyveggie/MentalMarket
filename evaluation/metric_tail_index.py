#!/usr/bin/env python3
"""Tail-index metric calculations (Hill 1975)."""

from __future__ import annotations

import math


def hill_tail_index(samples: list[float], k: int | None = None) -> tuple[float | None, int]:
    """Hill estimator alpha for positive-tail samples."""
    xs = sorted((x for x in samples if x > 0), reverse=True)
    n = len(xs)
    if n < 10:
        return None, 0

    if k is None:
        k = max(5, int(math.sqrt(n)))
    k = max(5, min(k, n - 1))

    x_k1 = xs[k]
    if x_k1 <= 0:
        return None, k

    s = 0.0
    used = 0
    for i in range(k):
        if xs[i] <= 0:
            continue
        ratio = xs[i] / x_k1
        if ratio <= 1.0:
            continue
        s += math.log(ratio)
        used += 1

    if used == 0 or s <= 1e-15:
        return None, k

    alpha = used / s
    return alpha, k


def rolling_hill(
    days: list[int],
    returns: list[float],
    window: int,
) -> tuple[list[int], list[float], list[float], list[int], list[int]]:
    out_days: list[int] = []
    alpha_pos_curve: list[float] = []
    alpha_neg_curve: list[float] = []
    k_pos_curve: list[int] = []
    k_neg_curve: list[int] = []

    for i in range(window - 1, len(returns)):
        seg = returns[i - window + 1 : i + 1]
        pos_tail = [x for x in seg if x > 0]
        neg_tail = [-x for x in seg if x < 0]

        alpha_pos, k_pos = hill_tail_index(pos_tail)
        alpha_neg, k_neg = hill_tail_index(neg_tail)

        out_days.append(days[i])
        alpha_pos_curve.append(alpha_pos if alpha_pos is not None else float('nan'))
        alpha_neg_curve.append(alpha_neg if alpha_neg is not None else float('nan'))
        k_pos_curve.append(k_pos)
        k_neg_curve.append(k_neg)

    return out_days, alpha_pos_curve, alpha_neg_curve, k_pos_curve, k_neg_curve
