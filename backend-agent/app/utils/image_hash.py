"""图像感知哈希（dhash）与格式校验工具模块。

基于 Pillow 实现 dhash（difference hash）算法，
用于上传图像与设备采集图像的去重（dedup_hash 字段）。
"""
from PIL import Image

# 允许上传的图像格式后缀白名单
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def get_extension(filename: str) -> str | None:
    """提取文件名中的小写扩展名并校验白名单。

    Args:
        filename: 上传文件的原始文件名。

    Returns:
        str | None: 白名单内的扩展名（如 .jpg）；不合法或不在白名单返回 None。
    """
    dot_index = filename.rfind(".")
    if dot_index < 0:
        return None
    ext = filename[dot_index:].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None
    return ext


def dhash_hex(image: Image.Image, hash_size: int = 8) -> str:
    """计算图像的 dhash 感知哈希（十六进制字符串）。

    算法：灰度化后缩放为 (hash_size+1) x hash_size，
    逐行比较相邻像素亮度，亮于右侧记 1，否则记 0，拼为 64bit 哈希。

    Args:
        image: 已打开的 PIL 图像对象。
        hash_size: 哈希边长，默认 8（输出 64bit）。

    Returns:
        str: 16 位十六进制哈希字符串。

    Raises:
        Exception: 图像数据损坏无法解码时由 Pillow 抛出。
    """
    gray = image.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    pixels = list(gray.getdata())
    bits: list[int] = []
    for row in range(hash_size):
        row_start = row * (hash_size + 1)
        for col in range(hash_size):
            left = pixels[row_start + col]
            right = pixels[row_start + col + 1]
            bits.append(1 if left > right else 0)
    # 64bit 分组转十六进制（每 4bit 一位）
    value = 0
    for bit in bits:
        value = (value << 1) | bit
    return f"{value:016x}"
