# -*- coding: utf-8 -*-
"""逐秒扫描两段素材的画面可用性，供分镜挑选不黑、有内容的源区间。

ffmpeg 解码成 96x54 rgb24，numpy 算亮度 / 非黑占比 / 色彩能量 / 细节度，
输出每秒一个分数 + 一张时间轴评分图。只读原视频。
"""
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import WORK, FFMPEG as FF, as_tuples, require_ffmpeg  # noqa: E402

require_ffmpeg()

VIDEOS = as_tuples(with_label=False)
W, H = 96, 54


def scan(path):
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-i", path,
           "-vf", f"fps=1,scale={W}:{H}:flags=area", "-f", "rawvideo",
           "-pix_fmt", "rgb24", "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode(errors="ignore")[-800:])
    buf = np.frombuffer(p.stdout, dtype=np.uint8)
    n = len(buf) // (W * H * 3)
    return buf[:n * W * H * 3].reshape(n, H, W, 3).astype(np.float32) / 255.0


def score_frame(x):
    lum = 0.299 * x[..., 0] + 0.587 * x[..., 1] + 0.114 * x[..., 2]
    nonblack = float((lum > 0.075).mean())
    mean_lum = float(lum.mean())
    sat = float((x.max(axis=2) - x.min(axis=2)).mean())
    # 细节：相邻像素亮度差的均值，衡量画面有没有内容而不是纯色光斑
    detail = float(np.abs(np.diff(lum, axis=0)).mean() + np.abs(np.diff(lum, axis=1)).mean()) / 2
    s = (0.42 * nonblack + 0.22 * min(mean_lum * 2.6, 1.0)
         + 0.20 * min(sat * 3.2, 1.0) + 0.16 * min(detail * 9.0, 1.0))
    return {"score": round(s, 4), "nonblack": round(nonblack, 4),
            "lum": round(mean_lum, 4), "sat": round(sat, 4),
            "detail": round(detail, 4)}


def draw(all_rows, out):
    width, row_h, left, right = 1200, 150, 60, 20
    plot_w = width - left - right
    img = Image.new("RGB", (width, 46 + len(all_rows) * row_h), (246, 246, 248))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 15)
        small = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 12)
    except OSError:
        font = small = ImageFont.load_default()
    d.text((12, 12), "逐秒画面可用性评分（越高＝越亮、越有内容；低分多为死黑/空镜）",
           fill=(25, 25, 25), font=font)
    for k, (key, rows, duration) in enumerate(all_rows):
        y = 46 + k * row_h
        d.text((12, y + 36), f"[{key}]", fill=(20, 20, 20), font=font)
        for t in range(0, int(duration) + 1, 10):
            px = left + int(plot_w * t / duration)
            d.line([(px, y + 6), (px, y + 118)], fill=(224, 224, 228), width=1)
            d.text((px + 2, y + 122), f"{t}s", fill=(140, 140, 140), font=small)
        pts = []
        for j, r in enumerate(rows):
            px = left + int(plot_w * j / max(1, duration))
            py = y + 108 - int(r["score"] * 96)
            pts.append((px, py))
        if len(pts) > 1:
            d.line(pts, fill=(196, 62, 90), width=2)
        # 标出阈值线
        d.line([(left, y + 108 - int(0.42 * 96)),
                (left + plot_w, y + 108 - int(0.42 * 96))],
               fill=(120, 160, 200), width=1, )
        vals = [r["score"] for r in rows]
        d.text((left + 4, y + 10), f"均值 {np.mean(vals):.3f} / 最高 {max(vals):.3f}",
               fill=(100, 100, 100), font=small)
    img.save(out, quality=90)
    print("评分图: " + out)


def main():
    os.makedirs(WORK, exist_ok=True)
    payload, all_rows = {}, []
    for key, path in VIDEOS:
        frames = scan(path)
        rows = [score_frame(f) for f in frames]
        payload[key] = {"path": path, "frames": len(rows), "rows": rows}
        all_rows.append((key, rows, len(rows)))
        good = [i for i, r in enumerate(rows) if r["score"] >= 0.42]
        print(f"[{key}] {len(rows)} 秒 | 可用(>=0.42) {len(good)} 秒 "
              f"| 均值 {np.mean([r['score'] for r in rows]):.3f} "
              f"| 最佳区间 {good[:14]}")
        worst = sorted(range(len(rows)), key=lambda i: rows[i]["score"])[:8]
        print(f"     最差秒: {sorted(worst)}")
    draw(all_rows, os.path.join(WORK, "frame_scores.jpg"))
    with open(os.path.join(WORK, "frame_scores.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print("评分数据: " + os.path.join(WORK, "frame_scores.json"))


if __name__ == "__main__":
    main()
