#!/usr/bin/env python3
"""Efficient Market Hypothesis (EMH) metric calculations.

弱式 EMH 检测:
- 收益率自相关 (Return ACF lag 1-5)
- Lo-MacKinlay 方差比 (Variance Ratio, k=2/5/10)
- Hurst 指数 (R/S 分析)
- 游程检验 (Runs Test)

References:
- Lo & MacKinlay (1988): variance ratio test
- Hurst (1951): R/S analysis for long memory
- Wald & Wolfowitz (1940): runs test
"""

from __future__ import annotations

import math


# ──────── Return Autocorrelation ────────

def _acf(series: list[float], lag: int) -> float:
    """Biased sample autocorrelation at given lag."""
    n = len(series)
    if n <= lag or n < 3:
        return 0.0
    mean = sum(series) / n
    var = sum((x - mean) ** 2 for x in series)
    if var <= 1e-15:
        return 0.0
    cov = sum((series[i] - mean) * (series[i + lag] - mean) for i in range(n - lag))
    return cov / var


def rolling_return_acf(
    days: list[int],
    returns: list[float],
    window: int,
    lags: list[int] | None = None,
) -> tuple[list[int], dict[int, list[float]]]:
    """Rolling autocorrelation of raw returns at multiple lags.

    Returns:
        (out_days, {lag: [acf_values]})
    """
    if lags is None:
        lags = [1, 2, 3, 4, 5]
    out_days: list[int] = []
    acf_by_lag: dict[int, list[float]] = {k: [] for k in lags}

    for i in range(window - 1, len(returns)):
        seg = returns[i - window + 1 : i + 1]
        out_days.append(days[i])
        for lag in lags:
            acf_by_lag[lag].append(_acf(seg, lag))

    return out_days, acf_by_lag


# ──────── Variance Ratio (Lo-MacKinlay 1988) ────────

def _variance_ratio(returns: list[float], k: int) -> float | None:
    """Compute VR(k) = Var(r_k) / (k * Var(r_1)).

    Under random walk, VR(k) = 1.
    VR > 1 → positive autocorrelation (momentum/trending).
    VR < 1 → negative autocorrelation (mean reversion).
    """
    n = len(returns)
    if n < k + 1:
        return None

    # 1-period variance
    mean1 = sum(returns) / n
    var1 = sum((r - mean1) ** 2 for r in returns) / (n - 1)
    if var1 <= 1e-15:
        return None

    # k-period returns
    k_returns: list[float] = []
    for i in range(k, n + 1):
        k_returns.append(sum(returns[i - k : i]))

    if len(k_returns) < 2:
        return None
    mean_k = sum(k_returns) / len(k_returns)
    var_k = sum((r - mean_k) ** 2 for r in k_returns) / (len(k_returns) - 1)

    vr = var_k / (k * var1)
    return vr


def rolling_variance_ratio(
    days: list[int],
    returns: list[float],
    window: int,
    k_list: list[int] | None = None,
) -> tuple[list[int], dict[int, list[float]]]:
    """Rolling variance ratio at multiple horizons.

    Returns:
        (out_days, {k: [vr_values]})
    """
    if k_list is None:
        k_list = [2, 5, 10]
    out_days: list[int] = []
    vr_by_k: dict[int, list[float]] = {k: [] for k in k_list}

    for i in range(window - 1, len(returns)):
        seg = returns[i - window + 1 : i + 1]
        out_days.append(days[i])
        for k in k_list:
            vr = _variance_ratio(seg, k)
            vr_by_k[k].append(vr if vr is not None else float("nan"))

    return out_days, vr_by_k


# ──────── Hurst Exponent (R/S Analysis) ────────

