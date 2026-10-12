"""图像感知哈希（dhash）与上传去重/质量标记单元测试。

验证内容：
1. dhash_hex：同一图像两次哈希一致（确定性）、不同图像哈希不同（可区分性）、
   输出为 16 位十六进制字符串；
2. save_upload_image 同地块感知哈希去重（重复上传返回 duplicate=True 且不重复入库）、
   入库记录 quality_status 质量标记（合法图像标记为 pass）、dedup_hash 落库一致；
3. get_extension 扩展名白名单校验（非法扩展名拒绝上传并返回 400 业务异常）。

上传文件与图像记录挂在 pytest_ 前缀测试地块上，用例结束自动清理。
"""
import io

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app.core.response import BusinessException
from app.models.image import CollectedImage
from app.services.image_service import save_upload_image
from app.utils.image_hash import dhash_hex, get_extension
from conftest import make_png_bytes


def _open_png(png_bytes: bytes) -> Image.Image:
    """从字节流解码 PIL 图像对象。

    Args:
        png_bytes: PNG 图像字节流。

    Returns:
        Image.Image: 已加载像素的 PIL 图像。
    """
    image = Image.open(io.BytesIO(png_bytes))
    image.load()
    return image


class TestDhash:
    """dhash 感知哈希算法测试。"""

    def test_same_image_identical_hash(self) -> None:
        """同一图像两次计算哈希必须完全一致（确定性）。"""
        png_bytes = make_png_bytes(seed=0)
        hash_first = dhash_hex(_open_png(png_bytes))
        hash_second = dhash_hex(_open_png(png_bytes))
        assert hash_first == hash_second

    def test_different_images_different_hash(self) -> None:
        """不同图像哈希必须不同（可区分性，用于去重判定）。"""
        hash_first = dhash_hex(_open_png(make_png_bytes(seed=0)))
        hash_second = dhash_hex(_open_png(make_png_bytes(seed=1)))
        assert hash_first != hash_second

    def test_hash_is_16_hex_chars(self) -> None:
        """dhash 输出为 64bit（16 个十六进制字符）。"""
        value = dhash_hex(_open_png(make_png_bytes(seed=2)))
        assert len(value) == 16
        int(value, 16)  # 非法十六进制字符会抛 ValueError

    def test_hash_stable_across_decoding_roundtrip(self) -> None:
        """同一图像重新编码（PNG 往返）后哈希保持一致（对编码噪声不敏感）。"""
        png_bytes = make_png_bytes(seed=3)
        image = _open_png(png_bytes)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        assert dhash_hex(image) == dhash_hex(_open_png(buffer.getvalue()))


class TestUploadDedup:
    """上传链路：感知哈希去重与质量标记测试。"""

    def test_duplicate_upload_returns_existing(self, db: Session, test_plot) -> None:
        """同地块上传同一图像：第二次返回 duplicate=True，且指向同一条已有记录。"""
        png_bytes = make_png_bytes(seed=4)
        filename = "pytest_dedup.png"
        first = save_upload_image(
            db, file_bytes=png_bytes, filename=filename, plot_id=test_plot.id,
            source="manual", device_id=None, uploaded_by=None,
        )
        second = save_upload_image(
            db, file_bytes=png_bytes, filename=filename, plot_id=test_plot.id,
            source="manual", device_id=None, uploaded_by=None,
        )
        assert first["duplicate"] is False
        assert second["duplicate"] is True
        assert second["id"] == first["id"]
        # 数据库中该地块该哈希仅一条记录（uk_dedup 语义）
        rows = (
            db.query(CollectedImage)
            .filter(CollectedImage.plot_id == test_plot.id)
            .all()
        )
        assert len(rows) == 1

    def test_different_images_not_deduplicated(self, db: Session, test_plot) -> None:
        """不同图像哈希不同：两次上传均入库且 dedup_hash 互不相同。"""
        first = save_upload_image(
            db, file_bytes=make_png_bytes(seed=5), filename="pytest_a.png", plot_id=test_plot.id,
            source="manual", device_id=None, uploaded_by=None,
        )
        second = save_upload_image(
            db, file_bytes=make_png_bytes(seed=6), filename="pytest_b.png", plot_id=test_plot.id,
            source="manual", device_id=None, uploaded_by=None,
        )
        assert first["duplicate"] is False
        assert second["duplicate"] is False
        assert first["id"] != second["id"]
        hashes = {
            row.dedup_hash
            for row in db.query(CollectedImage).filter(CollectedImage.plot_id == test_plot.id).all()
        }
        assert len(hashes) == 2

    def test_quality_marked_pass_for_valid_image(self, db: Session, test_plot) -> None:
        """合法图像入库时质量标记 quality_status = pass。"""
        save_upload_image(
            db, file_bytes=make_png_bytes(seed=7), filename="pytest_quality.png", plot_id=test_plot.id,
            source="manual", device_id=None, uploaded_by=None,
        )
        record = (
            db.query(CollectedImage)
            .filter(CollectedImage.plot_id == test_plot.id)
            .first()
        )
        assert record is not None
        assert record.quality_status == "pass"

    def test_invalid_extension_rejected(self, db: Session, test_plot) -> None:
        """非白名单扩展名拒绝上传（BusinessException 400），不产生图像记录。"""
        with pytest.raises(BusinessException) as exc_info:
            save_upload_image(
                db, file_bytes=b"not-an-image", filename="pytest_payload.txt", plot_id=test_plot.id,
                source="manual", device_id=None, uploaded_by=None,
            )
        assert exc_info.value.code == 400
        assert db.query(CollectedImage).filter(CollectedImage.plot_id == test_plot.id).count() == 0


class TestExtensionWhitelist:
    """扩展名白名单校验测试。"""

    @pytest.mark.parametrize(
        "filename, expected",
        [(".PNG", ".png"), ("a.jpg", ".jpg"), ("b.JPEG", ".jpeg"), ("c.webp", ".webp"), ("d.BMP", ".bmp")],
        ids=["png大小写", "jpg", "jpeg", "webp", "bmp"],
    )
    def test_allowed_extensions(self, filename: str, expected: str) -> None:
        """白名单内扩展名（大小写不敏感）返回小写形式。"""
        assert get_extension(filename) == expected

    @pytest.mark.parametrize(
        "filename", ["no_ext", "e.gif", "f.pdf", "g.tar.gz.docx"],
        ids=["无扩展名", "gif不在白名单", "pdf不在白名单", "非图片扩展"],
    )
    def test_rejected_filenames(self, filename: str) -> None:
        """白名单外或无扩展名返回 None。"""
        assert get_extension(filename) is None
