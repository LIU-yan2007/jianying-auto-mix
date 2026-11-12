# -*- coding: utf-8 -*-
"""对比平安发来的视频与本机 v1 / v2 成片：规格、编码来源、画面、音频。"""
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.abspath(__file__))
from config import WORK, FFMPEG as FF, FFPROBE as FP, require_ffmpeg  # noqa: E402

require_ffmpeg()

FILES = [(os.path.basename(p), p) for p in sys.argv[1:]]
if len(FILES) < 2:
    raise SystemExit(
        "用法：python compare_videos.py <视频1> <视频2> [视频3 ...]\n"
        "按同样时间点抽帧并排，用于逐镜比对差异。"
    )
SR, HOP = 22050, 512
TIMES = [1.5, 9.0, 19.0, 30.0, 44.0, 57.5]
TW, TH = 480, 270


def tags(path):
    p = subprocess.run([FP, "-v", "error", "-show_entries",
                        "format_tags:stream_tags", "-of", "json", path],
                       capture_output=True, text=True)
    return json.loads(p.stdout or "{}")


def audio_rms(path):
    p = subprocess.run([FF, "-v", "error", "-i", path, "-vn", "-ac", "1",
                        "-ar", str(SR), "-f", "f32le", "-acodec", "pcm_f32le", "-"],
                       capture_output=True)
    x = np.frombuffer(p.stdout, dtype=np.float32)
    n = len(x) // HOP
    fr = x[:n * HOP].reshape(n, HOP)
    return np.sqrt((fr ** 2).mean(axis=1) + 1e-12)


def frame(path, t, out):
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}",
                    "-i", path, "-frames:v", "1", "-vf", f"scale={TW}:{TH}", out, "-y"],
                   check=True, capture_output=True)
    return np.asarray(Image.open(out).convert("RGB"), dtype=np.float32) / 255.0


def main():
    os.makedirs(WORK, exist_ok=True)
    print("=== 编码来源（encoder / handler） ===")
    for label, path in FILES:
        t = tags(path)
        ft = t.get("format", {}).get("tags", {})
        st = [s.get("tags", {}) for s in t.get("streams", [])]
        enc = ft.get("encoder") or (st[0].get("encoder") if st else "") or "-"
        major = ft.get("major_brand", "-")
        handler = (st[0].get("handler_name") if st else "-") or "-"
        print(f"  {label:16s} encoder={enc!r} major_brand={major!r} handler={handler!r}")

    print("\n=== 音频 RMS 曲线对比（每秒） ===")
    rms = {}
    for label, path in FILES:
        r = audio_rms(path)
        rms[label] = r
        per_s = [float(r[int(i * SR / HOP):int((i + 1) * SR / HOP)].mean())
                 for i in range(60)]
        print(f"  {label:16s} 均值={np.mean(per_s):.5f} 峰值={max(per_s):.5f} "
              f"前10秒={per_s[:10]}")
    a = rms["你发来的"][:60 * SR // HOP]
    b = rms["我的 v2 返工版"][:60 * SR // HOP]
    c = rms["我的 v1 初版"][:60 * SR // HOP]
    n = min(len(a), len(b), len(c))
    corr_v2 = float(np.corrcoef(a[:n], b[:n])[0, 1])
    corr_v1 = float(np.corrcoef(a[:n], c[:n])[0, 1])
    print(f"  与你发来的音频相关系数: v2={corr_v2:.4f} / v1={corr_v1:.4f}")
    # 逐秒相对 v2 的能量突增（外来音效会在这里显形）
    pa = np.array([a[int(i * SR / HOP):int((i + 1) * SR / HOP)].mean()
                   for i in range(60)])
    pb = np.array([b[int(i * SR / HOP):int((i + 1) * SR / HOP)].mean()
                   for i in range(60)])
    spikes = [(i, round(float(pa[i] / (pb[i] + 1e-9)), 2))
              for i in range(60) if pa[i] > pb[i] * 1.35 and pa[i] > 0.02]
    print(f"  相对 v2 的额外能量尖峰（疑似音效/额外音轨）: {spikes[:20]}")

    print("\n=== 同时间点画面差异（平均亮度 / 饱和度 / 与 v2 的像素差） ===")
    canvas = Image.new("RGB", (TW * 2, (TH + 26) * len(TIMES)), (16, 16, 18))
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 14)
    except OSError:
        font = ImageFont.load_default()
    for k, t in enumerate(TIMES):
        fa = frame(FILES[0][1], t, os.path.join(WORK, f"cmp_a_{k}.png"))
        fb = frame(FILES[1][1], t, os.path.join(WORK, f"cmp_b_{k}.png"))
        fc = frame(FILES[2][1], t, os.path.join(WORK, f"cmp_c_{k}.png"))
        def stats(x):
            lum = (0.299 * x[..., 0] + 0.587 * x[..., 1] + 0.114 * x[..., 2]).mean()
            sat = (x.max(axis=2) - x.min(axis=2)).mean()
            return lum, sat
        la, sa = stats(fa)
        lb, sb = stats(fb)
        diff = float(np.abs(fa - fb).mean())
        diff1 = float(np.abs(fa - fc).mean())
        print(f"  t={t:5.1f}s  你发来 亮度{la:.3f}/饱和{sa:.3f} | "
              f"v2 {lb:.3f}/{sb:.3f} | 与v2像素差 {diff:.3f} | 与v1像素差 {diff1:.3f}")
        y = k * (TH + 26)
        canvas.paste(Image.open(os.path.join(WORK, f"cmp_a_{k}.png")).convert("RGB"), (0, y + 26))
        canvas.paste(Image.open(os.path.join(WORK, f"cmp_b_{k}.png")).convert("RGB"), (TW, y + 26))
        d.text((8, y + 5), f"t = {t:.1f}s", fill=(235, 235, 235), font=font)
        d.text((TW + 8, y + 5), f"像素差 {diff:.3f}", fill=(235, 235, 235), font=font)
    d.text((8, 4), "左：你发来的", fill=(255, 210, 120), font=font)
    d.text((TW + 8, 4), "右：我的 v2 返工版", fill=(140, 210, 255), font=font)
    out = os.path.join(ROOT, "exports", "对比_画面并排.jpg")
    canvas.save(out, quality=92)
    print("\n对比图: " + out)


if __name__ == "__main__":
    main()
