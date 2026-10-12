"""图像上传业务服务模块。

处理多图上传：落盘（uploads/{yyyy_mm}/uuid.ext）、dhash 计算、
同地块感知哈希去重（duplicate 判定）与 collected_image 入库。
"""
import io
import uuid
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR
from app.core.response import BusinessException
from app.models.device import Device
from app.models.image import CollectedImage
from app.models.plot import Plot
from app.utils.image_hash import get_extension, dhash_hex
from app.utils.time_utils import now

# 上传根目录：backend-agent/uploads
UPLOAD_DIR = BASE_DIR / "uploads"


def save_upload_image(db: Session, file_bytes: bytes, filename: str, plot_id: int,
                      source: str, device_id: int | None, uploaded_by: int | None) -> dict[str, Any]:
    """保存单张上传图像并入库（含同地块感知哈希去重）。

    Args:
        db: 数据库会话。
        file_bytes: 图像文件二进制内容。
        filename: 原始文件名（用于扩展名校验）。
        plot_id: 地块/棚室ID。
        source: 来源 manual/device。
        device_id: 采集设备ID（手动上传为 None）。
        uploaded_by: 上传人ID（手动上传为当前用户）。

    Returns:
        dict: {id, url, duplicate}；duplicate=True 时 id/url 为库中已存在记录。

    Raises:
        BusinessException: 400 文件不是合法图像或扩展名不在白名单；
                           404 地块或设备不存在。
    """
    plot = db.query(Plot).filter(Plot.id == plot_id).first()
    if plot is None:
        raise BusinessException(404, "地块不存在")
    if device_id is not None:
        device = db.query(Device).filter(Device.id == device_id).first()
        if device is None:
            raise BusinessException(404, "采集设备不存在")

    ext = get_extension(filename or "")
    if ext is None:
        raise BusinessException(400, "仅支持 jpg/jpeg/png/webp/bmp 格式图片")

    # 解码校验 + 计算 dhash
    try:
        image = Image.open(io.BytesIO(file_bytes))
        image.load()
        hash_hex = dhash_hex(image)
    except BusinessException:
        raise
    except Exception:
        raise BusinessException(400, "文件不是有效图片，无法解码")

    # 同地块内感知哈希去重：命中则不重复入库
    existing = (
        db.query(CollectedImage)
        .filter(CollectedImage.dedup_hash == hash_hex, CollectedImage.plot_id == plot_id)
        .first()
    )
    if existing is not None:
        return {"id": existing.id, "url": existing.cos_url, "duplicate": True}

    # 落盘：uploads/{yyyy_mm}/uuid.ext
    current = now()
    sub_dir = f"{current.year}_{current.month:02d}"
    target_dir = UPLOAD_DIR / sub_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{uuid.uuid4().hex}{ext}"
    target_path = target_dir / file_name
    target_path.write_bytes(file_bytes)

    record = CollectedImage(
        plot_id=plot_id,
        device_id=device_id,
        source=source,
        cos_url=f"/uploads/{sub_dir}/{file_name}",
        thumb_url=None,
        quality_status="pass",
        dedup_hash=hash_hex,
        uploaded_by=uploaded_by,
        captured_at=current,
    )
    db.add(record)
    db.commit()
    return {"id": record.id, "url": record.cos_url, "duplicate": False}
