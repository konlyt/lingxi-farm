# -*- coding: utf-8 -*-
"""评测集构建脚本：用 Pillow 合成病虫害病斑图像并生成评测集清单。

按四类病害特征模板合成 640x640 JPEG 图像（每类默认 8 张，可 --per-class 覆盖）：
- early_blight   番茄早疫病：褐色同心轮纹病斑 + 黄晕圈；
- late_blight    番茄晚疫病：水渍状、边缘不整齐的大型病斑；
- powdery_mildew 白粉病：叶面白色粉状霉层；
- healthy        健康叶片：绿色叶面无病斑。

每张图像叠加随机扰动（病斑位置/数量/大小、背景色温、叶脉走向、噪声），
产物落盘：
- backend-agent/tests/eval/images/{class_name}/{class_name}_{序号}.jpg
- backend-agent/tests/eval/eval_set.json（清单：id/image_path/label_disease/
  label_category/plot_type_hint，病种分类按 confidence_threshold_config 的
  disease_category 语义填写，病害为 common，健康为 null）。

用法：
    python scripts/build_eval_set.py [--per-class 8]

注意：重复运行会整目录重建 images/，保证评测数据自造自清、无残留。
"""
import argparse
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

# 工程根目录（backend-agent/），兼容任意工作目录启动
BACKEND_DIR = Path(__file__).resolve().parent.parent
# 评测产物根目录（相对 backend-agent）
EVAL_DIR = BACKEND_DIR / "tests" / "eval"
# 合成图像尺寸（像素）
IMAGE_SIZE = 640
# 随机种子上限（每次运行不同，保证扰动多样性）
RANDOM_SEED = 20261012


def _make_leaf_base(rng: np.random.Generator) -> Image.Image:
    """绘制带随机色温扰动的绿色叶面底图（径向渐变 + 噪声）。

    Args:
        rng: numpy 随机数生成器（控制背景色温与噪声强度）。

    Returns:
        Image.Image: RGB 模式的叶面底图。
    """
    size = IMAGE_SIZE
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    # 光斑中心随机偏移，模拟光照不均
    cx = size / 2 + rng.uniform(-60, 60)
    cy = size / 2 + rng.uniform(-60, 60)
    dist = np.sqrt(((xx - cx) / (size * 0.68)) ** 2 + ((yy - cy) / (size * 0.68)) ** 2)

    # 背景色温扰动：warm 为正偏黄绿，为负偏深绿
    base_green = rng.uniform(115, 160)
    warm = rng.uniform(-20, 30)
    green = base_green - dist * 55 + rng.normal(0, 5.0, (size, size))
    red = base_green * 0.45 + warm - dist * 28 + rng.normal(0, 4.0, (size, size))
    blue = base_green * 0.34 - dist * 16 + rng.normal(0, 4.0, (size, size))

    canvas = np.stack(
        [np.clip(red, 0, 255), np.clip(green, 0, 255), np.clip(blue, 0, 255)], axis=-1
    ).astype(np.uint8)
    return Image.fromarray(canvas, mode="RGB")


