from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

ASR_HOTWORDS = ",".join([
    "空调|10", "铜管|10", "支架|8", "抽真空|10", "室外机|8", "内机|8",
    "制冷|8", "排水管|8", "加氟|10", "压缩机|8", "安装费|8", "材料费|8",
])


@dataclass(frozen=True)
class AsrSettings:
    enabled: bool
    secret_id: str
    secret_key: str
    region: str
    engine: str
    hotwords: str
    timeout_seconds: int = 25

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.secret_id and self.secret_key)


def get_asr_settings() -> AsrSettings:
    return AsrSettings(
        enabled=os.getenv("TENCENT_ASR_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"},
        secret_id=os.getenv("TENCENTCLOUD_SECRET_ID", "").strip(),
        secret_key=os.getenv("TENCENTCLOUD_SECRET_KEY", "").strip(),
        region=os.getenv("TENCENTCLOUD_REGION", "ap-shanghai").strip() or "ap-shanghai",
        engine=os.getenv("TENCENT_ASR_ENGINE", "16k_zh").strip() or "16k_zh",
        hotwords=ASR_HOTWORDS,
    )


@dataclass(frozen=True)
class AiReportSettings:
    enabled: bool
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int = 45

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.api_key and self.base_url and self.model)


def get_ai_report_settings() -> AiReportSettings:
    return AiReportSettings(
        enabled=os.getenv("AI_REPORT_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"},
        api_key=os.getenv("DASHSCOPE_API_KEY", "").strip(),
        base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").strip(),
        model=os.getenv("DASHSCOPE_MODEL", "qwen3.5-plus-2026-02-15").strip(),
    )


@dataclass(frozen=True)
class DatabaseSettings:
    environment: str
    url: str
    pool_size: int
    max_overflow: int


def get_database_settings() -> DatabaseSettings:
    environment = os.getenv("GANWANLE_ENV", "development").strip().lower()
    default = f"sqlite:///{(Path(__file__).resolve().parent / 'data' / 'ganwanle.db').as_posix()}"
    url = os.getenv("DATABASE_URL", default).strip()
    if environment == "production" and not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Production requires PostgreSQL")
    return DatabaseSettings(
        environment,
        url,
        int(os.getenv("DATABASE_POOL_SIZE", "5")),
        int(os.getenv("DATABASE_MAX_OVERFLOW", "5")),
    )
