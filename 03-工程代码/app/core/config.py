"""应用配置：环境变量集中校验、启动快速失败。

对应《模型框架设计说明书》ARCH-003 §3.4 `app/core/config.py`。
纪律：配置只从环境变量／`.env` 读取，**不得在业务代码中内联硬编码**。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """服务配置。字段名与 `.env.example` 中的 `APP_*` 一一对应。"""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 应用 ----
    app_name: str = "AI 漫剧剧本与分镜提示词生成系统"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    debug: bool = False

    # ---- 备案主体标识（**脱敏版留空，由部署环境注入**）----
    # provider_name / provider_code 为空时，`pack_meta` 一律写占位符并登记，
    # **绝不自拟假值**（见 app/services/pack_meta.py）。
    provider_name: str = ""
    provider_code: str = ""

    # ---- 推理后端（ARCH-003 §6.1「可替换是架构底线」）----
    # 取值：mock | vllm | local | remote；切换只改本项，业务代码零改动。
    inference_backend: str = "mock"

    # ---- 提示词资产根目录（03-工程代码/prompts）----
    prompts_root: str = ""

    # ---- 会话（SW-001「会话超时恢复」）----
    session_ttl_seconds: int = 3600

    # ---- 身份与租户（T-008 二期接入，本批只保留配置位）----
    auth_enabled: bool = False

    @property
    def prompts_dir(self) -> Path:
        """提示词资产根目录：显式配置优先，否则按包位置上溯定位。"""
        if self.prompts_root:
            return Path(self.prompts_root).expanduser().resolve()
        # 本文件位于 <工程代码>/app/core/config.py → 上溯三级得 <工程代码>/prompts
        return Path(__file__).resolve().parents[2] / "prompts"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例。测试可通过 `get_settings.cache_clear()` 重置。"""
    return Settings()
