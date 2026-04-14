# 推理-发帖一致性分析（Reasoning–Post Consistency）

## 目的

检测智能体是否存在**策略性操纵发帖**——即内心推理（thinking）和公开帖子（posting）
内容不一致。低一致性意味着 agent "想的"和"说的"不同，可能在有意误导其他交易者。

## 推理文本字段

| ToM 层级 | 字段 | 含义 |
|----------|------|------|
| ToM-0 | `mental_reasoning` | 占位符（不参与分析） |
| ToM-1 | `mental_reasoning` | 一阶推理：基于市场信息的分析判断 |
| ToM-2 | `tom1_reasoning` | 一阶推理：我认为其他交易者会怎么做 |
| ToM-2 | `tom2_reasoning` | 二阶推理：其他人认为我会怎么做，我如何反制 |

> **注意**：ToM-2 的两个推理分量被独立分析（`tom2_r1` 和 `tom2_r2`），
> 避免拼接导致一阶共享文本膨胀相似度。

---

## 分析方法

### 三层去模板策略

LLM 生成的推理/帖子文本包含大量结构性重复（系统句式模板、LLM 组特有句式、当日共享行情引用），
需要逐层剥离才能准确衡量推理与帖子之间的真实一致度。

| 层级 | 范围 | 默认阈值 | 目标 |
|------|------|----------|------|
| Layer 1 全局 | 全部文本（推理+帖子） | >80% | 系统级句式模板、常见连接词 |
| Layer 2 组级 | 同 ToM 组 | >60% | LLM 组特有的句式模板 |
| Layer 3 逐日 | 同天所有文本 | >50% | 当日共享行情数据、新闻引用（最小 5 条） |

三层逐层递进，不重复计数。

### 多粒度 n-gram

同时使用 bigram + trigram，更精准捕捉 3~5 个词的模板短语。

### 去模板 NCD 压缩距离

1. 从 token 序列中**剥离被标记为模板的 span**
2. 用 zlib 压缩去模板后的推理文本和帖子文本
3. 计算归一化压缩距离

$$\text{NCD}(A,B) = \frac{C(AB) - \min(C(A), C(B))}{\max(C(A), C(B))}$$

图表中显示 $1 - \text{NCD}$（相似度方向）。值越低 = 推理与帖子越不一致 = 越可能在策略性操纵。

---

## 输出文件

| 文件 | 说明 |
|------|------|
| `推理发帖一致性_{label}.png` | 各实验的 NCD 一致性时间序列 |
| `推理发帖一致性_多实验对比.png` | 柱状图对比 |
| `推理发帖一致性_Agent分布.png` | Agent 散点图（NCD sim vs 活跃天数） |
| `推理发帖一致性_汇总.json` | 汇总统计（含模板检测报告 + 最不一致 Top-10 agents） |

## 代码位置

| 脚本 | 说明 |
|------|------|
| `evaluation/reasoning_homogeneity/plot_reasoning_post_consistency.py` | 推理-发帖一致性分析（三层去模板 NCD） |

## 运行命令

```bash
python evaluation/reasoning_homogeneity/plot_reasoning_post_consistency.py \
  runs/ToM1 runs/ToM2 \
  --labels "ToM1,ToM2" \
  --output-dir evaluation/reasoning_homogeneity \
  --prefix "推理发帖一致性"

# 自定义去模板阈值
python evaluation/reasoning_homogeneity/plot_reasoning_post_consistency.py \
  runs/ToM1 runs/ToM2 \
  --global-thresh 0.75 --group-thresh 0.55 --daily-thresh 0.40 \
  --output-dir evaluation/reasoning_homogeneity
```
