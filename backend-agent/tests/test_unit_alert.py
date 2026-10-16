"""预警聚合去重逻辑单元测试。

直接调用 app.services.alert_service 服务层函数，直连真实 MySQL 验证：
1. create_or_merge_alert 新建 active 预警（含 updates 时间线与即时推送记录）；
2. 同 case_key 再触发合并：occurrence_count+1 且不新建预警；
3. 级别升级路径：传入更高级别立即升级、occurrence 达阈值自动升级（均补即时推送，
   受 v2.5「60 分钟即时邮件节流」约束）；
4. resolve 后同 case_key 再触发新建新预警（聚合窗口关闭）；
5. create_daily_digest_push 每日汇总推送唯一（uk_digest 兜底）。

测试预警挂在本测试创建的 pytest_ 前缀地块上，用例结束自动清理，
不触碰库中演示数据。
"""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models.alert import Alert, AlertPushRecord
from app.models.user import SysUser
from app.services.alert_service import _next_level, create_daily_digest_push, create_or_merge_alert
from app.utils.time_utils import now


def _unique_case_key() -> str:
    """生成测试专用唯一聚合键（避免与库中演示预警的 case_key 冲突）。

    Returns:
        str: 形如 pytest:<随机串>:pest:pytest灰霉病 的聚合键。
    """
    return f"pytest:{uuid.uuid4().hex[:12]}:pest:pytest灰霉病"


def _enabled_user_count(db: Session) -> int:
    """统计启用状态用户数（推送记录按启用用户逐人写入）。

    Args:
        db: 数据库会话。

    Returns:
        int: 启用用户数量。
    """
    return db.query(SysUser).filter(SysUser.status == 1).count()


class TestNextLevel:
    """_next_level 级别升级规则纯函数测试。"""

    def test_incoming_higher_level_wins(self) -> None:
        """传入更高级别时取较高者（病情加重升级）。"""
        assert _next_level("info", "critical", 1) == "critical"
        assert _next_level("warning", "info", 1) == "warning"

    def test_occurrence_threshold_upgrade(self) -> None:
        """occurrence 达阈值升级：≥3 保证 warning，≥5 升 critical。"""
        assert _next_level("info", "info", 2) == "info"
        assert _next_level("info", "info", 3) == "warning"
        assert _next_level("warning", "warning", 4) == "warning"
        assert _next_level("warning", "warning", 5) == "critical"
        assert _next_level("info", "info", 99) == "critical"


