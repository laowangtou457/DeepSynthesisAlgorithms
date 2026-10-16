"""vLLM 推理后端（OpenAI 兼容 HTTP `/chat/completions`）。

平台前提（**必须先知情**）
--------------------------
vLLM 官方支持矩阵为 **Linux / WSL2**，**不支持 Windows 原生**。故本机部署形态是
「Windows 宿主 → WSL2 Ubuntu → vLLM 服务进程（回环端口）」：应用跑在 Windows 侧，
经 `localhost` 转发访问 WSL2 内的推理服务。启动参数、显存调优与落盘位置见
`04-部署运维/OPS-002_WSL2-vLLM部署手册.md`。

契约与纪律
----------
1. 只实现 `app.inference.base.TextGenerator` 契约，**不掺入任何业务语义**；
2. 提示词由服务层渲染后传入，本模块**只做传输与形态转换**——
   **不拼接、不改写、不裁剪**提示词内容（裁剪属模板层的 `segment` 职责）；
3. 受约束解码按 `APP_VLLM_GUIDED_DECODING_MODE` **声明式**选择参数形态
   （`structured_outputs` / `guided_json` / `response_format` / `off`），
   参数形态**收敛在一处**，不在代码里散落 if；
   ⚠️ **版本敏感**：vLLM **v0.12.0 起移除 `guided_json`**（改用 `structured_outputs`）。
   旧字段发给新版引擎会被**静默忽略** → 无约束解码。故默认取新版形态，
   目标引擎 < 0.12.0 时须**显式改配置**，并在上线核对清单中记明引擎版本；
4. 失败一律抛 `AppError(GENERATION_FAILED)`，**绝不静默降级为 mock 或空串**
   ——「宁可显式报错，也不静默降级」是本工程的一贯纪律；
5. 错误信息与日志**不得携带 API Key**。

消息形态映射
------------
服务层传入的是 `RenderedPrompt.as_text()`（形如 `<system>\\n…\\n\\n<task>\\n…`）。
本模块把它还原为 chat 形态：`system` 节 → `role=system`，其余节 → `role=user`，
并保留首行 `[stage:…]` 标记（它是链路阶段的留痕，不是可丢弃的噪声）。
⚠️ 节切分依赖 `<节名>\\n` 前缀，模板正文中若出现同形态文本会被误切 —— 模板资产受控，
该边界可接受；若将来模板允许自由正文，须改为显式分段。
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.inference.base import GenParams, GenResult, TextGenerator

logger = get_logger("inference.vllm")

#: 服务层在渲染串首行加的阶段标记，用于日志与留痕；**不丢弃**。
_STAGE_LINE = re.compile(r"^\[stage:[a-z_]+\]\s*\n")

#: 五节块：`<system>\n{正文}`，节间以空行分隔，末节止于串尾。
_SECTION = re.compile(r"<([a-z]+)>\n(.*?)(?=\n\n<[a-z]+>\n|\Z)", re.S)


def split_sections(text: str) -> dict[str, str]:
    """把 `RenderedPrompt.as_text()` 的形态还原为 `{节名: 正文}`。"""
    return {m.group(1): m.group(2).rstrip("\n") for m in _SECTION.finditer(text)}


def to_messages(prompt: str) -> list[dict[str, str]]:
    """渲染串 → chat `messages`。

    无节结构时**整体作为单条 user 消息**（不丢内容，形态降级而非内容降级）。
    """
    stage_match = _STAGE_LINE.match(prompt)
    stage_line = stage_match.group(0).strip() if stage_match else ""
    body = prompt[stage_match.end() :] if stage_match else prompt

    sections = split_sections(body)
    if not sections:
        return [{"role": "user", "content": prompt}]

    system_text = sections.pop("system", "")
    rest = "\n\n".join(f"<{name}>\n{text}" for name, text in sections.items())
    if stage_line:
        rest = f"{stage_line}\n{rest}"

    messages: list[dict[str, str]] = []
    if system_text:
        messages.append({"role": "system", "content": system_text})
    if rest:
        messages.append({"role": "user", "content": rest})
    if not messages:  # pragma: no cover - 仅空模板触发
        messages.append({"role": "user", "content": prompt})
    return messages


class VllmBackend(TextGenerator):
    """vLLM OpenAI 兼容后端。

    `transport` 仅供测试注入（`httpx.MockTransport`），生产留 `None`。
    """

    name = "vllm"
    context_window = 32768
    max_output_tokens = 8192

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 180.0,
        guided_decoding_mode: str = "structured_outputs",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.guided_decoding_mode = guided_decoding_mode
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        #: 实际服务端模型标识；首次成功响应后回填（`/v1/models` 亦可探测）。
        self._served_model: str | None = None

    # ------------------------------------------------------------ 属性
    @property
    def version(self) -> str:  # type: ignore[override]
        """模型版本口径：优先取服务端回包 `model`，未探测时回落配置名。

        ⚠️ 权重 revision（commit hash）无法由 OpenAI 兼容接口取得，
        须由 `--revision` 启动参数决定并在 `T-013` 登记。
        """
        return self._served_model or self.model

    # ------------------------------------------------------------ 生命周期
    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout, transport=self._transport)
        return self._client

    async def aclose(self) -> None:
        """释放连接池。调用方负责在应用关闭时调用。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------ 请求装配
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(
        self,
        prompt: str,
        params: GenParams,
        json_schema: dict | None,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": to_messages(prompt),
            "temperature": params.temperature,
            "top_p": params.top_p,
            "max_tokens": params.max_tokens,
            "repetition_penalty": params.repetition_penalty,
        }
        if params.top_k:
            payload["top_k"] = params.top_k
        if params.stop:
            payload["stop"] = list(params.stop)
        if stream:
            payload["stream"] = True

        # ---- 受约束解码（形态收敛于此，见模块 docstring 纪律 3）----
        # ⚠️ **版本敏感**：vLLM **v0.12.0 起移除** `guided_json` / `guided_choice` 等旧字段，
        #    统一改用 `structured_outputs: {"json": …}`。旧字段发给新版引擎会被
        #    **静默忽略** → 退化为无约束解码（最危险的失败：看似成功、实则无约束）。
        #    故默认取新版形态；如目标引擎 < 0.12.0，须**显式**改配置，不得靠回退。
        if json_schema is not None and self.guided_decoding_mode != "off":
            if self.guided_decoding_mode == "structured_outputs":
                # vLLM >= 0.12.0 官方形态
                payload["structured_outputs"] = {"json": json_schema}
            elif self.guided_decoding_mode == "guided_json":
                # vLLM < 0.12.0 的原生参数（0.4+ 存在）
                payload["guided_json"] = json_schema
            elif self.guided_decoding_mode == "response_format":
                # OpenAI 标准形态（多数引擎通用，vLLM 亦支持）
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "structured_output", "schema": json_schema},
                }
            else:
                # 未知形态：**显式失败**，绝不「当作没约束」继续跑
                raise AppError(
                    ErrorCode.GENERATION_FAILED,
                    f"未知的受约束解码形态：{self.guided_decoding_mode}"
                    "（可选：structured_outputs / guided_json / response_format / off）",
                    details={"guided_decoding_mode": self.guided_decoding_mode},
                )
        return payload

    # ------------------------------------------------------------ 错误映射
    def _raise_transport(self, exc: Exception, *, url: str) -> None:
        """把传输层异常统一映射为 `GENERATION_FAILED`（**不泄露 Key**）。"""
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            snippet = ""
            try:
                snippet = exc.response.text[:300]
            except Exception:  # pragma: no cover - 响应体不可读时不阻断
                snippet = ""
            logger.error(
                "vllm_http_error",
                extra={"extra_fields": {"status": status, "url": url}},
            )
            raise AppError(
                ErrorCode.GENERATION_FAILED,
                f"推理后端返回错误状态 {status}",
                details={"status": status, "endpoint": url, "body": snippet},
                # 4xx 多为请求本身不合法，重试无意义；5xx 可重试。
                retryable=500 <= status < 600,
            ) from exc
        if isinstance(exc, httpx.TimeoutException):
            logger.error("vllm_timeout", extra={"extra_fields": {"url": url}})
            raise AppError(
                ErrorCode.GENERATION_FAILED,
                f"推理后端响应超时（{self.timeout}s）",
                details={"endpoint": url, "timeout_seconds": self.timeout},
                retryable=True,
            ) from exc
        logger.error(
            "vllm_transport_error",
            extra={"extra_fields": {"exc_type": type(exc).__name__, "url": url}},
        )
        raise AppError(
            ErrorCode.GENERATION_FAILED,
            "无法连接推理后端（服务是否已启动？见 OPS-002）",
            details={"endpoint": url, "exc_type": type(exc).__name__},
            retryable=True,
        ) from exc

    # ------------------------------------------------------------ 契约实现
    async def generate(
        self, prompt: str, params: GenParams, json_schema: dict | None = None
    ) -> GenResult:
        url = f"{self.base_url}/chat/completions"
        payload = self._payload(prompt, params, json_schema, stream=False)
        client = self._ensure_client()
        try:
            resp = await client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            self._raise_transport(exc, url=url)
            raise  # pragma: no cover - _raise_transport 必抛

        if data.get("model"):
            self._served_model = str(data["model"])
        choices = data.get("choices") or []
        if not choices:
            raise AppError(
                ErrorCode.GENERATION_FAILED,
                "推理后端返回内容为空（choices 缺失）",
                details={"endpoint": url},
            )
        choice = choices[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        usage = data.get("usage") or {}
        return GenResult(
            text=text,
            finish_reason=str(choice.get("finish_reason") or "stop"),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            meta={
                "backend": self.name,
                "model": self.model,
                "served_model": self._served_model,
                "guided_decoding": (
                    self.guided_decoding_mode if json_schema is not None else "off"
                ),
                "json_schema_applied": json_schema is not None
                and self.guided_decoding_mode != "off",
            },
        )

    async def stream(
        self, prompt: str, params: GenParams, json_schema: dict | None = None
    ) -> AsyncIterator[str]:  # type: ignore[override]
        url = f"{self.base_url}/chat/completions"
        payload = self._payload(prompt, params, json_schema, stream=True)
        client = self._ensure_client()
        try:
            async with client.stream("POST", url, json=payload, headers=self._headers()) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        event = json.loads(chunk)
                    except json.JSONDecodeError:  # pragma: no cover - 心跳等非 JSON 行
                        continue
                    if event.get("model"):
                        self._served_model = str(event["model"])
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        yield piece
        except httpx.HTTPError as exc:
            self._raise_transport(exc, url=url)


def build_from_settings(settings: Any) -> VllmBackend:
    """按配置装配后端（`registry` 的唯一入口；**配置只在此处读取一次**）。"""
    return VllmBackend(
        base_url=settings.vllm_base_url,
        model=settings.vllm_model,
        api_key=settings.vllm_api_key,
        timeout=settings.vllm_timeout_seconds,
        guided_decoding_mode=settings.vllm_guided_decoding_mode,
    )
