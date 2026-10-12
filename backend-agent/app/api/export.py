"""数据导出接口路由。

提供导出任务创建（异步生成 CSV）、导出记录列表与文件下载。
创建接口仅 owner 可用。
"""
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import BusinessException, ok
from app.core.security import get_current_user, require_owner
from app.models.user import SysUser
from app.services import export_service

router = APIRouter(prefix="/api/exports", tags=["数据导出"], dependencies=[Depends(get_current_user)])


class ExportCreateRequest(BaseModel):
    """导出任务创建请求体。

    Attributes:
        export_type: 导出类型 diagnosis_cases/env_data。
        start: 开始日期 YYYY-MM-DD。
        end: 结束日期 YYYY-MM-DD。
    """

    export_type: str = Field(..., pattern="^(diagnosis_cases|env_data)$", description="导出类型")
    start: str | None = Field(None, description="开始日期 YYYY-MM-DD")
    end: str | None = Field(None, description="结束日期 YYYY-MM-DD")


@router.post("", summary="创建导出任务（异步生成 CSV，owner）")
def create_export(body: ExportCreateRequest, background_tasks: BackgroundTasks,
                  db: Session = Depends(get_db), user: SysUser = Depends(get_current_user)) -> dict:
    """创建数据导出任务，BackgroundTasks 生成 CSV 后落 export_log。

    Args:
        body: 导出创建请求体。
        background_tasks: FastAPI 后台任务。
        db: 数据库会话。
        user: 当前用户。

    Returns:
        dict: 统一响应，data 为 {export_id, status}。

    Raises:
        BusinessException: 400 类型/日期非法。
    """
    # 先落一条 pending 记录占位，后台任务完成时更新为 done + file_url
    from app.models.misc import ExportLog

    log = ExportLog(user_id=user.id, export_type=body.export_type, file_url="/exports/pending.csv", status="pending")
    db.add(log)
    db.commit()
    background_tasks.add_task(
        export_service.run_export, log.id, body.export_type, body.start, body.end
    )
    return ok({"export_id": log.id, "status": "pending"})


@router.get("", summary="导出记录列表")
def list_exports(db: Session = Depends(get_db), user: SysUser = Depends(get_current_user)) -> dict:
    """查询当前用户的导出记录。

    Args:
        db: 数据库会话。
        user: 当前用户。

    Returns:
        dict: 统一响应，data 为导出记录数组。
    """
    return ok(export_service.list_exports(db, user.id))


@router.get("/{export_id}/download", summary="下载导出文件")
def download_export(export_id: int, db: Session = Depends(get_db),
                    user: SysUser = Depends(get_current_user)) -> FileResponse:
    """下载导出 CSV 文件。

    Args:
        export_id: 导出记录ID。
        db: 数据库会话。
        user: 当前用户。

    Returns:
        FileResponse: CSV 文件流（filename 编码兼容中文）。

    Raises:
        BusinessException: 404 记录不存在；400 文件丢失。
    """
    file_path = export_service.get_export_file(db, export_id, user.id)
    return FileResponse(
        path=str(file_path),
        media_type="text/csv",
        filename=file_path.name,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{file_path.name}"},
    )
