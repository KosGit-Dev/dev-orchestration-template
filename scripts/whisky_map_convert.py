#!/usr/bin/env python3
"""Natural Earth 110m land GeoJSON を Miller 図法の SVG パスへ変換する。

出力は app/data/worldmap.js（window.WCQ_WORLD へ代入する JS ファイル）。
アプリ側 JS の project() と同じ定数を使うこと（W=1000, LAT_TOP=78, LAT_BOTTOM=-56）。
"""

import json
import math
import sys

W = 1000.0
LAT_TOP = 78.0
LAT_BOTTOM = -56.0


def miller_y(lat_deg: float) -> float:
    lat = math.radians(lat_deg)
    return 1.25 * math.log(math.tan(math.pi / 4 + 0.4 * lat))


Y_TOP = miller_y(LAT_TOP)
Y_BOTTOM = miller_y(LAT_BOTTOM)
H = W * (Y_TOP - Y_BOTTOM) / (2 * math.pi)


def project(lon: float, lat: float) -> tuple[float, float]:
    x = (lon + 180.0) / 360.0 * W
    y = (Y_TOP - miller_y(lat)) / (Y_TOP - Y_BOTTOM) * H
    return x, y


def ring_area(pts: list[tuple[float, float]]) -> float:
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def ring_to_path(ring: list[list[float]]) -> str | None:
    pts = []
    for lon, lat in ring:
        if lat < LAT_BOTTOM:
            lat = LAT_BOTTOM
        if lat > LAT_TOP:
            lat = LAT_TOP
        x, y = project(lon, lat)
        pts.append((round(x, 1), round(y, 1)))
    # 近接点の間引き
    slim: list[tuple[float, float]] = []
    for p in pts:
        if not slim or abs(p[0] - slim[-1][0]) + abs(p[1] - slim[-1][1]) >= 0.8:
            slim.append(p)
    if len(slim) < 6 or ring_area(slim) < 3.0:
        return None
    d = f"M{slim[0][0]} {slim[0][1]}"
    for x, y in slim[1:]:
        d += f"L{x} {y}"
    return d + "Z"


# エリア詳細ビュー用の切り出し範囲（lon_min, lat_min, lon_max, lat_max）
AREA_BBOXES = {
    "scotland": (-8.4, 54.2, -0.4, 61.3),
    "ireland": (-11.0, 51.2, -5.0, 55.6),
    "japan": (127.5, 30.0, 146.5, 46.2),
    "usa": (-92.0, 32.5, -79.5, 40.5),
    "canada": (-100.0, 41.0, -58.0, 53.5),
    "taiwan": (119.0, 21.3, 123.0, 25.8),
    "india": (67.0, 6.0, 92.0, 30.0),
    "australia": (139.0, -44.5, 152.5, -31.5),
    "england-wales": (-6.6, 49.7, 2.2, 55.9),
    "europe": (-6.0, 42.5, 22.0, 66.5),
}


def clip_ring(pts: list[tuple[float, float]], bbox: tuple[float, float, float, float]):
    """Sutherland–Hodgman で矩形にクリップする（投影前の lon/lat 座標系）。"""
    x0, y0, x1, y1 = bbox
    edges = [
        (
            lambda p: p[0] >= x0,
            lambda a, b: (x0, a[1] + (b[1] - a[1]) * (x0 - a[0]) / (b[0] - a[0])),
        ),
        (
            lambda p: p[0] <= x1,
            lambda a, b: (x1, a[1] + (b[1] - a[1]) * (x1 - a[0]) / (b[0] - a[0])),
        ),
        (
            lambda p: p[1] >= y0,
            lambda a, b: (a[0] + (b[0] - a[0]) * (y0 - a[1]) / (b[1] - a[1]), y0),
        ),
        (
            lambda p: p[1] <= y1,
            lambda a, b: (a[0] + (b[0] - a[0]) * (y1 - a[1]) / (b[1] - a[1]), y1),
        ),
    ]
    out = pts
    for inside, intersect in edges:
        if not out:
            return []
        cur = []
        prev = out[-1]
        for p in out:
            if inside(p):
                if not inside(prev):
                    cur.append(intersect(prev, p))
                cur.append(p)
            elif inside(prev):
                cur.append(intersect(prev, p))
            prev = p
        out = cur
    return out


def area_paths(gj: dict, bbox: tuple[float, float, float, float]) -> str:
    paths = []
    for feat in gj["features"]:
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            ring = [(pt[0], pt[1]) for pt in poly[0]]
            clipped = clip_ring(ring, bbox)
            if len(clipped) < 4:
                continue
            pts = []
            for lon, lat in clipped:
                x, y = project(lon, lat)
                p = (round(x, 2), round(y, 2))
                if not pts or abs(p[0] - pts[-1][0]) + abs(p[1] - pts[-1][1]) >= 0.05:
                    pts.append(p)
            if len(pts) < 4 or ring_area(pts) < 0.05:
                continue
            d = f"M{pts[0][0]} {pts[0][1]}" + "".join(f"L{x} {y}" for x, y in pts[1:]) + "Z"
            paths.append(d)
    return "".join(paths)


def build_area_maps(src: str, dst: str) -> None:
    with open(src, encoding="utf-8") as f:
        gj = json.load(f)
    out: dict[str, dict] = {}
    for area, bbox in AREA_BBOXES.items():
        path = area_paths(gj, bbox)
        p0 = project(bbox[0], bbox[3])  # 左上（lat 大きい方が上）
        p1 = project(bbox[2], bbox[1])
        out[area] = {
            "path": path,
            "vb": [
                round(p0[0], 1),
                round(p0[1], 1),
                round(p1[0] - p0[0], 1),
                round(p1[1] - p0[1], 1),
            ],
        }
    with open(dst, "w", encoding="utf-8") as f:
        f.write("// 生成物: Natural Earth 50m (public domain) を元に変換（--areas モード）\n")
        f.write("window.WCQ_AREAMAPS = ")
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    size = sum(len(v["path"]) for v in out.values())
    print(f"OK areas={len(out)} total path chars={size // 1024}KB -> {dst}")


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] == "--areas":
        build_area_maps(sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) != 3:
        print("usage: whisky_map_convert.py [--areas] <input.geojson> <output.js>", file=sys.stderr)
        raise SystemExit(2)
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        gj = json.load(f)
    paths: list[str] = []
    for feat in gj["features"]:
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            # 南極大陸は割愛（描画範囲外）
            if all(pt[1] < LAT_BOTTOM + 1 for pt in poly[0]):
                continue
            d = ring_to_path(poly[0])
            if d:
                paths.append(d)
    out = {
        "w": round(W, 1),
        "h": round(H, 1),
        "latTop": LAT_TOP,
        "latBottom": LAT_BOTTOM,
        "path": "".join(paths),
    }
    with open(dst, "w", encoding="utf-8") as f:
        f.write(
            "// 生成物: Natural Earth 110m (public domain) を元に変換（whisky_map_convert.py）\n"
        )
        f.write("window.WCQ_WORLD = ")
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    print(f"OK {len(paths)} rings -> {dst} (h={H:.1f})")


if __name__ == "__main__":
    main()
