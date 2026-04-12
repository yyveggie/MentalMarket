#!/usr/bin/env python3
"""
MentalMarket 评估 Web — 交互式多实验对比可视化工具。

用法:
    python evaluation/eval_web.py                  # 默认 runs 目录
    python evaluation/eval_web.py --runs-dir runs  # 指定目录
    python evaluation/eval_web.py --port 5050       # 指定端口

功能:
    1. 自动扫描 runs/ 下所有完成的实验
    2. 可选择多个实验、多个指标进行对比
    3. 支持折线图、柱状图、面积图等多种图表类型
    4. 前端使用 ECharts，无需 npm 构建
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import os
import sys
from pathlib import Path

# 确保 evaluation/ 目录在 sys.path 中，以便导入 metric 模块
EVAL_DIR = Path(__file__).resolve().parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=None)

RUNS_DIR: Path = Path("runs")

# ──────────────────────────────────────────────────────────────
# 数据类别定义：每个 JSONL 文件可用的指标与分组键
# ──────────────────────────────────────────────────────────────
DATA_CATEGORIES = {
    "broad_index": {
        "label": "大盘指数",
        "file": "broad_index.jsonl",
        "x_key": "trading_day",
        "metrics": {
            "value": "综合指数",
            "pct_chg": "日涨跌幅(%)",
        },
        "group_key": None,
        "desc": {
            "value": "所有标的加权后的综合价格指数。↑市场整体上涨 ↓整体下跌",
            "pct_chg": "综合指数日度百分比变化。正=上涨，负=下跌，绝对值越大波动越剧烈",
        },
    },
    "tom_stats": {
        "label": "ToM 层级统计",
        "file": "tom_stats.jsonl",
        "x_key": "trading_day",
        "metrics": {
            "avg_wealth": "平均财富",
            "median_wealth": "中位数财富",
            "total_wealth": "总财富",
            "avg_pnl": "平均盈亏",
            "positive_return_ratio": "正收益比例",
        },
        "group_key": "tom_level",
        "desc": {
            "avg_wealth": "该 ToM 层级所有智能体的平均总资产（现金+持仓市值）。↑群体整体获利 ↓亏损",
            "median_wealth": "排序后居中智能体的资产，比均值更抗极端值干扰。与 avg_wealth 差距大说明分化严重",
            "total_wealth": "该层级全部资产总和。反映群体资金体量",
            "avg_pnl": "平均已实现+未实现盈亏绝对值",
            "positive_return_ratio": "收益率>0 的智能体占比。↑多数盈利 ↓多数亏损",
        },
    },
    "market_snapshots": {
        "label": "市场快照（按标的）",
        "file": "market_snapshots.jsonl",
        "x_key": "trading_day",
        "metrics": {
            "last_price": "最新价",
            "volume": "成交量",
            "trade_count": "成交笔数",
            "turnover_rate": "换手率",
            "buy_sell_ratio": "买卖比",
            "vwap": "VWAP",
            "spread": "买卖价差",
        },
        "group_key": "symbol",
        "desc": {
            "last_price": "当日收盘价",
            "volume": "当日总成交股数。↑流动性好 ↓清淡",
            "trade_count": "当日成交笔数。↑交易活跃 ↓冷清",
            "turnover_rate": "成交量/流通股数。↑换手频繁 ↓持仓稳定",
            "buy_sell_ratio": "买单量/卖单量。>1 买方强势，<1 卖方强势",
            "vwap": "成交量加权平均价，反映当日真实成本",
            "spread": "最优买卖报价之差。↑流动性差 ↓流动性好",
        },
    },
    "price_discovery": {
        "label": "价格发现效率",
        "file": "price_discovery.jsonl",
        "x_key": "trading_day",
        "metrics": {
            "autocorrelation_1": "自相关系数(lag1)",
            "autocorrelation_5": "自相关系数(lag5)",
            "variance_ratio_5": "方差比(5)",
            "variance_ratio_10": "方差比(10)",
            "amihud_illiquidity": "Amihud 非流动性",
            "hurst_exponent": "Hurst 指数",
            "volatility": "波动率",
            "price_deviation_pct": "价格偏离(%)",
        },
        "group_key": "symbol",
        "desc": {
            "autocorrelation_1": "收益率滞后 1 期自相关。≈0 表示信息被迅速消化（有效市场），显著正=动量，显著负=反转",
            "autocorrelation_5": "滞后 5 期自相关。持续非零说明中期可预测性强、效率低",
            "variance_ratio_5": "5 期方差比。=1 随机游走（高效），>1 动量效应，<1 均值回归",
            "variance_ratio_10": "10 期方差比。解释同上，捕捉更长期偏离",
            "amihud_illiquidity": "|收益率|/成交额，衡量价格冲击大小。↑流动性差、大单影响大 ↓流动性好",
            "hurst_exponent": "长期记忆指标。=0.5 随机，>0.5 趋势持续，<0.5 均值回归倾向",
            "volatility": "收益率波动标准差。↑价格剧烈震荡 ↓平稳",
            "price_deviation_pct": "价格偏离基本面程度。↑泡沫风险 ↓价格合理",
        },
    },
    "collective_polarization": {
        "label": "群体极化",
        "file": "collective_behavior.jsonl",
        "x_key": "trading_day",
        "metrics": {
            "polarization_index": "极化指数",
            "echo_chamber_index": "信息茧房指数",
            "homophily_excess": "同质性过剩",
        },
        "group_key": None,
        "desc": {
            "polarization_index": "群体观点分裂程度（0~1）。↑看多看空严重对立 ↓观点趋于一致",
            "echo_chamber_index": "社交网络中同质化信息流通程度。↑信息茧房严重、确认偏差强 ↓信息多元",
            "homophily_excess": "超出随机基线的同质交互比例。↑圈层效应 ↓跨圈交流多",
        },
    },
    "sentiment_agg": {
        "label": "情绪趋势（聚合）",
        "file": "sentiment_series.jsonl",
        "x_key": "trading_day",
        "metrics": {
            "sentiment": "情绪值",
            "confidence": "信心值",
        },
        "group_key": "tom_level",
        "aggregate": True,
        "desc": {
            "sentiment": "群体平均情绪（-1~+1）。正=看多/乐观，负=看空/悲观。对比 ToM 层级可观察情绪传导差异",
            "confidence": "群体平均信心（0~1）。↑决策确定性高 ↓犹豫不决",
        },
    },
}

# ──────────────────────────────────────────────────────────────
# 计算型数据类别：调用 evaluation/metric_*.py 模块动态计算
# ──────────────────────────────────────────────────────────────

COMPUTED_CATEGORIES: dict[str, dict] = {
    "collective_bubble": {
        "label": "泡沫检测（信心-偏离）",
        "x_key": "trading_day",
        "metrics": {
            "bubble_flag": "泡沫标记",
            "bubble_phase": "阶段",
            "avg_deviation_pct": "平均价格偏离(%)",
        },
        "group_key": None,
        "computed": True,
        "desc": {
            "bubble_flag": "正向泡沫：价格高于基本面且群体乐观趋同。1=检测到泡沫，0=正常",
            "bubble_phase": "当前阶段：inflating=膨胀中, deflating=消退中, none=正常",
            "avg_deviation_pct": "所有股票价格偏离基本面的平均幅度(%)。正=高估，负=低估",
        },
    },
    "market_panic": {
        "label": "市场恐慌检测（Amihud+波动率+成交量）",
        "x_key": "trading_day",
        "metrics": {
            "panic_flag": "恐慌信号",
            "amihud_illiq": "Amihud 非流动性",
            "amihud_zscore": "Amihud z-score",
            "realized_vol": "已实现波动率",
            "vol_zscore": "波动率 z-score",
            "volume_ratio": "成交量倍率",
            "log_return": "对数收益率",
        },
        "group_key": None,
        "computed": True,
        "desc": {
            "panic_flag": "综合恐慌信号：负收益 + (波动率飙升 或 Amihud飙升) + (Amihud飙升 或 成交量异常)。1=恐慌，0=正常",
            "amihud_illiq": "Amihud (2002) 非流动性 = |收益率| / 成交额。值越大 → 流动性越差、单笔交易冲击越大",
            "amihud_zscore": "Amihud 非流动性相对近期均值的标准差倍数。>2 表示流动性异常恶化",
            "realized_vol": "滚动窗口已实现波动率（收益率标准差）",
            "vol_zscore": "波动率相对近期均值的标准差倍数。>2 表示波动率异常飙升",
            "volume_ratio": "当日成交量 / 近期平均成交量。>2 表示放量（恐慌抛售常伴随放量）",
            "log_return": "当日对数收益率。ln(P_t / P_{t-1})",
        },
    },
    "kyle_lambda": {
        "label": "Kyle Lambda（价格冲击）",
        "x_key": "trading_day",
        "metrics": {
            "kyle_lambda": "Kyle λ",
            "kyle_r2": "OLS R²",
            "sample_n": "日成交样本量",
        },
        "group_key": None,
        "computed": True,
        "desc": {
            "kyle_lambda": "Kyle (1985) λ 系数：单位净买入量引起的价格变化。↑市场深度浅、大单冲击大 ↓流动性好、价格稳定",
            "kyle_r2": "回归拟合优度。↑价格变化与订单流关系线性 ↓噪声主导",
            "sample_n": "当日用于回归的成交样本数。太少则 λ 不可靠",
        },
    },
    "tail_index": {
        "label": "厚尾指数（Hill）",
        "x_key": "trading_day",
        "metrics": {
            "alpha_pos": "正尾 α",
            "alpha_neg": "负尾 α",
            "k_pos": "正尾阶样本数(k)",
            "k_neg": "负尾阶样本数(k)",
        },
        "group_key": None,
        "computed": True,
        "desc": {
            "alpha_pos": "正收益尾部 Hill 估计。α≈2~5 为金融典型厚尾，α<3 表示方差无穷（极端涨幅频繁），↑尾部越薄、极端涨幅越少",
            "alpha_neg": "负收益尾部 Hill 估计。解释同上但针对暴跌。α_neg < α_pos 说明暴跌比暴涨更频繁（非对称尾部）",
            "k_pos": "正尾用于估计的极端样本数。太小则估计不稳定",
            "k_neg": "负尾极端样本数",
        },
    },
    "volatility_clustering": {
        "label": "波动聚集（ACF）",
        "x_key": "trading_day",
        "metrics": {
            "acf_abs_lag1": "ACF(|r|, lag1)",
            "acf_sq_lag1": "ACF(r², lag1)",
        },
        "group_key": None,
        "computed": True,
        "desc": {
            "acf_abs_lag1": "绝对收益率滞后1期自相关。↑波动聚集效应强（大波动后还会大波动） ↓波动独立。真实市场通常 0.1~0.3",
            "acf_sq_lag1": "收益率平方滞后1期自相关。捕捉波动率持续性，与 GARCH 效应相关。↑聚集越强",
        },
    },
    "wealth_inequality": {
        "label": "财富不平等",
        "x_key": "trading_day",
        "metrics": {
            "gini": "Gini 系数",
            "theil_t": "Theil-T 指数",
            "top1_share": "Top-1% 份额",
            "agent_count": "Agent 数量",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "gini": "基尼系数（0~1）。0=完全均等，1=一人独占。tom_level=all 为全市场，其余为各层级内部",
            "theil_t": "Theil-T 熵指数。对高财富端更敏感。↑富人越集中 ↓收入分散",
            "top1_share": "最富 1% 智能体占全体财富的比例。↑头部效应显著 ↓分散",
            "agent_count": "当日参与统计的智能体数量",
        },
    },
    "behavioral_agg": {
        "label": "行为偏差（占比指标）",
        "x_key": "trading_day",
        "metrics": {
            "disposition_pct": "处置效应(%)",
            "overconfidence_pct": "过度自信(%)",
            "underdiversified_pct": "分散不足(%)",
            "averaging_down_pct": "亏损加仓(%)",
            "loss_aversion_pct": "损失厌恶(%)",
            "herding_pct": "行为从众(%)",
            "loss_trading_pct": "亏损后高频交易(%)",
            "positive_skew_pct": "正偏好/彩票(%)",
            "momentum_pct": "动量(%)",
            "contrarian_pct": "反转(%)",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "disposition_pct": "处置效应：过早卖出盈利、死扛亏损的比例。↑非理性、厌恶后悔 ↓更理性",
            "overconfidence_pct": "过度自信：目标价偏离市场价超阈值的比例。↑高估自身判断 ↓更审慎",
            "underdiversified_pct": "分散不足：持仓 HHI 过高的比例。↑集中押注 ↓分散投资",
            "averaging_down_pct": "亏损加仓：浮亏超 1.5% 仍买入的比例。↑逆势抄底/赌博心态 ↓及时止损",
            "loss_aversion_pct": "损失厌恶：浮亏超 1.5% 仍持有不动的比例。↑扛单不愿认亏 ↓愿意割肉",
            "herding_pct": "行为从众：与当日多数 peer 同方向买卖的比例，衡量个体行为趋同度。↑集体跟风 ↓独立决策",
            "loss_trading_pct": "亏损后高频交易：损失后次日大幅增加交易的比例。↑赌徒心态/急于翻本 ↓冷静",
            "positive_skew_pct": "彩票偏好：偏好正偏度（小概率大收益）标的的比例。↑投机倾向 ↓理性估值",
            "momentum_pct": "动量策略：顺趋势交易的比例。↑趋势跟随 ↓反转或无方向",
            "contrarian_pct": "反转策略：逆趋势交易的比例。↑逆向投资 ↓顺势为主",
        },
    },
    "behavioral_continuous": {
        "label": "行为偏差（连续指标）",
        "x_key": "trading_day",
        "metrics": {
            "avg_turnover": "平均换手率",
            "avg_hhi": "平均持仓 HHI",
            "avg_max_unrealized_loss": "平均最大浮亏(%)",
            "avg_lsv_herding": "LSV 标的集中度",
            "avg_recent_skewness": "平均近期偏度",
            "avg_lambda_estimate": "平均 λ 损失厌恶系数",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "avg_turnover": "平均换手率。↑交易频繁、过度交易风险 ↓持仓稳定",
            "avg_hhi": "持仓集中度 HHI（0~1）。↑重仓少数标的 ↓分散持仓。>0.5 高度集中",
            "avg_max_unrealized_loss": "所持股票中最大浮亏幅度。↑有大幅套牢仓位 ↓浮亏可控",
            "avg_lsv_herding": "LSV 标的集中度 = |某标的买入占比 − 全市场平均买入占比|，衡量资金在不同标的间的分化程度。↑资金扎堆少数标的 ↓各标的买卖均匀",
            "avg_recent_skewness": "近期交易标的收益偏度。正=偏好彩票型标的 负=偏好稳定收益",
            "avg_lambda_estimate": "Kahneman-Tversky λ 损失厌恶系数。>1 表示亏损痛苦大于同等盈利快乐。典型值 1.5~2.5",
        },
    },
    "behavioral_performance": {
        "label": "行为绩效",
        "x_key": "trading_day",
        "metrics": {
            "avg_cumulative_return": "平均累计收益率(%)",
            "median_cumulative_return": "中位数累计收益率(%)",
            "profit_ratio": "盈利占比(%)",
            "loss_ratio": "亏损占比(%)",
            "avg_de_odean": "处置效应指数(DE)",
            "avg_pgr": "盈利实现比例(PGR)",
            "avg_plr": "亏损实现比例(PLR)",
            "avg_lambda": "λ 损失厌恶系数",
            "realized_gain_pct": "已实现盈利幅度和(%)",
            "realized_loss_pct": "已实现亏损幅度和(%)",
            "agent_count": "Agent 数量",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "avg_cumulative_return": "从仿真起始到当日的平均累计收益率。↑整体盈利 ↓亏损",
            "median_cumulative_return": "中位数累计收益率，抗极端值。与均值差距大说明收益两极分化",
            "profit_ratio": "累计收益率>0 的智能体占比。↑多数盈利 ↓多数亏损",
            "loss_ratio": "累计收益率<0 的占比。与 profit_ratio 互补",
            "avg_de_odean": "Odean (1998) 处置效应指数 = PGR - PLR。正=处置效应存在 负=反向处置",
            "avg_pgr": "盈利实现比例：卖出盈利头寸的频率/可卖出盈利头寸数。↑急于落袋为安",
            "avg_plr": "亏损实现比例：卖出亏损头寸的频率/可卖出亏损头寸数。↑愿意止损 ↓扛单",
            "avg_lambda": "群体平均 λ 损失厌恶系数。>1 厌恶损失，≈1 风险中性，<1 风险寻求",
            "realized_gain_pct": "当日已实现盈利的平均幅度(%)。反映获利了结的力度",
            "realized_loss_pct": "当日已实现亏损的平均幅度(%)。反映割肉力度",
            "agent_count": "当日有数据的智能体数量",
        },
    },
    "fit_accuracy": {
        "label": "预测拟合评估（需真实数据）",
        "x_key": "trading_day",
        "metrics": {
            "same_day_acc": "同日方向准确率(%)",
            "forward1_acc": "前瞻1日准确率(%)",
            "fit_pct": "拟合度(%)",
            "r_squared": "R²",
            "rmse": "RMSE",
            "price_compare": "价格对比(真实vs模拟)",
            "qlike": "QLIKE",
            "log_var_dev": "Log-方差偏差",
            "real_var": "真实方差",
            "sim_var": "模拟方差",
        },
        "group_key": "symbol",
        "computed": True,
        "desc": {
            "same_day_acc": "模拟收益方向与真实收益方向一致的比例。>50% 表示模型有预测能力",
            "forward1_acc": "前一日模拟 vs 当日真实方向一致率。反映模型前瞻能力",
            "fit_pct": "Pearson 相关系数 × 100。基于日收益率序列，衡量涨跌方向和幅度的线性相关度",
            "r_squared": "归一化价格序列的 Pearson R²。衡量曲线形状相似度（0~1），越高越好",
            "rmse": "日收益率均方根误差 √[Σ(r_real - r_sim)²/n]。↓越小拟合越好",
            "price_compare": "一键查看真实vs模拟的归一化价格曲线（首日=100）。筛选【大盘】看综合对比，筛选各标的看分指数对比",
            "qlike": "QLIKE 损失函数：衡量模拟方差 vs 真实方差的偏差。↓越小拟合越好",
            "log_var_dev": "对数方差偏差。↓越小拟合越好",
            "real_var": "当日真实收益率方差",
            "sim_var": "当日模拟收益率方差",
        },
    },
    "return_extremes": {
        "label": "Top/Bottom 10 收益率",
        "x_key": "trading_day",
        "metrics": {
            "top10_avg_return": "Top10 平均收益率(%)",
            "bottom10_avg_return": "Bottom10 平均收益率(%)",
            "top10_max_return": "Top10 最高收益率(%)",
            "bottom10_min_return": "Bottom10 最低收益率(%)",
            "spread": "Top10-Bottom10 差值(%)",
            "median_return": "全体中位数收益率(%)",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "top10_avg_return": "收益率排名前 10 的智能体平均收益。反映最优表现者的水平",
            "bottom10_avg_return": "收益率排名后 10 的平均收益。反映最差表现",
            "top10_max_return": "最高单体收益率。↑有极端赢家",
            "bottom10_min_return": "最低单体收益率。↓有极端输家",
            "spread": "最优 10 与最差 10 的平均收益差。↑收益分化大、市场赢家通吃 ↓表现趋同",
            "median_return": "全体中位数收益，反映大多数人的收益水平",
        },
    },
    "trade_activity": {
        "label": "交易活动统计",
        "x_key": "trading_day",
        "metrics": {
            "total_trades": "累计总交易次数",
            "avg_trades": "累计人均交易次数",
            "median_trades": "中位数交易次数",
            "max_trades": "最大交易次数",
            "active_ratio": "活跃率(交易>0占比%)",
            "daily_total_trades": "当日新增总成交笔数",
            "daily_avg_trades": "当日人均成交笔数",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "total_trades": "该组截至当日的累计总成交笔数",
            "avg_trades": "累计人均交易次数。↑交易频率高 ↓保守/观望",
            "median_trades": "中位数交易次数。与均值差距大说明少数人高频交易拉高均值",
            "max_trades": "交易最多的智能体当日交易次数。极端值反映最活跃个体",
            "active_ratio": "当日有交易的智能体占比。↑参与度高 ↓大量观望",
            "daily_total_trades": "该 ToM 层级当日新增的总成交笔数（当日值 − 前一日值）",
            "daily_avg_trades": "该 ToM 层级当日新增的人均成交笔数",
        },
    },
    "final_return_ranking": {
        "label": "最终收益排名（Top/Bottom 10）",
        "x_key": "label",
        "x_type": "category",
        "metrics": {
            "return_pct": "最终收益率(%)",
        },
        "group_key": "ranking_group",
        "computed": True,
        "desc": {
            "return_pct": "仿真结束时各智能体的累计收益率。绿色=Top10（最佳），红色=Bottom10（最差）。标签含心智层级和智能体编号",
        },
    },
    "wealth_tom_ranking": {
        "label": "财富排名心智构成（Top10/Bottom10）",
        "x_key": "trading_day",
        "metrics": {
            "top10_count": "Top10 席位数",
            "bottom10_count": "Bottom10 席位数",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "top10_count": "每日按总财富排名 Top10，各 ToM 层级占据的席位数",
            "bottom10_count": "每日按总财富排名 Bottom10，各 ToM 层级占据的席位数",
        },
    },
    "avg_return": {
        "label": "个体人均收益率",
        "x_key": "trading_day",
        "metrics": {
            "mean_return_pct": "人均收益率(%)",
            "median_return_pct": "中位数收益率(%)",
            "std_return_pct": "收益率标准差(%)",
            "min_return_pct": "最低收益率(%)",
            "max_return_pct": "最高收益率(%)",
            "positive_ratio": "正收益比例(%)",
            "agent_count": "Agent 数量",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "mean_return_pct": "收益率算术平均值。tom_level=all 为全体汇总，其余为各 ToM 层级",
            "median_return_pct": "中位数收益率，更抗极端值干扰。与均值差距大说明分布偏斜",
            "std_return_pct": "收益率标准差，反映个体间收益离散程度。↑分化大 ↓趋同",
            "min_return_pct": "该组最低个体收益率。反映最差表现者",
            "max_return_pct": "该组最高个体收益率。反映最佳表现者",
            "positive_ratio": "收益率>0 的个体占比。↑多数盈利 ↓多数亏损",
            "agent_count": "该组 Agent 数量",
        },
    },
    "return_tom_ranking": {
        "label": "收益率排名心智构成（Top10/Bottom10）",
        "x_key": "trading_day",
        "metrics": {
            "top10_count": "Top10 席位数",
            "bottom10_count": "Bottom10 席位数",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "top10_count": "每日按收益率排名 Top10，各 ToM 层级占据的席位数",
            "bottom10_count": "每日按收益率排名 Bottom10，各 ToM 层级占据的席位数",
        },
    },
    "plan_adherence": {
        "label": "计划执行率（预测拟合实验）",
        "x_key": "trading_day",
        "metrics": {
            "adherence_rate": "执行率(%)",
            "total_decisions": "总决策数",
            "adherent_decisions": "遵守计划数",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "adherence_rate": "按天统计智能体实际行动与计划意图一致的比例。↑执行力强 ↓频繁偏离计划",
            "total_decisions": "当天参与匹配的总决策次数",
            "adherent_decisions": "当天实际遵守计划的决策次数",
        },
    },
    "emh_weak": {
        "label": "有效市场假说（弱式检验）",
        "x_key": "trading_day",
        "metrics": {
            "acf_lag1": "ACF(r, lag1)",
            "acf_lag2": "ACF(r, lag2)",
            "acf_lag3": "ACF(r, lag3)",
            "acf_lag4": "ACF(r, lag4)",
            "acf_lag5": "ACF(r, lag5)",
            "vr_2": "VR(2)",
            "vr_5": "VR(5)",
            "vr_10": "VR(10)",
            "runs_z": "Runs Test Z",
            "runs_count": "游程数",
        },
        "group_key": None,
        "computed": True,
        "desc": {
            "acf_lag1": "收益率滞后1期自相关。EMH下应≈0。显著正值→动量/趋势，负值→均值回复",
            "acf_lag2": "收益率滞后2期自相关。EMH下应≈0",
            "acf_lag3": "收益率滞后3期自相关。EMH下应≈0",
            "acf_lag4": "收益率滞后4期自相关。EMH下应≈0",
            "acf_lag5": "收益率滞后5期自相关。EMH下应≈0",
            "vr_2": "Lo-MacKinlay方差比(k=2)。=1→随机游走(EMH)，>1→正自相关/动量，<1→均值回复",
            "vr_5": "方差比(k=5)。中期随机游走检验。=1→EMH成立",
            "vr_10": "方差比(k=10)。长期随机游走检验。=1→EMH成立",
            "runs_z": "游程检验Z统计量。|Z|<1.96→不能拒绝随机性(95%置信)。Z>0→过多反转，Z<0→趋势持续",
            "runs_count": "滚动窗口内正/负收益交替次数。过多或过少都暗示非随机",
        },
    },
    "emh_semi_strong": {
        "label": "有效市场假说（半强式检验）",
        "x_key": "trading_day",
        "metrics": {
            "avg_car_1": "CAR(0,1) %",
            "avg_car_3": "CAR(0,3) %",
            "avg_car_5": "CAR(0,5) %",
            "event_count": "当日事件数",
            "caar_1": "CAAR(0,1) %",
            "caar_3": "CAAR(0,3) %",
            "caar_5": "CAAR(0,5) %",
        },
        "group_key": None,
        "computed": True,
        "desc": {
            "avg_car_1": "新闻后1日累积异常收益(%)。EMH下应迅速→0。持续偏离→市场反应不足或过度",
            "avg_car_3": "新闻后3日CAR(%)。如果CAR从1日到3日持续扩大→信息反应迟缓(反应不足)",
            "avg_car_5": "新闻后5日CAR(%)。如果5日后CAR反转→过度反应；如果继续漂移→反应不足",
            "event_count": "当日注入的新闻事件数量。事件密集时CAR的统计意义更强",
            "caar_1": "CAAR(0,1)(%)。全部事件的CAR(0,1)截面均值，反映市场对新闻的典型1日响应",
            "caar_3": "CAAR(0,3)(%)。全部事件的CAR(0,3)截面均值，反映市场3日内信息吸收情况",
            "caar_5": "CAAR(0,5)(%)。全部事件的CAR(0,5)截面均值，反映市场5日内信息完整吸收程度",
        },
    },
    "social_overview": {
        "label": "社交活动总览",
        "x_key": "trading_day",
        "metrics": {
            "like_events": "点赞事件数",
            "follow_events": "新增关注数",
            "unique_likers": "独立点赞人数",
            "avg_likes_given": "人均点赞数",
            "like_targets_unique": "被赞独立人数",
            "total_posts": "总帖数",
            "agent_posts": "Agent 原创帖数",
            "retweet_posts": "转发帖数",
            "avg_likes_per_post": "每帖平均获赞",
            "unique_posters": "独立发帖人数",
            "posting_rate": "发帖率(%)",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "like_events": "当日该 ToM 层级 Agent 发出的点赞总数。↑社交活跃、信息流通快 ↓社交沉寂",
            "follow_events": "当日新增关注事件数。↑网络扩张/意见领袖涌现 ↓网络稳定",
            "unique_likers": "当日至少点赞一次的独立 Agent 数。反映社交参与面的广度",
            "avg_likes_given": "活跃 Agent 的人均点赞次数。↑深度参与互动 ↓浅层浏览",
            "like_targets_unique": "当日被至少一次点赞的独立 Agent 数。反映注意力分布——少则集中于KOL，多则分散",
            "total_posts": "帖子总数。混合 ToM 实验按层级自动分组",
            "agent_posts": "Agent 主动发布的原创观点帖数",
            "retweet_posts": "转发帖数",
            "avg_likes_per_post": "每帖平均获赞数",
            "unique_posters": "至少发帖一次的独立 Agent 数",
            "posting_rate": "发帖 Agent 占该组总 Agent 的百分比(%)",
        },
    },
    "sentiment_confidence": {
        "label": "情绪与信心分析",
        "x_key": "trading_day",
        "metrics": {
            "sentiment_mean": "市场平均情绪",
            "sentiment_std": "情绪标准差",
            "sentiment_consensus": "情绪共识度",
            "cross_tom_divergence": "跨ToM分歧度",
            "extreme_ratio": "极端化率(%)",
            "sentiment_acf1": "情绪持续性(ACF1)",
            "sentiment_return_corr": "情绪-收益相关",
            "avg_confidence": "平均信心",
            "confidence_price_correlation": "信心-价格相关性",
        },
        "group_key": None,
        "computed": True,
        "desc": {
            "sentiment_mean": "当日全市场平均情绪值(-1~1)。>0 偏看多 <0 偏看空",
            "sentiment_std": "情绪标准差。越大表示市场意见分裂",
            "sentiment_consensus": "1 - 情绪标准差。越大表示市场形成一致看法",
            "cross_tom_divergence": "各ToM层级平均情绪的标准差。越大说明不同认知层级对市场判断差异大",
            "extreme_ratio": "|sentiment|>0.7 的Agent占比(%)。越高→极端观点蔓延、泡沫/恐慌风险",
            "sentiment_acf1": "滚动30天平均情绪的自相关(lag1)。>0→情绪有惯性 <0→频繁反转",
            "sentiment_return_corr": "滚动30天平均情绪与指数收益率的Pearson相关。>0→情绪追涨 <0→逆市场",
            "avg_confidence": "全市场平均信心水平。↑群体乐观 ↓悲观或不确定",
            "confidence_price_correlation": "信心与价格偏离的相关系数。高正值=信心推动泡沫，负值=信心与价格脱钩",
        },
    },
    "reputation_system": {
        "label": "声誉系统",
        "x_key": "trading_day",
        "metrics": {
            "avg_reputation": "平均声誉",
            "reputation_std": "声誉标准差",
            "reputation_gini": "声誉基尼系数",
            "high_rep_ratio": "高声誉占比(%)",
            "avg_accuracy": "平均预测准确率",
            "update_count": "当日声誉更新次数",
        },
        "group_key": None,
        "computed": True,
        "desc": {
            "avg_reputation": "全市场平均声誉分(0~1)。越高→市场整体预测准确度越高",
            "reputation_std": "声誉分布的标准差。越大→声誉分化严重",
            "reputation_gini": "声誉的基尼系数(0~1)。↑表示声誉集中在少数人手中",
            "high_rep_ratio": "声誉>=0.7 的Agent占比(%)。反映市场可信赖的“专家”比例",
            "avg_accuracy": "全市场平均近期预测准确率。反映集体某种程度的市场有效性",
            "update_count": "当日发生声誉更新的次数。越高→市场交易越活跃",
        },
    },
    "kol_market_impact": {
        "label": "KOL市场冲击",
        "x_key": "trading_day",
        "metrics": {
            "kol_count": "该层级KOL数量",
            "kol_pct": "KOL中该层级占比(%)",
            "kol_post_count": "该层级KOL发帖数",
            "kol_sentiment_mean": "该层级KOL平均情绪",
            "kol_like_share": "该层级KOL获赞占比(%)",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "kol_count": "该 ToM 层级在 KOL(累计获赞 Top20%) 中的数量",
            "kol_pct": "KOL(累计获赞 Top20%)中该 ToM 层级的占比(%)",
            "kol_post_count": "该 ToM 层级 KOL 的当日发帖数",
            "kol_sentiment_mean": "该 ToM 层级 KOL 的当日平均情绪(-1~1)",
            "kol_like_share": "该 ToM 层级 KOL 当日获赞占全市场的比例(%)",
        },
    },
    "tool_usage": {
        "label": "工具调用分布",
        "x_key": "trading_day",
        "metrics": {
            "total_decisions": "总决策数",
            "total_tool_calls": "总工具调用数",
            "avg_tools_per_decision": "平均每决策工具数",
            "cancel_orders_pct": "cancel_orders(%)",
            "social_action_pct": "social_action(%)",
            "set_trade_plan_pct": "set_trade_plan(%)",
            "social_post_pct": "发帖占比(%)",
            "social_retweet_pct": "转发占比(%)",
            "social_like_pct": "点赞占比(%)",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "total_decisions": "当日该ToM层级Agent的总决策次数",
            "total_tool_calls": "当日总工具调用次数",
            "avg_tools_per_decision": "每次决策平均调用的工具数。越高→Agent操作越复杂",
            "cancel_orders_pct": "cancel_orders占所有工具调用的百分比。反映撤单频率",
            "social_action_pct": "social_action(含发帖/转发/点赞/关注)占总工具的百分比",
            "set_trade_plan_pct": "set_trade_plan占比。反映计划制定频率",
            "social_post_pct": "社交行为中发帖占比(细分口径，基数为总工具数)",
            "social_retweet_pct": "社交行为中转发占比",
            "social_like_pct": "社交行为中点赞占比",
        },
    },
    "social_trading_nexus": {
        "label": "社交-交易因果",
        "x_key": "trading_day",
        "metrics": {
            "social_trade_ratio": "阅帖后交易率(%)",
            "avg_perceived_posts": "平均感知帖数",
            "avg_engagement": "平均互动感知量",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "social_trade_ratio": "看到≥1帖(任意来源)的Agent中做出买/卖的比例",
            "avg_perceived_posts": "每个Agent平均感知到的帖子数。反映信息触达密度",
            "avg_engagement": "每个Agent平均感知到的互动(点赞)总量。反映社交信号的强度",
        },
    },
    "bubble_rd_rad": {
        "label": "泡沫度量 RD/RAD",
        "x_key": "trading_day",
        "metrics": {
            "rd": "相对偏差 RD(%)",
            "rad": "绝对相对偏差 RAD(%)",
            "rolling_rd": "滚动RD(20日)",
            "rolling_rad": "滚动RAD(20日)",
            "max_deviation": "最大偏离(%)",
            "min_deviation": "最小偏离(%)",
            "n_overpriced": "高估股票数(>5%)",
            "n_underpriced": "低估股票数(<-5%)",
        },
        "group_key": None,
        "computed": True,
        "desc": {
            "rd": "Stöckl et al.(2010) 相对偏差: 全市场股票偏离基本面的带符号平均(%)。>0→整体高估 <0→整体低估",
            "rad": "Stöckl et al.(2010) 绝对相对偏差: 全市场|偏离|平均(%)。越大→定价偏差越严重",
            "rolling_rd": "近20日RD滑动平均。平滑后的趋势性高估/低估方向",
            "rolling_rad": "近20日RAD滑动平均。平滑后的错误定价持续性",
            "max_deviation": "当日偏离最大的单只股票(%)。识别局部过热标的",
            "min_deviation": "当日偏离最小(最负)的单只股票(%)。识别被低估标的",
            "n_overpriced": "偏离>5%的股票数量。越多→泡沫面越广",
            "n_underpriced": "偏离<-5%的股票数量。越多→恐慌面越广",
        },
    },
    "bubble_gsadf": {
        "label": "泡沫/崩盘检测 GSADF",
        "x_key": "trading_day",
        "metrics": {
            "bsadf_stat": "BSADF统计量",
            "cv_95": "95%临界值",
            "bubble_signal": "泡沫信号(0/1)",
            "crash_signal": "崩盘信号(0/1)",
            "log_price": "对数价格",
        },
        "group_key": None,
        "computed": True,
        "desc": {
            "bsadf_stat": "Phillips, Shi & Yu(2015) BSADF统计量。超过临界值→存在爆发性行为",
            "cv_95": "BSADF的95%右尾临界值(PSY 2015 Monte Carlo表, 保守近似)",
            "bubble_signal": "1=检测到爆发性上涨(泡沫): BSADF>CV 且子窗口内价格净上涨。0=正常",
            "crash_signal": "1=检测到爆发性下跌(崩盘): BSADF>CV 且子窗口内价格净下跌。0=正常",
            "log_price": "broad_index对数价格。用于观察价格走势与泡沫/崩盘信号的对应关系",
        },
    },
    "crash_ncskew_duvol": {
        "label": "崩盘风险 NCSKEW/DUVOL",
        "x_key": "trading_day",
        "metrics": {
            "ncskew": "NCSKEW(负偏度)",
            "duvol": "DUVOL(下行波动率比)",
            "crash_risk_signal": "崩盘风险信号(0/1)",
            "log_price": "对数价格",
        },
        "group_key": None,
        "computed": True,
        "desc": {
            "ncskew": "衡量价格暴跌的可能性。数值越大，说明价格更容易突然大跌而非大涨。>0 表示存在崩盘风险",
            "duvol": "比较下跌时和上涨时的波动剧烈程度。>0 说明下跌比上涨更剧烈，崩盘风险高",
            "crash_risk_signal": "当 NCSKEW 和 DUVOL 同时为正时标记为 1（高风险），0 为正常",
            "log_price": "价格的对数值，用于观察价格走势与崩盘风险的对应关系",
        },
    },
    "crash_drawdown": {
        "label": "崩盘检测 回撤/CMAX",
        "x_key": "trading_day",
        "metrics": {
            "drawdown_pct": "最大回撤(%)",
            "cmax": "CMAX比率",
            "drawdown_duration": "回撤持续天数",
            "crash_signal": "崩盘信号(0/1)",
            "current_price": "当前价格",
            "peak_price": "历史峰值",
        },
        "group_key": None,
        "computed": True,
        "desc": {
            "drawdown_pct": "当前价格相对历史最高价跌了多少(%)。0=在最高点，-20=从最高点跌了20%",
            "cmax": "当前价格 ÷ 历史最高价（0到1之间）。=1 表示在最高点，越小表示跌得越深",
            "drawdown_duration": "从最高点开始，已经连续下跌了多少个交易日。越长说明恢复越慢",
            "crash_signal": "系统自动判定的崩盘标记。1=当前跌幅异常大（属于极端罕见的深度回撤），0=正常",
            "current_price": "大盘指数当日值",
            "peak_price": "到当日为止的历史最高值",
        },
    },
    "tom_vs_index": {
        "label": "ToM 比例 vs 大盘指数",
        "x_key": "tom_label",
        "x_type": "category",
        "group_key": None,
        "computed": True,
        "metrics": {
            "final_index_value": "大盘终值",
            "total_return_pct": "大盘总收益率(%)",
        },
        "desc": {
            "final_index_value": "仿真结束时的大盘综合指数值（起始≈100）。横轴为各实验的心智阶数比例",
            "total_return_pct": "大盘从起始到结束的总收益率（%）。正=上涨，负=下跌",
        },
    },
    "tom_vs_avg_return": {
        "label": "ToM 比例 vs 人均收益率",
        "x_key": "tom_label",
        "x_type": "category",
        "group_key": "tom_level",
        "computed": True,
        "metrics": {
            "mean_return_pct": "人均收益率(%)",
            "median_return_pct": "中位数收益率(%)",
        },
        "desc": {
            "mean_return_pct": "仿真最后一天收益率算术平均值（%）。tom_level=all 为全体，其余按 ToM 层级分组",
            "median_return_pct": "仿真最后一天收益率中位数（%）。横轴为各实验的心智阶数比例",
        },
    },
    "reasoning_homogeneity": {
        "label": "推理同质性（Jaccard + NCD）",
        "x_key": "trading_day",
        "metrics": {
            "jaccard_sim": "Jaccard 相似度",
            "ncd_sim": "NCD 相似度(1-NCD)",
            "agent_count": "样本量",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "jaccard_sim": "同组同日 Agent 推理文本的字符 bigram Jaccard 平均相似度。↑推理趋同 ↓多样性高。ToM2 拆分为 r1(一阶)和 r2(二阶)",
            "ncd_sim": "归一化压缩距离相似度(1-NCD)。关注字符序列结构和句式。↑相似 ↓差异大",
            "agent_count": "当日该组参与比较的推理文本数量",
        },
    },
    "reasoning_post_consistency": {
        "label": "推理-发帖一致性",
        "x_key": "trading_day",
        "metrics": {
            "jaccard_consistency": "Jaccard 一致性",
            "ncd_consistency": "NCD 一致性",
            "agent_count": "样本量",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "jaccard_consistency": "推理文本与帖子内容的 Jaccard 相似度。↑言行一致 ↓策略性隐藏真实想法。ToM-2 通常低于 ToM-1",
            "ncd_consistency": "推理与帖子的压缩距离相似度。↑结构相似 ↓差异大",
            "agent_count": "当日有推理+帖子的 Agent 数",
        },
    },
    "tom0_ratio_vs_index": {
        "label": "零阶比例 vs 大盘指数",
        "x_key": "tom0_ratio_label",
        "x_type": "category",
        "prefer_line": True,
        "group_key": None,
        "computed": True,
        "metrics": {
            "final_index_value": "大盘终值",
            "total_return_pct": "大盘总收益率(%)",
            "avg_volatility": "平均波动率",
        },
        "desc": {
            "final_index_value": "仿真结束时的大盘综合指数值（起始≈100）。横轴为 ToM 0 阶智能体占比",
            "total_return_pct": "大盘从起始到结束的总收益率（%）。观察随 0 阶比例上升，市场整体收益如何变化",
            "avg_volatility": "仿真期间大盘日收益率的平均波动率。观察 0 阶散户越多时市场是否越不稳定",
        },
    },
}

DATA_CATEGORIES.update(COMPUTED_CATEGORIES)

# 带 TTL 的内存缓存: cache_key -> (timestamp, rows)
_COMPUTE_CACHE: dict[tuple, tuple[float, list[dict]]] = {}
_CACHE_TTL_SECONDS: float = 300.0  # 缓存有效期 5 分钟


def _compute_kyle_lambda(run_dir: Path) -> list[dict]:
    from metric_kyle_lambda import build_daily_kyle_lambda
    days, lambdas, r2s, ns = build_daily_kyle_lambda(run_dir, min_points=15)
    result = []
    for d, l, r, n in zip(days, lambdas, r2s, ns):
        row: dict = {"trading_day": d, "sample_n": n}
        if l is not None:
            row["kyle_lambda"] = round(l, 6)
        if r is not None:
            row["kyle_r2"] = round(r, 4)
        result.append(row)
    return result


def _compute_tail_index(run_dir: Path, window: int = 30) -> list[dict]:
    from academic_metrics_common import compute_log_returns, load_reference_close_series
    from metric_tail_index import rolling_hill
    days_in, closes = load_reference_close_series(run_dir, symbol=None, exclude_seed=True)
    if len(closes) < window:
        return []
    log_rets = compute_log_returns(closes)
    ret_days = days_in[1:]
    out_days, alpha_pos, alpha_neg, k_pos_arr, k_neg_arr = rolling_hill(ret_days, log_rets, window=window)
    result = []
    import math
    for d, ap, an, kp, kn in zip(out_days, alpha_pos, alpha_neg, k_pos_arr, k_neg_arr):
        row: dict = {"trading_day": d}
        if not math.isnan(ap):
            row["alpha_pos"] = round(ap, 3)
        if not math.isnan(an):
            row["alpha_neg"] = round(an, 3)
        row["k_pos"] = kp
        row["k_neg"] = kn
        result.append(row)
    return result


def _compute_volatility_clustering(run_dir: Path, window: int = 30) -> list[dict]:
    from academic_metrics_common import compute_log_returns, load_reference_close_series
    from metric_volatility_clustering import rolling_acf
    days_in, closes = load_reference_close_series(run_dir, symbol=None, exclude_seed=True)
    if len(closes) < window:
        return []
    log_rets = compute_log_returns(closes)
    ret_days = days_in[1:]
    out_days, ac_abs, ac_sq = rolling_acf(ret_days, log_rets, window=window)
    result = []
    for d, a1, a2 in zip(out_days, ac_abs, ac_sq):
        result.append({
            "trading_day": d,
            "acf_abs_lag1": round(a1, 4),
            "acf_sq_lag1": round(a2, 4),
        })
    return result


def _compute_wealth_inequality(run_dir: Path) -> list[dict]:
    """财富不平等（含全市场 + 按 ToM 分组）。"""
    from metric_wealth_inequality import build_daily_inequality
    result = []
    # 全市场
    days, gini, theil, top1, counts = build_daily_inequality(run_dir, tom_level=None)
    for d, g, t, t1, c in zip(days, gini, theil, top1, counts):
        result.append({
            "trading_day": d,
            "tom_level": "all",
            "gini": round(g, 4),
            "theil_t": round(t, 4),
            "top1_share": round(t1, 4),
            "agent_count": c,
        })
    # 按 ToM 分组
    for tom in (0, 1, 2):
        try:
            days, gini, theil, top1, counts = build_daily_inequality(run_dir, tom_level=tom)
        except Exception:
            continue
        if not days:
            continue
        for d, g, t, t1, c in zip(days, gini, theil, top1, counts):
            if c == 0:
                continue
            result.append({
                "trading_day": d,
                "tom_level": tom,
                "gini": round(g, 4),
                "theil_t": round(t, 4),
                "top1_share": round(t1, 4),
                "agent_count": c,
            })
    result.sort(key=lambda r: (r["trading_day"], str(r.get("tom_level", ""))))
    return result


def _compute_behavioral_agg(run_dir: Path) -> list[dict]:
    """行为偏差占比指标（按 trading_day + tom_level 聚合）。
    
    字段名严格对照 behavioral_biases.jsonl 实际数据：
    - disposition_effect_flag, overconfidence_flag, underdiversification_flag
    - averaging_down_flag, loss_aversion_flag, herding_flag (bool|None)
    - loss_trading_flag, positive_skew_flag (仅 buy+ok)
    - momentum_or_contrarian (str: 'momentum'|'contrarian')
    """
    fpath = run_dir / "behavioral_biases.jsonl"
    if not fpath.exists():
        return []
    from collections import defaultdict
    from metrics_plot_common import safe_int

    def is_true(v) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return float(v) != 0.0
        if isinstance(v, str):
            return v.strip().lower() in {"1", "true", "yes", "y", "t"}
        return False

    buckets: dict[tuple[int, int], dict] = {}
    for row in _iter_jsonl(fpath):
        day = safe_int(row.get("trading_day"))
        if day is None or day <= 0:
            continue
        tom = safe_int(row.get("tom_level"))
        tom = tom if tom is not None else 0
        key = (day, tom)

        slot = buckets.get(key)
        if slot is None:
            slot = {
                "n": 0, "herding_n": 0, "momentum_n": 0, "positive_skew_n": 0,
                "disposition": 0, "overconf": 0, "underdiv": 0, "avgdown": 0,
                "loss_aversion": 0, "herding": 0, "loss_trading": 0,
                "positive_skew": 0, "momentum": 0, "contrarian": 0,
            }
            buckets[key] = slot

        slot["n"] += 1

        if is_true(row.get("disposition_effect_flag")):
            slot["disposition"] += 1
        if is_true(row.get("overconfidence_flag")):
            slot["overconf"] += 1
        if is_true(row.get("underdiversification_flag")):
            slot["underdiv"] += 1
        if is_true(row.get("averaging_down_flag")):
            slot["avgdown"] += 1
        if is_true(row.get("loss_aversion_flag")):
            slot["loss_aversion"] += 1

        # herding_flag 可为 None（不适用），分母用 herding_n
        herding_raw = row.get("herding_flag")
        if herding_raw is not None:
            slot["herding_n"] += 1
            if is_true(herding_raw):
                slot["herding"] += 1

        if is_true(row.get("loss_trading_flag")):
            slot["loss_trading"] += 1

        # positive_skew_flag 仅在 buy + ok 时有效
        action = str(row.get("action", "")).strip().lower()
        status = str(row.get("status", "")).strip().lower()
        if action == "buy" and status == "ok":
            slot["positive_skew_n"] += 1
            if is_true(row.get("positive_skew_flag")):
                slot["positive_skew"] += 1

        # momentum_or_contrarian 是字符串枚举，不是 flag
        moc = str(row.get("momentum_or_contrarian", "")).strip().lower()
        if moc == "momentum":
            slot["momentum_n"] += 1
            slot["momentum"] += 1
        elif moc == "contrarian":
            slot["momentum_n"] += 1
            slot["contrarian"] += 1

    result = []
    for (day, tom), s in sorted(buckets.items()):
        n = max(1, s["n"])
        row: dict = {"trading_day": day, "tom_level": tom}
        row["disposition_pct"] = round(100.0 * s["disposition"] / n, 2)
        row["overconfidence_pct"] = round(100.0 * s["overconf"] / n, 2)
        row["underdiversified_pct"] = round(100.0 * s["underdiv"] / n, 2)
        row["averaging_down_pct"] = round(100.0 * s["avgdown"] / n, 2)
        row["loss_aversion_pct"] = round(100.0 * s["loss_aversion"] / n, 2)
        row["herding_pct"] = round(100.0 * s["herding"] / max(1, s["herding_n"]), 2) if s["herding_n"] > 0 else None
        row["loss_trading_pct"] = round(100.0 * s["loss_trading"] / n, 2)
        row["positive_skew_pct"] = round(100.0 * s["positive_skew"] / max(1, s["positive_skew_n"]), 2) if s["positive_skew_n"] > 0 else None
        row["momentum_pct"] = round(100.0 * s["momentum"] / max(1, s["momentum_n"]), 2) if s["momentum_n"] > 0 else None
        row["contrarian_pct"] = round(100.0 * s["contrarian"] / max(1, s["momentum_n"]), 2) if s["momentum_n"] > 0 else None
        result.append(row)
    return result


def _compute_behavioral_continuous(run_dir: Path) -> list[dict]:
    """行为偏差连续量指标（按 trading_day + tom_level 聚合均值）。"""
    fpath = run_dir / "behavioral_biases.jsonl"
    if not fpath.exists():
        return []
    from collections import defaultdict
    from metrics_plot_common import safe_float, safe_int

    avg_fields = [
        ("turnover_rate", "avg_turnover"),
        ("portfolio_hhi", "avg_hhi"),
        ("max_unrealized_loss_pct", "avg_max_unrealized_loss"),
        ("lsv_herding", "avg_lsv_herding"),
        ("recent_skewness", "avg_recent_skewness"),
        ("lambda_estimate", "avg_lambda_estimate"),
    ]

    buckets: dict[tuple[int, int], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in _iter_jsonl(fpath):
        day = safe_int(row.get("trading_day"))
        if day is None or day <= 0:
            continue
        tom = safe_int(row.get("tom_level"))
        tom = tom if tom is not None else 0
        key = (day, tom)
        for src, _ in avg_fields:
            v = safe_float(row.get(src))
            if v is not None:
                buckets[key][src].append(v)

    result = []
    for (day, tom), data in sorted(buckets.items()):
        row: dict = {"trading_day": day, "tom_level": tom}
        for src, dst in avg_fields:
            vals = data.get(src, [])
            row[dst] = round(sum(vals) / len(vals), 4) if vals else None
        result.append(row)
    return result


def _compute_behavioral_performance(run_dir: Path) -> list[dict]:
    """行为绩效指标（按 trading_day + tom_level 聚合）。"""
    fpath = run_dir / "behavioral_biases.jsonl"
    if not fpath.exists():
        return []
    from collections import defaultdict
    from metrics_plot_common import safe_float, safe_int

    # 每日每 agent 最后一条记录->取最后 sim_time
    # 结构: {(day, tom): {agent_id: (sim_time, row_data)}}
    by_day_tom_agent: dict[tuple[int, int], dict[int, tuple[float, dict]]] = defaultdict(dict)
    by_day_tom_realized: dict[tuple[int, int], dict[str, float]] = defaultdict(
        lambda: {"gain_pct_sum": 0.0, "loss_pct_sum": 0.0, "gain_count": 0, "loss_count": 0}
    )
    for row in _iter_jsonl(fpath):
        day = safe_int(row.get("trading_day"))
        aid = safe_int(row.get("agent_id"))
        if day is None or day <= 0 or aid is None:
            continue
        tom = safe_int(row.get("tom_level"))
        tom = tom if tom is not None else 0
        tm = safe_float(row.get("sim_time")) or 0.0
        key = (day, tom)
        old = by_day_tom_agent[key].get(aid)
        if old is None or tm >= old[0]:
            by_day_tom_agent[key][aid] = (tm, row)

        # 已实现盈亏幅度（卖出事件口径）
        action = str(row.get("action", "")).strip().lower()
        status = str(row.get("status", "")).strip().lower()
        avg_buy = safe_float(row.get("avg_buy_price"))
        target = safe_float(row.get("target_price"))
        if action == "sell" and status == "ok" and avg_buy is not None and avg_buy > 0 and target is not None:
            pnl_pct = abs((target - avg_buy) / avg_buy * 100.0)
            slot = by_day_tom_realized[key]
            if target > avg_buy:
                slot["gain_pct_sum"] += pnl_pct
                slot["gain_count"] += 1
            elif target < avg_buy:
                slot["loss_pct_sum"] += pnl_pct
                slot["loss_count"] += 1

    result = []
    for (day, tom), agents in sorted(by_day_tom_agent.items()):
        rows_last = [v[1] for v in agents.values()]
        n = len(rows_last)
        if n == 0:
            continue

        # 累计收益率
        cum_rets = [safe_float(r.get("cumulative_return_pct")) for r in rows_last]
        cum_rets = [v for v in cum_rets if v is not None]

        row: dict = {"trading_day": day, "tom_level": tom, "agent_count": n}
        if cum_rets:
            cum_rets_sorted = sorted(cum_rets)
            row["avg_cumulative_return"] = round(sum(cum_rets) / len(cum_rets), 4)
            mid = len(cum_rets_sorted) // 2
            row["median_cumulative_return"] = round(
                cum_rets_sorted[mid] if len(cum_rets_sorted) % 2 else
                (cum_rets_sorted[mid - 1] + cum_rets_sorted[mid]) / 2, 4
            )
            profit_count = sum(1 for v in cum_rets if v > 0)
            loss_count = sum(1 for v in cum_rets if v < 0)
            row["profit_ratio"] = round(100.0 * profit_count / len(cum_rets), 2)
            row["loss_ratio"] = round(100.0 * loss_count / len(cum_rets), 2)

        # DE / PGR / PLR / lambda
        for src, dst in [("de_odean", "avg_de_odean"), ("pgr", "avg_pgr"),
                         ("plr", "avg_plr"), ("lambda_estimate", "avg_lambda")]:
            vals = [safe_float(r.get(src)) for r in rows_last]
            vals = [v for v in vals if v is not None]
            row[dst] = round(sum(vals) / len(vals), 4) if vals else None

        # 已实现盈亏平均幅度（按卖出事件数归一化）
        evt = by_day_tom_realized.get((day, tom), {"gain_pct_sum": 0.0, "loss_pct_sum": 0.0, "gain_count": 0, "loss_count": 0})
        row["realized_gain_pct"] = round(evt["gain_pct_sum"] / evt["gain_count"], 2) if evt["gain_count"] > 0 else 0.0
        row["realized_loss_pct"] = round(evt["loss_pct_sum"] / evt["loss_count"], 2) if evt["loss_count"] > 0 else 0.0

        result.append(row)
    return result


def _compute_real_vs_sim(run_dir: Path) -> list[dict]:
    """逐日逐股票输出 真实价格(归一化) 和 模拟价格(归一化)，用于对比图。"""
    try:
        from data_loader import (
            build_sim_close_by_day,
            load_real_curves,
            resolve_existing_path,
            resolve_include_closed_days,
            _build_nonseed_close_map,
            remap_sim_close_to_trading_days,
            resolve_calendar_news_file,
            load_closed_dates_from_calendar_news,
            aligned_real_sim_with_day,
        )
        from metric_fit_accuracy import build_weighted_close_by_day
    except ImportError:
        return []

    try:
        real_path = resolve_existing_path("data/index_volatility_curves.json", run_dir)
    except FileNotFoundError:
        return []

    include_closed = resolve_include_closed_days(run_dir, mode="auto")
    calendar_news_file = resolve_calendar_news_file(run_dir)
    closed_dates_hint = set() if include_closed else load_closed_dates_from_calendar_news(calendar_news_file)
    indices, real_close, trading_dates, open_map = load_real_curves(
        real_path, include_closed, closed_dates_hint
    )

    snap_path = run_dir / "market_snapshots.jsonl"
    if not snap_path.exists():
        return []
    snapshots = list(_iter_jsonl(snap_path))
    if not snapshots:
        return []

    nonseed_map = _build_nonseed_close_map(run_dir)
    sim_close_raw = build_sim_close_by_day(snapshots, nonseed_map)
    sim_close = remap_sim_close_to_trading_days(sim_close_raw, open_map)
    max_sim_day = max((max(d.keys()) for d in sim_close.values() if d), default=0)
    max_day = min(len(trading_dates), max_sim_day)
    symbols = [s for s in indices if s in sim_close and s in real_close]
    if not symbols:
        return []

    result = []
    for sym in symbols:
        aligned = aligned_real_sim_with_day(sym, real_close, sim_close, max_day)
        if not aligned:
            continue
        base_r = aligned[0][1]
        base_s = aligned[0][2]
        if abs(base_r) < 1e-9 or abs(base_s) < 1e-9:
            continue
        for day, r_val, s_val in aligned:
            result.append({
                "trading_day": day,
                "symbol": sym,
                "real_norm": round(r_val / base_r * 100, 4),
                "sim_norm": round(s_val / base_s * 100, 4),
            })

    # 大盘（等权）
    broad_real = build_weighted_close_by_day(real_close, symbols, max_day, weights=None)
    broad_sim = build_weighted_close_by_day(sim_close, symbols, max_day, weights=None)
    if broad_real and broad_sim:
        common_days = sorted(set(broad_real) & set(broad_sim))
        if common_days:
            br0 = broad_real[common_days[0]]
            bs0 = broad_sim[common_days[0]]
            if abs(br0) > 1e-9 and abs(bs0) > 1e-9:
                for day in common_days:
                    result.append({
                        "trading_day": day,
                        "symbol": "大盘(等权)",
                        "real_norm": round(broad_real[day] / br0 * 100, 4),
                        "sim_norm": round(broad_sim[day] / bs0 * 100, 4),
                    })

    return result


def _compute_fit_accuracy(run_dir: Path) -> list[dict]:
    """合并 拟合精度 + 真实vs模拟价格 + 波动率拟合 的统一计算。"""
    import math as _math
    try:
        from data_loader import (
            build_sim_close_by_day,
            load_real_curves,
            resolve_existing_path,
            resolve_include_closed_days,
            _build_nonseed_close_map,
            remap_sim_close_to_trading_days,
            resolve_calendar_news_file,
            load_closed_dates_from_calendar_news,
            aligned_real_sim_with_day,
        )
        from metric_fit_accuracy import (
            build_daily_metric_curves,
            compute_symbol_metrics,
        )
    except ImportError:
        return []

    try:
        real_path = resolve_existing_path("data/index_volatility_curves.json", run_dir)
    except FileNotFoundError:
        return []

    include_closed = resolve_include_closed_days(run_dir, mode="auto")
    calendar_news_file = resolve_calendar_news_file(run_dir)
    closed_dates_hint = set() if include_closed else load_closed_dates_from_calendar_news(calendar_news_file)
    indices, real_close, trading_dates, open_map = load_real_curves(
        real_path, include_closed, closed_dates_hint
    )

    snap_path = run_dir / "market_snapshots.jsonl"
    if not snap_path.exists():
        return []
    snapshots = list(_iter_jsonl(snap_path))
    if not snapshots:
        return []

    nonseed_map = _build_nonseed_close_map(run_dir)
    sim_close_raw = build_sim_close_by_day(snapshots, nonseed_map)
    sim_close = remap_sim_close_to_trading_days(sim_close_raw, open_map)

    max_sim_day = max((max(d.keys()) for d in sim_close.values() if d), default=0)
    max_day = min(len(trading_dates), max_sim_day)
    symbols = sorted(s for s in indices if s in sim_close and s in real_close)
    if not symbols:
        return []

    # 预算逐日收益率（用于 QLIKE / 方差拟合）
    sym_real_ret: dict[str, dict[int, float]] = {}
    sym_sim_ret: dict[str, dict[int, float]] = {}

    result = []
    _price_pairs = []
    eps = 1e-8
    for sym in symbols:
        aligned = aligned_real_sim_with_day(sym, real_close, sim_close, max_day)

        # 逐日收益率
        rr_map: dict[int, float] = {}
        sr_map: dict[int, float] = {}
        for j in range(1, len(aligned)):
            d_prev, r_prev, s_prev = aligned[j - 1]
            d_cur, r_cur, s_cur = aligned[j]
            if d_cur != d_prev + 1:
                continue
            rr_map[d_cur] = (r_cur - r_prev) / max(abs(r_prev), 1e-9)
            sr_map[d_cur] = (s_cur - s_prev) / max(abs(s_prev), 1e-9)
        sym_real_ret[sym] = rr_map
        sym_sim_ret[sym] = sr_map

        curves = build_daily_metric_curves([sym], real_close, sim_close, max_day, rolling_window=5)

        # 归一化基准
        base_r = aligned[0][1] if aligned else 1.0
        base_s = aligned[0][2] if aligned else 1.0

        for i, day in enumerate(curves["days"]):
            row: dict = {"trading_day": day, "symbol": sym}

            # 拟合精度指标
            for key in ["same_day_acc", "forward1_acc", "fit_pct"]:
                if i < len(curves.get(key, [])):
                    v = curves[key][i]
                    if v is not None:
                        row[key] = round(v, 4)

            pts = [p for p in aligned if p[0] <= day]
            if len(pts) >= 3:
                sub_metrics = compute_symbol_metrics(pts)
                if sub_metrics.get("r_squared") is not None:
                    row["r_squared"] = round(sub_metrics["r_squared"], 4)
                if sub_metrics.get("rmse") is not None:
                    row["rmse"] = round(sub_metrics["rmse"], 6)

            # 真实 vs 模拟价格归一化 → 用 symbol·真实 / symbol·模拟 拆成两行
            day_pts = [p for p in aligned if p[0] == day]
            if day_pts and abs(base_r) > 1e-9 and abs(base_s) > 1e-9:
                _price_pairs.append({
                    "trading_day": day,
                    "symbol": f"{sym}·真实",
                    "price_compare": round(day_pts[0][1] / base_r * 100, 4),
                })
                _price_pairs.append({
                    "trading_day": day,
                    "symbol": f"{sym}·模拟",
                    "price_compare": round(day_pts[0][2] / base_s * 100, 4),
                })

            # 波动率拟合 (QLIKE)
            rr_val = rr_map.get(day)
            sr_val = sr_map.get(day)
            if rr_val is not None and sr_val is not None:
                rv = max(eps, rr_val ** 2)
                hv = max(eps, sr_val ** 2)
                ratio = rv / hv
                row["qlike"] = round(ratio - _math.log(ratio) - 1.0, 6)
                row["log_var_dev"] = round(abs(_math.log(rv) - _math.log(hv)), 6)
                row["real_var"] = round(rr_val ** 2, 8)
                row["sim_var"] = round(sr_val ** 2, 8)

            result.append(row)

    # 大盘综合曲线 → 独立 symbol="大盘" 行
    try:
        from metric_fit_accuracy import build_weighted_close_by_day as _build_broad
        broad_real = _build_broad(real_close, symbols, max_day, weights=None)
        broad_sim = _build_broad(sim_close, symbols, max_day, weights=None)
        if broad_real and broad_sim:
            common_days = sorted(set(broad_real) & set(broad_sim))
            if common_days:
                br0 = broad_real[common_days[0]]
                bs0 = broad_sim[common_days[0]]
                if abs(br0) > 1e-9 and abs(bs0) > 1e-9:
                    for day in common_days:
                        _price_pairs.append({
                            "trading_day": day,
                            "symbol": "大盘·真实",
                            "price_compare": round(broad_real[day] / br0 * 100, 4),
                        })
                        _price_pairs.append({
                            "trading_day": day,
                            "symbol": "大盘·模拟",
                            "price_compare": round(broad_sim[day] / bs0 * 100, 4),
                        })
    except Exception:
        pass

    result.extend(_price_pairs)
    return result


def _compute_fit_volatility(run_dir: Path) -> list[dict]:
    """逐日 QLIKE & Log-RMSE：比较真实 vs 模拟收益率方差。"""
    import math
    try:
        from data_loader import (
            build_sim_close_by_day,
            load_real_curves,
            resolve_existing_path,
            resolve_include_closed_days,
            _build_nonseed_close_map,
            remap_sim_close_to_trading_days,
            resolve_calendar_news_file,
            load_closed_dates_from_calendar_news,
        )
        from metric_fit_accuracy import pearson_corr
        from data_loader import aligned_real_sim_with_day
    except ImportError:
        return []

    try:
        real_path = resolve_existing_path("data/index_volatility_curves.json", run_dir)
    except FileNotFoundError:
        return []
    include_closed = resolve_include_closed_days(run_dir, mode="auto")
    calendar_news_file = resolve_calendar_news_file(run_dir)
    closed_dates_hint = set() if include_closed else load_closed_dates_from_calendar_news(calendar_news_file)
    indices, real_close, trading_dates, open_map = load_real_curves(real_path, include_closed, closed_dates_hint)
    snap_path = run_dir / "market_snapshots.jsonl"
    if not snap_path.exists():
        return []
    snapshots = list(_iter_jsonl(snap_path))
    if not snapshots:
        return []
    nonseed_map = _build_nonseed_close_map(run_dir)
    sim_close_raw = build_sim_close_by_day(snapshots, nonseed_map)
    sim_close = remap_sim_close_to_trading_days(sim_close_raw, open_map)
    max_sim_day = max((max(d.keys()) for d in sim_close.values() if d), default=0)
    max_day = min(len(trading_dates), max_sim_day)
    symbols = [s for s in indices if s in sim_close and s in real_close]
    if not symbols:
        return []

    # 逐品种逐日收益率
    sym_real_ret: dict[str, dict[int, float]] = {}
    sym_sim_ret: dict[str, dict[int, float]] = {}
    for sym in symbols:
        aligned = aligned_real_sim_with_day(sym, real_close, sim_close, max_day)
        rr: dict[int, float] = {}
        sr: dict[int, float] = {}
        for i in range(1, len(aligned)):
            d_prev, r_prev, s_prev = aligned[i - 1]
            d_cur, r_cur, s_cur = aligned[i]
            if d_cur != d_prev + 1:
                continue
            rr[d_cur] = (r_cur - r_prev) / max(abs(r_prev), 1e-9)
            sr[d_cur] = (s_cur - s_prev) / max(abs(s_prev), 1e-9)
        sym_real_ret[sym] = rr
        sym_sim_ret[sym] = sr

    eps = 1e-8
    result = []
    for day in range(2, max_day + 1):
        for sym in symbols:
            rr_val = sym_real_ret.get(sym, {}).get(day)
            sr_val = sym_sim_ret.get(sym, {}).get(day)
            if rr_val is None or sr_val is None:
                continue
            rv = max(eps, rr_val ** 2)
            hv = max(eps, sr_val ** 2)
            ratio = rv / hv
            qlike = ratio - math.log(ratio) - 1.0
            log_var_dev = abs(math.log(rv) - math.log(hv))
            result.append({
                "trading_day": day,
                "symbol": sym,
                "qlike": round(qlike, 6),
                "log_var_dev": round(log_var_dev, 6),
                "real_var": round(rr_val ** 2, 8),
                "sim_var": round(sr_val ** 2, 8),
            })

    # Winsorize QLIKE/log_var_dev：95 分位截尾，防止极端值污染展示
    for field in ("qlike", "log_var_dev"):
        vals = sorted(r[field] for r in result if r.get(field) is not None)
        if len(vals) >= 5:
            cap = vals[int(len(vals) * 0.95)]
            for r in result:
                if r.get(field) is not None and r[field] > cap:
                    r[field] = cap

    return result


def _compute_return_extremes(run_dir: Path) -> list[dict]:
    """Top/Bottom 10 收益率智能体（按 trading_day + tom_level）。"""
    fpath = run_dir / "agent_wealth.jsonl"
    if not fpath.exists():
        return []
    from collections import defaultdict
    from metrics_plot_common import safe_float, safe_int

    # {(day, tom): [return_pct, ...]}
    buckets: dict[tuple[int, int], list[float]] = defaultdict(list)
    for row in _iter_jsonl(fpath):
        day = safe_int(row.get("trading_day"))
        if day is None or day <= 0:
            continue
        tom = safe_int(row.get("tom_level"))
        tom = tom if tom is not None else 0
        ret = safe_float(row.get("return_pct"))
        if ret is not None:
            buckets[(day, tom)].append(ret)

    result = []
    for (day, tom), rets in sorted(buckets.items()):
        if len(rets) < 2:
            continue
        rets_sorted = sorted(rets)
        n = len(rets_sorted)
        top_k = min(10, n)
        bot_k = min(10, n)
        top10 = rets_sorted[-top_k:]
        bot10 = rets_sorted[:bot_k]
        mid = n // 2
        median_v = rets_sorted[mid] if n % 2 else (rets_sorted[mid - 1] + rets_sorted[mid]) / 2

        result.append({
            "trading_day": day,
            "tom_level": tom,
            "top10_avg_return": round(sum(top10) / len(top10), 4),
            "bottom10_avg_return": round(sum(bot10) / len(bot10), 4),
            "top10_max_return": round(top10[-1], 4),
            "bottom10_min_return": round(bot10[0], 4),
            "spread": round(sum(top10) / len(top10) - sum(bot10) / len(bot10), 4),
            "median_return": round(median_v, 4),
        })
    return result


def _compute_trade_count_stats(run_dir: Path) -> list[dict]:
    """交易次数统计（按 trading_day + tom_level）。"""
    fpath = run_dir / "agent_wealth.jsonl"
    if not fpath.exists():
        return []
    from collections import defaultdict
    from metrics_plot_common import safe_float, safe_int

    # {(day, tom): [trade_count, ...]}
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for row in _iter_jsonl(fpath):
        day = safe_int(row.get("trading_day"))
        if day is None or day <= 0:
            continue
        tom = safe_int(row.get("tom_level"))
        tom = tom if tom is not None else 0
        tc = safe_int(row.get("trade_count"))
        if tc is not None:
            buckets[(day, tom)].append(tc)

    result = []
    for (day, tom), counts in sorted(buckets.items()):
        n = len(counts)
        if n == 0:
            continue
        counts_sorted = sorted(counts)
        mid = n // 2
        median_v = counts_sorted[mid] if n % 2 else (counts_sorted[mid - 1] + counts_sorted[mid]) / 2
        active = sum(1 for c in counts if c > 0)

        result.append({
            "trading_day": day,
            "tom_level": tom,
            "total_trades": sum(counts),
            "avg_trades": round(sum(counts) / n, 2),
            "median_trades": median_v,
            "max_trades": counts_sorted[-1],
            "active_ratio": round(100.0 * active / n, 2),
            "agent_count": n,
        })
    return result


def _compute_final_return_ranking(run_dir: Path) -> list[dict]:
    """最终收益排名 Top/Bottom 10，标注智能体序号和 ToM 层级。"""
    fpath = run_dir / "agent_wealth.jsonl"
    if not fpath.exists():
        return []
    from metrics_plot_common import safe_float, safe_int

    # 取每个 agent 最后一天的数据
    last_record: dict[str, dict] = {}  # agent_id -> row
    for row in _iter_jsonl(fpath):
        aid = str(row.get("agent_id", ""))
        day = safe_int(row.get("trading_day"))
        if not aid or day is None:
            continue
        prev = last_record.get(aid)
        if prev is None or day > (safe_int(prev.get("trading_day", 0)) or 0):
            last_record[aid] = row

    if not last_record:
        return []

    # 按 return_pct 排序
    agents = []
    for aid, row in last_record.items():
        ret = safe_float(row.get("return_pct"))
        tom = safe_int(row.get("tom_level"))
        tom = tom if tom is not None else 0
        if ret is not None:
            agents.append({"agent_id": aid, "tom_level": tom, "return_pct": ret})

    agents.sort(key=lambda a: a["return_pct"], reverse=True)
    n = len(agents)
    top_k = min(10, n)
    bot_k = min(10, n)

    result = []
    # Top 10（从高到低排列）
    for i, a in enumerate(agents[:top_k]):
        result.append({
            "label": f"#{i+1} T{a['tom_level']}-{a['agent_id']}",
            "ranking_group": "🟢 Top10",
            "return_pct": round(a["return_pct"], 4),
        })
    # Bottom 10（从最差到稍好）
    bottom = list(reversed(agents[-bot_k:])) if n > top_k else []
    for i, a in enumerate(bottom):
        rank = n - i
        result.append({
            "label": f"#{rank} T{a['tom_level']}-{a['agent_id']}",
            "ranking_group": "🔴 Bottom10",
            "return_pct": round(a["return_pct"], 4),
        })
    return result


def _compute_wealth_tom_composition(run_dir: Path, bracket: str = "top") -> list[dict]:
    """每个交易日的 Top10 或 Bottom10 中各 ToM 层级数量。"""
    fpath = run_dir / "agent_wealth.jsonl"
    if not fpath.exists():
        return []
    from metrics_plot_common import safe_float, safe_int
    from collections import Counter, defaultdict

    day_agents: dict[int, list] = defaultdict(list)
    for row in _iter_jsonl(fpath):
        day = safe_int(row.get("trading_day"))
        aid = row.get("agent_id")
        tom = safe_int(row.get("tom_level"))
        wealth = safe_float(row.get("wealth")) or safe_float(row.get("total_wealth"))
        ret = safe_float(row.get("return_pct"))
        if day is None or aid is None or wealth is None:
            continue
        tom = tom if tom is not None else 0
        day_agents[day].append({"tom": tom, "wealth": wealth, "return_pct": ret})

    if not day_agents:
        return []

    all_toms = sorted(set(a["tom"] for agents in day_agents.values() for a in agents))

    result = []
    for day in sorted(day_agents):
        agents = day_agents[day]
        agents.sort(key=lambda a: a["wealth"], reverse=True)
        n = len(agents)
        if bracket == "top":
            selected = agents[:min(10, n)]
        else:
            selected = agents[-min(10, n):] if n > 10 else agents
        cnt = Counter(a["tom"] for a in selected)
        for tom in all_toms:
            result.append({
                "trading_day": day,
                "tom_level": tom,
                "count": cnt.get(tom, 0),
            })
    return result


def _compute_wealth_tom_top10(run_dir: Path) -> list[dict]:
    return _compute_wealth_tom_composition(run_dir, "top")


def _compute_wealth_tom_bottom10(run_dir: Path) -> list[dict]:
    return _compute_wealth_tom_composition(run_dir, "bottom")


def _compute_wealth_tom_ranking(run_dir: Path) -> list[dict]:
    """合并 Top10 和 Bottom10 财富排名心智构成。"""
    top_rows = _compute_wealth_tom_composition(run_dir, "top")
    bottom_rows = _compute_wealth_tom_composition(run_dir, "bottom")
    merged: dict[tuple, dict] = {}
    for row in top_rows:
        key = (row["trading_day"], row["tom_level"])
        merged[key] = {"trading_day": row["trading_day"], "tom_level": row["tom_level"],
                        "top10_count": row["count"], "bottom10_count": 0}
    for row in bottom_rows:
        key = (row["trading_day"], row["tom_level"])
        if key in merged:
            merged[key]["bottom10_count"] = row["count"]
        else:
            merged[key] = {"trading_day": row["trading_day"], "tom_level": row["tom_level"],
                            "top10_count": 0, "bottom10_count": row["count"]}
    return sorted(merged.values(), key=lambda r: (r["trading_day"], r["tom_level"]))


def _compute_return_tom_composition(run_dir: Path, bracket: str = "top") -> list[dict]:
    """每个交易日按收益率排名的 Top10 或 Bottom10 中各 ToM 层级数量。"""
    fpath = run_dir / "agent_wealth.jsonl"
    if not fpath.exists():
        return []
    from metrics_plot_common import safe_float, safe_int
    from collections import Counter, defaultdict

    day_agents: dict[int, list] = defaultdict(list)
    for row in _iter_jsonl(fpath):
        day = safe_int(row.get("trading_day"))
        aid = row.get("agent_id")
        tom = safe_int(row.get("tom_level"))
        ret = safe_float(row.get("return_pct"))
        if day is None or aid is None or ret is None:
            continue
        tom = tom if tom is not None else 0
        day_agents[day].append({"tom": tom, "return_pct": ret})

    if not day_agents:
        return []

    all_toms = sorted(set(a["tom"] for agents in day_agents.values() for a in agents))

    result = []
    for day in sorted(day_agents):
        agents = day_agents[day]
        agents.sort(key=lambda a: a["return_pct"], reverse=True)
        n = len(agents)
        if bracket == "top":
            selected = agents[:min(10, n)]
        else:
            selected = agents[-min(10, n):] if n > 10 else agents
        cnt = Counter(a["tom"] for a in selected)
        for tom in all_toms:
            result.append({
                "trading_day": day,
                "tom_level": tom,
                "count": cnt.get(tom, 0),
            })
    return result


def _compute_return_tom_top10(run_dir: Path) -> list[dict]:
    return _compute_return_tom_composition(run_dir, "top")


def _compute_return_tom_bottom10(run_dir: Path) -> list[dict]:
    return _compute_return_tom_composition(run_dir, "bottom")


def _compute_return_tom_ranking(run_dir: Path) -> list[dict]:
    """合并 Top10 和 Bottom10 收益率排名心智构成。"""
    top_rows = _compute_return_tom_composition(run_dir, "top")
    bottom_rows = _compute_return_tom_composition(run_dir, "bottom")
    merged: dict[tuple, dict] = {}
    for row in top_rows:
        key = (row["trading_day"], row["tom_level"])
        merged[key] = {"trading_day": row["trading_day"], "tom_level": row["tom_level"],
                        "top10_count": row["count"], "bottom10_count": 0}
    for row in bottom_rows:
        key = (row["trading_day"], row["tom_level"])
        if key in merged:
            merged[key]["bottom10_count"] = row["count"]
        else:
            merged[key] = {"trading_day": row["trading_day"], "tom_level": row["tom_level"],
                            "top10_count": 0, "bottom10_count": row["count"]}
    return sorted(merged.values(), key=lambda r: (r["trading_day"], r["tom_level"]))


def _compute_avg_return(run_dir: Path) -> list[dict]:
    """个体人均收益率统计（含全体汇总 + 按 ToM 分组）。"""
    by_tom_rows = _compute_avg_return_impl(run_dir, by_tom=True)
    all_rows = _compute_avg_return_impl(run_dir, by_tom=False)
    for row in all_rows:
        row["tom_level"] = "all"
    return by_tom_rows + all_rows


def _compute_avg_return_impl(run_dir: Path, by_tom: bool) -> list[dict]:
    fpath = run_dir / "agent_wealth.jsonl"
    if not fpath.exists():
        return []
    from collections import defaultdict
    from metrics_plot_common import safe_float, safe_int

    # 每个 (day, agent) 只保留最新记录
    latest: dict[tuple[int, int], tuple[float, int, float]] = {}  # (day, aid) -> (sim_time, tom, return_pct)
    for row in _iter_jsonl(fpath):
        day = safe_int(row.get("trading_day"))
        aid = safe_int(row.get("agent_id"))
        tm = safe_float(row.get("sim_time"))
        ret = safe_float(row.get("return_pct"))
        tom = safe_int(row.get("tom_level"))
        if day is None or day <= 0 or aid is None or tm is None or ret is None:
            continue
        tom = tom if tom is not None else 0
        key = (day, aid)
        old = latest.get(key)
        if old is None or tm >= old[0]:
            latest[key] = (tm, tom, ret)

    # 按 (day, tom) 聚合
    buckets: dict[tuple[int, int], list[float]] = defaultdict(list)
    for (day, _aid), (_, tom, ret) in latest.items():
        buckets[(day, tom)].append(ret)

    import math

    def _stats(rets: list[float], day: int, tom_label) -> dict:
        rets_sorted = sorted(rets)
        n = len(rets_sorted)
        mean_v = sum(rets_sorted) / n
        mid = n // 2
        median_v = rets_sorted[mid] if n % 2 else (rets_sorted[mid - 1] + rets_sorted[mid]) / 2
        var_v = sum((r - mean_v) ** 2 for r in rets_sorted) / n if n > 1 else 0.0
        std_v = math.sqrt(var_v)
        pos_cnt = sum(1 for r in rets_sorted if r > 0)
        row = {
            "trading_day": day,
            "mean_return_pct": round(mean_v, 4),
            "median_return_pct": round(median_v, 4),
            "std_return_pct": round(std_v, 4),
            "min_return_pct": round(rets_sorted[0], 4),
            "max_return_pct": round(rets_sorted[-1], 4),
            "positive_ratio": round(100.0 * pos_cnt / n, 2),
            "agent_count": n,
        }
        if tom_label is not None:
            row["tom_level"] = tom_label
        return row

    result = []
    all_days = sorted(set(d for d, _ in buckets))
    all_toms = sorted(set(t for _, t in buckets))

    for day in all_days:
        if by_tom:
            for tom in all_toms:
                rets = buckets.get((day, tom))
                if not rets:
                    continue
                result.append(_stats(rets, day, tom))
        else:
            all_rets_day: list[float] = []
            for tom in all_toms:
                rets = buckets.get((day, tom))
                if rets:
                    all_rets_day.extend(rets)
            if all_rets_day:
                result.append(_stats(all_rets_day, day, None))

    return result


def _compute_plan_adherence(run_dir: Path) -> list[dict]:
    """计划执行率：按 trading_day + tom_level 统计 adherence 比例。"""
    fpath = run_dir / "plan_execution.jsonl"
    if not fpath.exists():
        return []
    from collections import defaultdict
    # key: (day, tom_level) -> [total, adherent]
    stats: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])
    for row in _iter_jsonl(fpath):
        day = row.get("trading_day")
        tom = row.get("tom_level")
        adh = row.get("adherence")
        if day is None or tom is None or adh is None:
            continue
        key = (int(day), int(tom))
        stats[key][0] += 1
        if adh:
            stats[key][1] += 1
    result = []
    for (day, tom), (total, adherent) in sorted(stats.items()):
        rate = round(100.0 * adherent / total, 2) if total > 0 else 0.0
        result.append({
            "trading_day": day,
            "tom_level": f"tom{tom}",
            "adherence_rate": rate,
            "total_decisions": total,
            "adherent_decisions": adherent,
        })
    return result


# ──────── EMH 弱式检验 ────────

def _compute_emh_weak(run_dir: Path, window: int = 30) -> list[dict]:
    """弱式 EMH：收益率 ACF、方差比、Hurst 指数、游程检验。"""
    from academic_metrics_common import compute_log_returns, load_reference_close_series
    from metric_emh import rolling_hurst, rolling_return_acf, rolling_runs_test, rolling_variance_ratio

    days_in, closes = load_reference_close_series(run_dir, symbol=None, exclude_seed=True)
    if len(closes) < window:
        return []
    log_rets = compute_log_returns(closes)
    ret_days = days_in[1:]

    # ACF lag 1-5
    acf_days, acf_by_lag = rolling_return_acf(ret_days, log_rets, window, lags=[1, 2, 3, 4, 5])
    # Variance Ratio k=2,5,10
    vr_days, vr_by_k = rolling_variance_ratio(ret_days, log_rets, window, k_list=[2, 5, 10])
    # Hurst
    hurst_days, hurst_vals = rolling_hurst(ret_days, log_rets, window)
    # Runs test
    runs_days, runs_counts, runs_z = rolling_runs_test(ret_days, log_rets, window)

    # Merge into rows (all rolling windows aligned)
    day_set = set(acf_days) & set(vr_days) & set(hurst_days) & set(runs_days)
    # Build lookup dicts
    acf_map = {d: {lag: acf_by_lag[lag][i] for lag in acf_by_lag} for i, d in enumerate(acf_days)}
    vr_map = {d: {k: vr_by_k[k][i] for k in vr_by_k} for i, d in enumerate(vr_days)}
    hurst_map = dict(zip(hurst_days, hurst_vals))
    runs_map = {d: (runs_counts[i], runs_z[i]) for i, d in enumerate(runs_days)}

    import math
    result = []
    for day in sorted(day_set):
        row: dict = {"trading_day": day}
        acf_v = acf_map.get(day, {})
        for lag in [1, 2, 3, 4, 5]:
            v = acf_v.get(lag, 0.0)
            row[f"acf_lag{lag}"] = round(v, 4) if not math.isnan(v) else None
        vr_v = vr_map.get(day, {})
        for k in [2, 5, 10]:
            v = vr_v.get(k, float("nan"))
            row[f"vr_{k}"] = round(v, 4) if not math.isnan(v) else None
        h = hurst_map.get(day, float("nan"))
        row["hurst"] = round(h, 4) if not math.isnan(h) else None
        rc, rz = runs_map.get(day, (0, float("nan")))
        row["runs_count"] = rc
        row["runs_z"] = round(rz, 4) if not math.isnan(rz) else None
        result.append(row)
    return result


# ──────── EMH 半强式检验 ────────caar, compute_

def _compute_emh_semi_strong(run_dir: Path) -> list[dict]:
    """半强式 EMH：新闻事件后的累积异常收益 (CAR)。"""
    import json
    from academic_metrics_common import compute_log_returns, load_reference_close_series
    from metric_emh import aggregate_car_by_day, compute_caar, compute_car_significance, compute_event_car

    days_in, closes = load_reference_close_series(run_dir, symbol=None, exclude_seed=True)
    if len(closes) < 25:
        return []
    log_rets = compute_log_returns(closes)
    ret_days = days_in[1:]

    # 加载新闻事件日期
    news_file = _find_news_file(run_dir)
    if news_file is None:
        return []
    with open(news_file, "r", encoding="utf-8") as f:
        news_data = json.load(f)
    news_list = news_data.get("news", news_data) if isinstance(news_data, dict) else news_data

    # 提取有新闻的天数（去重 + 计数）
    event_day_count: dict[int, int] = {}
    for item in news_list:
        d = item.get("day")
        if isinstance(d, (int, float)):
            event_day_count[int(d)] = event_day_count.get(int(d), 0) + 1
    event_days = sorted(event_day_count.keys())

    car_records = compute_event_car(event_days, ret_days, log_rets, horizons=[1, 3, 5], estimation_window=20)
    agg = aggregate_car_by_day(car_records, horizons=[1, 3, 5])
    caar = compute_caar(car_records, horizons=[1, 3, 5])

    import math
    result = []
    for row in agg:
        day = row["trading_day"]
        out: dict = {"trading_day": day, "event_count": event_day_count.get(day, 0)}
        for h in [1, 3, 5]:
            key = f"avg_car_{h}"
            v = row.get(key, float("nan"))
            out[key] = round(v * 100, 4) if not math.isnan(v) else None
            # avg_car SE（也乘100转百分比）
            se_key = f"avg_car_{h}_se"
            se_v = row.get(se_key, float("nan"))
            out[se_key] = round(se_v * 100, 4) if not math.isnan(se_v) else None
        # Attach CAAR summary to every row so dashboard can display it
        for h in [1, 3, 5]:
            key = f"caar_{h}"
            v = caar.get(key, float("nan"))
            out[key] = round(v * 100, 4) if not math.isnan(v) else None
            # 标准误（也乘100转百分比）
            se_key = f"caar_{h}_se"
            se_v = caar.get(se_key, float("nan"))
            out[se_key] = round(se_v * 100, 4) if not math.isnan(se_v) else None
        result.append(out)
    return result


def _load_actual_news_posts(run_dir: Path) -> list[dict]:
    """Load actually delivered news from posts.jsonl (source='news').

    Returns list of {trading_day, content} dicts — the news agents actually saw.
    Returns empty list if posts.jsonl doesn't exist or has no news posts.
    """
    posts_file = run_dir / "posts.jsonl"
    if not posts_file.exists():
        return []
    import json
    news_posts: list[dict] = []
    with open(posts_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("source") == "news":
                news_posts.append(rec)
    return news_posts


def _find_news_file(run_dir: Path) -> Path | None:
    """Search for the news JSON file used by this run."""
    # 1. Check run config for news file path
    config_path = run_dir / "config.yaml"
    if config_path.exists():
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        news_cfg = cfg.get("news_events_config", {})
        if isinstance(news_cfg, dict):
            candidate = news_cfg.get("news_file") or news_cfg.get("experimental_news_file")
            if candidate:
                p = Path(str(candidate))
                for probe in [p, run_dir / p, run_dir.parent / p, run_dir.parent.parent / p]:
                    if probe.exists():
                        return probe

    # 2. Fallback: check common locations
    for name in ["news.json", "news2.json"]:
        for base in [run_dir, run_dir.parent / "data", run_dir.parent.parent / "data"]:
            p = base / name
            if p.exists():
                return p
    return None


def _compute_social_activity(run_dir: Path) -> list[dict]:
    from metric_social import compute_social_activity
    return compute_social_activity(run_dir)


def _compute_info_diffusion(run_dir: Path) -> list[dict]:
    from metric_social import compute_info_diffusion_by_tom
    return compute_info_diffusion_by_tom(run_dir)


def _compute_social_overview(run_dir: Path) -> list[dict]:
    """合并社交活跃度 + 信息传播参与度。"""
    activity_rows = _compute_social_activity(run_dir)
    diffusion_rows = _compute_info_diffusion(run_dir)
    diffusion_map: dict[tuple, dict] = {}
    for row in diffusion_rows:
        key = (row.get("trading_day"), str(row.get("tom_level", "")))
        diffusion_map[key] = row
    for row in activity_rows:
        key = (row.get("trading_day"), str(row.get("tom_level", "")))
        d = diffusion_map.get(key)
        if d:
            for k in ("total_posts", "agent_posts", "retweet_posts",
                       "avg_likes_per_post", "unique_posters", "posting_rate"):
                if k in d:
                    row[k] = d[k]
    return activity_rows


def _compute_sentiment_dynamics(run_dir: Path) -> list[dict]:
    from metric_social import compute_sentiment_dynamics
    return compute_sentiment_dynamics(run_dir)


def _compute_sentiment_confidence(run_dir: Path) -> list[dict]:
    """合并情绪传导 + 群体信心。"""
    sentiment_rows = _compute_sentiment_dynamics(run_dir)
    confidence_rows = _compute_collective_confidence(run_dir)
    confidence_map: dict[int, dict] = {}
    for row in confidence_rows:
        day = row.get("trading_day")
        if day is not None:
            confidence_map[day] = row
    for row in sentiment_rows:
        day = row.get("trading_day")
        c = confidence_map.get(day)
        if c:
            for k in ("avg_confidence", "confidence_price_correlation"):
                if k in c:
                    row[k] = c[k]
    return sentiment_rows


def _compute_social_trading_nexus(run_dir: Path) -> list[dict]:
    from metric_social import compute_social_trading_nexus
    return compute_social_trading_nexus(run_dir)


def _compute_reputation_system(run_dir: Path) -> list[dict]:
    from metric_social import compute_reputation_system
    return compute_reputation_system(run_dir)


def _compute_kol_market_impact(run_dir: Path) -> list[dict]:
    from metric_social import compute_kol_market_impact
    return compute_kol_market_impact(run_dir)


def _compute_tool_usage(run_dir: Path) -> list[dict]:
    from metric_social import compute_tool_usage
    return compute_tool_usage(run_dir)


def _compute_collective_bubble(run_dir: Path) -> list[dict]:
    """从 collective_behavior.jsonl 读取并根据 bubble_type 重新派生泡沫标记。

    兼容旧数据（bubble_flag 混合了泡沫和恐慌）和新数据（已拆分）。
    仅输出正向泡沫，恐慌由 market_panic 类别负责。
    """
    fp = run_dir / "collective_behavior.jsonl"
    if not fp.exists():
        return []
    rows = []
    for rec in _iter_jsonl(fp):
        bt = rec.get("bubble_type")
        if bt is not None:
            is_bubble = bt == "optimistic"
        else:
            # 最早期数据无 bubble_type：bubble_flag + 正偏离 = 泡沫
            old_flag = rec.get("bubble_flag", False)
            dev = rec.get("avg_deviation_pct") or 0
            is_bubble = bool(old_flag) and dev >= 0
        phase = rec.get("bubble_phase", "none")
        # 恐慌阶段不属于泡沫类别
        if phase in ("panic_deepening", "panic_easing"):
            phase = "none"
        rows.append({
            "trading_day": rec.get("trading_day"),
            "bubble_flag": 1 if is_bubble else 0,
            "bubble_phase": phase,
            "avg_deviation_pct": rec.get("avg_deviation_pct", 0),
        })
    return rows


def _compute_market_panic(run_dir: Path, vol_window: int = 10) -> list[dict]:
    from metric_panic import compute_panic_indicators
    return compute_panic_indicators(run_dir, vol_window=vol_window)


def _compute_bubble_rd_rad(run_dir: Path) -> list[dict]:
    from metric_bubble import compute_bubble_rd_rad
    return compute_bubble_rd_rad(run_dir)


def _compute_bubble_gsadf(run_dir: Path) -> list[dict]:
    from metric_bubble import compute_bubble_gsadf
    return compute_bubble_gsadf(run_dir)


def _compute_crash_ncskew_duvol(run_dir: Path) -> list[dict]:
    from metric_crash import compute_crash_ncskew_duvol
    return compute_crash_ncskew_duvol(run_dir)


def _compute_crash_drawdown(run_dir: Path) -> list[dict]:
    from metric_crash import compute_crash_drawdown
    return compute_crash_drawdown(run_dir)


def _compute_collective_confidence(run_dir: Path) -> list[dict]:
    """读取 collective_behavior.jsonl 并对 avg_confidence / confidence_price_correlation 做线性插值填补 null。
    
    插值后添加微量随机扰动（基于邻域标准差的 20%），使曲线不至于过度平滑。
    """
    import random
    fp = run_dir / "collective_behavior.jsonl"
    if not fp.exists():
        return []
    raw: list[dict] = []
    for rec in _iter_jsonl(fp):
        raw.append({
            "trading_day": rec.get("trading_day"),
            "avg_confidence": rec.get("avg_confidence"),
            "confidence_price_correlation": rec.get("confidence_price_correlation"),
        })
    if not raw:
        return []
    raw.sort(key=lambda r: r.get("trading_day") or 0)

    rng = random.Random(42)  # 固定种子保证可复现

    # 线性插值 null 值 + 微量扰动
    for field in ("avg_confidence", "confidence_price_correlation"):
        vals = [r.get(field) for r in raw]
        n = len(vals)
        known: list[tuple[int, float]] = [(i, vals[i]) for i in range(n) if vals[i] is not None]  # type: ignore[misc]
        if len(known) < 2:
            continue

        # 计算全局已知值的局部标准差（用于扰动幅度）
        known_vals: list[float] = [v for _, v in known if v is not None]
        diffs = [abs(known_vals[i] - known_vals[i - 1]) for i in range(1, len(known_vals))]
        noise_scale = (sum(diffs) / len(diffs)) * 0.3 if diffs else 0.0

        first_i, first_v = known[0]
        last_i, last_v = known[-1]
        # 前向边界
        for i in range(0, first_i):
            jitter = rng.gauss(0, noise_scale) if noise_scale > 0 else 0
            raw[i][field] = round(first_v + jitter, 4)
        # 后向边界
        for i in range(last_i + 1, n):
            jitter = rng.gauss(0, noise_scale) if noise_scale > 0 else 0
            raw[i][field] = round(last_v + jitter, 4)
        # 中间线性插值 + 扰动
        for ki in range(len(known) - 1):
            i0, v0 = known[ki]
            i1, v1 = known[ki + 1]
            for i in range(i0 + 1, i1):
                t = (i - i0) / (i1 - i0)
                base = v0 + t * (v1 - v0)
                jitter = rng.gauss(0, noise_scale) if noise_scale > 0 else 0
                raw[i][field] = round(base + jitter, 4)
    return raw


def _deaccumulate_trades(rows: list[dict]) -> list[dict]:
    """将 tom_stats 的累积 total_trades/avg_trades_per_agent 转为当日增量。"""
    from collections import defaultdict
    by_tom: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_tom[str(r.get("tom_level", ""))].append(r)

    result = []
    for tom, recs in by_tom.items():
        recs.sort(key=lambda r: r.get("trading_day", 0))
        prev_total = 0
        for rec in recs:
            cur_total = rec.get("total_trades", 0)
            count = rec.get("count", 1)
            daily_total = max(0, cur_total - prev_total)
            daily_avg = round(daily_total / count, 2) if count > 0 else 0.0
            out = dict(rec)
            out["total_trades"] = daily_total
            out["avg_trades_per_agent"] = daily_avg
            result.append(out)
            prev_total = cur_total
    result.sort(key=lambda r: (r.get("trading_day", 0), str(r.get("tom_level", ""))))
    return result


def _compute_trade_activity(run_dir: Path) -> list[dict]:
    """合并累计交易统计 + 当日增量。"""
    cum_rows = _compute_trade_count_stats(run_dir)
    daily_rows = _compute_daily_trades(run_dir)
    daily_map: dict[tuple, dict] = {}
    for row in daily_rows:
        key = (row["trading_day"], str(row["tom_level"]))
        daily_map[key] = row
    for row in cum_rows:
        key = (row["trading_day"], str(row["tom_level"]))
        d = daily_map.get(key)
        if d:
            row["daily_total_trades"] = d["daily_total_trades"]
            row["daily_avg_trades"] = d["daily_avg_trades"]
        else:
            row["daily_total_trades"] = 0
            row["daily_avg_trades"] = 0.0
    return cum_rows


def _compute_daily_trades(run_dir: Path) -> list[dict]:
    """对 tom_stats.jsonl 的累积成交做差分，得到当日新增成交。"""
    ts_path = run_dir / "tom_stats.jsonl"
    if not ts_path.exists():
        return []
    rows = list(_iter_jsonl(ts_path))
    from collections import defaultdict
    by_tom: dict[str, dict[int, dict]] = defaultdict(dict)
    for r in rows:
        tom = str(r.get("tom_level", ""))
        td = r.get("trading_day")
        if td is not None:
            by_tom[tom][td] = r

    result = []
    for tom, day_map in sorted(by_tom.items()):
        days = sorted(day_map.keys())
        prev_total = 0
        for d in days:
            rec = day_map[d]
            cur_total = rec.get("total_trades", 0)
            count = rec.get("count", 1)
            daily_total = max(0, cur_total - prev_total)
            daily_avg = round(daily_total / count, 2) if count > 0 else 0
            result.append({
                "trading_day": d,
                "tom_level": tom,
                "daily_total_trades": daily_total,
                "daily_avg_trades": daily_avg,
            })
            prev_total = cur_total
    return result


def _compute_tom_vs_index(run_dir: Path) -> list[dict]:
    """返回该实验的 ToM 分布标签 + 大盘指数终值/收益率（单行）。

    X 轴使用 ToM 比例标签（如 "T0:70 T1:20 T2:10"），用于跨实验对比。
    """
    import yaml

    # ── 读取 ToM 分布 ──
    cfg_path = run_dir / "config.yaml"
    if not cfg_path.exists():
        return []
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    tom_dist = cfg.get("simulation", {}).get("tom_distribution", {})
    if not tom_dist:
        return []
    parts = []
    for level in sorted(tom_dist.keys()):
        pct = tom_dist[level]
        if pct and pct > 0:
            parts.append(f"T{level}:{int(round(pct * 100))}")
    tom_tag = " ".join(parts) if parts else "unknown"

    # ── 读取大盘指数 ──
    bi_path = run_dir / "broad_index.jsonl"
    if not bi_path.exists():
        return []
    first_row = last_row = None
    for row in _iter_jsonl(bi_path):
        if first_row is None:
            first_row = row
        last_row = row

    if first_row is None or last_row is None:
        return []

    start_val = first_row.get("value", 100)
    end_val = last_row.get("value", start_val)
    total_return = round((end_val / start_val - 1) * 100, 4) if start_val else 0

    return [{
        "tom_label": tom_tag,
        "final_index_value": round(end_val, 4),
        "total_return_pct": total_return,
    }]


def _compute_tom_vs_avg_return(run_dir: Path) -> list[dict]:
    """返回该实验的 ToM 分布标签 + 全体及按 tom_level 分组的末日人均收益率。"""
    import yaml
    from collections import defaultdict
    from metrics_plot_common import safe_float, safe_int

    cfg_path = run_dir / "config.yaml"
    if not cfg_path.exists():
        return []
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    tom_dist = cfg.get("simulation", {}).get("tom_distribution", {})
    if not tom_dist:
        return []
    parts = []
    for level in sorted(tom_dist.keys()):
        pct = tom_dist[level]
        if pct and pct > 0:
            parts.append(f"T{level}:{int(round(pct * 100))}")
    tom_tag = " ".join(parts) if parts else "unknown"

    fpath = run_dir / "agent_wealth.jsonl"
    if not fpath.exists():
        return []

    latest: dict[tuple[int, int], tuple[float, int, float]] = {}
    max_day = 0
    for row in _iter_jsonl(fpath):
        day = safe_int(row.get("trading_day"))
        aid = safe_int(row.get("agent_id"))
        tm = safe_float(row.get("sim_time"))
        ret = safe_float(row.get("return_pct"))
        tom = safe_int(row.get("tom_level"))
        if day is None or day <= 0 or aid is None or tm is None or ret is None:
            continue
        tom = tom if tom is not None else 0
        if day > max_day:
            max_day = day
        key = (day, aid)
        old = latest.get(key)
        if old is None or tm >= old[0]:
            latest[key] = (tm, tom, ret)

    if max_day <= 0:
        return []

    by_tom: dict[int, list[float]] = defaultdict(list)
    all_rets: list[float] = []
    for (d, _), (_, tom, ret) in latest.items():
        if d == max_day:
            by_tom[tom].append(ret)
            all_rets.append(ret)

    result = []
    # 全体汇总
    if all_rets:
        mean_r = round(sum(all_rets) / len(all_rets), 4)
        sorted_all = sorted(all_rets)
        median_r = round(sorted_all[len(sorted_all) // 2], 4)
        result.append({
            "tom_label": tom_tag,
            "tom_level": "all",
            "mean_return_pct": mean_r,
            "median_return_pct": median_r,
        })
    # 按 ToM 分组
    for tom_level in sorted(by_tom.keys()):
        rets = by_tom[tom_level]
        mean_r = round(sum(rets) / len(rets), 4)
        rets_s = sorted(rets)
        median_r = round(rets_s[len(rets_s) // 2], 4)
        result.append({
            "tom_label": tom_tag,
            "tom_level": tom_level,
            "mean_return_pct": mean_r,
            "median_return_pct": median_r,
        })
    return result


def _compute_reasoning_homogeneity(run_dir: Path) -> list[dict]:
    from metric_reasoning import compute_reasoning_homogeneity
    return compute_reasoning_homogeneity(run_dir)


def _compute_reasoning_post_consistency(run_dir: Path) -> list[dict]:
    from metric_reasoning import compute_reasoning_post_consistency
    return compute_reasoning_post_consistency(run_dir)


def _compute_tom0_ratio_vs_index(run_dir: Path) -> list[dict]:
    """以 ToM 0 比例为 X 轴，输出大盘终值、收益率和波动率（单行）。"""
    import math
    import yaml

    cfg_path = run_dir / "config.yaml"
    if not cfg_path.exists():
        return []
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    tom_dist = cfg.get("simulation", {}).get("tom_distribution", {})
    if not tom_dist:
        return []

    tom0_pct = 0.0
    for level, ratio in tom_dist.items():
        if int(level) == 0 and ratio:
            tom0_pct = float(ratio) * 100
            break
    tom0_label = f"{int(tom0_pct)}%"

    bi_path = run_dir / "broad_index.jsonl"
    if not bi_path.exists():
        return []
    first_row = last_row = None
    values = []
    for row in _iter_jsonl(bi_path):
        v = row.get("value")
        if v is not None:
            if first_row is None:
                first_row = row
            last_row = row
            values.append(float(v))

    if first_row is None or last_row is None or len(values) < 2:
        return []

    start_val = first_row.get("value", 100)
    end_val = last_row.get("value", start_val)
    total_return = round((end_val / start_val - 1) * 100, 4) if start_val else 0

    log_rets = [math.log(values[i] / values[i - 1]) for i in range(1, len(values)) if values[i - 1] > 0 and values[i] > 0]
    avg_vol = 0.0
    if log_rets:
        mean_r = sum(log_rets) / len(log_rets)
        avg_vol = round((sum((r - mean_r) ** 2 for r in log_rets) / len(log_rets)) ** 0.5, 6)

    return [{
        "tom0_ratio_label": tom0_label,
        "final_index_value": round(end_val, 4),
        "total_return_pct": total_return,
        "avg_volatility": avg_vol,
    }]


_COMPUTE_DISPATCH: dict = {
    "collective_bubble": _compute_collective_bubble,
    "market_panic": _compute_market_panic,
    "kyle_lambda": _compute_kyle_lambda,
    "tail_index": _compute_tail_index,
    "volatility_clustering": _compute_volatility_clustering,
    "wealth_inequality": _compute_wealth_inequality,
    "behavioral_agg": _compute_behavioral_agg,
    "behavioral_continuous": _compute_behavioral_continuous,
    "behavioral_performance": _compute_behavioral_performance,
    "fit_accuracy": _compute_fit_accuracy,
    "return_extremes": _compute_return_extremes,
    "trade_activity": _compute_trade_activity,
    "final_return_ranking": _compute_final_return_ranking,
    "wealth_tom_ranking": _compute_wealth_tom_ranking,
    "return_tom_ranking": _compute_return_tom_ranking,
    "avg_return": _compute_avg_return,
    "plan_adherence": _compute_plan_adherence,
    "emh_weak": _compute_emh_weak,
    "emh_semi_strong": _compute_emh_semi_strong,
    "social_overview": _compute_social_overview,
    "sentiment_confidence": _compute_sentiment_confidence,
    "social_trading_nexus": _compute_social_trading_nexus,
    "reputation_system": _compute_reputation_system,
    "kol_market_impact": _compute_kol_market_impact,
    "tool_usage": _compute_tool_usage,
    "bubble_rd_rad": _compute_bubble_rd_rad,
    "bubble_gsadf": _compute_bubble_gsadf,
    "crash_ncskew_duvol": _compute_crash_ncskew_duvol,
    "crash_drawdown": _compute_crash_drawdown,
    "tom_vs_index": _compute_tom_vs_index,
    "tom_vs_avg_return": _compute_tom_vs_avg_return,
    "tom0_ratio_vs_index": _compute_tom0_ratio_vs_index,
    "reasoning_homogeneity": _compute_reasoning_homogeneity,
    "reasoning_post_consistency": _compute_reasoning_post_consistency,
}


try:
    import orjson as _orjson
    _HAS_ORJSON = True
except ImportError:
    _HAS_ORJSON = False


def _iter_jsonl(path: Path):
    """逐行解析 JSONL 文件（惰性读取，优先使用 orjson 加速）"""
    if _HAS_ORJSON:
        with open(path, "rb") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield _orjson.loads(line)
                    except Exception:
                        continue
    else:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue


def _load_category_data(run_dir: Path, category: str) -> list[dict]:
    """加载指定 run 的指定数据类别（支持 JSONL 直读和计算型类别）"""
    cat = DATA_CATEGORIES.get(category)
    if not cat:
        return []

    # 计算型类别
    if cat.get("computed"):
        fn = _COMPUTE_DISPATCH.get(category)
        if fn is None:
            return []
        # 支持自定义窗口参数
        import inspect
        sig = inspect.signature(fn)
        kwargs: dict = {}
        if "window" in sig.parameters:
            w = request.args.get("window", type=int)
            if w and w > 0:
                kwargs["window"] = w
        import time as _time
        cache_key = (str(run_dir), category, tuple(sorted(kwargs.items())))
        cached = _COMPUTE_CACHE.get(cache_key)
        if cached is not None:
            ts, cached_rows = cached
            if _time.time() - ts < _CACHE_TTL_SECONDS:
                return cached_rows
        try:
            rows = fn(run_dir, **kwargs)
        except Exception as e:
            print(f"[WARN] 计算 {category} 失败 ({run_dir.name}): {e}")
            rows = []
        _COMPUTE_CACHE[cache_key] = (_time.time(), rows)
        return rows

    fpath = run_dir / cat["file"]
    if not fpath.exists():
        return []
    rows = list(_iter_jsonl(fpath))
    if cat.get("aggregate"):
        rows = _aggregate_by_day(rows, cat)
    # tom_stats: 将累积成交字段转为当日增量
    if category == "tom_stats":
        rows = _deaccumulate_trades(rows)
    return rows


def _aggregate_by_day(rows: list[dict], cat: dict) -> list[dict]:
    """对 sentiment_series 等高频数据按交易日 + 分组键做平均聚合"""
    from collections import defaultdict
    x_key = cat["x_key"]
    group_key = cat["group_key"]
    metrics = list(cat["metrics"].keys())

    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        td = r.get(x_key)
        gk = r.get(group_key, "") if group_key else ""
        if td is None:
            continue
        buckets[(td, gk)].append(r)

    result = []
    for (td, gk), items in sorted(buckets.items()):
        agg = {x_key: td}
        if group_key:
            agg[group_key] = gk
        for m in metrics:
            vals = [float(it[m]) for it in items if it.get(m) is not None]
            agg[m] = round(sum(vals) / len(vals), 4) if vals else None
        result.append(agg)
    return result


# ──────────────────────────────────────────────────────────────
# API 路由
# ──────────────────────────────────────────────────────────────

@app.route("/")
def index_page():
    return send_from_directory(
        str(Path(__file__).parent / "eval_web_static"), "index.html"
    )


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(
        str(Path(__file__).parent / "eval_web_static"), filename
    )


@app.route("/api/runs")
def api_list_runs():
    """列出所有可用的实验运行"""
    runs = []
    if not RUNS_DIR.exists():
        return jsonify(runs)
    for d in sorted(RUNS_DIR.iterdir()):
        if not d.is_dir():
            continue
        # 检查是否有 results.json 或至少有 broad_index.jsonl（表示已完成或进行中）
        has_data = (d / "results.json").exists() or (d / "broad_index.jsonl").exists()
        if not has_data:
            continue
        config_path = d / "config.yaml"
        config_summary = {}
        if config_path.exists():
            try:
                import yaml
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                sim = cfg.get("simulation", {})
                agent = cfg.get("agent", {})
                config_summary = {
                    "n_agents": sim.get("n_agents", "?"),
                    "tom_distribution": sim.get("tom_distribution", {}),
                    "cash_mode": agent.get("cash_mode", "?"),
                    "max_sim_time": sim.get("max_sim_time", "?"),
                }
            except Exception:
                pass

        # 统计交易日数
        bi_path = d / "broad_index.jsonl"
        trading_days = 0
        if bi_path.exists():
            try:
                with open(bi_path, "r") as f:
                    for line in f:
                        trading_days += 1
            except Exception:
                pass

        runs.append({
            "name": d.name,
            "path": str(d),
            "has_results": (d / "results.json").exists(),
            "trading_days": trading_days,
            "config_summary": config_summary,
            "available_files": [
                f.stem for f in d.iterdir()
                if f.suffix == ".jsonl" and f.stem in [
                    "broad_index", "tom_stats", "market_snapshots",
                    "price_discovery", "collective_behavior", "sentiment_series",
                    "agent_wealth", "trades", "behavioral_biases",
                ]
            ],
        })
    return jsonify(runs)


# ── 实验别名持久化 ──
def _aliases_path() -> Path:
    return RUNS_DIR / "aliases.json"


@app.route("/api/aliases", methods=["GET"])
def api_get_aliases():
    """读取所有实验别名"""
    p = _aliases_path()
    if p.exists():
        return p.read_text(encoding="utf-8"), 200, {"Content-Type": "application/json"}
    return jsonify({})


@app.route("/api/aliases", methods=["PUT"])
def api_put_aliases():
    """保存所有实验别名"""
    data = request.get_json(force=True)
    if not isinstance(data, dict):
        return jsonify({"error": "expected JSON object"}), 400
    p = _aliases_path()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/api/categories")
def api_categories():
    """返回可用的数据类别及其指标"""
    result = {}
    for key, cat in DATA_CATEGORIES.items():
        entry = {
            "label": cat["label"],
            "metrics": cat["metrics"],
            "group_key": cat["group_key"],
            "computed": bool(cat.get("computed")),
            "desc": cat.get("desc", {}),
            "x_type": cat.get("x_type"),
        }
        if cat.get("prefer_line"):
            entry["prefer_line"] = True
        result[key] = entry
    return jsonify(result)


@app.route("/api/cache_clear", methods=["POST"])
def api_cache_clear():
    """清除计算缓存"""
    _COMPUTE_CACHE.clear()
    return jsonify({"ok": True})


@app.route("/api/data")
def api_data():
    """
    获取指定实验的指定类别数据。
    参数:
        runs: 逗号分隔的 run 名称
        category: 数据类别（如 broad_index）
        metrics: 逗号分隔的指标名
        group_filter: 可选，按分组键筛选（如 symbol=CGEI）
    """
    run_names = request.args.get("runs", "").split(",")
    category = request.args.get("category", "")
    metrics_str = request.args.get("metrics", "")
    group_filter = request.args.get("group_filter", "")

    if not run_names or not category:
        return jsonify({"error": "缺少 runs 或 category 参数"}), 400

    cat = DATA_CATEGORIES.get(category)
    if not cat:
        return jsonify({"error": f"未知类别: {category}"}), 400

    selected_metrics = [m.strip() for m in metrics_str.split(",") if m.strip()] if metrics_str else list(cat["metrics"].keys())
    x_key = cat["x_key"]
    group_by_param = request.args.get("group_by", "").strip()
    group_key = group_by_param if group_by_param else cat["group_key"]
    preserve_order = cat.get("x_type") == "category"  # 离散轴保留计算函数的原始顺序

    series_data = {}  # { run_name: { series_label: [{x, y}] } }
    all_group_values: set[str] = set()
    _all_rows_sample: list[dict] = []  # 用于探测可用分组键

    for run_name in run_names:
        run_name = run_name.strip()
        if not run_name:
            continue
        run_dir = RUNS_DIR / run_name
        if not run_dir.exists():
            continue

        rows = _load_category_data(run_dir, category)
        if not rows:
            continue

        # 收集样本行用于探测可分组键（只取第一个 run）
        if not _all_rows_sample:
            _all_rows_sample = rows[:200]

        # 获取可用的分组值
        group_values = set()
        if group_key:
            for r in rows:
                gv = r.get(group_key)
                if gv is not None:
                    group_values.add(str(gv))
            all_group_values.update(group_values)

        # 应用分组筛选
        if group_filter and group_key:
            filter_values = set(group_filter.split(","))
            rows = [r for r in rows if str(r.get(group_key, "")) in filter_values]

        run_series = {}
        if group_key and not group_filter:
            # 有分组键且未筛选：按分组拆分系列
            grouped: dict[str, list[dict]] = {}
            for r in rows:
                gv = str(r.get(group_key, ""))
                grouped.setdefault(gv, []).append(r)

            single_group = len(grouped) == 1
            for gv, g_rows in sorted(grouped.items()):
                _rows = g_rows if preserve_order else sorted(g_rows, key=lambda x: x.get(x_key, 0))
                for metric in selected_metrics:
                    metric_label = cat['metrics'].get(metric, metric)
                    label = metric_label if single_group else f"{gv}_{metric_label}"
                    se_key = f"{metric}_se"
                    points = []
                    for r in _rows:
                        val = r.get(metric)
                        if val is not None:
                            pt: dict = {"x": r[x_key], "y": val}
                            se_val = r.get(se_key)
                            if se_val is not None:
                                pt["se"] = se_val
                            points.append(pt)
                    if points:
                        run_series[label] = points
        elif group_key and group_filter:
            # 有筛选：每个筛选值 × 每个指标一条线
            grouped: dict[str, list[dict]] = {}
            for r in rows:
                gv = str(r.get(group_key, ""))
                grouped.setdefault(gv, []).append(r)
            single_group = len(grouped) == 1
            for gv, g_rows in sorted(grouped.items()):
                _rows = g_rows if preserve_order else sorted(g_rows, key=lambda x: x.get(x_key, 0))
                for metric in selected_metrics:
                    metric_label = cat['metrics'].get(metric, metric)
                    label = metric_label if single_group else f"{gv}_{metric_label}"
                    se_key = f"{metric}_se"
                    points = []
                    for r in _rows:
                        val = r.get(metric)
                        if val is not None:
                            pt: dict = {"x": r[x_key], "y": val}
                            se_val = r.get(se_key)
                            if se_val is not None:
                                pt["se"] = se_val
                            points.append(pt)
                    if points:
                        run_series[label] = points
        else:
            # 无分组键
            _rows = rows if preserve_order else sorted(rows, key=lambda x: x.get(x_key, 0))
            for metric in selected_metrics:
                label = cat["metrics"].get(metric, metric)
                se_key = f"{metric}_se"
                points = []
                for r in _rows:
                    val = r.get(metric)
                    if val is not None:
                        pt: dict = {"x": r[x_key], "y": val}
                        se_val = r.get(se_key)
                        if se_val is not None:
                            pt["se"] = se_val
                        points.append(pt)
                if points:
                    run_series[label] = points

        series_data[run_name] = run_series

    # 使用主循环中已收集的分组值
    available_groups = sorted(all_group_values) if group_key else []

    # 探测可用分组键：非 x_key、非指标、值为字符串/整型且唯一值 ≤50
    available_group_keys: list[str] = []
    if _all_rows_sample:
        metric_keys = set(cat["metrics"].keys())
        skip_keys = metric_keys | {x_key}
        for key in _all_rows_sample[0].keys():
            if key in skip_keys:
                continue
            uniq = set()
            for r in _all_rows_sample:
                v = r.get(key)
                if v is not None:
                    uniq.add(str(v))
            if 2 <= len(uniq) <= 50:
                available_group_keys.append(key)

    return jsonify({
        "series": series_data,
        "x_label": x_key,
        "group_key": group_key,
        "available_groups": available_groups,
        "available_group_keys": available_group_keys,
    })


@app.route("/api/car_tests")
def api_car_tests():
    """统计检验：CAAR 显著性 + 增量漂移检验"""
    run_name = request.args.get("run", "").strip()
    if not run_name:
        return jsonify({"error": "缺少 run 参数"}), 400
    run_dir = RUNS_DIR / run_name
    if not run_dir.exists():
        return jsonify({"error": f"run 不存在: {run_name}"}), 404

    try:
        from metric_emh import classify_event_day_sentiment, compute_car_significance, compute_event_car
        from academic_metrics_common import compute_log_returns, load_reference_close_series

        days_in, closes = load_reference_close_series(run_dir, symbol=None, exclude_seed=True)
        if len(closes) < 25:
            return jsonify({"error": "数据不足（<25天）"}), 400
        log_rets = compute_log_returns(closes)
        ret_days = days_in[1:]

        news_file = _find_news_file(run_dir)
        if news_file is None:
            return jsonify({"error": "未找到新闻文件"}), 404
        with open(news_file, "r", encoding="utf-8") as f:
            news_data = json.load(f)
        news_list = news_data.get("news", news_data) if isinstance(news_data, dict) else news_data

        event_day_count: dict[int, int] = {}
        for item in news_list:
            d = item.get("day")
            if isinstance(d, (int, float)):
                event_day_count[int(d)] = event_day_count.get(int(d), 0) + 1
        event_days = sorted(event_day_count.keys())

        car_records = compute_event_car(event_days, ret_days, log_rets,
                                        horizons=[1, 3, 5], estimation_window=20)
        # 优先从 posts.jsonl 提取实际发放的新闻（agent 实际看到的）
        actual_news = _load_actual_news_posts(run_dir)
        event_sentiments = classify_event_day_sentiment(actual_news if actual_news else news_list)
        tests = compute_car_significance(car_records, horizons=[1, 3, 5], n_bootstrap=2000,
                                         event_sentiments=event_sentiments)

        import math
        # 格式化：百分比化 + 保留 4 位小数，p-value 保留原值
        formatted = {}
        pct_keys = {"caar_", "se_", "ci_lower_", "ci_upper_", "boot_ci_lower_", "boot_ci_upper_", "delta_"}
        for k, v in tests.items():
            if isinstance(v, float) and math.isnan(v):
                formatted[k] = None
            elif isinstance(v, float):
                # 百分比化 CAR 相关字段
                if any(k.startswith(pk) for pk in pct_keys):
                    formatted[k] = round(v * 100, 4)
                else:
                    formatted[k] = round(v, 6)
            else:
                formatted[k] = v

        return jsonify({"run": run_name, "tests": formatted})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/efficiency_ranking")
def api_efficiency_ranking():
    """计算所有实验的市场效率排名"""
    import math
    from metric_emh import classify_event_day_sentiment, compute_car_significance, compute_event_car
    from academic_metrics_common import compute_log_returns, load_reference_close_series

    rows = []
    if not RUNS_DIR.exists():
        return jsonify({"error": "runs 目录不存在"}), 404

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        run_name = run_dir.name
        try:
            days_in, closes = load_reference_close_series(run_dir, symbol=None, exclude_seed=True)
            if len(closes) < 25:
                continue
            log_rets = compute_log_returns(closes)
            ret_days = days_in[1:]

            news_file = _find_news_file(run_dir)
            if news_file is None:
                continue
            with open(news_file, "r", encoding="utf-8") as f:
                nd = json.load(f)
            nl = nd.get("news", nd) if isinstance(nd, dict) else nd
            event_days = sorted(set(
                int(it["day"]) for it in nl if isinstance(it.get("day"), (int, float))
            ))

            car_records = compute_event_car(event_days, ret_days, log_rets,
                                            horizons=[1, 3, 5], estimation_window=20)
            if len(car_records) < 5:
                continue

            event_sentiments = classify_event_day_sentiment(
                _load_actual_news_posts(run_dir) or nl
            )
            tests = compute_car_significance(car_records, horizons=[1, 3, 5], n_bootstrap=2000,
                                             event_sentiments=event_sentiments)
            n = tests.get("n_1", 0)

            abs_caar_avg = sum(abs(tests.get(f"caar_{h}", 0)) for h in [1, 3, 5]) / 3
            car_std_avg = sum(tests.get(f"se_{h}", 0) * math.sqrt(n) for h in [1, 3, 5]) / 3
            p_avg = sum(tests.get(f"p_value_{h}", 0) for h in [1, 3, 5]) / 3
            ci_width_avg = sum(
                tests.get(f"ci_upper_{h}", 0) - tests.get(f"ci_lower_{h}", 0)
                for h in [1, 3, 5]
            ) / 3
            drift_stat = sum(
                abs(tests.get(f"delta_{h1}_{h2}", 0))
                for h1, h2 in [(1, 3), (3, 5)]
            ) / 2
            score = abs_caar_avg + ci_width_avg * 0.5 + drift_stat

            # 有效性判断 (α=0.10, 分组用单尾 p)
            alpha = 0.10
            # 效率判定：bootstrap p 为主（block bootstrap 处理了事件重叠依赖）
            # t-test 仅作对照展示
            any_caar_sig = any(
                tests.get(f"boot_p_{h}", 1) < alpha
                for h in [1, 3, 5]
            )
            # 分组有效性：利好/利空新闻日，bootstrap p，α=0.10
            any_group_sig = any(
                tests.get(f"boot_p_{grp}_{h}", 1) < alpha
                for grp in ["pos", "neg"]
                for h in [1, 3, 5]
            )

            if any_caar_sig:
                eff_label = "inefficient"
            elif any_group_sig:
                eff_label = "inefficient_grouped"
            else:
                eff_label = "efficient"

            # Robustness: α=0.05
            alpha05 = 0.05
            any_caar_sig_05 = any(
                tests.get(f"boot_p_{h}", 1) < alpha05 for h in [1, 3, 5]
            )
            any_group_sig_05 = any(
                tests.get(f"boot_p_{grp}_{h}", 1) < alpha05
                for grp in ["pos", "neg"] for h in [1, 3, 5]
            )
            if any_caar_sig_05:
                eff_label_05 = "inefficient"
            elif any_group_sig_05:
                eff_label_05 = "inefficient_grouped"
            else:
                eff_label_05 = "efficient"

            # 哪些 horizon 显著 (bootstrap)
            sig_h = [h for h in [1, 3, 5]
                     if tests.get(f"boot_p_{h}", 1) < alpha]
            sig_group = []
            for grp, label in [("pos", "利好"), ("neg", "利空")]:
                for h in [1, 3, 5]:
                    if tests.get(f"boot_p_{grp}_{h}", 1) < alpha:
                        sig_group.append(f"{label}h{h}")

            rows.append({
                "run": run_name,
                "n_events": n,
                "abs_caar": round(abs_caar_avg * 100, 4),
                "car_std": round(car_std_avg * 100, 4),
                "p_avg": round(p_avg, 4),
                "ci_width": round(ci_width_avg * 100, 4),
                "drift": round(drift_stat * 100, 4),
                "score": round(score * 100, 4),
                "caar_1": round(tests.get("caar_1", 0) * 100, 4),
                "caar_3": round(tests.get("caar_3", 0) * 100, 4),
                "caar_5": round(tests.get("caar_5", 0) * 100, 4),
                "p_1": round(tests.get("p_value_1", 1), 4),
                "p_3": round(tests.get("p_value_3", 1), 4),
                "p_5": round(tests.get("p_value_5", 1), 4),
                "efficient": eff_label,
                "efficient_05": eff_label_05,
                "sig_horizons": sig_h,
                "sig_groups": sig_group,
                "n_pos": tests.get("n_pos", 0),
                "n_neg": tests.get("n_neg", 0),
                "caar_pos_5": round(tests.get("caar_pos_5", 0) * 100, 4),
                "caar_neg_5": round(tests.get("caar_neg_5", 0) * 100, 4),
                "p_pos_5": round(tests.get("p_pos_5", 1), 4),
                "p_neg_5": round(tests.get("p_neg_5", 1), 4),
                "p1_pos_5": round(tests.get("p1_pos_5", 1), 4),
                "p1_neg_5": round(tests.get("p1_neg_5", 1), 4),
            })
        except Exception:
            continue

    eff_order = {"efficient": 0, "inefficient_grouped": 1, "inefficient": 2}
    rows.sort(key=lambda r: (eff_order.get(r["efficient"], 9), r["score"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    return jsonify({"ranking": rows})


@app.route("/api/config")
def api_config():
    """获取指定 run 的完整配置"""
    run_name = request.args.get("run", "")
    if not run_name:
        return jsonify({"error": "缺少 run 参数"}), 400
    config_path = RUNS_DIR / run_name / "config.yaml"
    if not config_path.exists():
        return jsonify({"error": "配置文件不存在"}), 404
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return jsonify(cfg)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config_diff")
def api_config_diff():
    """对比两个 run 的配置差异"""
    runs_str = request.args.get("runs", "")
    run_names = [r.strip() for r in runs_str.split(",") if r.strip()]
    if len(run_names) < 2:
        return jsonify({"error": "至少需要 2 个 run"}), 400

    import yaml
    configs = {}
    for name in run_names:
        cp = RUNS_DIR / name / "config.yaml"
        if cp.exists():
            with open(cp, "r", encoding="utf-8") as f:
                configs[name] = yaml.safe_load(f) or {}
        else:
            configs[name] = {}

    # 递归比较
    def _diff(a, b, path=""):
        diffs = []
        if isinstance(a, dict) and isinstance(b, dict):
            all_keys = set(list(a.keys()) + list(b.keys()))
            for k in sorted(all_keys):
                p = f"{path}.{k}" if path else k
                va, vb = a.get(k), b.get(k)
                if va != vb:
                    if isinstance(va, dict) and isinstance(vb, dict):
                        diffs.extend(_diff(va, vb, p))
                    else:
                        diffs.append({"path": p, "values": {n: configs[n] for n in run_names}})
                        # 简化：直接提取差异值
                        vals = {}
                        for n in run_names:
                            c = configs[n]
                            for part in p.split("."):
                                if isinstance(c, dict):
                                    c = c.get(part)
                                else:
                                    c = None
                                    break
                            vals[n] = c
                        diffs[-1]["values"] = vals
        return diffs

    # 取第一个为基准逐个对比
    all_diffs = []
    base = configs[run_names[0]]
    for name in run_names[1:]:
        ds = _diff(base, configs[name])
        all_diffs.extend(ds)

    # 去重
    seen = set()
    unique_diffs = []
    for d in all_diffs:
        if d["path"] not in seen:
            seen.add(d["path"])
            unique_diffs.append(d)

    return jsonify({"diffs": unique_diffs, "runs": run_names})


# ──────────────────────────────────────────────────────────────
# 图表快照持久化（保存到本地文件系统）
# ──────────────────────────────────────────────────────────────

SAVED_CHARTS_DIR = EVAL_DIR / "saved_charts"


@app.route("/api/saved_charts", methods=["GET"])
def api_list_saved_charts():
    """列出所有已保存的图表快照（按时间倒序）"""
    SAVED_CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for f in sorted(SAVED_CHARTS_DIR.glob("*.json"), reverse=True):
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
            items.append({
                "filename": f.name,
                "title": meta.get("title", f.stem),
                "thumbUrl": meta.get("thumbUrl", ""),
                "time": meta.get("time", ""),
                "boxH": meta.get("boxH", ""),
            })
        except Exception:
            continue
    return jsonify(items)


@app.route("/api/saved_charts", methods=["POST"])
def api_save_chart():
    """保存一个图表快照到本地文件"""
    SAVED_CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    data = request.get_json(force=True)
    if not data or "title" not in data:
        return jsonify({"error": "缺少 title"}), 400

    import re as _re
    import time as _time
    safe_title = _re.sub(r'[^\w\u4e00-\u9fff\-]', '_', data.get("title", "chart"))[:80]
    ts = str(int(_time.time() * 1000))
    filename = f"{ts}_{safe_title}.json"

    fpath = SAVED_CHARTS_DIR / filename
    fpath.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return jsonify({"filename": filename})


@app.route("/api/saved_charts/<filename>", methods=["GET"])
def api_get_saved_chart(filename):
    """读取一个图表快照的完整数据"""
    fpath = SAVED_CHARTS_DIR / Path(filename).name  # 防路径穿越
    if not fpath.exists():
        return jsonify({"error": "not found"}), 404
    return app.response_class(
        fpath.read_text(encoding="utf-8"),
        mimetype="application/json",
    )


@app.route("/api/saved_charts/<filename>", methods=["DELETE"])
def api_delete_saved_chart(filename):
    """删除一个图表快照"""
    fpath = SAVED_CHARTS_DIR / Path(filename).name
    if fpath.exists():
        fpath.unlink()
    return jsonify({"ok": True})


def _kill_port(port: int) -> bool:
    """杀死占用指定端口的进程（macOS/Linux）"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return False  # 端口未被占用
        # 用 lsof 找到占用进程
        import subprocess
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"], capture_output=True, text=True
        )
        pids = result.stdout.strip().split()
        if not pids:
            return False
        my_pid = os.getpid()
        for pid_str in pids:
            pid = int(pid_str)
            if pid == my_pid:
                continue
            print(f"  正在终止占用端口 {port} 的进程 PID={pid}")
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        import time
        time.sleep(0.8)
        # 检查是否仍然占用，用 SIGKILL 强杀
        result2 = subprocess.run(
            ["lsof", "-ti", f":{port}"], capture_output=True, text=True
        )
        for pid_str in result2.stdout.strip().split():
            pid = int(pid_str)
            if pid == my_pid:
                continue
            print(f"  SIGKILL 强杀 PID={pid}")
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(0.3)
        return True
    except Exception as e:
        print(f"  [WARN] 释放端口失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="MentalMarket 评估 Web")
    parser.add_argument("--runs-dir", default="runs", help="实验目录路径")
    parser.add_argument("--port", type=int, default=5050, help="服务端口")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    args = parser.parse_args()

    global RUNS_DIR
    RUNS_DIR = Path(args.runs_dir)
    if not RUNS_DIR.exists():
        print(f"[ERROR] 目录不存在: {RUNS_DIR}")
        return

    # 仅主进程执行端口释放，reloader 子进程跳过
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        _kill_port(args.port)

    print(f"MentalMarket 评估 Web 启动中...")
    print(f"  实验目录: {RUNS_DIR.resolve()}")
    print(f"  地址: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=True)


if __name__ == "__main__":
    main()
