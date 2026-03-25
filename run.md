# MentalMarket 运行指南

## 配置文件

| 文件 | 用途 |
|------|------|
| `config.yaml` | 完整实验（1000 Agent，100 交易日） |
| `config_100.yaml` | 快速测试（100 Agent，参数已按比例调整） |

Docker 默认使用 `config_100.yaml`（在 `docker-compose.yaml` 的 `command` 中指定）。

---

## Docker 运行（推荐）

### 启动

```bash
# 前台运行（日志直接打印，Ctrl+C 停止）
docker compose up --build

# 后台运行（适合长时间实验）
docker compose up --build -d
```

### 停止

```bash
# 前台模式：直接 Ctrl+C（自动保存 checkpoint）

# 后台模式
docker compose stop       # 停止容器（保留容器状态）
docker compose down       # 停止并清理容器
```

### 查看日志

```bash
docker compose logs -f              # 实时跟踪
docker compose logs --tail 100      # 最近 100 行
```

### 看板

```bash
open http://localhost:8765
```

---

## 切换配置

编辑 `docker-compose.yaml` 中的 `command` 字段：

```yaml
# 使用 100 Agent 快速测试（默认）
command: ["--config", "config_100.yaml"]

# 使用 1000 Agent 完整实验
command: ["--config", "config.yaml"]

# 自定义 Agent 数量和时长（覆盖配置文件中的值）
command: ["--config", "config_100.yaml", "--agents", "50", "--time", "7200"]
```

修改后重启：

```bash
docker compose down && docker compose up --build
```

> 仅修改 `config.yaml` / `config_100.yaml` 内容无需 `--build`，直接 `docker compose down && docker compose up` 即可。

---

## 断点续跑

```bash
# 1. 查看已有运行记录
ls runs/

# 2. 修改 docker-compose.yaml 的 command
command: ["--config", "config_100.yaml", "--resume", "runs/20260318_070402"]

# 3. 启动（自动从 checkpoint 恢复）
docker compose up
```

---

## 前端热更新（不停止实验）

```bash
# 首次安装依赖
cd app/dashboard/frontend && npm install

# 修改 .vue/.ts 文件后重新编译
npm run build

# 刷新浏览器即可生效，无需重启实验
```

> 原理：`docker-compose.yaml` 中 `app/dashboard/static` 通过 volume 挂载到容器，编译产物直接覆盖静态文件。

修改后端 Python 代码（`app/`、`prompts/`、`tools/`）则需要重新构建镜像：`docker compose up --build`

---

## 本地运行（不用 Docker）

```bash
pip install -r requirements.txt

python run.py                                    # 默认配置（config.yaml）
python run.py --config config_100.yaml           # 快速测试
python run.py --agents 50 --time 7200            # 自定义参数
python run.py --config config_100.yaml --resume runs/20260319_223957      # 断点续跑

# 看板
open http://127.0.0.1:8765
```

---

## 迁移到其他设备

**方案 A：导出镜像**

```bash
# 导出
docker save mentalmarket-simulation:latest | gzip > mentalmarket.tar.gz

# 目标设备：导入并运行
docker load < mentalmarket.tar.gz
mkdir -p runs
docker compose up
```

**方案 B：传源码后构建**

```bash
# 打包（排除大文件）
tar czf mentalmarket-src.tar.gz \
    --exclude='node_modules' --exclude='runs' \
    --exclude='__pycache__' --exclude='.conda' \
    MentalMarket/

# 目标设备
tar xzf mentalmarket-src.tar.gz && cd MentalMarket
docker compose up --build
```

---

## 实验数据

所有数据保存在 `runs/<时间戳>/`：

| 文件 | 内容 |
|------|------|
| `config.yaml` | 本次运行的配置快照 |
| `agents_init.jsonl` | Agent 初始状态 |
| `agents_final.jsonl` | Agent 最终状态 |
| `decisions.jsonl` | LLM 推理记录（Prompt + 输出 + 执行结果） |
| `trades.jsonl` | 成交记录 |
| `posts.jsonl` | 社交帖子 |
| `sentiment_series.jsonl` | 情绪时序 |
| `behavioral_biases.jsonl` | 行为偏差指标 |
| `market_snapshots.jsonl` | 市场微观结构（每交易日） |
| `agent_wealth.jsonl` | Agent 财富快照（每交易日） |
| `tom_stats.jsonl` | ToM 分层统计 |
| `order_events.jsonl` | 订单事件（提交/撤销/过期） |
| `liquidity_provision.jsonl` | 流动性供给（Maker/Taker） |
| `info_cascade.jsonl` | 信息传播链路 |
| `social_graph_events.jsonl` | 社交图谱事件（关注/KOL） |
| `reputation_history.jsonl` | 声誉变动 |
| `price_discovery.jsonl` | 价格发现质量指标 |
| `broad_index.jsonl` | 大盘指数 |
| `checkpoint.pkl` | 断点续跑文件 |
| `results.json` | 仿真结果摘要 |
