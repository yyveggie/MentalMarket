# MentalMarket

MentalMarket 是一个基于大语言模型 Agent 的金融市场仿真项目，用于模拟不同心智水平投资者在连续双向拍卖市场和社交网络中的交易、发帖、关注与声誉变化。

![MentalMarket Dashboard](app/dashboard/MentalMarket.png)

## 配置方式

复制示例配置文件并按需修改：

```bash
cp config.example.yaml config.yaml
```

在 `config.yaml` 中配置仿真参数、Agent 数量、市场参数、社交网络参数和 LLM 服务。

LLM 服务配置位于 `api.providers`：

```yaml
api:
  providers:
    - name: provider_1
      base_url: "<your-openai-compatible-api-base-url>"
      api_key: $MENTALMARKET_PROVIDER_1_API_KEY
      model: "<your-model-name>"
      max_concurrency: 20
      timeout: 60
      extra_body: {}

  routing:
    0: [provider_1]
    1: [provider_1]
    2: [provider_1]
```

API Key 建议通过环境变量提供：

```bash
export MENTALMARKET_PROVIDER_1_API_KEY="your_api_key"
```

## 启动方式

安装依赖：

```bash
pip install -r requirements.txt
```

启动默认仿真：

```bash
python run.py --config config.yaml
```

使用 100 Agent 示例配置：

```bash
cp config_100.example.yaml config_100.yaml
python run.py --config config_100.yaml
```

启动实时模式示例：

```bash
cp config_realtime.example.yaml config_realtime.yaml
python run.py --config config_realtime.yaml
```

看板默认地址：

```text
http://localhost:8765
```
