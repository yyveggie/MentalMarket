"""
多服务商 LLM API 异步负载均衡器。
支持 OpenAI / Anthropic / Google / DeepSeek，按 ToM 阶数路由模型，
使用 asyncio.Semaphore 做并发控制。
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    name: str                    # openai / anthropic / google / deepseek
    base_url: str
    api_key: str
    model: str
    max_concurrency: int = 20   # 每个服务商的并发上限
    timeout: float = 60.0
    extra_body: dict = field(default_factory=dict)  # 额外请求体参数（如 enable_thinking）


@dataclass
class APIBalancer:
    """
    按 ToM 阶数将请求路由到不同的 LLM 服务商 (LangChain 重构版)。
    """

    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    _semaphores: dict[str, asyncio.Semaphore] = field(default_factory=dict, repr=False)
    _models: dict[str, BaseChatModel] = field(default_factory=dict, repr=False)
    # ToM 阶数 → 服务商名称列表（轮询）
    routing: dict[int, list[str]] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict, repr=False)
    # 公共系统 prompt 缓存
    _system_cache: Optional[str] = None
    _system_cache_by_tom: dict[int, str] = field(default_factory=dict, repr=False)
    _bound_model_cache: dict[tuple, BaseChatModel] = field(default_factory=dict, repr=False)
    temperature: float = 0.7
    max_tokens: int = 512
    debug_print: bool = True
    colorized_print: bool = True

    def add_provider(self, cfg: ProviderConfig):
        self.providers[cfg.name] = cfg

    async def init(self):
        """初始化信号量和 LangChain Chat 模型"""
        for name, cfg in self.providers.items():
            self._semaphores[name] = asyncio.Semaphore(cfg.max_concurrency)
            self._counters[name] = 0
            
            model_kwargs = {"extra_body": dict(cfg.extra_body)} if cfg.extra_body else {}
            self._models[name] = ChatOpenAI(
                model=cfg.model,
                api_key=cfg.api_key,  # type: ignore
                base_url=cfg.base_url,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                max_retries=1,
                timeout=cfg.timeout,
                model_kwargs=model_kwargs,
            )

    async def close(self):
        pass

    def set_system_cache(self, system_prompt: str | dict[int, str]):
        """设置系统 prompt，支持全局字符串或按 ToM 分层配置。"""
        if isinstance(system_prompt, dict):
            self._system_cache_by_tom = {int(k): str(v) for k, v in system_prompt.items()}
            self._system_cache = None
        else:
            self._system_cache = str(system_prompt)
            self._system_cache_by_tom = {}

    def _pick_provider(self, tom_level: int) -> ProviderConfig:
        """根据 ToM 阶数轮询选择服务商（按阶数独立计数，确保均匀分配）"""
        candidates = self.routing.get(tom_level)
        if not candidates:
            all_names = list(self.providers.keys())
            if not all_names:
                raise ValueError("no providers configured")
            logger.warning("No routing configured for tom_level=%d, falling back to all providers: %s", tom_level, all_names)
            candidates = all_names
        counter_key = f"_tom_{tom_level}"
        idx = self._counters.get(counter_key, 0)
        name = candidates[idx % len(candidates)]
        self._counters[counter_key] = idx + 1
        return self.providers[name]

    async def invoke_tools(self, tom_level: int, messages: list, tools: list, round_info: str = "", tool_choice: str | None = None):
        from langchain_core.messages import SystemMessage

        system = self._system_cache_by_tom.get(int(tom_level), self._system_cache) or "You are a financial market trading agent."

        all_messages = messages.copy()
        if not any(isinstance(m, SystemMessage) for m in all_messages):
            all_messages.insert(0, SystemMessage(content=system))

        candidates = self.routing.get(tom_level, list(self.providers.keys()))
        if not candidates:
            candidates = list(self.providers.keys())
        if not candidates:
            raise ValueError(f"no providers configured for tom_level={tom_level}")

        first_provider = self._pick_provider(tom_level)
        ordered = [first_provider.name] + [n for n in candidates if n != first_provider.name]

        max_retries_per_provider = 2
        last_err: Exception | None = None
        for attempt, provider_name in enumerate(ordered):
            provider = self.providers[provider_name]
            sem = self._semaphores[provider.name]
            model = self._models[provider.name]

            tool_ids = tuple(id(t) for t in tools) if tools else ()
            cache_key = (provider_name, tool_ids, tool_choice)
            for retry in range(max_retries_per_provider):
                retry_wait = 0.0
                async with sem:
                    if tools:
                        bound_model = self._bound_model_cache.get(cache_key)
                        if bound_model is None:
                            bind_kwargs = {}
                            if tool_choice is not None:
                                bind_kwargs["tool_choice"] = tool_choice
                            bound_model = model.bind_tools(tools, **bind_kwargs)
                            self._bound_model_cache[cache_key] = bound_model
                    else:
                        bound_model = model
                    try:
                        res = await bound_model.ainvoke(all_messages)
                    except Exception as api_err:
                        last_err = api_err
                        if retry < max_retries_per_provider - 1:
                            retry_wait = 1.0 * (2 ** retry)
                            logger.warning(
                                "API call failed [%s/%s] (ToM%d) %s: %s — retry %d/%d in %.1fs",
                                provider.name, provider.model, tom_level, round_info,
                                type(api_err).__name__, retry + 1, max_retries_per_provider, retry_wait,
                            )
                        else:
                            logger.warning(
                                "API call failed [%s/%s] (ToM%d) %s: %s: %s — failover to next provider (%d/%d)",
                                provider.name, provider.model, tom_level, round_info,
                                type(api_err).__name__, api_err, attempt + 1, len(ordered),
                            )
                            break
                    else:
                        tc = getattr(res, 'tool_calls', [])
                        itc = getattr(res, 'invalid_tool_calls', [])
                        if not tc and not itc:
                            logger.info(
                                "[%s/%s] ToM%d empty tool_calls: content=%r %s",
                                provider.name, provider.model, tom_level,
                                str(res.content or "")[:80], round_info,
                            )
                        if self.debug_print:
                            colors = ['\033[91m', '\033[92m', '\033[93m', '\033[94m', '\033[95m', '\033[96m']
                            color = colors[tom_level % len(colors)] if self.colorized_print else ""
                            reset = '\033[0m' if self.colorized_print else ""
                            print(f"{color}{'='*60}\n"
                                    f"{round_info} [ToM Level: {tom_level}] Provider: {provider.name}\n"
                                    f"--- MESSAGE --- \n{res.content}\n"
                                    f"--- TOOL CALLS --- \n{tc}\n"
                                    f"--- INVALID TOOL CALLS --- \n{itc}\n"
                                    f"{'='*60}{reset}\n")
                        return res
                if retry_wait > 0:
                    await asyncio.sleep(retry_wait)

        logger.error("All providers failed for ToM%d %s", tom_level, round_info)
        raise last_err or RuntimeError(f"All {len(ordered)} providers failed for ToM{tom_level}")


def build_balancer_from_config(api_config: dict) -> APIBalancer:
    """从配置字典创建负载均衡器"""
    infer_cfg = api_config.get("inference", {})
    balancer = APIBalancer(
        temperature=float(infer_cfg.get("temperature", 0.7)),
        max_tokens=int(infer_cfg.get("max_tokens", 512)),
        debug_print=bool(infer_cfg.get("debug_print", True)),
        colorized_print=bool(infer_cfg.get("colorized_print", True)),
    )

    for provider_cfg in api_config.get("providers", []):
        # 支持从环境变量读取 API key
        api_key = provider_cfg.get("api_key", "")
        if api_key.startswith("$"):
            api_key = os.environ.get(api_key[1:], "")

        cfg = ProviderConfig(
            name=provider_cfg["name"],
            base_url=provider_cfg["base_url"],
            api_key=api_key,
            model=provider_cfg["model"],
            max_concurrency=provider_cfg.get("max_concurrency", 20),
            timeout=provider_cfg.get("timeout", 60.0),
            extra_body=provider_cfg.get("extra_body", {}),
        )
        balancer.add_provider(cfg)

    # 路由规则
    routing = api_config.get("routing", {})
    for level_str, names in routing.items():
        balancer.routing[int(level_str)] = names

    return balancer
