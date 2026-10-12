"""图像上传接口路由。

提供统一图像上传接口（1–4 张，手动/设备双通道），
文件落盘 uploads/{yyyy_mm}/uuid.ext，dhash 感知哈希同地块去重。
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import BusinessException, ok
from app.core.security import require_owner
from app.services.image_service import save_upload_image

router = APIRouter(prefix="/api/images", tags=["图像上传"], dependencies=[Depends(require_owner)])

# 单次上传张数限制
MIN_FILES = 1
MAX_FILES = 4


@router.post("", summary="上传图像（1–4 张，双通道统一）")
async def upload_images(
    files: list[UploadFile] = File(..., description="图像文件列表（1-4张）"),
    plot_id: int = Form(..., gt=0, description="地块/棚室ID"),
    source: str = Form("manual", description="来源 manual/device"),
    device_id: Optional[int] = Form(None, gt=0, description="采集设备ID（device 来源时可选）"),
    user=Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    """统一图像上传：保存文件、计算 dhash、同地块去重后入库。

    Args:
        files: 上传的图像文件列表（1–4 张）。
        plot_id: 地块/棚室ID。
        source: 来源标记 manual（人为通道）/ device（自动通道）。
        device_id: 采集设备ID（手动上传可空）。
        user: 当前认证用户（require_owner 依赖注入）。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 [{id, url, duplicate}]，duplicate=True 表示同地块命中已有图像。

    Raises:
        BusinessException: 400 数量超限或 source 非法；404 地块/设备不存在；400 文件非有效图片。
    """
    if not MIN_FILES <= len(files) <= MAX_FILES:
        raise BusinessException(400, f"每次上传需 {MIN_FILES}–{MAX_FILES} 张图像")
    if source not in ("manual", "device"):
        raise BusinessException(400, "source 仅支持 manual/device")
    uploaded_by = user.id if source == "manual" else None
    results = []
    for file in files:
        file_bytes = await file.read()
        item = save_upload_image(
            db=db,
            file_bytes=file_bytes,
            filename=file.filename or "",
            plot_id=plot_id,
            source=source,
            device_id=device_id,
            uploaded_by=uploaded_by,
        )
        results.append(item)
    return ok(results)