def _draw_veins(image: Image.Image, rng: np.random.Generator) -> None:
    """在叶面上绘制主叶脉与侧叶脉（深绿色线条）。

    Args:
        image: 待绘制的叶面图像（就地修改）。
        rng: 随机数生成器（控制叶脉走向与疏密）。
    """
    draw = ImageDraw.Draw(image)
    size = IMAGE_SIZE
    # 主脉：自上而下轻微弯曲
    top_x = rng.uniform(size * 0.40, size * 0.60)
    bot_x = rng.uniform(size * 0.40, size * 0.60)
    bend_x = rng.uniform(size * 0.42, size * 0.58)
    main_points = [
        (top_x + (bend_x - top_x) * (t / 10) ** 1.5, size * (t / 10))
        for t in range(11)
    ]
    vein_color = (int(rng.uniform(28, 46)), int(rng.uniform(80, 105)), int(rng.uniform(28, 44)))
    draw.line(main_points, fill=vein_color, width=int(rng.uniform(4, 6)))
    # 侧脉：从主脉向两侧斜出
    side_count = int(rng.integers(6, 10))
    for i in range(side_count):
        t = (i + 1) / (side_count + 1)
        bx, by = top_x + (bot_x - top_x) * t, size * t
        # 顶点随高度线性插值近似主脉位置
        mx = top_x + (bend_x - top_x) * (t ** 1.5)
        length = rng.uniform(120, 220)
        angle = rng.uniform(0.45, 0.85) * (1 if i % 2 == 0 else -1)
        draw.line(
            [(mx, by), (mx + math.cos(angle) * length, by + abs(math.sin(angle)) * length * 0.6)],
            fill=vein_color,
            width=int(rng.uniform(2, 3)),
        )
        draw.line(
            [(mx, by), (mx - math.cos(angle) * length, by + abs(math.sin(angle)) * length * 0.6)],
            fill=vein_color,
            width=int(rng.uniform(2, 3)),
        )


def _draw_noise(image: Image.Image, rng: np.random.Generator) -> None:
    """在图像上撒随机纹理噪点，模拟自然叶片质感与拍摄噪声。

    Args:
        image: 待绘制的图像（就地修改）。
        rng: 随机数生成器。
    """
    draw = ImageDraw.Draw(image)
    for _ in range(int(rng.integers(700, 1400))):
        x = int(rng.integers(0, IMAGE_SIZE))
        y = int(rng.integers(0, IMAGE_SIZE))
        r = int(rng.integers(1, 3))
        delta = int(rng.integers(-30, 24))
        base = image.getpixel((x, y))
        color = tuple(max(0, min(255, c + delta)) for c in base[:3])
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def _draw_early_blight(image: Image.Image, rng: np.random.Generator) -> None:
    """绘制番茄早疫病病斑：褐色同心轮纹 + 周围黄色晕圈。

    Args:
        image: 待绘制的图像（通过 RGBA 覆盖层叠加，就地修改）。
        rng: 随机数生成器（控制病斑位置/数量/大小/轮纹层数）。
    """
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    spot_count = int(rng.integers(3, 9))
    for _ in range(spot_count):
        cx = int(rng.uniform(70, IMAGE_SIZE - 70))
        cy = int(rng.uniform(70, IMAGE_SIZE - 70))
        rx = int(rng.uniform(26, 62))
        ry = int(rx * rng.uniform(0.72, 1.0))
        # 黄晕圈（病斑周围叶组织失绿）
        halo_rx, halo_ry = int(rx * rng.uniform(1.25, 1.5)), int(ry * rng.uniform(1.25, 1.5))
        draw.ellipse(
            [cx - halo_rx, cy - halo_ry, cx + halo_rx, cy + halo_ry],
            fill=(176, 186, 62, int(rng.uniform(55, 85))),
        )
        # 褐色同心轮纹：由外向内交替深浅
        rings = int(rng.integers(4, 8))
        for i in range(rings):
            f = 1.0 - i / rings
            if i % 2 == 0:
                color = (int(rng.uniform(74, 92)), int(rng.uniform(46, 58)), int(rng.uniform(20, 30)), 235)
            else:
                color = (int(rng.uniform(120, 145)), int(rng.uniform(84, 100)), int(rng.uniform(40, 55)), 235)
            draw.ellipse(
                [cx - rx * f, cy - ry * f, cx + rx * f, cy + ry * f],
                fill=color,
            )
        # 中心坏死点
        draw.ellipse(
            [cx - rx * 0.16, cy - ry * 0.16, cx + rx * 0.16, cy + ry * 0.16],
            fill=(48, 28, 12, 245),
        )
    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"), (0, 0))


