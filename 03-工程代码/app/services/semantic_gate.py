"""语义闸客户端 —— Qwen3Guard-Gen-4B（`T-108` ③，`DEV-20261110-012` 部署）。

服务形态：8 卡服务器 GPU7 上的 vLLM OpenAI 兼容服务（`safety-guard.service`，
服务器 127.0.0.1:8001，本机经 SSH 隧道 18002 访问）。

输出格式（官方，`DEV-20261110-012` §2 冒烟实测）：
- 输入侧审核（单条 user 消息）：`Safety: Safe|Unsafe|Controversial` ＋ `Categories: …`
  （⚠️ **无 `Refusal:` 行**，该行只在输出侧审核出现——机读解析不得按两侧行数强一致断言）；
- 输出侧审核（user＋assistant 双消息）：多一行 `Refusal: Yes|No`。

失效语义（**fail-open ＋ 留痕**）：语义闸不可用／超时 ⇒ 调用方回落词闸判定，
不得因语义闸故障拒绝正常请求——词闸＋输出复检＋人工抽检仍在线（双层兜底）；
但故障必须留痕（`degraded`），不得静默旁路。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

#: 安全类别封闭枚举（官方 README；`None` 表示无类别）
CATEGORIES: tuple[str, ...] = (
    "Violent",
    "Non-violent Illegal Acts",
    "Sexual Content or Sexual Acts",
    "PII",
    "Suicide & Self-Harm",
    "Unethical Acts",
    "Politically Sensitive Topics",
    "Copyright Violation",
    "None",
)

_LABEL_RE = re.compile(r"Safety:\s*(Safe|Unsafe|Controversial)", re.IGNORECASE)
_CATEGORY_RE = re.compile(
    r"(" + "|".join(re.escape(c) for c in CATEGORIES[:-1]) + r"|None)"
)
_REFUSAL_RE = re.compile(r"Refusal:\s*(Yes|No)", re.IGNORECASE)


@dataclass(frozen=True)
class SemanticVerdict:
    """一次语义审核的机读结果。"""

    label: str  # Safe / Unsafe / Controversial / unknown（解析失败）
    categories: tuple[str, ...]
    refusal: str | None  # Yes / No；输入侧审核恒为 None（官方格式无该行）
    raw: str
    ok: bool  # 解析成功

    @property
    def unsafe(self) -> bool:
        return self.ok and self.label == "Unsafe"

    @property
    def sensitive(self) -> bool:
        return self.ok and self.label == "Controversial"


def parse_guard_output(text: str) -> SemanticVerdict:
    """解析守卫模型输出（容错：两侧行数不一致、大小写、多余空白）。"""
    raw = text.strip()
    m = _LABEL_RE.search(raw)
    if not m:
        return SemanticVerdict("unknown", (), None, raw, False)
    cats = tuple(dict.fromkeys(_CATEGORY_RE.findall(raw)))
    r = _REFUSAL_RE.search(raw)
    return SemanticVerdict(
        label=m.group(1).capitalize(),
        categories=tuple(c for c in cats if c != "None") or (),
        refusal=r.group(1).capitalize() if r else None,
        raw=raw,
        ok=True,
    )


class SemanticGate:
    """Qwen3Guard-Gen-4B 客户端（同步 httpx；守卫模型 4B，单次判定亚秒级）。"""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout: float = 15.0,
        api_key: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout
        self._api_key = api_key
        self._client: httpx.Client | None = None

    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout, trust_env=False)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.aclose()
            self._client = None

    def _ask(self, messages: list[dict[str, str]]) -> SemanticVerdict:
        client = self._ensure_client()
        try:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 128,
                    "temperature": 0,
                },
                headers={"Authorization": f"Bearer {self._api_key}"} if self._api_key else {},
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001 —— 语义闸失效按 fail-open 上抛标记
            logger.warning("语义闸调用失败（fail-open，回落词闸判定）: %s", type(exc).__name__)
            return SemanticVerdict("unknown", (), None, f"{type(exc).__name__}: {exc}", False)
        return parse_guard_output(content)

    def moderate_prompt(self, text: str) -> SemanticVerdict:
        """输入侧审核：判断用户请求是否为违法／有害请求。"""
        return self._ask([{"role": "user", "content": text}])

    def moderate_response(self, prompt: str, response: str) -> SemanticVerdict:
        """输出侧审核：判断对 prompt 的回应内容是否安全（官方双消息形态）。"""
        return self._ask(
            [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": response},
            ]
        )
