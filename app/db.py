"""SQLAlchemy 引擎、Session 工厂，以及小型项目所需的兼容迁移。"""

import uuid

from sqlalchemy import BigInteger, create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from . import config
from .models import Base

_database_url = config.settings.database_url
# Railway 注入的 DATABASE_URL 形如 postgres://...,SQLAlchemy 需要 postgresql://。
if _database_url.startswith("postgres://"):
    _database_url = _database_url.replace("postgres://", "postgresql://", 1)

# SQLite 本地兜底:允许跨线程使用连接(后台 worker 会从另一个线程访问)。
_connect_args = (
    {"check_same_thread": False} if _database_url.startswith("sqlite") else {}
)
engine = create_engine(_database_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

_LEGACY_CHAT_ID_TABLES = ("messages", "thoughts", "scheduled_wakeups")


def init_db() -> None:
    """建表(幂等)并把早期 Telegram-only 数据升级为内部身份模型。"""
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "postgresql":
        _migrate_chat_id_to_bigint()
    _ensure_identity_columns()
    _backfill_legacy_telegram_data()
    _ensure_agent_job_columns()
    _backfill_legacy_timer_jobs()


def _migrate_chat_id_to_bigint() -> None:
    """把 chat_id 从 INTEGER 升级为 BIGINT。

    Telegram 的 chat_id 可能超过 32 位整数上限(PostgreSQL 的 INTEGER 会溢出),
    所以要用 BIGINT。已经建好的老表在这里就地改类型;新建的表模型里已用
    BigInteger,会被自动跳过。
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    tables_to_alter = []
    for table in _LEGACY_CHAT_ID_TABLES:
        if table not in existing_tables:
            continue
        for col in inspector.get_columns(table):
            if col["name"] == "chat_id" and not isinstance(col["type"], BigInteger):
                tables_to_alter.append(table)
                break

    with engine.begin() as conn:
        for table in tables_to_alter:
            conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN chat_id TYPE BIGINT"))


def _ensure_identity_columns() -> None:
    """给旧表补上 user_id / conversation_id。

    项目还没有引入 Alembic；这一段是针对 v1 已部署数据库的窄迁移。
    新装数据库会由 metadata.create_all 直接创建完整列。
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    column_type = "VARCHAR(36)"

    with engine.begin() as conn:
        for table in _LEGACY_CHAT_ID_TABLES:
            if table not in existing_tables:
                continue
            columns = {column["name"] for column in inspector.get_columns(table)}
            if "user_id" not in columns:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN user_id {column_type}"))
            if "conversation_id" not in columns:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN conversation_id {column_type}")
                )
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS ix_{table}_user_id ON {table} (user_id)"
                )
            )
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS ix_{table}_conversation_id "
                    f"ON {table} (conversation_id)"
                )
            )


def _backfill_legacy_telegram_data() -> None:
    """把旧 chat_id 数据映射为 User / Identity / Conversation。

    早期版本没有保存 Telegram ``from.id``，因此历史私聊以 chat_id 作为
    Telegram identity 回填。新进入的消息会使用真正的 from.id。
    """
    from . import models

    session = SessionLocal()
    try:
        chat_ids = set()
        for model in (models.Message, models.Thought, models.ScheduledWakeup):
            chat_ids.update(
                chat_id
                for (chat_id,) in session.query(model.chat_id).distinct().all()
                if chat_id is not None
            )

        for chat_id in chat_ids:
            external_id = str(chat_id)
            identity = (
                session.query(models.Identity)
                .filter(
                    models.Identity.provider == "telegram",
                    models.Identity.external_id == external_id,
                )
                .one_or_none()
            )
            if identity is None:
                user = models.User(id=str(uuid.uuid4()))
                session.add(user)
                session.flush()
                identity = models.Identity(
                    user_id=user.id, provider="telegram", external_id=external_id
                )
                session.add(identity)
                session.flush()

            conversation = (
                session.query(models.Conversation)
                .filter(
                    models.Conversation.channel == "telegram",
                    models.Conversation.external_chat_id == external_id,
                )
                .one_or_none()
            )
            if conversation is None:
                conversation = models.Conversation(
                    id=str(uuid.uuid4()),
                    user_id=identity.user_id,
                    channel="telegram",
                    external_chat_id=external_id,
                )
                session.add(conversation)
                session.flush()

            for model in (models.Message, models.Thought, models.ScheduledWakeup):
                (
                    session.query(model)
                    .filter(model.chat_id == chat_id, model.user_id.is_(None))
                    .update(
                        {
                            model.user_id: identity.user_id,
                            model.conversation_id: conversation.id,
                        },
                        synchronize_session=False,
                    )
                )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _ensure_agent_job_columns() -> None:
    """兼容极少数已经部署过早期 AgentJob 表的实例。"""
    inspector = inspect(engine)
    if "agent_jobs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("agent_jobs")}
    if "result_text" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE agent_jobs ADD COLUMN result_text TEXT"))


def _backfill_legacy_timer_jobs() -> None:
    """为 Cron 时代尚未触发的 timer 创建新的持久任务。"""
    from . import models

    session = SessionLocal()
    try:
        existing_wakeup_ids = {
            (job.payload or {}).get("scheduled_wakeup_id")
            for job in session.query(models.AgentJob).all()
            if (job.payload or {}).get("scheduled_wakeup_id") is not None
        }
        wakeups = (
            session.query(models.ScheduledWakeup)
            .filter(
                models.ScheduledWakeup.status == "pending",
                models.ScheduledWakeup.user_id.is_not(None),
                models.ScheduledWakeup.conversation_id.is_not(None),
            )
            .all()
        )
        for wakeup in wakeups:
            if wakeup.id in existing_wakeup_ids:
                continue
            session.add(
                models.AgentJob(
                    id=str(uuid.uuid4()),
                    user_id=wakeup.user_id,
                    conversation_id=wakeup.conversation_id,
                    kind="timer",
                    run_at=wakeup.fire_at,
                    payload={
                        "wake_reason": f"定时器到点,当时的理由是:「{wakeup.reason}」",
                        "scheduled_wakeup_id": wakeup.id,
                    },
                    status="pending",
                )
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
