"""sys_user 表邮箱字段幂等迁移脚本。

为存量数据库补齐邮箱推送所需字段与唯一索引（新建库经 create_all 已自带，可重复运行）：
- 新增列 email        VARCHAR(128) NULL           （推送邮箱，唯一索引 uk_email）；
- 新增列 email_bind_status TINYINT NOT NULL DEFAULT 0（绑定状态 0未绑/1已绑）。

幂等策略：先查 INFORMATION_SCHEMA.COLUMNS，列已存在则跳过对应 ALTER。

用法：
    python scripts/migrate_email_fields.py
"""
import sys
from pathlib import Path
from urllib.parse import quote_plus

# 保证以任意工作目录运行均可导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql

from app.core.config import settings


def _column_exists(cursor: pymysql.cursors.Cursor, column_name: str) -> bool:
    """检查 sys_user 表中指定列是否已存在。

    Args:
        cursor: pymysql 游标。
        column_name: 待检查的列名。

    Returns:
        bool: 列已存在返回 True，不存在返回 False。
    """
    cursor.execute(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'sys_user' AND COLUMN_NAME = %s",
        (settings.db_name, column_name),
    )
    return cursor.fetchone()[0] > 0


def migrate() -> None:
    """执行幂等迁移：缺失列逐一 ALTER TABLE 补齐。

    使用独立 pymysql 连接直连 MySQL（与 init_db.py 一致），
    全部语句执行成功后提交；重复运行不产生任何副作用。

    Raises:
        pymysql.err.OperationalError: MySQL 服务不可达或账号密码错误时抛出。
        pymysql.err.MySQLError: ALTER 语句执行失败时抛出。
    """
    conn = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cursor:
            if _column_exists(cursor, "email"):
                print("[迁移] sys_user.email 已存在，跳过")
            else:
                cursor.execute(
                    "ALTER TABLE `sys_user` "
                    "ADD COLUMN `email` VARCHAR(128) NULL DEFAULT NULL COMMENT '推送邮箱（唯一）' "
                    "AFTER `wx_bind_status`, "
                    "ADD UNIQUE INDEX `uk_email` (`email`)"
                )
                print("[迁移] 已新增 sys_user.email（VARCHAR(128) NULL，uk_email 唯一索引）")
            if _column_exists(cursor, "email_bind_status"):
                print("[迁移] sys_user.email_bind_status 已存在，跳过")
            else:
                cursor.execute(
                    "ALTER TABLE `sys_user` "
                    "ADD COLUMN `email_bind_status` TINYINT NOT NULL DEFAULT 0 "
                    "COMMENT '邮箱绑定状态 0未绑/1已绑' AFTER `email`"
                )
                print("[迁移] 已新增 sys_user.email_bind_status（TINYINT NOT NULL DEFAULT 0）")
        conn.commit()
        print("[迁移] sys_user 邮箱字段迁移完成（幂等）")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