def _hurst_rs(series: list[float]) -> float | None:
    """Estimate Hurst exponent via rescaled range (R/S) analysis.

    H = 0.5 → random walk (EMH consistent)
    H > 0.5 → persistent / trending
    H < 0.5 → anti-persistent / mean reverting
    """
    n = len(series)
    if n < 20:
        return None

    # Geometric spacing with factor 1.4 for more OLS points
    sizes: list[int] = []
    s = max(8, n // 16)
    seen: set[int] = set()
    while s <= n:
        s_int = int(s)
        if s_int not in seen and s_int >= 8:
            sizes.append(s_int)
            seen.add(s_int)
        s *= 1.4
    # Ensure we include n itself if large enough
    if n not in seen and n >= 8:
        sizes.append(n)
    if len(sizes) < 2:
        return None

    log_ns: list[float] = []
    log_rs: list[float] = []

    for size in sizes:
        rs_vals: list[float] = []
        n_blocks = n // size
        if n_blocks < 1:
            continue
        for b in range(n_blocks):
            block = series[b * size : (b + 1) * size]
            mean_b = sum(block) / size
            deviations = [x - mean_b for x in block]

            # Cumulative deviation
            cumdev: list[float] = []
            acc = 0.0
            for d in deviations:
                acc += d
                cumdev.append(acc)

            R = max(cumdev) - min(cumdev)
            S = math.sqrt(sum(d ** 2 for d in deviations) / size)
            if S > 1e-15:
                rs_vals.append(R / S)

        if rs_vals:
            avg_rs = sum(rs_vals) / len(rs_vals)
            if avg_rs > 0:
                log_ns.append(math.log(size))
                log_rs.append(math.log(avg_rs))

    if len(log_ns) < 2:
        return None

    # OLS: log(R/S) = H * log(n) + c
    n_pts = len(log_ns)
    sx = sum(log_ns)
    sy = sum(log_rs)
    sxx = sum(x * x for x in log_ns)
    sxy = sum(x * y for x, y in zip(log_ns, log_rs))
    denom = n_pts * sxx - sx * sx
    if abs(denom) < 1e-15:
        return None
    H = (n_pts * sxy - sx * sy) / denom
    return max(0.0, min(1.0, H))


def rolling_hurst(
    days: list[int],
    returns: list[float],
    window: int,
) -> tuple[list[int], list[float]]:
    """Rolling Hurst exponent.

    Returns:
        (out_days, hurst_values)
    """
    out_days: list[int] = []
    hurst_vals: list[float] = []

    for i in range(window - 1, len(returns)):
        seg = returns[i - window + 1 : i + 1]
        h = _hurst_rs(seg)
        out_days.append(days[i])
        hurst_vals.append(h if h is not None else float("nan"))

    return out_days, hurst_vals


# ──────── Runs Test ────────

def _runs_test(series: list[float]) -> tuple[int, float] | None:
    """Non-parametric runs test for randomness.

    Returns:
        (n_runs, z_statistic)

    |Z| < 1.96 → cannot reject randomness at 95% confidence.
    Z >> 0 → too many runs (mean reversion).
    Z << 0 → too few runs (trending/momentum).
    """
    n = len(series)
    if n < 10:
        return None

    signs = [1 if x >= 0 else -1 for x in series]
    n_pos = sum(1 for s in signs if s == 1)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return None

    # Count runs
    runs = 1
    for i in range(1, n):
        if signs[i] != signs[i - 1]:
            runs += 1

    # Expected runs and variance under H0
    expected = 1.0 + (2.0 * n_pos * n_neg) / n
    var_r = (2.0 * n_pos * n_neg * (2.0 * n_pos * n_neg - n)) / (n * n * (n - 1.0))
    if var_r <= 0:
        return runs, 0.0
    z = (runs - expected) / math.sqrt(var_r)
    return runs, z


def rolling_runs_test(
    days: list[int],
    returns: list[float],
    window: int,
) -> tuple[list[int], list[int], list[float]]:
    """Rolling runs test.

    Returns:
        (out_days, runs_counts, z_statistics)
    """
    out_days: list[int] = []
    runs_list: list[int] = []
    z_list: list[float] = []

    for i in range(window - 1, len(returns)):
        seg = returns[i - window + 1 : i + 1]
        result = _runs_test(seg)
        out_days.append(days[i])
        if result is not None:
            runs_list.append(result[0])
            z_list.append(result[1])
        else:
            runs_list.append(0)
            z_list.append(float("nan"))

    return out_days, runs_list, z_list


# ──────── Semi-strong: Cumulative Abnormal Return ────────

# ── Ex-ante news sentiment classifier (transformer model) ──

_SENT_CACHE: dict[str, float] = {}  # title → score cache (in-process)
_SENT_CLASSIFIER = None  # lazy-loaded pipeline


def _get_sentiment_classifier():
    """Lazy-load the sentiment classification pipeline (singleton)."""
    global _SENT_CLASSIFIER
    if _SENT_CLASSIFIER is None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline as hf_pipeline
        model_name = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
        try:
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModelForSequenceClassification.from_pretrained(model_name)
        except (OSError, Exception):
            tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
            model = AutoModelForSequenceClassification.from_pretrained(model_name, local_files_only=True)
        import torch
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = 0
        else:
            device = -1
        _SENT_CLASSIFIER = hf_pipeline(
            "text-classification", model=model, tokenizer=tokenizer,
            device=device, top_k=None, truncation=True, max_length=512,
        )
    return _SENT_CLASSIFIER


def _score_from_probs(probs: list[dict]) -> float:
    """Convert model output probabilities to sentiment score in [-1, 1].

    Score = p(positive) - p(negative).
    """
    p_map = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
    for item in probs:
        label = item["label"].lower().strip()
        if "positive" in label or "label_2" in label:
            p_map["positive"] = item["score"]
        elif "negative" in label or "label_0" in label:
            p_map["negative"] = item["score"]
        else:
            p_map["neutral"] = item["score"]
    return p_map["positive"] - p_map["negative"]


def classify_news_sentiment_batch(titles: list[str]) -> list[float]:
    """Classify a batch of news headlines, return sentiment scores in [-1, 1]."""
    classifier = _get_sentiment_classifier()
    uncached = [(i, t) for i, t in enumerate(titles) if t not in _SENT_CACHE]
    if uncached:
        texts = [t for _, t in uncached]
        results = classifier(texts, batch_size=64)
        for (i, t), probs in zip(uncached, results):
            _SENT_CACHE[t] = _score_from_probs(probs)
    return [_SENT_CACHE[t] for t in titles]


def classify_event_day_sentiment(
    news_list: list[dict],
) -> dict[int, str]:
    """Classify each event day's net sentiment.

    优先使用预标注的 sentiment 字段（由 batch_classify_news_sentiment.py 生成），
    无预标注时 fallback 到 Transformer 模型。

    Accepts news_list items with either 'title' or 'content' field,
    and 'day' or 'trading_day' for the day number.

    Returns {day: 'positive'/'negative'/'neutral'}.
    """
    from collections import defaultdict

    has_pre_labeled = sum(1 for item in news_list if "sentiment" in item)
    use_pre_labeled = has_pre_labeled > len(news_list) * 0.5

    if use_pre_labeled:
        _LABEL_SCORE = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
        day_scores: dict[int, list[float]] = defaultdict(list)
        for item in news_list:
            d = item.get("day") or item.get("trading_day")
            if not isinstance(d, (int, float)):
                continue
            label = str(item.get("sentiment", "neutral")).strip().lower()
            day_scores[int(d)].append(_LABEL_SCORE.get(label, 0.0))

        result: dict[int, str] = {}
        for day, scores in day_scores.items():
            avg = sum(scores) / len(scores) if scores else 0.0
            if avg > 0:
                result[day] = "positive"
            elif avg < 0:
                result[day] = "negative"
            else:
                result[day] = "neutral"
        return result

    day_titles: dict[int, list[str]] = defaultdict(list)
    for item in news_list:
        d = item.get("day") or item.get("trading_day")
        if not isinstance(d, (int, float)):
            continue
        title = (item.get("title") or item.get("content") or "").strip()
        if title:
            day_titles[int(d)].append(title)

    all_titles = list({t for titles in day_titles.values() for t in titles})
    if all_titles:
        classify_news_sentiment_batch(all_titles)

    result = {}
    for day, titles in day_titles.items():
        scores = [_SENT_CACHE.get(t, 0.0) for t in titles]
        avg = sum(scores) / len(scores) if scores else 0.0
        if avg > 0:
            result[day] = "positive"
        elif avg < 0:
            result[day] = "negative"
        else:
            result[day] = "neutral"
    return result


def compute_event_car(
    event_days: list[int],
    all_days: list[int],
    returns: list[float],
    horizons: list[int] | None = None,
    estimation_window: int = 20,
    model: str = "market_adjusted",
) -> list[dict]:
    """Compute Cumulative Abnormal Returns (CAR) around news events.

    Args:
        model: Normal return model.
            - "mean_adjusted": per-event estimation window mean (MacKinlay 1997 default)
            - "market_adjusted": global average return across the full sample

    For each event day:
    1. Estimate expected return using the chosen model.
    2. For each horizon h, compute CAR(0, h) = sum of abnormal returns from t to t+h.

    Returns:
        list of {event_day, car_1, car_3, car_5}
    """
    if horizons is None:
        horizons = [1, 3, 5]

    # Build day → index map
    day_to_idx: dict[int, int] = {}
    for idx, d in enumerate(all_days):
        day_to_idx[d] = idx

    # Global average return for market-adjusted model
    global_mean_r = sum(returns) / len(returns) if returns else 0.0

    results: list[dict] = []
    for ev_day in event_days:
        ev_idx = day_to_idx.get(ev_day)
        if ev_idx is None:
            continue

        if model == "market_adjusted":
            expected_r = global_mean_r
        else:
            # Mean-adjusted: estimation window mean
            est_start = ev_idx - estimation_window
            if est_start < 0:
                est_start = 0
            est_end = ev_idx
            if est_end - est_start < 10:
                continue  # Too few samples for reliable expected return
            est_returns = returns[est_start:est_end]
            expected_r = sum(est_returns) / len(est_returns) if est_returns else 0.0

        row: dict = {"event_day": ev_day}
        for h in horizons:
            # CAR(0, +h) = sum of AR from t=0 to t=+h, inclusive → h+1 days
            end_idx = min(ev_idx + h + 1, len(returns))
            if ev_idx >= len(returns):
                row[f"car_{h}"] = float("nan")
                continue
            ar_sum = sum(returns[t] - expected_r for t in range(ev_idx, end_idx))
            row[f"car_{h}"] = ar_sum
        results.append(row)

    return results


def aggregate_car_by_day(
    car_records: list[dict],
    horizons: list[int] | None = None,
) -> list[dict]:
    """Aggregate CAR metrics per event day (average across events on same day).

    Returns list of {trading_day, avg_car_1, avg_car_3, avg_car_5, event_count}.
    """
    if horizons is None:
        horizons = [1, 3, 5]

    by_day: dict[int, list[dict]] = {}
    for rec in car_records:
        d = rec["event_day"]
        by_day.setdefault(d, []).append(rec)

    results: list[dict] = []
    for day in sorted(by_day):
        recs = by_day[day]
        row: dict = {"trading_day": day, "event_count": len(recs)}
        for h in horizons:
            car_vals = [r[f"car_{h}"] for r in recs if not math.isnan(r.get(f"car_{h}", float("nan")))]
            n = len(car_vals)
            mean = (sum(car_vals) / n) if n else float("nan")
            row[f"avg_car_{h}"] = mean
            if n > 1:
                variance = sum((v - mean) ** 2 for v in car_vals) / (n - 1)
                row[f"avg_car_{h}_se"] = math.sqrt(variance / n)
            else:
                row[f"avg_car_{h}_se"] = float("nan")
        results.append(row)
    return results


def compute_caar(
    car_records: list[dict],
    horizons: list[int] | None = None,
) -> dict[str, float]:
    """Compute CAAR (Cumulative Average Abnormal Return) across all events.

    CAAR(h) = mean of CAR(0,h) over all events, giving a single summary
    number per horizon that reflects the *typical* market response pattern.

    Returns dict like {"caar_1": 0.003, "caar_3": 0.005, "caar_5": 0.002}.
    """
    if horizons is None:
        horizons = [1, 3, 5]

    result: dict[str, float] = {}
    for h in horizons:
        vals = [
            r[f"car_{h}"]
            for r in car_records
            if not math.isnan(r.get(f"car_{h}", float("nan")))
        ]
        n = len(vals)
        mean = (sum(vals) / n) if n else float("nan")
        result[f"caar_{h}"] = mean
        # 标准误 SE = std / sqrt(n)
        if n > 1:
            variance = sum((v - mean) ** 2 for v in vals) / (n - 1)
            result[f"caar_{h}_se"] = math.sqrt(variance / n)
        else:
            result[f"caar_{h}_se"] = float("nan")
    return result


def _block_bootstrap_means(
    vals: list[float],
    n_bootstrap: int,
    block_size: int,
    rng,
) -> list[float]:
    """Circular block bootstrap for CAAR mean estimation.

    Accounts for cross-sectional dependence between overlapping event windows.
    Draws ceil(n/block_size) contiguous blocks (with wrap-around) to form each
    bootstrap sample of size n.
    """
    n = len(vals)
    if n < 2:
        return []
    bs = min(block_size, n)
    n_blocks = math.ceil(n / bs)
    boot_means: list[float] = []
    for _ in range(n_bootstrap):
        sample: list[float] = []
        for _ in range(n_blocks):
            start = rng.randint(0, n - 1)
            for j in range(bs):
                sample.append(vals[(start + j) % n])
        # Trim to exactly n
        sample = sample[:n]
        boot_means.append(sum(sample) / n)
    return boot_means


def compute_car_significance(
    car_records: list[dict],
    horizons: list[int] | None = None,
    n_bootstrap: int = 1000,
    event_sentiments: dict[int, str] | None = None,
    block_size: int = 5,
) -> dict:
    """Compute statistical significance tests for CAR / CAAR.

    Args:
        event_sentiments: Optional mapping {event_day: 'positive'/'negative'/'neutral'}
            for ex-ante sentiment grouping. If None, sentiment-grouped tests are skipped.
        block_size: Block size for circular block bootstrap (default 5).
            Accounts for cross-sectional dependence due to overlapping event windows.

    Returns a dict with:
    - For each horizon h:
      - caar_{h}: mean CAR
      - se_{h}: standard error
      - t_stat_{h}: t-statistic (H0: CAAR=0)
      - p_value_{h}: two-sided p-value
      - ci_lower_{h}, ci_upper_{h}: 95% confidence interval
      - n_{h}: number of events
    - For consecutive horizon pairs (h1→h2):
      - delta_{h1}_{h2}: mean incremental CAR
      - delta_t_{h1}_{h2}: t-stat for paired difference
      - delta_p_{h1}_{h2}: p-value for paired difference
      - drift_{h1}_{h2}: "none" / "positive_drift" / "negative_drift"
    - Bootstrap CI for CAAR (more robust for non-normal distributions):
      - boot_ci_lower_{h}, boot_ci_upper_{h}: bootstrap 95% CI
    """
    import random

    if horizons is None:
        horizons = [1, 3, 5]

    # Sort records by event_day to preserve temporal order for block bootstrap
    car_records = sorted(car_records, key=lambda r: r.get("event_day", 0))

    result: dict = {}

    # ── Per-horizon tests ──
    car_vals_by_h: dict[int, list[float]] = {}
    for h in horizons:
        vals = [
            r[f"car_{h}"]
            for r in car_records
            if not math.isnan(r.get(f"car_{h}", float("nan")))
        ]
        car_vals_by_h[h] = vals
        n = len(vals)
        result[f"n_{h}"] = n

        if n < 2:
            for key in [f"caar_{h}", f"se_{h}", f"t_stat_{h}", f"p_value_{h}",
                        f"ci_lower_{h}", f"ci_upper_{h}",
                        f"boot_ci_lower_{h}", f"boot_ci_upper_{h}"]:
                result[key] = float("nan")
            continue

        mean = sum(vals) / n
        variance = sum((v - mean) ** 2 for v in vals) / (n - 1)
        se = math.sqrt(variance / n)
        t_stat = mean / se if se > 0 else float("nan")

        # Two-sided p-value using t-distribution approximation
        # Use normal approximation for large n (>30), otherwise scipy-free t approx
        df = n - 1
        p_value = _two_sided_t_pvalue(t_stat, df)

        # 95% CI: mean ± t_crit * SE
        t_crit = _t_critical_95(df)
        ci_lower = mean - t_crit * se
        ci_upper = mean + t_crit * se

        result[f"caar_{h}"] = mean
        result[f"se_{h}"] = se
        result[f"t_stat_{h}"] = t_stat
        result[f"p_value_{h}"] = p_value
        result[f"ci_lower_{h}"] = ci_lower
        result[f"ci_upper_{h}"] = ci_upper

        # Block bootstrap 95% CI + bootstrap p-value
        # Uses circular block bootstrap to account for cross-sectional dependence
        if n_bootstrap > 0 and n >= 5:
            rng = random.Random(42)
            boot_means = _block_bootstrap_means(vals, n_bootstrap, block_size, rng)
            boot_means.sort()
            lo_idx = max(0, int(0.025 * n_bootstrap))
            hi_idx = min(n_bootstrap - 1, int(0.975 * n_bootstrap))
            result[f"boot_ci_lower_{h}"] = boot_means[lo_idx]
            result[f"boot_ci_upper_{h}"] = boot_means[hi_idx]
            # Bootstrap p-value (two-sided): under H0 (centered at 0),
            # proportion of |boot_mean - observed_mean| >= |observed_mean|
            n_extreme = sum(1 for bm in boot_means if abs(bm - mean) >= abs(mean))
            result[f"boot_p_{h}"] = n_extreme / n_bootstrap
        else:
            result[f"boot_ci_lower_{h}"] = float("nan")
            result[f"boot_ci_upper_{h}"] = float("nan")
            result[f"boot_p_{h}"] = float("nan")

    # ── Incremental (drift) tests: paired differences ──
    for i in range(len(horizons) - 1):
        h1, h2 = horizons[i], horizons[i + 1]
        tag = f"{h1}_{h2}"

        # Paired differences: for events that have both horizons
        diffs = []
        for r in car_records:
            v1 = r.get(f"car_{h1}", float("nan"))
            v2 = r.get(f"car_{h2}", float("nan"))
            if not math.isnan(v1) and not math.isnan(v2):
                diffs.append(v2 - v1)

        n_d = len(diffs)
        result[f"delta_n_{tag}"] = n_d

        if n_d < 2:
            for key in [f"delta_{tag}", f"delta_t_{tag}", f"delta_p_{tag}", f"drift_{tag}"]:
                result[key] = float("nan") if key != f"drift_{tag}" else "insufficient_data"
            continue

        d_mean = sum(diffs) / n_d
        d_var = sum((d - d_mean) ** 2 for d in diffs) / (n_d - 1)
        d_se = math.sqrt(d_var / n_d)
        d_t = d_mean / d_se if d_se > 0 else float("nan")
        d_p = _two_sided_t_pvalue(d_t, n_d - 1)

        result[f"delta_{tag}"] = d_mean
        result[f"delta_t_{tag}"] = d_t
        result[f"delta_p_{tag}"] = d_p

        # Drift interpretation (α=0.10)
        if d_p < 0.10:
            result[f"drift_{tag}"] = "positive_drift" if d_mean > 0 else "negative_drift"
        else:
            result[f"drift_{tag}"] = "none"

    # ── Sign Test (non-parametric: proportion of positive CARs) ──
    for h in horizons:
        vals = car_vals_by_h.get(h, [])
        n = len(vals)
        if n < 5:
            result[f"sign_pos_pct_{h}"] = float("nan")
            result[f"sign_p_{h}"] = float("nan")
            continue
        n_pos = sum(1 for v in vals if v > 0)
        pos_pct = n_pos / n
        z_sign = (n_pos - 0.5 * n) / math.sqrt(0.25 * n)
        result[f"sign_pos_pct_{h}"] = pos_pct
        result[f"sign_p_{h}"] = 2 * _normal_cdf_complement(abs(z_sign))

    # ── Corrado Rank Test (non-parametric, Corrado 1989) ──
    for h in horizons:
        vals = car_vals_by_h.get(h, [])
        n = len(vals)
        if n < 5:
            result[f"rank_t_{h}"] = float("nan")
            result[f"rank_p_{h}"] = float("nan")
            continue
        sorted_vals = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        for rank_pos, orig_idx in enumerate(sorted_vals):
            ranks[orig_idx] = (rank_pos + 1) / (n + 1) - 0.5
        avg_rank = sum(ranks) / n
        rank_var = sum((r - avg_rank) ** 2 for r in ranks) / n
        rank_t = avg_rank / math.sqrt(rank_var / n) if rank_var > 0 else 0.0
        result[f"rank_t_{h}"] = rank_t
        result[f"rank_p_{h}"] = 2 * _normal_cdf_complement(abs(rank_t))

    # ── Absorption Ratio: how much of h=5 reaction is captured by h=1 ──
    if 1 in car_vals_by_h and 5 in car_vals_by_h:
        vals_1 = car_vals_by_h[1]
        vals_5 = car_vals_by_h[5]
        if vals_1 and vals_5:
            abs_mean_1 = sum(abs(v) for v in vals_1) / len(vals_1)
            abs_mean_5 = sum(abs(v) for v in vals_5) / len(vals_5)
            result["absorption_ratio"] = (abs_mean_1 / abs_mean_5
                                          if abs_mean_5 > 1e-10 else float("nan"))
        else:
            result["absorption_ratio"] = float("nan")

    # ── Ex-ante sentiment-grouped tests ──
    # Group by news sentiment label (truly ex-ante, no look-ahead bias).
    # Test H0: CAAR = 0 within each sentiment group, for each horizon.
    if event_sentiments:
        pos_recs = [r for r in car_records if event_sentiments.get(r["event_day"]) == "positive"]
        neg_recs = [r for r in car_records if event_sentiments.get(r["event_day"]) == "negative"]
    else:
        pos_recs = []
        neg_recs = []

    for group_tag, recs in [("pos", pos_recs), ("neg", neg_recs)]:
        result[f"n_{group_tag}"] = len(recs)
        for h in horizons:
            vals = [r[f"car_{h}"] for r in recs
                    if not math.isnan(r.get(f"car_{h}", float("nan")))]
            n_g = len(vals)
            if n_g < 2:
                for key in [f"caar_{group_tag}_{h}", f"se_{group_tag}_{h}",
                            f"t_{group_tag}_{h}", f"p_{group_tag}_{h}",
                            f"p1_{group_tag}_{h}", f"boot_p_{group_tag}_{h}"]:
                    result[key] = float("nan")
                continue
            mean_g = sum(vals) / n_g
            var_g = sum((v - mean_g) ** 2 for v in vals) / (n_g - 1)
            se_g = math.sqrt(var_g / n_g)
            t_g = mean_g / se_g if se_g > 0 else float("nan")
            p_g = _two_sided_t_pvalue(t_g, n_g - 1)
            p1_g = p_g / 2 if not math.isnan(p_g) else float("nan")
            # Block bootstrap p-value for group (two-sided)
            if n_bootstrap > 0 and n_g >= 5:
                rng_g = random.Random(42 + hash(group_tag) + h)
                boot_ms = _block_bootstrap_means(vals, n_bootstrap, block_size, rng_g)
                n_ext = sum(1 for bm in boot_ms if abs(bm - mean_g) >= abs(mean_g))
                boot_p_g = n_ext / n_bootstrap
            else:
                boot_p_g = float("nan")
            result[f"caar_{group_tag}_{h}"] = mean_g
            result[f"se_{group_tag}_{h}"] = se_g
            result[f"t_{group_tag}_{h}"] = t_g
            result[f"p_{group_tag}_{h}"] = p_g
            result[f"p1_{group_tag}_{h}"] = p1_g
            result[f"boot_p_{group_tag}_{h}"] = boot_p_g

    return result


def _two_sided_t_pvalue(t_stat: float, df: int) -> float:
    """Approximate two-sided p-value for t-distribution without scipy."""
    if math.isnan(t_stat) or df < 1:
        return float("nan")
    # Use normal approximation for large df
    x = abs(t_stat)
    if df > 100:
        # Normal approximation
        p = 2 * _normal_cdf_complement(x)
    else:
        # Abramowitz & Stegun 26.7.1:
        # p_two_sided = I_x(df/2, 1/2) where x = df/(df+t^2)
        p = _regularized_beta(0.5 * df, 0.5, df / (df + x * x))
    return min(max(p, 0.0), 1.0)


def _normal_cdf_complement(x: float) -> float:
    """P(Z > x) for standard normal, Abramowitz & Stegun approximation."""
    if x < 0:
        return 1.0 - _normal_cdf_complement(-x)
    t = 1.0 / (1.0 + 0.2316419 * x)
    poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    return poly * math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _regularized_beta(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b) via continued fraction."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    # Use symmetry relation for faster convergence
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - _regularized_beta(b, a, 1.0 - x)
    # I_x(a,b) = x^a (1-x)^b / (a * B(a,b)) * CF(a,b,x)
    log_prefix = (a * math.log(x) + b * math.log(1 - x)
                  - math.log(a)
                  - _log_beta(a, b))
    prefix = math.exp(log_prefix)
    return _betainc_cf(a, b, x) * prefix


def _log_beta(a: float, b: float) -> float:
    """Log of Beta function."""
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _betainc_cf(a: float, b: float, x: float) -> float:
    """Continued fraction for regularized incomplete beta."""
    max_iter = 200
    eps = 1e-10
    f = 1.0
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1)
    if abs(d) < eps:
        d = eps
    d = 1.0 / d
    f = d

    for m in range(1, max_iter + 1):
        # Even step
        num = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        d = 1.0 + num * d
        if abs(d) < eps:
            d = eps
        c = 1.0 + num / c
        if abs(c) < eps:
            c = eps
        d = 1.0 / d
        f *= d * c

        # Odd step
        num = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + num * d
        if abs(d) < eps:
            d = eps
        c = 1.0 + num / c
        if abs(c) < eps:
            c = eps
        d = 1.0 / d
        delta = d * c
        f *= delta
        if abs(delta - 1.0) < eps:
            break

    return f


def _t_critical_95(df: int) -> float:
    """Approximate 95% (two-sided) critical value for t-distribution."""
    if df >= 120:
        return 1.96
    # Approximation for smaller df
    # Based on Cornish-Fisher expansion
    z = 1.959964
    g1 = (z ** 3 + z) / (4 * df)
    g2 = (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * df * df)
    return z + g1 + g2
