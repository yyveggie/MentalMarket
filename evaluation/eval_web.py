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
            "avg_return_pct": "平均收益率(%)",
            "avg_pnl": "平均盈亏",
            "total_trades": "总成交笔数",
            "avg_trades_per_agent": "人均成交笔数",
            "positive_return_ratio": "正收益比例",
            "gini_coefficient": "基尼系数",
            "top10_wealth_share": "Top10%财富占比",
        },
        "group_key": "tom_level",
        "desc": {
            "avg_wealth": "该 ToM 层级所有智能体的平均总资产（现金+持仓市值）。↑群体整体获利 ↓亏损",
            "median_wealth": "排序后居中智能体的资产，比均值更抗极端值干扰。与 avg_wealth 差距大说明分化严重",
            "total_wealth": "该层级全部资产总和。反映群体资金体量",
            "avg_return_pct": "平均收益率。正=群体盈利，负=亏损",
            "avg_pnl": "平均已实现+未实现盈亏绝对值",
            "total_trades": "该层级当日总成交笔数。↑交易活跃 ↓偏保守",
            "avg_trades_per_agent": "人均成交。↑交易行为频繁 ↓倾向持有",
            "positive_return_ratio": "收益率>0 的智能体占比。↑多数盈利 ↓多数亏损",
            "gini_coefficient": "财富不平等程度，0=完全均等，1=极度不等。↑贫富分化 ↓较均匀",
            "top10_wealth_share": "最富 10% 智能体占全组财富的比例。↑财富集中 ↓分散",
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
            "volatility": "波动率",
            "spread": "买卖价差",
            "price_deviation_pct": "价格偏离(%)",
        },
        "group_key": "symbol",
        "desc": {
            "last_price": "当日收盘价",
            "volume": "当日总成交股数。↑流动性好 ↓清淡",
            "trade_count": "当日成交笔数。↑交易活跃 ↓冷清",
            "turnover_rate": "成交量/流通股数。↑换手频繁 ↓持仓稳定",
            "buy_sell_ratio": "买单量/卖单量。>1 买方强势，<1 卖方强势",
            "vwap": "成交量加权平均价，反映当日真实成本",
            "volatility": "日内价格波动标准差。↑波动大、风险高 ↓平稳",
            "spread": "最优买卖报价之差。↑流动性差 ↓流动性好",
            "price_deviation_pct": "当前价格偏离基本面的百分比。↑高估 ↓低估",
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
            "extreme_ratio": "极端比例",
            "echo_chamber_index": "信息茧房指数",
            "homophily_excess": "同质性过剩",
        },
        "group_key": None,
        "desc": {
            "polarization_index": "群体观点分裂程度（0~1）。↑看多看空严重对立 ↓观点趋于一致",
            "extreme_ratio": "持极端观点智能体的比例。↑非理性情绪蔓延 ↓理性主导",
            "echo_chamber_index": "社交网络中同质化信息流通程度。↑信息茧房严重、确认偏差强 ↓信息多元",
            "homophily_excess": "超出随机基线的同质交互比例。↑圈层效应 ↓跨圈交流多",
        },
    },
    "collective_bubble": {
        "label": "泡沫检测",
        "file": "collective_behavior.jsonl",
        "x_key": "trading_day",
        "metrics": {
            "bubble_flag": "泡沫标记",
            "bubble_phase": "泡沫阶段",
            "avg_deviation_pct": "平均价格偏离(%)",
        },
        "group_key": None,
        "desc": {
            "bubble_flag": "是否处于泡沫状态（1=是，0=否）。根据价格偏离+信心双指标判定",
            "bubble_phase": "泡沫阶段编码：0=正常，1=形成，2=膨胀，3=破裂",
            "avg_deviation_pct": "平均价格偏离基本面幅度。↑整体定价偏差大 ↓定价合理",
        },
    },
    "collective_confidence": {
        "label": "群体信心",
        "file": "collective_behavior.jsonl",
        "x_key": "trading_day",
        "metrics": {
            "avg_confidence": "平均信心",
            "confidence_price_correlation": "信心-价格相关性",
        },
        "group_key": None,
        "desc": {
            "avg_confidence": "全市场平均信心水平。↑群体乐观 ↓悲观或不确定",
            "confidence_price_correlation": "信心与价格偏离的相关系数。高正值=信心推动泡沫，负值=信心与价格脱钩",
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
    "kyle_lambda": {
        "label": "📐 Kyle Lambda（价格冲击）",
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
        "label": "📊 厚尾指数（Hill）",
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
        "label": "📈 波动聚集（ACF）",
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
        "label": "💰 财富不平等",
        "x_key": "trading_day",
        "metrics": {
            "gini": "Gini 系数",
            "theil_t": "Theil-T 指数",
            "top1_share": "Top-1% 份额",
            "agent_count": "Agent 数量",
        },
        "group_key": None,
        "computed": True,
        "desc": {
            "gini": "基尼系数（0~1）。0=完全均等，1=一人独占。↑贫富差距扩大 ↓分配趋于均匀",
            "theil_t": "Theil-T 熵指数。对高财富端更敏感。↑富人越集中 ↓收入分散",
            "top1_share": "最富 1% 智能体占全体财富的比例。↑头部效应显著 ↓分散",
            "agent_count": "当日参与统计的智能体数量",
        },
    },
    "behavioral_agg": {
        "label": "🧠 行为偏差（占比指标）",
        "x_key": "trading_day",
        "metrics": {
            "disposition_pct": "处置效应(%)",
            "overconfidence_pct": "过度自信(%)",
            "underdiversified_pct": "分散不足(%)",
            "averaging_down_pct": "亏损加仓(%)",
            "loss_aversion_pct": "损失厌恶(%)",
            "herding_pct": "从众(%)",
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
            "herding_pct": "从众行为：与多数人同方向操作的比例。↑追涨杀跌 ↓独立决策",
            "loss_trading_pct": "亏损后高频交易：损失后次日大幅增加交易的比例。↑赌徒心态/急于翻本 ↓冷静",
            "positive_skew_pct": "彩票偏好：偏好正偏度（小概率大收益）标的的比例。↑投机倾向 ↓理性估值",
            "momentum_pct": "动量策略：顺趋势交易的比例。↑趋势跟随 ↓反转或无方向",
            "contrarian_pct": "反转策略：逆趋势交易的比例。↑逆向投资 ↓顺势为主",
        },
    },
    "behavioral_continuous": {
        "label": "🧠 行为偏差（连续指标）",
        "x_key": "trading_day",
        "metrics": {
            "avg_turnover": "平均换手率",
            "avg_hhi": "平均持仓 HHI",
            "avg_max_unrealized_loss": "平均最大浮亏(%)",
            "avg_lsv_herding": "平均 LSV 羊群强度",
            "avg_recent_skewness": "平均近期偏度",
            "avg_lambda_estimate": "平均 λ 损失厌恶系数",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "avg_turnover": "平均换手率。↑交易频繁、过度交易风险 ↓持仓稳定",
            "avg_hhi": "持仓集中度 HHI（0~1）。↑重仓少数标的 ↓分散持仓。>0.5 高度集中",
            "avg_max_unrealized_loss": "所持股票中最大浮亏幅度。↑有大幅套牢仓位 ↓浮亏可控",
            "avg_lsv_herding": "LSV 羊群强度指标。>0 表示交易方向与群体一致程度超过随机基准。↑从众程度高",
            "avg_recent_skewness": "近期交易标的收益偏度。正=偏好彩票型标的 负=偏好稳定收益",
            "avg_lambda_estimate": "Kahneman-Tversky λ 损失厌恶系数。>1 表示亏损痛苦大于同等盈利快乐。典型值 1.5~2.5",
        },
    },
    "behavioral_performance": {
        "label": "📊 行为绩效",
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
            "avg_de_odaan": "Odean (1998) 处置效应指数 = PGR - PLR。正=处置效应存在 负=反向处置",
            "avg_pgr": "盈利实现比例：卖出盈利头寸的频率/可卖出盈利头寸数。↑急于落袋为安",
            "avg_plr": "亏损实现比例：卖出亏损头寸的频率/可卖出亏损头寸数。↑愿意止损 ↓扛单",
            "avg_lambda": "群体平均 λ 损失厌恶系数。>1 厌恶损失，≈1 风险中性，<1 风险寻求",
            "realized_gain_pct": "当日已实现盈利的平均幅度总和。反映获利了结的力度",
            "realized_loss_pct": "当日已实现亏损的平均幅度总和。反映割肉力度",
            "agent_count": "当日有数据的智能体数量",
        },
    },
    "fit_accuracy": {
        "label": "🎯 拟合精度（expanding window）",
        "x_key": "trading_day",
        "metrics": {
            "same_day_acc": "同日方向准确率(%)",
            "forward1_acc": "前瞻1日准确率(%)",
            "fit_pct": "拟合度(%)",
            "r_squared": "R²",
        },
        "group_key": "symbol",
        "computed": True,
        "desc": {
            "same_day_acc": "模拟收益方向与真实收益方向一致的比例。>50% 表示模型有预测能力",
            "forward1_acc": "前一日模拟 vs 当日真实方向一致率。反映模型前瞻能力",
            "fit_pct": "模拟与真实价格曲线的拟合度。↑模拟越逼真 ↓偏差大",
            "r_squared": "归一化价格序列的 Pearson R²。衡量曲线形状相似度（0~1），越高越好",
        },
    },
    "fit_volatility": {
        "label": "📐 波动率拟合（QLIKE & Log-RMSE）",
        "x_key": "trading_day",
        "metrics": {
            "qlike": "QLIKE",
            "log_rmse": "Log-RMSE",
            "real_var": "真实方差",
            "sim_var": "模拟方差",
        },
        "group_key": "symbol",
        "computed": True,
        "desc": {
            "qlike": "QLIKE 损失函数：衡量模拟方差 vs 真实方差的偏差。↓越小拟合越好，=0 完美匹配",
            "log_rmse": "对数方差 RMSE：对波动率取对数后的均方根误差。↓越小拟合越好",
            "real_var": "当日真实收益率方差（基于指数收益率平方）",
            "sim_var": "当日模拟收益率方差（基于指数收益率平方）",
        },
    },
    "wealth_inequality_by_tom": {
        "label": "💰 财富不平等（按 ToM 分组）",
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
            "gini": "该 ToM 层级内部的基尼系数。可对比不同层级内部贫富差距",
            "theil_t": "层级内 Theil-T 指数。对比不同 ToM 的内部分化",
            "top1_share": "层级内最富 1% 的财富占比",
            "agent_count": "该层级智能体数量",
        },
    },
    "return_extremes": {
        "label": "🏆 Top/Bottom 10 收益率",
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
    "trade_count_stats": {
        "label": "📈 交易次数统计",
        "x_key": "trading_day",
        "metrics": {
            "total_trades": "总交易次数",
            "avg_trades": "平均交易次数",
            "median_trades": "中位数交易次数",
            "max_trades": "最大交易次数",
            "active_ratio": "活跃率(交易>0占比%)",
            "agent_count": "Agent 数量",
        },
        "group_key": "tom_level",
        "computed": True,
        "desc": {
            "total_trades": "该组当日总成交笔数。反映市场总活跃度",
            "avg_trades": "人均交易次数。↑交易频率高 ↓保守/观望",
            "median_trades": "中位数交易次数。与均值差距大说明少数人高频交易拉高均值",
            "max_trades": "交易最多的智能体当日交易次数。极端值反映最活跃个体",
            "active_ratio": "当日有交易的智能体占比。↑参与度高 ↓大量观望",
            "agent_count": "该组智能体总数",
        },
    },
    "final_return_ranking": {
        "label": "🏅 最终收益排名（Top/Bottom 10）",
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
    "plan_adherence": {
        "label": "📋 计划执行率（预测拟合实验）",
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
}

DATA_CATEGORIES.update(COMPUTED_CATEGORIES)

# 简单内存缓存: (run_name, category) -> rows
_COMPUTE_CACHE: dict[tuple[str, str], list[dict]] = {}


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
    from metric_wealth_inequality import build_daily_inequality
    days, gini, theil, top1, counts = build_daily_inequality(run_dir, tom_level=None)
    result = []
    for d, g, t, t1, c in zip(days, gini, theil, top1, counts):
        result.append({
            "trading_day": d,
            "gini": round(g, 4),
            "theil_t": round(t, 4),
            "top1_share": round(t1, 4),
            "agent_count": c,
        })
    return result


def _compute_wealth_inequality_by_tom(run_dir: Path) -> list[dict]:
    from metric_wealth_inequality import build_daily_inequality
    result = []
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
    result.sort(key=lambda r: (r["trading_day"], r["tom_level"]))
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
        lambda: {"gain_pct_sum": 0.0, "loss_pct_sum": 0.0}
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
            elif target < avg_buy:
                slot["loss_pct_sum"] += pnl_pct

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

        # 已实现盈亏幅度和
        evt = by_day_tom_realized.get((day, tom), {"gain_pct_sum": 0.0, "loss_pct_sum": 0.0})
        row["realized_gain_pct"] = round(evt["gain_pct_sum"], 2)
        row["realized_loss_pct"] = round(evt["loss_pct_sum"], 2)

        result.append(row)
    return result


def _compute_fit_accuracy(run_dir: Path) -> list[dict]:
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
        from metric_fit_accuracy import build_daily_metric_curves, pearson_corr
    except ImportError:
        return []

    real_path = resolve_existing_path("data/index_volatility_curves.json", run_dir)
    if real_path is None:
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
        curves = build_daily_metric_curves([sym], real_close, sim_close, max_day, rolling_window=0)
        aligned = aligned_real_sim_with_day(sym, real_close, sim_close, max_day)

        # 逐日 expanding R² (per-symbol)
        for i, day in enumerate(curves["days"]):
            row: dict = {"trading_day": day, "symbol": sym}
            for key in ["same_day_acc", "forward1_acc", "fit_pct"]:
                if i < len(curves.get(key, [])):
                    v = curves[key][i]
                    if v is not None:
                        row[key] = round(v, 4)
            # per-symbol R²
            pts = [p for p in aligned if p[0] <= day]
            if len(pts) >= 3:
                base_r, base_s = pts[0][1], pts[0][2]
                if abs(base_r) > 1e-9 and abs(base_s) > 1e-9:
                    nr = [r / base_r for _, r, _ in pts]
                    ns = [s / base_s for _, _, s in pts]
                    pc = pearson_corr(nr, ns)
                    if pc is not None:
                        row["r_squared"] = round(pc ** 2, 4)
            result.append(row)
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

    real_path = resolve_existing_path("data/index_volatility_curves.json", run_dir)
    if real_path is None:
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
            rr = sym_real_ret.get(sym, {}).get(day)
            sr = sym_sim_ret.get(sym, {}).get(day)
            if rr is None or sr is None:
                continue
            rv = max(eps, rr ** 2)
            hv = max(eps, sr ** 2)
            ratio = rv / hv
            qlike = ratio - math.log(ratio) - 1.0
            log_rmse = abs(math.log(rv) - math.log(hv))
            result.append({
                "trading_day": day,
                "symbol": sym,
                "qlike": round(qlike, 6),
                "log_rmse": round(log_rmse, 6),
                "real_var": round(rr ** 2, 8),
                "sim_var": round(sr ** 2, 8),
            })
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
        if prev is None or day > safe_int(prev.get("trading_day", 0)):
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


_COMPUTE_DISPATCH: dict[str, callable] = {
    "kyle_lambda": _compute_kyle_lambda,
    "tail_index": _compute_tail_index,
    "volatility_clustering": _compute_volatility_clustering,
    "wealth_inequality": _compute_wealth_inequality,
    "wealth_inequality_by_tom": _compute_wealth_inequality_by_tom,
    "behavioral_agg": _compute_behavioral_agg,
    "behavioral_continuous": _compute_behavioral_continuous,
    "behavioral_performance": _compute_behavioral_performance,
    "fit_accuracy": _compute_fit_accuracy,
    "fit_volatility": _compute_fit_volatility,
    "return_extremes": _compute_return_extremes,
    "trade_count_stats": _compute_trade_count_stats,
    "final_return_ranking": _compute_final_return_ranking,
    "plan_adherence": _compute_plan_adherence,
}


def _iter_jsonl(path: Path):
    """逐行解析 JSONL 文件（惰性读取）"""
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
        cache_key = (str(run_dir), category, tuple(sorted(kwargs.items())))
        if cache_key in _COMPUTE_CACHE:
            return _COMPUTE_CACHE[cache_key]
        try:
            rows = fn(run_dir, **kwargs)
        except Exception as e:
            print(f"[WARN] 计算 {category} 失败 ({run_dir.name}): {e}")
            rows = []
        _COMPUTE_CACHE[cache_key] = rows
        return rows

    fpath = run_dir / cat["file"]
    if not fpath.exists():
        return []
    rows = list(_iter_jsonl(fpath))
    if cat.get("aggregate"):
        rows = _aggregate_by_day(rows, cat)
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


@app.route("/api/categories")
def api_categories():
    """返回可用的数据类别及其指标"""
    result = {}
    for key, cat in DATA_CATEGORIES.items():
        result[key] = {
            "label": cat["label"],
            "metrics": cat["metrics"],
            "group_key": cat["group_key"],
            "computed": bool(cat.get("computed")),
            "desc": cat.get("desc", {}),
            "x_type": cat.get("x_type"),  # 'category' for discrete x-axis
        }
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
    group_key = cat["group_key"]
    preserve_order = cat.get("x_type") == "category"  # 离散轴保留计算函数的原始顺序

    series_data = {}  # { run_name: { series_label: [{x, y}] } }
    all_group_values: set[str] = set()

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

            for gv, g_rows in sorted(grouped.items()):
                _rows = g_rows if preserve_order else sorted(g_rows, key=lambda x: x.get(x_key, 0))
                for metric in selected_metrics:
                    label = f"{gv}_{cat['metrics'].get(metric, metric)}"
                    points = []
                    for r in _rows:
                        val = r.get(metric)
                        if val is not None:
                            points.append({"x": r[x_key], "y": val})
                    if points:
                        run_series[label] = points
        elif group_key and group_filter:
            # 有筛选：每个筛选值 × 每个指标一条线
            grouped: dict[str, list[dict]] = {}
            for r in rows:
                gv = str(r.get(group_key, ""))
                grouped.setdefault(gv, []).append(r)
            for gv, g_rows in sorted(grouped.items()):
                _rows = g_rows if preserve_order else sorted(g_rows, key=lambda x: x.get(x_key, 0))
                for metric in selected_metrics:
                    label = f"{gv}_{cat['metrics'].get(metric, metric)}"
                    points = []
                    for r in _rows:
                        val = r.get(metric)
                        if val is not None:
                            points.append({"x": r[x_key], "y": val})
                    if points:
                        run_series[label] = points
        else:
            # 无分组键
            _rows = rows if preserve_order else sorted(rows, key=lambda x: x.get(x_key, 0))
            for metric in selected_metrics:
                label = cat["metrics"].get(metric, metric)
                points = []
                for r in _rows:
                    val = r.get(metric)
                    if val is not None:
                        points.append({"x": r[x_key], "y": val})
                if points:
                    run_series[label] = points

        series_data[run_name] = run_series

    # 使用主循环中已收集的分组值
    available_groups = sorted(all_group_values) if group_key else []

    return jsonify({
        "series": series_data,
        "x_label": x_key,
        "group_key": group_key,
        "available_groups": available_groups,
    })


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