def _draw_late_blight(image: Image.Image, rng: np.random.Generator) -> None:
    """绘制番茄晚疫病病斑：水渍状、边缘不整齐的大型深褐色斑块。

    Args:
        image: 待绘制的图像（通过 RGBA 覆盖层叠加，就地修改）。
        rng: 随机数生成器（控制病斑位置/数量/大小/轮廓抖动）。
    """
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    blotch_count = int(rng.integers(1, 5))
    for _ in range(blotch_count):
        cx = int(rng.uniform(120, IMAGE_SIZE - 120))
        cy = int(rng.uniform(120, IMAGE_SIZE - 120))
        base_r = int(rng.uniform(85, 150))
        sides = int(rng.integers(12, 19))
        # 不规则轮廓：极坐标顶点半径随机抖动（边缘不整齐）
        angles = sorted(rng.uniform(0, 2 * math.pi) for _ in range(sides))
        radii = [base_r * rng.uniform(0.70, 1.28) for _ in range(sides)]
        body = [
            (cx + r * math.cos(a), cy + r * math.sin(a) * rng.uniform(0.78, 1.0))
            for a, r in zip(angles, radii)
        ]
        # 水渍状扩散边缘：放大轮廓的半透明暗色晕
        halo = [(cx + (p[0] - cx) * 1.22, cy + (p[1] - cy) * 1.22) for p in body]
        draw.polygon(halo, fill=(44, 56, 36, int(rng.uniform(85, 120))))
        # 主体：深褐偏灰绿水渍斑
        draw.polygon(body, fill=(int(rng.uniform(58, 72)), int(rng.uniform(52, 64)), int(rng.uniform(34, 44)), 240))
        # 斑内深色坏死纹理
        for _ in range(int(rng.integers(2, 5))):
            px, py = cx + rng.uniform(-0.4, 0.4) * base_r, cy + rng.uniform(-0.4, 0.4) * base_r
            pr = base_r * rng.uniform(0.10, 0.24)
            draw.ellipse(
                [px - pr, py - pr * 0.7, px + pr, py + pr * 0.7],
                fill=(30, 34, 22, int(rng.uniform(140, 190))),
            )
    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"), (0, 0))


def _draw_powdery_mildew(image: Image.Image, rng: np.random.Generator) -> None:
    """绘制白粉病病征：叶面白色粉状霉层（半透明白斑簇 + 蔓延小斑）。

    Args:
        image: 待绘制的图像（通过 RGBA 覆盖层叠加，就地修改）。
        rng: 随机数生成器（控制粉层位置/范围/浓度）。
    """
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    patch_count = int(rng.integers(2, 6))
    for _ in range(patch_count):
        cx = int(rng.uniform(90, IMAGE_SIZE - 90))
        cy = int(rng.uniform(90, IMAGE_SIZE - 90))
        pr = int(rng.uniform(55, 120))
        # 粉层主体：半透明白色大椭圆
        draw.ellipse(
            [cx - pr, cy - pr * 0.75, cx + pr, cy + pr * 0.75],
            fill=(248, 248, 240, int(rng.uniform(120, 175))),
        )
        # 中心浓白核
        draw.ellipse(
            [cx - pr * 0.5, cy - pr * 0.38, cx + pr * 0.5, cy + pr * 0.38],
            fill=(255, 255, 250, int(rng.uniform(185, 225))),
        )
        # 边缘蔓延小斑：模拟粉层向外扩散
        spread = int(rng.integers(8, 16))
        for _ in range(spread):
            ang = rng.uniform(0, 2 * math.pi)
            dist = pr * rng.uniform(0.9, 1.5)
            sx = cx + dist * math.cos(ang)
            sy = cy + dist * math.sin(ang) * 0.75
            sr = rng.uniform(5, 18)
            draw.ellipse(
                [sx - sr, sy - sr * 0.7, sx + sr, sy + sr * 0.7],
                fill=(252, 252, 246, int(rng.uniform(90, 170))),
            )
    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"), (0, 0))


