"""SQLAlchemy 引擎 + Session 工厂。"""

from sqlalchemy import BigInteger, create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from . import config
from .models import Base

_database_url = config.settings.database_url
# Railway 注入的 DATABASE_URL 形如 postgres://...,SQLAlchemy 需要 postgresql://。
if _database_url.startswith("postgres://"):
    _database_url = _database_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(_database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

_CHAT_ID_TABLES = ("messages", "thoughts", "scheduled_wakeups")


def init_db() -> None:
    """建表(幂等)+ 对已存在的表做一次列类型修正。"""
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "postgresql":
        _migrate_chat_id_to_bigint()


def _migrate_chat_id_to_bigint() -> None:
    """把 chat_id 从 INTEGER 升级为 BIGINT。

    Telegram 的 chat_id 可能超过 32 位整数上限(PostgreSQL 的 INTEGER 会溢出),
    所以要用 BIGINT。已经建好的老表在这里就地改类型;新建的表模型里已用
    BigInteger,会被自动跳过。
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    tables_to_alter = []
    for table in _CHAT_ID_TABLES:
        if table not in existing_tables:
            continue
        for col in inspector.get_columns(table):
            if col["name"] == "chat_id" and not isinstance(col["type"], BigInteger):
                tables_to_alter.append(table)
                break

    with engine.begin() as conn:
        for table in tables_to_alter:
            conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN chat_id TYPE BIGINT"))
