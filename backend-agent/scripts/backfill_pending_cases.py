"""一次性数据修复脚本：为历史诊断任务补建待确认案例。

背景（缺陷 D-04）：修复前仅低置信度路径生成案例库记录，
高置信度异常诊断无 case 关联，详情页确认/纠正操作区不显示。
本脚本扫描所有 done 状态、识别结果非 healthy 且尚无案例记录的任务，
统一补建 status=pending 的案例。

运行方式（后端虚拟环境）：
    .venv/Scripts/python.exe scripts/backfill_pending_cases.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal  # noqa: E402
from app.models.case import CaseLibrary  # noqa: E402
from app.models.diagnosis import DiagnosisResult, DiagnosisTask  # noqa: E402


def main() -> None:
    """扫描并补建案例，输出补建数量。"""
    db = SessionLocal()
    created = 0
    try:
        tasks = db.query(DiagnosisTask).filter(DiagnosisTask.status == "done").all()
        for task in tasks:
            if db.query(CaseLibrary.id).filter(CaseLibrary.task_id == task.id).first() is not None:
                continue
            result = (
                db.query(DiagnosisResult)
                .filter(DiagnosisResult.task_id == task.id, DiagnosisResult.model_path == "fused")
                .first()
            )
            if result is None:
                result = (
                    db.query(DiagnosisResult).filter(DiagnosisResult.task_id == task.id).first()
                )
            if result is None:
                continue
            raw = result.raw_output or {}
            if isinstance(raw, dict) and raw.get("healthy"):
                continue  # 健康结果不生成案例
            if not result.disease_name or result.disease_name in ("unknown", "未识别"):
                continue
            db.add(
                CaseLibrary(
                    task_id=task.id,
                    ai_disease_name=result.disease_name,
                    status="pending",
                    source=task.source or "manual",
                    disease_category=result.disease_category,
                )
            )
            created += 1
        db.commit()
        print(f"backfill done: created {created} pending cases")
    finally:
        db.close()


if __name__ == "__main__":
    main()