# 病类别绘制与标注配置：
# key 与图像子目录/文件名前缀一致，value 为 (中文病名, 病种分类, 绘制函数)
CLASS_CONFIGS: dict[str, dict[str, Any]] = {
    "early_blight": {
        "label_disease": "番茄早疫病",
        "label_category": "common",
        "renderer": _draw_early_blight,
    },
    "late_blight": {
        "label_disease": "番茄晚疫病",
        "label_category": "common",
        "renderer": _draw_late_blight,
    },
    "powdery_mildew": {
        "label_disease": "白粉病",
        "label_category": "common",
        "renderer": _draw_powdery_mildew,
    },
    "healthy": {
        "label_disease": "健康",
        "label_category": None,
        "renderer": None,
    },
}


def _synth_one(class_name: str, index: int, seed: int, out_dir: Path) -> dict[str, Any]:
    """合成单张评测图像并落盘，返回对应评测集条目。

    Args:
        class_name: 病类别英文键（与 images 子目录同名）。
        index: 类内序号（从 1 开始）。
        seed: 该图像的随机种子（背景/叶脉/扰动均由此派生）。
        out_dir: 图像输出目录（images/{class_name}）。

    Returns:
        dict: 评测集条目 {id, image_path, label_disease, label_category, plot_type_hint}。
    """
    rng = np.random.default_rng(seed)
    image = _make_leaf_base(rng)
    _draw_veins(image, rng)
    renderer = CLASS_CONFIGS[class_name]["renderer"]
    if renderer is not None:
        renderer(image, rng)
    _draw_noise(image, rng)

    file_stem = f"{class_name}_{index:03d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{file_stem}.jpg"
    image.save(out_path, format="JPEG", quality=90)

    plot_hint = "greenhouse" if rng.uniform(0, 1) < 0.6 else "open_field"
    return {
        "id": file_stem,
        "image_path": f"images/{class_name}/{file_stem}.jpg",
        "label_disease": CLASS_CONFIGS[class_name]["label_disease"],
        "label_category": CLASS_CONFIGS[class_name]["label_category"],
        "plot_type_hint": plot_hint,
    }


def build_eval_set(per_class: int) -> dict[str, Any]:
    """构建完整评测集：重建图像目录并生成 eval_set.json 清单。

    Args:
        per_class: 每类合成图像数量（≥1）。

    Returns:
        dict: 构建统计 {total, per_class, images_dir, json_path}。

    Raises:
        ValueError: per_class 小于 1 时抛出。
    """
    if per_class < 1:
        raise ValueError("per_class 必须 ≥ 1")
    images_root = EVAL_DIR / "images"
    # 自造自清：整目录重建，避免历史残留
    if images_root.exists():
        shutil.rmtree(images_root)

    entries: list[dict[str, Any]] = []
    for offset, class_name in enumerate(CLASS_CONFIGS):
        out_dir = images_root / class_name
        for index in range(1, per_class + 1):
            seed = RANDOM_SEED + offset * 10000 + index
            entries.append(_synth_one(class_name, index, seed, out_dir))

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    json_path = EVAL_DIR / "eval_set.json"
    json_path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "total": len(entries),
        "per_class": {
            name: per_class for name in CLASS_CONFIGS
        },
        "images_dir": str(images_root),
        "json_path": str(json_path),
    }


def main() -> None:
    """命令行入口：解析 --per-class 参数并构建评测集，打印统计信息。

    Raises:
        SystemExit: 参数非法或构建失败时以非零码退出。
    """
    parser = argparse.ArgumentParser(description="构建病虫害合成评测集")
    parser.add_argument(
        "--per-class",
        type=int,
        default=8,
        help="每类合成图像数量（默认 8，四类共 32 张）",
    )
    args = parser.parse_args()
    try:
        stats = build_eval_set(args.per_class)
    except Exception as exc:  # noqa: BLE001 构建失败直接退出并提示
        print(f"[错误] 评测集构建失败: {exc}")
        sys.exit(1)

    print("========== 评测集构建完成 ==========")
    print(f"图像目录: {stats['images_dir']}")
    print(f"清单文件: {stats['json_path']}")
    print(f"总条数  : {stats['total']}")
    for name, count in stats["per_class"].items():
        print(f"  - {name:<16} {count} 张  ({CLASS_CONFIGS[name]['label_disease']})")


if __name__ == "__main__":
    main()
