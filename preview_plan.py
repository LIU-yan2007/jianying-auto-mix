# -*- coding: utf-8 -*-
"""按分镜表抽代表性帧，拼一张 4x3 视觉预览，批量编码前先目视验收构图与色彩弧线。"""
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
from config import WORK, FFMPEG as FF, require_ffmpeg  # noqa: E402

require_ffmpeg()
OUT = os.path.join(WORK, "plan_preview.jpg")


def main():
    with open(os.path.join(PROJECT_DIR, "edit_plan.json"), "r", encoding="utf-8") as f:
        plan = json.load(f)
    segs = plan["segments"]
    # 每幕均匀取样，共 12 张
    picks = [0, 2, 4, 7, 10, 13, 16, 20, 24, 28, 32, 35]
    picks = [i for i in picks if i < len(segs)]
    tw, th = 480, 270
    canvas = Image.new("RGB", (tw * 4, (th + 24) * 3), (18, 18, 20))
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 14)
    except OSError:
        font = ImageFont.load_default()

    for k, i in enumerate(picks):
        s = segs[i]
        c = s["crop"]
        vf = (f"crop={c['cw']}:{c['ch']}:{c['x']}:{c['y']},"
              f"scale={tw}:{th}:flags=lanczos,{s['grade']}")
        tmp = os.path.join(WORK, f"pv_{i:02d}.png")
        cmd = [FF, "-hide_banner", "-loglevel", "error", "-ss", f"{s['src_start']:.3f}",
               "-i", plan["videos"][s["src"]]["path"], "-frames:v", "1",
               "-vf", vf, tmp, "-y"]
        p = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
        if p.returncode != 0:
            print(f"seg {i} 失败: {p.stderr[-300:]}")
            continue
        x, y = (k % 4) * tw, (k // 4) * (th + 24)
        canvas.paste(Image.open(tmp).convert("RGB"), (x, y + 24))
        d.text((x + 8, y + 4), f"#{i:02d}  {s['start']:.1f}s  幕{s['act']}  "
                               f"[{s['src']}] z{s['zoom']}", fill=(235, 235, 235), font=font)
    canvas.save(OUT, quality=92)
    print("分镜预览: " + OUT)


if __name__ == "__main__":
    main()
