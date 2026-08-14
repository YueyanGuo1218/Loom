"""配置:从环境变量读取(部署时在 Railway 的 Variables 里配,本机开发用 .env)。"""

from typing import Optional
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    anthropic_api_key: str
    # 可选:Anthropic API 中转站/自定义 base_url(留空则用官方 api.anthropic.com)。
    anthropic_base_url: Optional[str] = None

    # Railway 附加 Postgres 后会自动注入 DATABASE_URL;本机开发默认用 SQLite。
    database_url: str = "sqlite:///./loom.db"

    # 可选:webhook 公网地址,配了之后启动时自动 set_webhook。
    webhook_url: Optional[str] = None
    # 可选:Telegram webhook 鉴权 secret。
    webhook_secret: Optional[str] = None
    # 可选:保护 /internal/cron 的 secret。
    cron_secret: Optional[str] = None

    # 时区,影响「下周一」这类时间的解析。
    loom_tz: str = "Asia/Shanghai"

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.loom_tz)


settings = Settings()
