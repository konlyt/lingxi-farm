"""sys_user 表手机号字段幂等迁移脚本。

为存量数据库补齐手机号登录/注册所需字段与唯一索引：
- 新增列 phone VARCHAR(20) NULL（手机号，唯一索引 uk_phone）。

新建库经 create_all 已自带，本脚本仅用于老库补列，可重复运行。

用法：
    python scripts/migrate_phone_field.py
"""
import sys
from pathlib import Path

# 保证以任意工作目录运行均可导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql

from app.core.config import settings


def _column_exists(cursor: pymysql.cursors.Cursor, column_name: str) -> bool:
    """检查 sys_user 表中指定列是否已存在。"""
    cursor.execute(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'sys_user' AND COLUMN_NAME = %s",
        (settings.db_name, column_name),
    )
    return cursor.fetchone()[0] > 0


def _index_exists(cursor: pymysql.cursors.Cursor, index_name: str) -> bool:
    """检查 sys_user 表中指定索引是否已存在。"""
    cursor.execute(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'sys_user' AND INDEX_NAME = %s",
        (settings.db_name, index_name),
    )
    return cursor.fetchone()[0] > 0


def migrate() -> None:
    """执行幂等迁移：缺失列与唯一索引逐一补齐。"""
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
            if _column_exists(cursor, "phone"):
                print("[迁移] sys_user.phone 已存在，跳过列")
            else:
                cursor.execute(
                    "ALTER TABLE `sys_user` "
                    "ADD COLUMN `phone` VARCHAR(20) NULL DEFAULT NULL "
                    "COMMENT '手机号（唯一，手机号登录/注册使用）' AFTER `username`"
                )
                print("[迁移] 已新增 sys_user.phone（VARCHAR(20) NULL）")

            if _index_exists(cursor, "uk_phone"):
                print("[迁移] uk_phone 唯一索引已存在，跳过")
            else:
                cursor.execute(
                    "ALTER TABLE `sys_user` ADD UNIQUE INDEX `uk_phone` (`phone`)"
                )
                print("[迁移] 已新增 uk_phone 唯一索引")
        conn.commit()
        print("[迁移] sys_user 手机号字段迁移完成（幂等）")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
