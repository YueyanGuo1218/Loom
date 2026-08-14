"""SQLAlchemy 引擎 + Session 工厂。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from . import config
from .models import Base

_database_url = config.settings.database_url
# Railway 注入的 DATABASE_URL 形如 postgres://...,SQLAlchemy 需要 postgresql://。
if _database_url.startswith("postgres://"):
    _database_url = _database_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(_database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """建表(幂等,重复调用无害)。"""
    Base.metadata.create_all(bind=engine)
