#!/usr/bin/env python3
"""Backward-compatible shim. Split into data_loader / metric_fit_accuracy / plot_fit_accuracy."""

from data_loader import (  # noqa: F401
    _build_nonseed_close_map,
    aligned_real_sim_with_day,
    build_sim_close_by_day,
    infer_closed_from_row,
    load_closed_dates_from_calendar_news,
    load_include_closed_days_from_run_config,
    load_real_curves,
    load_run_config,
    remap_sim_close_to_trading_days,
    resolve_calendar_news_file,
    resolve_existing_path,
    resolve_include_closed_days,
)
from metric_fit_accuracy import (  # noqa: F401
    BROAD_EQW_SYMBOL,
    DailyCurves,
    build_daily_fit_curve_for_symbol,
    build_daily_metric_curves,
    build_equal_weight_close_by_day,
    build_per_symbol_fit_curves,
    compute_overall,
    compute_symbol_metrics,
    pearson_corr,
    sign,
)
from plot_fit_accuracy import (  # noqa: F401
    main,
    plot_fit_curves_by_symbol,
    plot_metric_curves,
    plot_symbol_bars,
)

if __name__ == "__main__":
    main()
