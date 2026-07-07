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


def main() -> None:
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