class TestCreateOrMergeAlert:
    """create_or_merge_alert 聚合逻辑测试（真实数据库，测后自动清理）。"""

    def test_create_new_active_alert(self, db: Session, test_plot) -> None:
        """首次触发：新建 active 预警，occurrence_count=1，含时间线与即时推送记录。"""
        case_key = _unique_case_key()
        alert = create_or_merge_alert(
            db,
            plot_id=test_plot.id,
            alert_type="pest",
            case_key=case_key,
            title=f"{test_plot.name} 发现pytest灰霉病",
            content={"disease_name": "pytest灰霉病", "confidence": 0.9},
            level="warning",
        )
        assert alert.status == "active"
        assert alert.occurrence_count == 1
        assert alert.level == "warning"
        assert alert.case_key == case_key
        # 新建时 content 统一带 updates 时间线（首事件为「首次触发」）
        assert alert.content["updates"][0]["event"] == "首次触发"
        # 即时推送按启用用户逐人落一条记录
        push_count = (
            db.query(AlertPushRecord)
            .filter(AlertPushRecord.alert_id == alert.id, AlertPushRecord.push_type == "instant")
            .count()
        )
        assert push_count == _enabled_user_count(db)

    def test_merge_same_case_key_no_new_row(self, db: Session, test_plot) -> None:
        """同 case_key 活跃预警再次触发：不新建，occurrence_count+1，时间线追加。"""
        case_key = _unique_case_key()
        first = create_or_merge_alert(
            db, plot_id=test_plot.id, alert_type="pest", case_key=case_key,
            title="pytest首次", content={"disease_name": "pytest灰霉病"}, level="warning",
        )
        second = create_or_merge_alert(
            db, plot_id=test_plot.id, alert_type="pest", case_key=case_key,
            title="pytest再次", content={"disease_name": "pytest灰霉病", "note": "复查仍检出"}, level="warning",
        )
        assert second.id == first.id
        assert second.occurrence_count == 2
        assert len(second.content["updates"]) == 2
        assert second.content["updates"][-1]["event"] == "再次触发"
        # 数据库层验证该 case_key 活跃预警仅一条（聚合去重）
        active_rows = (
            db.query(Alert)
            .filter(Alert.case_key == case_key, Alert.status == "active")
            .all()
        )
        assert len(active_rows) == 1

    def test_level_upgrade_on_higher_incoming_level(self, db: Session, test_plot) -> None:
        """传入更高 level 立即升级，且补一条即时推送（病情加重即时提醒）。"""
        case_key = _unique_case_key()
        user_count = _enabled_user_count(db)
        alert = create_or_merge_alert(
            db, plot_id=test_plot.id, alert_type="pest", case_key=case_key,
            title="pytest升级", content={"disease_name": "pytest灰霉病"}, level="info",
        )
        assert alert.level == "info"
        # v2.5 刷屏治理：即时邮件 60 分钟节流。先把首轮推送记录的发送时间老化 2 小时
        # 豁免节流，才能验证「升级补推」行为（节流本身由 test_instant_push_throttled 覆盖）
        db.query(AlertPushRecord).filter(
            AlertPushRecord.alert_id == alert.id,
            AlertPushRecord.push_type == "instant",
        ).update({"sent_at": now() - timedelta(hours=2)}, synchronize_session=False)
        db.commit()
        merged = create_or_merge_alert(
            db, plot_id=test_plot.id, alert_type="pest", case_key=case_key,
            title="pytest升级", content={"disease_name": "pytest灰霉病"}, level="critical",
        )
        assert merged.level == "critical"
        # 新建 1 轮 + 升级 1 轮，即时推送总数 = 2 × 启用用户数
        push_count = (
            db.query(AlertPushRecord)
            .filter(AlertPushRecord.alert_id == alert.id, AlertPushRecord.push_type == "instant")
            .count()
        )
        assert push_count == 2 * user_count

    def test_instant_push_throttled_within_60min(self, db: Session, test_plot) -> None:
        """v2.5 刷屏治理：60 分钟内同预警的第二次即时推送被节流（不落新记录）。"""
        case_key = _unique_case_key()
        user_count = _enabled_user_count(db)
        alert = create_or_merge_alert(
            db, plot_id=test_plot.id, alert_type="pest", case_key=case_key,
            title="pytest节流", content={"disease_name": "pytest灰霉病"}, level="info",
        )
        # 紧接着升级（不老化 sent_at）：第二轮即时推送应被 60 分钟节流跳过
        merged = create_or_merge_alert(
            db, plot_id=test_plot.id, alert_type="pest", case_key=case_key,
            title="pytest节流", content={"disease_name": "pytest灰霉病"}, level="critical",
        )
        assert merged.level == "critical"
        push_count = (
            db.query(AlertPushRecord)
            .filter(AlertPushRecord.alert_id == alert.id, AlertPushRecord.push_type == "instant")
            .count()
        )
        sent_exists = (
            db.query(AlertPushRecord.id)
            .filter(
                AlertPushRecord.alert_id == alert.id,
                AlertPushRecord.push_type == "instant",
                AlertPushRecord.status == "sent",
            )
            .first()
        )
        if sent_exists is None:
            pytest.skip("邮件通道未配置时即时推送全部 failed，不触发 60 分钟节流，跳过")
        assert push_count == user_count  # 仅首轮落库，第二轮被节流

    def test_level_upgrade_by_occurrence_threshold(self, db: Session, test_plot) -> None:
        """occurrence 累计达阈值自动升级：5 次触发后升级为 critical。"""
        case_key = _unique_case_key()
        alert = None
        for _ in range(5):
            alert = create_or_merge_alert(
                db, plot_id=test_plot.id, alert_type="env", case_key=case_key,
                title="pytest阈值升级", content={"metric": "temp", "value": 35.0}, level="info",
            )
        assert alert is not None
        assert alert.occurrence_count == 5
        assert alert.level == "critical"

    def test_recreate_after_resolved(self, db: Session, test_plot) -> None:
        """resolve 关闭聚合窗口后，同 case_key 再触发应新建新预警（occurrence 重置为 1）。"""
        case_key = _unique_case_key()
        first = create_or_merge_alert(
            db, plot_id=test_plot.id, alert_type="pest", case_key=case_key,
            title="pytest解决前", content={"disease_name": "pytest灰霉病"}, level="warning",
        )
        # 模拟人工确认解决（status: active → resolved）
        first.status = "resolved"
        first.resolved_at = None
        db.commit()
        second = create_or_merge_alert(
            db, plot_id=test_plot.id, alert_type="pest", case_key=case_key,
            title="pytest解决后再触发", content={"disease_name": "pytest灰霉病"}, level="warning",
        )
        assert second.id != first.id
        assert second.status == "active"
        assert second.occurrence_count == 1
        rows = db.query(Alert).filter(Alert.case_key == case_key).all()
        assert len(rows) == 2

    def test_resolve_twice_same_case_ok(self, db: Session, test_plot) -> None:
        """同案例「解决→再触发→再解决」不应触发唯一键冲突。

        回归：uk_active_case 曾定义为 (case_key, status)，把已解决历史也锁死，
        同案例第二次确认解决时 MySQL 报 1062 Duplicate entry，前端 500。
        """
        case_key = _unique_case_key()
        first = create_or_merge_alert(
            db, plot_id=test_plot.id, alert_type="pest", case_key=case_key,
            title="pytest二解1", content={"disease_name": "pytest灰霉病"}, level="warning",
        )
        first.status = "resolved"
        db.commit()
        second = create_or_merge_alert(
            db, plot_id=test_plot.id, alert_type="pest", case_key=case_key,
            title="pytest二解2", content={"disease_name": "pytest灰霉病"}, level="warning",
        )
        assert second.status == "active"
        # 关键回归点：同 case_key 第二条预警再次解决，不得抛 IntegrityError(1062)
        second.status = "resolved"
        db.commit()
        db.refresh(second)
        assert second.status == "resolved"
        resolved_rows = (
            db.query(Alert)
            .filter(Alert.case_key == case_key, Alert.status == "resolved")
            .all()
        )
        assert len(resolved_rows) == 2

    def test_daily_digest_unique_per_day(self, db: Session, test_plot) -> None:
        """每日汇总推送 uk_digest 兜底：同日第二次写入返回 False 且不落库。"""
        case_key = _unique_case_key()
        alert = create_or_merge_alert(
            db, plot_id=test_plot.id, alert_type="pest", case_key=case_key,
            title="pytest每日汇总", content={"disease_name": "pytest灰霉病"}, level="warning",
        )
        first_ok = create_daily_digest_push(db, alert, date.today())
        second_ok = create_daily_digest_push(db, alert, date.today())
        assert first_ok is True
        assert second_ok is False
        digest_count = (
            db.query(AlertPushRecord)
            .filter(
                AlertPushRecord.alert_id == alert.id,
                AlertPushRecord.push_type == "daily_digest",
                AlertPushRecord.digest_date == date.today(),
            )
            .count()
        )
        assert digest_count == _enabled_user_count(db)
