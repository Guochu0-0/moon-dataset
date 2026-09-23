"""来源文档里「从名字反查来源」的规则：Mini-RF 产品 ID、CE-2 分幅名，以及条带元数据的汇总。

规则写成代码而不是只写在文档里，是因为两处都有**独立的第二来源**可以对账：产品 ID 的解码
结果能与元数据表（抄自官方标签）逐行比对，CE-2 分幅的经纬范围能与 geotransform 反算的
实测范围比对。文档里的解码表和分带表都由这里生成，对账失败就是测试失败，而不是一张
悄悄写错的表。

纯标准库，不碰地理库：分幅名到经纬范围只是查表加算术。
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass

from moondata.errors import MetadataUnreadable
from moondata.metadata import MetadataRow
from moondata.stats import SPLITS

# ---------------------------------------------------------------------------
# Mini-RF 产品 ID。各段取值抄自 SIS（MRF-4009）§4.7.1.1 与表 16。

_INSTRUMENT = {"L": "LRO", "F": "Forerunner", "B": "Both"}
_FREQUENCY = {"S": "S-band", "X": "X-band", "B": "Both", "N": "N/A"}
_MODE = {
    "B": "Baseline SAR", "I": "Interferometry", "S": "Scatterometry", "Z": "Zoom",
    "A": "Arecibo 定标", "G": "Greenbank 定标", "C": "其他定标", "O": "其他（遥测等）",
}
_LEVEL = {"R": "Raw PDR", "1": "Level 1", "2": "Level 2", "3": "Level 3"}
_FILE_TYPE = {
    "PD": "Packetized Data Record", "CD": "Calibrated Data Record",
    "S1": "Stokes 参数 1", "S2": "Stokes 参数 2", "S3": "Stokes 参数 3", "S4": "Stokes 参数 4",
    "SC": "同向圆极化图像", "OC": "反向圆极化图像", "CP": "圆极化比图像", "HK": "仪器遥测",
}
_PROJECTION = {
    "O": "Oblique cylindrical", "E": "Equirectangular", "P": "Polar stereographic", "X": "N/A",
}
BIN_PPD = {letter: 2**i for i, letter in enumerate("ABCDEFGHIJKLMNO")}
"""档位字母 → 每度像素数（SIS 表 16）。表里 A=1 ppd，此后每个字母翻一倍。"""
_VALUE_TYPE = {"U": "Unnormalized float", "F": "Normalized float", "B": "Byte"}

_PRODUCT_ID = re.compile(
    r"([LFB])([SXBN])([BISZAGCO])_(\d{5})_([R123])(PD|CD|S[1-4]|SC|OC|CP|HK)_"
    r"([OEPX])([A-OX])([UFB])_(\d{2})([NS])(\d{3})_V(\d)"
)


@dataclass(frozen=True)
class Segment:
    code: str
    field: str
    meaning: str


@dataclass(frozen=True)
class ProductId:
    text: str
    instrument: str
    band: str
    mode: str
    orbit: int
    level: str
    file_type: str
    projection: str
    bin_letter: str
    bin_ppd: int | None
    value_type: str
    center_lat: int
    """带符号，南纬为负。"""
    center_lon: int
    """东经 0–359。"""
    version: int
    codes: tuple[str, ...]
    """ID 里逐段的原文，与 `segments()` 一一对应。"""

    def segments(self) -> list[Segment]:
        """按 ID 中的顺序逐段列出，给文档的解码表用。"""
        m = ("",) + self.codes
        ppd = f"{self.bin_ppd} ppd" if self.bin_ppd is not None else "N/A"
        return [
            Segment(m[1], "平台", self.instrument),
            Segment(m[2], "频段", self.band),
            Segment(m[3], "雷达模式", self.mode),
            Segment(m[4], "轨道号（开始采集的那一轨）", str(self.orbit)),
            Segment(m[5], "处理级别", self.level),
            Segment(m[6], "文件类型", self.file_type),
            Segment(m[7], "投影", self.projection),
            Segment(m[8], "分辨率档位", ppd),
            Segment(m[9], "数值类型", self.value_type),
            Segment(m[10], "中心纬度（取整到度）", f"{abs(self.center_lat)}°"),
            Segment(m[11], "纬度半球", "北纬" if self.center_lat >= 0 else "南纬"),
            Segment(m[12], "中心经度（取整到度，东经 0–359）", f"{self.center_lon}°"),
            Segment(m[13], "产品版本", str(self.version)),
        ]


def decode_product_id(text: str) -> ProductId:
    """按 SIS 的命名规则解码。大小写都认：数据盘上的 SAR 文件名是小写的。"""
    upper = text.strip().upper()
    m = _PRODUCT_ID.fullmatch(upper)
    if m is None:
        raise MetadataUnreadable(f"不是 Mini-RF 产品 ID 的格式：{text!r}")
    lat = int(m[10])
    return ProductId(
        text=upper,
        instrument=_INSTRUMENT[m[1]],
        band=_FREQUENCY[m[2]],
        mode=_MODE[m[3]],
        orbit=int(m[4]),
        level=_LEVEL[m[5]],
        file_type=_FILE_TYPE[m[6]],
        projection=_PROJECTION[m[7]],
        bin_letter=m[8],
        bin_ppd=BIN_PPD.get(m[8]),
        value_type=_VALUE_TYPE[m[9]],
        center_lat=lat if m[11] == "N" else -lat,
        center_lon=int(m[12]),
        version=int(m[13]),
        codes=m.groups()[:12] + (f"V{m[13]}",),
    )


# ---------------------------------------------------------------------------
# CE-2 7 m DOM 的分幅。
#
# 分带、分行、分列的规则没有见到官方原文，是从本数据集用到的全部分幅的名字与
# geotransform 归纳出来的：每条纬度带 14°，分南北两行（行号 1 在北），列从西经 180°
# 起按固定经度宽度编号；标准纬线取在带的正中。极区（70° 以外）用极射赤面投影，
# 本数据集没有用到。

@dataclass(frozen=True)
class Ce2Band:
    letter: str
    south: int
    north: int
    lat_ts: int
    """墨卡托标准纬线，带符号。"""
    column_width: float
    """每幅的经度宽度（度）。"""


CE2_BANDS = (
    Ce2Band("C", 56, 70, 63, 15),
    Ce2Band("D", 42, 56, 49, 10),
    Ce2Band("E", 28, 42, 35, 9),
    Ce2Band("F", 14, 28, 21, 8),
    Ce2Band("G", 0, 14, 7, 7.5),
    Ce2Band("H", -14, 0, -7, 7.5),
    Ce2Band("I", -28, -14, -21, 8),
    Ce2Band("J", -42, -28, -35, 9),
    Ce2Band("K", -56, -42, -49, 10),
    Ce2Band("L", -70, -56, -63, 15),
)
_BANDS_BY_LETTER = {band.letter: band for band in CE2_BANDS}
_CE2_TILE = re.compile(r"_([A-Z])([12])(\d{2})_(\d{2})([NS])(\d{3})([EW])")


@dataclass(frozen=True)
class Ce2Tile:
    code: str
    """如 `G203`。"""
    band: Ce2Band
    row: int
    column: int
    name_lat: int
    name_lon: int
    """名字里写的经纬度，带符号（南纬、西经为负）。"""

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """（南, 北, 西, 东），度。"""
        half = (self.band.north - self.band.south) / 2
        north = self.band.north - (self.row - 1) * half
        west = -180 + (self.column - 1) * self.band.column_width
        return north - half, north, west, west + self.band.column_width


def parse_ce2_tile(name: str) -> Ce2Tile:
    m = _CE2_TILE.search(name)
    band = _BANDS_BY_LETTER.get(m[1]) if m else None
    if m is None or band is None:
        raise MetadataUnreadable(f"认不出的 CE-2 墨卡托分幅名：{name!r}")
    lat, lon = int(m[4]), int(m[6])
    return Ce2Tile(
        code=f"{m[1]}{m[2]}{m[3]}",
        band=band,
        row=int(m[2]),
        column=int(m[3]),
        name_lat=lat if m[5] == "N" else -lat,
        name_lon=lon if m[7] == "E" else -lon,
    )



def corrected_lat_ts(tile_name: str, lat_ts: float) -> float | None:
    """分幅头里的墨卡托标准纬线与它所在纬度带不符时，返回本带的值；相符则 `None`。

    有 5 幅分幅的 `lat_ts` 被写成了相邻纬度带的值（见来源文档），像素与 geotransform
    都没动，于是整幅图被放到几度之外，而且不报任何错。只比绝对值：墨卡托只取标准纬线
    的余弦，北半球写成负值不改变结果，不算错。
    """
    expected = parse_ce2_tile(tile_name).band.lat_ts
    return None if abs(abs(lat_ts) - abs(expected)) < 1e-9 else float(expected)

# ---------------------------------------------------------------------------
# 条带元数据汇总：来源文档里「原始 SAR 的几何与覆盖参数」一节的数字都从这里来。

CONSTANT_COLUMNS = ("任务阶段", "模式", "中心频率_GHz", "投影", "MAP_RESOLUTION_ppd", "原生采样_m", "波段数")
"""预期全表只有一种取值的列。文档按「全部为 X」来写，不止一种时照实列出。"""


@dataclass(frozen=True)
class Spread:
    low: float
    median: float
    high: float


@dataclass(frozen=True)
class StripSummary:
    count: int
    distinct: dict[str, list[str]]
    incidence: Spread
    look_directions: dict[str, int]
    width_px: Spread
    length_px: Spread
    range_resolution: Spread
    azimuth_resolution: Spread
    first_acquisition: str
    last_acquisition: str


def summarize_strips(rows: list[MetadataRow]) -> StripSummary:
    """`rows` 必须全是数据集里的 ROI（先过 `dataset_rows`）——混进已删除的行会多数一条，
    而这种错在汇总出来的数字上是看不出来的。"""
    outside = [row.roi for row in rows if row.split not in SPLITS]
    if outside:
        raise MetadataUnreadable(f"汇总里混进了不属于数据集的 ROI：{'、'.join(outside)}")

    def column(name: str) -> list[str]:
        try:
            return [row.fields[name] for row in rows]
        except KeyError as error:
            raise MetadataUnreadable(f"元数据表缺少列 {error}") from error

    def spread(name: str) -> Spread:
        values = [float(v) for v in column(name)]
        return Spread(min(values), statistics.median(values), max(values))

    times = sorted(column("成像时刻UTC"))
    return StripSummary(
        count=len(rows),
        distinct={name: sorted(set(column(name))) for name in CONSTANT_COLUMNS},
        incidence=spread("入射角_deg"),
        look_directions=dict(sorted(Counter(column("视向")).items())),
        width_px=spread("条带宽_px"),
        length_px=spread("条带长_px"),
        range_resolution=spread("实测有效分辨率_距离向_m"),
        azimuth_resolution=spread("实测有效分辨率_方位向_m"),
        first_acquisition=times[0],
        last_acquisition=times[-1],
    )
