"""FastAPI 入口:创建 app、挂路由、lifespan(建表 + 设 webhook)。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import config, telegram
from .cron import router as cron_router
from .db import init_db
from .webhook import router as webhook_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动:建表 + (若配了 WEBHOOK_URL)设置 Telegram webhook。
    init_db()
    logger.info("数据库已初始化")
    if config.settings.webhook_url:
        try:
            telegram.set_webhook()
            logger.info("webhook 已设置: %s", config.settings.webhook_url)
        except Exception:
            logger.exception("设置 webhook 失败")
    yield
    # 关闭:暂无需清理。


app = FastAPI(title="Loom", lifespan=lifespan)
app.include_router(webhook_router)
app.include_router(cron_router)


@app.get("/health")
def health():
    return {"status": "ok"}
