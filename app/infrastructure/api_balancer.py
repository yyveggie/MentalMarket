"""
多服务商 LLM API 异步负载均衡器。
支持 OpenAI / Anthropic / Google / DeepSeek，按 ToM 阶数路由模型，
使用 asyncio.Semaphore 做并发控制。
"""

from __future__ import annotations

import asyncio
import logging
import os
import pprint
import re
from dataclasses import dataclass, field
from typing import Any, Optional

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
    _bound_model_cache: dict[tuple, Any] = field(default_factory=dict, repr=False)
    temperature: float = 0.7
    max_tokens: int = 512
    max_retries_per_provider: int = 4
    retry_backoff_base_seconds: float = 1.0
    retry_backoff_cap_seconds: float = 8.0
    print_full_prompt: bool = True
    debug_print: bool = True
    colorized_print: bool = True

    @staticmethod
    def _extract_status_code(err: Exception) -> int | None:
        status = getattr(err, "status_code", None)
        if isinstance(status, int):
            return status
        response = getattr(err, "response", None)
        response_status = getattr(response, "status_code", None)
        if isinstance(response_status, int):
            return response_status
        text = str(err)
        m = re.search(r"\b([1-5]\d\d)\b", text)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
        return None

    def _is_retryable_error(self, err: Exception) -> bool:
        status = self._extract_status_code(err)
        name = type(err).__name__
        if status is not None:
            # 429 限流与 5xx 服务端异常可重试；其余 4xx 一般是请求内容/参数问题。
            if status == 429 or 500 <= status < 600:
                return True
            if 400 <= status < 500:
                return False

        lname = name.lower()
        if "badrequest" in lname or "invalidrequest" in lname:
            return False
        retryable_keywords = ("connect", "timeout", "tempor", "rate", "unavailable")
        if any(k in lname for k in retryable_keywords):
            return True
        return True

    def _should_dump_prompt(self, err: Exception) -> bool:
        status = self._extract_status_code(err)
        name = type(err).__name__
        if status is not None:
            return 400 <= status < 500 and status != 429
        return "BadRequestError" in name

    def add_provider(self, cfg: ProviderConfig):
        self.providers[cfg.name] = cfg

    async def init(self):
        """初始化信号量和 LangChain Chat 模型"""
        for name, cfg in self.providers.items():
            self._semaphores[name] = asyncio.Semaphore(cfg.max_concurrency)
            self._counters[name] = 0

            # 显式传参可避免 LangChain 对 model_kwargs 的参数归类告警。
            chat_kwargs: dict[str, Any] = {}
            if cfg.extra_body:
                chat_kwargs["extra_body"] = dict(cfg.extra_body)
            if self.max_tokens > 0:
                chat_kwargs["max_tokens"] = self.max_tokens
            self._models[name] = ChatOpenAI(
                model=cfg.model,
                api_key=cfg.api_key,  # type: ignore
                base_url=cfg.base_url,
                temperature=self.temperature,
                max_retries=1,
                timeout=cfg.timeout,
                **chat_kwargs,
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

        last_err: Exception | None = None
        for attempt, provider_name in enumerate(ordered):
            provider = self.providers[provider_name]
            sem = self._semaphores[provider.name]
            model = self._models[provider.name]

            tool_ids = tuple(id(t) for t in tools) if tools else ()
            cache_key = (provider_name, tool_ids, tool_choice)
            for retry in range(self.max_retries_per_provider):
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

                    if self.print_full_prompt:
                        print("\033[96m===== FULL PROMPT/MESSAGES BEFORE API CALL =====\033[0m")
                        print(f"[ToM Level: {tom_level}] Provider: {provider.name}  Model: {provider.model}  Round: {round_info}")
                        print("--- all_messages ---")
                        pprint.pprint(all_messages)
                        if tools:
                            print("--- tools ---")
                            print([getattr(t, "__name__", t.__class__.__name__) for t in tools])
                        if tool_choice is not None:
                            print("--- tool_choice ---")
                            print(tool_choice)
                        print("\033[96m===============================================\033[0m")

                    try:
                        res = await bound_model.ainvoke(all_messages)
                    except Exception as api_err:
                        last_err = api_err
                        retryable = self._is_retryable_error(api_err)
                        status_code = self._extract_status_code(api_err)
                        # 仅对 4xx(非429) 打印 prompt/messages，便于定位请求内容问题。
                        if self._should_dump_prompt(api_err):
                            print("\033[91m===== LLM 400 BadRequestError: PROMPT/MESSAGES THAT CAUSED ERROR =====\033[0m")
                            print(f"[ToM Level: {tom_level}] Provider: {provider.name}  Model: {provider.model}  Round: {round_info}")
                            print("--- all_messages ---")
                            pprint.pprint(all_messages)
                            print("--- Exception ---")
                            print(api_err)
                            print("\033[91m===============================================================\033[0m")

                        retry_budget = self.max_retries_per_provider if retryable else 1
                        if retry < retry_budget - 1:
                            retry_wait = min(
                                self.retry_backoff_base_seconds * (2 ** retry),
                                self.retry_backoff_cap_seconds,
                            )
                            logger.warning(
                                "API call failed [%s/%s] (ToM%d) %s: %s(status=%s,retryable=%s) — retry %d/%d in %.1fs",
                                provider.name, provider.model, tom_level, round_info,
                                type(api_err).__name__, status_code, retryable,
                                retry + 1, retry_budget, retry_wait,
                            )
                        else:
                            logger.warning(
                                "API call failed [%s/%s] (ToM%d) %s: %s(status=%s,retryable=%s): %s — failover to next provider (%d/%d)",
                                provider.name, provider.model, tom_level, round_info,
                                type(api_err).__name__, status_code, retryable, api_err, attempt + 1, len(ordered),
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
    default_timeout = float(infer_cfg.get("request_timeout", 90.0))
    balancer = APIBalancer(
        temperature=float(infer_cfg.get("temperature", 0.7)),
        max_tokens=int(infer_cfg.get("max_tokens", 512)),
        max_retries_per_provider=int(infer_cfg.get("max_retries_per_provider", 4)),
        retry_backoff_base_seconds=float(infer_cfg.get("retry_backoff_base_seconds", 1.0)),
        retry_backoff_cap_seconds=float(infer_cfg.get("retry_backoff_cap_seconds", 8.0)),
        print_full_prompt=bool(infer_cfg.get("print_full_prompt", True)),
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
            timeout=provider_cfg.get("timeout", default_timeout),
            extra_body=provider_cfg.get("extra_body", {}),
        )
        balancer.add_provider(cfg)

    # 路由规则
    routing = api_config.get("routing", {})
    for level_str, names in routing.items():
        balancer.routing[int(level_str)] = names

    return balancer
