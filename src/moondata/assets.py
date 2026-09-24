"""文档素材：从数据盘生成文档站用的图与逐 ROI 事实，输出入库到 `docs/assets/`。

    python scripts/make_assets.py basemap <lroc_color_poles_4k.tif>
    python scripts/make_assets.py samples
    python scripts/make_assets.py facts [ROI_054 ...]
    python scripts/make_assets.py overlays [ROI_054 ...]

按组分开，每组可单独重跑；`facts`、`overlays` 带 ROI 时只重做这几个，其余条目保留。
站点生成器（`moondata.site`）只读这些入库的产物，所以数据盘不在也能重建文档站。

读 CE-2 分幅一律经 `raster.read_footprint`：头里 `lat_ts` 写错的 5 幅由它按
`sources.LAT_TS_CORRECTIONS` 纠正，与两个编号脚本同一处，叠合图才不会错位。
**数据盘只读**，本模块只往 `docs/assets/` 写。
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image

from moondata import raster
from moondata.config import Config
from moondata.geometry import PixelGrid
from moondata.sources import (
    ASSETS_RELDIR,
    CE2_TILE,
    FACTS_NAME,
    OVERLAY_NAME,
    SAMPLES_NAME,
    dataset_overlap_images,
    dataset_patch_dir,
    ground_truth_files,
    load_roi_table,
    load_tie_points,
    locate_inputs,
    padded_roi,
)

STRETCH_PERCENTILES = (2, 98)
"""灰度拉伸取有效像素的这两个分位，亮暗两端各截掉一点，月面细节才看得出来。"""


# ---------------------------------------------------------------------------
# 全月底图


BASEMAP_SIZES = {"moon-4k.jpg": (4096, 2048), "moon-2k.jpg": (2048, 1024)}


def make_basemap(config: Config, source: Path) -> None:
    """首页与 ROI 页的全月底图：灰度、等距圆柱、经度 −180°–180° 从左到右。

    来源是 NASA SVS 4720「CGI Moon Kit」的 LRO LROC WAC 彩色拼图
    `lroc_color_poles_4k.tif`（https://svs.gsfc.nasa.gov/4720）。原始 TIFF 不入库，
    路径由命令行给出。
    """
    width, height = BASEMAP_SIZES["moon-4k.jpg"]
    array, _ = raster.preview(source, width, height, bands=(1, 2, 3))
    image = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8).transpose(1, 2, 0), "RGB").convert("L")
    out = _assets(config)
    for name, size in BASEMAP_SIZES.items():
        resized = image if image.size == size else image.resize(size, Image.LANCZOS)
        resized.save(out / name, quality=85, optimize=True)
        print(f"  已写出 {out / name}", flush=True)


# ---------------------------------------------------------------------------
# 首页样例


SAMPLE_PROBE = 128
"""挑样例时把光学 patch 降到这个边长来判有没有无数据、纹理够不够。"""


def make_samples(config: Config) -> None:
    """验证集、测试集每个 ROI 挑一对带评测真值点的 patch：没有无数据像素，真值点多、
    光学纹理丰富的优先。写 `samples/<ROI>_p<n>_{opt,sar}.jpg` 与 `samples.json`。

    真值点本身不复制：生成器从 `data/ground-truth/` 读。
    """
    data_root = config.require_data_root()
    out = _assets(config) / "samples"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    chosen = []
    for row in load_roi_table(config.repo_root):
        if row.split == "Train":
            continue
        patch_dir = dataset_patch_dir(data_root, row.split, row.roi)
        best: tuple[float, int] | None = None
        for truth in ground_truth_files(config.repo_root, row.split, row.roi):
            number = _patch_number(truth)
            optical, _ = raster.preview(patch_dir / "Optical" / f"patch_{number}.tif", SAMPLE_PROBE, SAMPLE_PROBE)
            if (optical == 0).any():
                continue
            score = _count_lines(truth) * 5 + float(optical.std())
            if best is None or score > best[0]:
                best = (score, number)
        if best is None:
            print(f"  {row.roi}：没有合适的样例", flush=True)
            continue
        number = best[1]
        _render_sample(patch_dir, number, out / f"{row.roi}_p{number}")
        chosen.append({"roi": row.roi, "split": row.split, "patch": number})
        print(f"  {row.roi}：patch_{number}", flush=True)
    _write_json(_assets(config) / SAMPLES_NAME, chosen)


def _render_sample(patch_dir: Path, number: int, stem: Path) -> None:
    """光学按灰度拉伸；SAR 画总功率 S1 = 波段 1 + 波段 2，取 dB 后拉伸。"""
    optical, _ = raster.preview(patch_dir / "Optical" / f"patch_{number}.tif", 512, 512)
    _gray(optical[0], optical[0] > 0).save(stem.with_name(stem.name + "_opt.jpg"), quality=88)
    sar, _ = raster.preview(patch_dir / "SAR" / f"patch_{number}.tif", 512, 512, bands=(1, 2))
    decibels = _decibels(sar[0], sar[1])
    _gray(np.nan_to_num(decibels), np.isfinite(decibels)).save(stem.with_name(stem.name + "_sar.jpg"), quality=88)


# ---------------------------------------------------------------------------
# 逐 ROI 事实


def make_facts(config: Config, rois: Sequence[str]) -> None:
    """ROI 页与总表要的逐 ROI 事实，写入 `roi-facts.json`。

    元数据表已有的列（产品 ID、成像时刻、入射角、视向、条带尺寸）不复制，生成器直接
    读原表。
    """
    data_root = config.require_data_root()
    splits = {row.roi: row.split for row in load_roi_table(config.repo_root)}
    path = _assets(config) / FACTS_NAME
    facts = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    for roi in [padded_roi(name) for name in rois] or sorted(splits):
        facts[roi] = roi_facts(config, data_root, roi, splits[roi])
        print(f"  {roi}：{facts[roi]['patches']} 对 patch，{len(facts[roi]['frames'])} 幅分幅", flush=True)
    _write_json(path, {roi: facts[roi] for roi in sorted(facts) if roi in splits})


def roi_facts(config: Config, data_root: Path, roi: str, split: str) -> dict:
    """一个 ROI 的事实。重叠区影像取数据盘上现有数据集的那一对：文档描述的是盘上的
    数据集，不是 `01_overlap.py` 在 `work/` 下的产物。"""
    inputs = locate_inputs(data_root, roi)
    frames = []
    for path in inputs.optical_tiles:
        footprint = raster.read_footprint(path, ce2_tile=True)
        grid = raster.read_grid(path)
        frames.append({
            "id": path.stem,
            "tile": CE2_TILE.match(path.name).group(1),
            # 纠正后的坐标系：`lat_ts` 写错的 5 幅在这里就是正确值
            "projection": raster.projection_params(footprint.crs_wkt),
            "pixel": grid.resolution,
            "size": [grid.width, grid.height],
        })
    optical, _ = dataset_overlap_images(data_root, roi)
    grid = raster.read_grid(optical)
    box = raster.read_footprint(optical, ce2_tile=False).lonlat.shifted_near(0.0)

    numbers = sorted(
        _patch_number(p) for p in (dataset_patch_dir(data_root, split, roi) / "Optical").glob("patch_*.tif")
    )
    truth = ground_truth_files(config.repo_root, split, roi)
    return {
        "patches": len(numbers),
        "last_patch": numbers[-1],
        "missing": sorted(set(range(numbers[-1] + 1)) - set(numbers)),
        "truth_patches": len(truth) or None,
        "truth_points": sum(_count_lines(p) for p in truth) or None,
        "tie_points": len(load_tie_points(config.repo_root, roi)[0]),
        "center": [round(box.centre_lon, 3), round((box.south + box.north) / 2, 3)],
        "bbox": [round(value, 4) for value in box],
        "frames": frames,
        "overlap": {
            "projection": raster.projection_params(grid.crs_wkt),
            "pixel": grid.resolution,
            "size": [grid.width, grid.height],
        },
    }


# ---------------------------------------------------------------------------
# 原始产品叠合图


OVERLAY_SIDE = 1600
"""叠合图画布的长边（像素）。67 个 ROI 的图层合计约 20 MB。"""
LAYER_FORMAT = {"format": "WEBP", "quality": 75, "method": 6}
"""有损 WebP 带透明通道：一幅分幅约 140 KB，同尺寸 PNG 要 600 KB。"""
READ_OVERSAMPLING = 2
"""源影像按画布分辨率的这么多倍读进来，再按均值落到画布上，比直接隔行取点平滑。"""


def make_overlays(config: Config, rois: Sequence[str]) -> None:
    """各 CE-2 分幅与 Mini-RF 条带重投影到重叠区影像的坐标系，画在同一张画布上。

    每幅分幅、条带各写一张带透明通道的灰度 WebP（`overlay/<ROI>/ce2_<幅号>.webp`、
    `sar.webp`），画布尺寸与各图层、重叠区在画布上的相对位置写入 `overlay.json`。
    """
    data_root = config.require_data_root()
    table = [row.roi for row in load_roi_table(config.repo_root)]
    path = _assets(config) / OVERLAY_NAME
    meta = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    for roi in [padded_roi(name) for name in rois] or table:
        meta[roi] = render_overlay(data_root, roi, _assets(config) / "overlay" / roi)
        print(f"  {roi}：画布 {meta[roi]['size'][0]}×{meta[roi]['size'][1]}，图宽 {meta[roi]['width_km']} km", flush=True)
    _write_json(path, {roi: meta[roi] for roi in sorted(meta) if roi in table})


def render_overlay(data_root: Path, roi: str, out: Path) -> dict:
    """画布取各分幅与条带在重叠区影像坐标系里的并集，长边 `OVERLAY_SIDE`；返回写进
    `overlay.json` 的一项。"""
    inputs = locate_inputs(data_root, roi)
    tiles = [raster.read_footprint(path, ce2_tile=True) for path in inputs.optical_tiles]
    sar = raster.read_footprint(inputs.sar, ce2_tile=False)
    target = raster.read_grid(dataset_overlap_images(data_root, roi)[0])

    boxes = {fp.path: raster.bounds_in(fp.path, fp.crs_wkt, target.crs_wkt) for fp in [*tiles, sar]}
    left = min(b[0] for b in boxes.values())
    bottom = min(b[1] for b in boxes.values())
    right = max(b[2] for b in boxes.values())
    top = max(b[3] for b in boxes.values())
    resolution = max(right - left, top - bottom) / OVERLAY_SIDE
    canvas = PixelGrid(
        target.crs_wkt, left, top, resolution, round((right - left) / resolution), round((top - bottom) / resolution)
    )

    layers = []
    for footprint in tiles:
        array, transform = _read_for(footprint.path, resolution)
        band = np.where(array[0] > 0, array[0], np.nan)
        layers.append((footprint, raster.warp_array(band, transform, footprint.crs_wkt, canvas)))
    array, transform = _read_for(sar.path, resolution, bands=(1, 2))
    strip = raster.warp_array(_decibels(array[0], array[1]), transform, sar.crs_wkt, canvas)

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    # 各分幅共用一组拉伸，拼在一起时亮度连续
    valid = np.concatenate([layer[np.isfinite(layer)] for _, layer in layers])
    low, high = np.percentile(valid, STRETCH_PERCENTILES) if valid.size else (0.0, 1.0)
    frames = []
    for footprint, layer in layers:
        tile = CE2_TILE.match(footprint.path.name).group(1)
        _gray_alpha(layer, low, high).save(out / f"ce2_{tile}.webp", **LAYER_FORMAT)
        frames.append({"tile": tile, "id": footprint.path.stem, "box": _relative(boxes[footprint.path], canvas)})
    low, high = np.nanpercentile(strip, STRETCH_PERCENTILES) if np.isfinite(strip).any() else (0.0, 1.0)
    _gray_alpha(strip, low, high).save(out / "sar.webp", **LAYER_FORMAT)
    return {
        "size": [canvas.width, canvas.height],
        "width_km": round((right - left) / 1000),
        "overlap": _relative(target.bounds, canvas),
        "frames": frames,
        "sar": _relative(boxes[sar.path], canvas),
    }


def _read_for(path: Path, resolution: float, bands: Sequence[int] = (1,)) -> tuple[np.ndarray, tuple]:
    """按画布分辨率的 `READ_OVERSAMPLING` 倍降采样读入。"""
    grid = raster.read_grid(path)
    factor = max(1.0, resolution / READ_OVERSAMPLING / grid.resolution)
    return raster.preview(path, math.ceil(grid.width / factor), math.ceil(grid.height / factor), bands)


def _relative(bounds: tuple[float, float, float, float], canvas: PixelGrid) -> list[float]:
    """投影坐标范围 → 画布上的 `[x, y, 宽, 高]`，都是画布宽高的比例。"""
    min_x, min_y, max_x, max_y = bounds
    width, height = canvas.width * canvas.resolution, canvas.height * canvas.resolution
    return [
        round((min_x - canvas.origin_x) / width, 4),
        round((canvas.origin_y - max_y) / height, 4),
        round((max_x - min_x) / width, 4),
        round((max_y - min_y) / height, 4),
    ]


# ---------------------------------------------------------------------------


def _assets(config: Config) -> Path:
    path = config.repo_root / ASSETS_RELDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _patch_number(path: Path) -> int:
    return int(path.stem.split("_")[1])


def _count_lines(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _decibels(h_power: np.ndarray, v_power: np.ndarray) -> np.ndarray:
    """总功率 S1 = 波段 1 + 波段 2，取 dB；非正值与 Mini-RF 的填充值（−3.4e38）记为 NaN。
    按 float64 相加：两个填充值相加会溢出 float32。"""
    power = h_power.astype(np.float64) + v_power
    valid = np.isfinite(power) & (power > 0)
    return np.where(valid, 10 * np.log10(np.where(valid, power, 1)), np.nan).astype(np.float32)


def _gray(array: np.ndarray, valid: np.ndarray) -> Image.Image:
    low, high = np.percentile(array[valid], STRETCH_PERCENTILES) if valid.any() else (0.0, 1.0)
    return Image.fromarray(_scale(array, low, high), "L")


def _gray_alpha(array: np.ndarray, low: float, high: float) -> Image.Image:
    valid = np.isfinite(array)
    gray = _scale(np.where(valid, array, low), low, high)
    return Image.fromarray(np.dstack([gray, np.where(valid, 255, 0).astype(np.uint8)]), "LA")


def _scale(array: np.ndarray, low: float, high: float) -> np.ndarray:
    return (np.clip((array - low) / (high - low + 1e-9), 0, 1) * 255).astype(np.uint8)


def _write_json(path: Path, document: object) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
