"""测试数据与重复记录清理脚本（一次性治理）。

处理三类问题（2026-10-12 用户报告：角标重复 + 邮箱刷屏）：
1. 停用测试地块：名称以 `pytest` 或 `__eval_` 开头的地块 status=0，
   其 active 预警全部置 resolved（测试运行遗留，持续被定时任务/邮件波及）；
2. 采收禁令去重：同 (plot_id, pesticide_id, ban_until) 的 active 禁令
   仅保留最早一条，其余置 expired（修复总览页角标重复）；
3. 存量 pending 汇总记录维持 pending（由每小时聚合任务接管发送）。

运行方式（在 backend-agent 目录下）：
    .venv/Scripts/python.exe scripts/cleanup_test_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import or_  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.alert import Alert  # noqa: E402
from app.models.knowledge import HarvestRestriction  # noqa: E402
from app.models.plot import Plot  # noqa: E402
from app.utils.time_utils import now  # noqa: E402


def main() -> None:
    db = SessionLocal()

    # 1) 停用测试地块
    test_plots = (
        db.query(Plot)
        .filter(or_(Plot.name.like("pytest%"), Plot.name.like("__eval\\_%")))
        .all()
    )
    for plot in test_plots:
        plot.status = 0
    print(f"[1] 停用测试地块: {len(test_plots)} 个 → {[p.name for p in test_plots]}")

    # 2) 其 active 预警置 resolved
    resolved = 0
    for plot in test_plots:
        alerts = (
            db.query(Alert)
            .filter(Alert.plot_id == plot.id, Alert.status == "active")
            .all()
        )
        for alert in alerts:
            alert.status = "resolved"
            alert.resolved_at = now()
            resolved += 1
    print(f"[2] 测试地块 active 预警置 resolved: {resolved} 条")

    # 3) 采收禁令去重：同 (plot, pesticide, ban_until) 保留最早一条 active
    active_bans = db.query(HarvestRestriction).filter(HarvestRestriction.status == "active").all()
    groups: dict[tuple, list[HarvestRestriction]] = {}
    for ban in active_bans:
        groups.setdefault((ban.plot_id, ban.pesticide_id, ban.ban_until), []).append(ban)
    removed = 0
    for _key, rows in groups.items():
        rows.sort(key=lambda r: r.id)
        for dup in rows[1:]:
            dup.status = "expired"
            dup.released_at = now()
            removed += 1
    print(f"[3] 采收禁令去重: 移除重复 {removed} 条（保留 {len(groups)} 条）")

    db.commit()
    db.close()
    print("清理完成。")


if __name__ == "__main__":
    main()
