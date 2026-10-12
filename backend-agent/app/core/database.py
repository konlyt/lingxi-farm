"""数据库连接模块。

基于 SQLAlchemy 2.0 构建 MySQL（PyMySQL 驱动）引擎与会话工厂，
统一 utf8mb4 字符集，并提供 FastAPI 依赖注入用的会话生成器
与全部 ORM 模型共用的声明式基类 `Base`。
"""
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from typing import Generator

from app.core.config import settings


class Base(DeclarativeBase):
    """全部 ORM 模型的声明式基类。

    所有模型类继承本基类，由 `create_all` 统一建表。
    """
    pass


def _build_database_url() -> str:
    """拼接 SQLAlchemy 数据库连接串。

    Returns:
        str: 形如 mysql+pymysql://user:pwd@host:port/db?charset=utf8mb4 的连接串，
             密码经 URL 编码以兼容特殊字符。
    """
    password = quote_plus(settings.db_password)
    return (
        f"mysql+pymysql://{settings.db_user}:{password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}?charset=utf8mb4"
    )


# 同步引擎：连接池预检 + 定时回收，避免 MySQL 8 小时断连问题
engine = create_engine(
    _build_database_url(),
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

# 会话工厂：不自动提交，由业务层显式 commit/rollback
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：提供一次请求内复用的数据库会话。

    Yields:
        Session: SQLAlchemy 会话实例，请求结束后无论是否异常均关闭。

    Raises:
        Exception: 数据库连接失败时在首次取连接时抛出，由全局异常处理器兜底。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
