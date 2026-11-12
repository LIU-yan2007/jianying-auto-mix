# -*- coding: utf-8 -*-
"""演唱会素材音轨诊断：解码 22050Hz mono f32，算频谱通量 / BPM / 能量曲线。

只读原视频，产物写入系统 temp。决定 BGM 取哪条音轨、取哪个 60 秒窗口。
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

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

VIDEOS = as_tuples(with_label=True)

SR, HOP = 22050, 512
FPS_A = SR / HOP


def decode(path, out):
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-i", path,
           "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-acodec", "pcm_f32le", out, "-y"]
    p = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-800:])
    return np.fromfile(out, dtype=np.float32)


def flux_and_rms(x):
    n = len(x) // HOP
    fr = x[:n * HOP].reshape(n, HOP)
    win = np.hanning(HOP)
    rms = np.sqrt((fr ** 2).mean(axis=1) + 1e-12)
    spec = np.abs(np.fft.rfft(fr * win, axis=1))
    flux = np.maximum(np.diff(spec, axis=0, prepend=spec[:1]), 0).sum(axis=1)
    return flux / (flux.max() + 1e-9), rms


def beat_info(flux, t0=0.0, t1=60.0):
    seg = flux[int(t0 * FPS_A):int(t1 * FPS_A)]
    f = seg - seg.mean()
    ac = np.correlate(f, f, mode="full")[len(f) - 1:]
    norm = ac[0] if ac[0] > 0 else 1.0
    lo, hi = int(FPS_A * 60 / 180), int(FPS_A * 60 / 60)
    region = ac[lo:hi + 1] / norm
    lag = lo + int(np.argmax(region))
    bpm = 60.0 * FPS_A / lag
    periodicity = float(region.max())
    period = FPS_A * 60.0 / bpm
    best, best_off = 0.0, 0.0
    for off in np.arange(0, period, 1.0):
        picks = np.arange(off, len(seg), period).astype(int)
        if len(picks) == 0:
            continue
        v = float(seg[picks].mean() / (seg.mean() + 1e-9))
        if v > best:
            best, best_off = v, float(off)
    return {
        "bpm": round(bpm, 2), "periodicity": round(periodicity, 4),
        "salience": round(best, 4), "phase": round(best_off / FPS_A, 4),
    }


def energy_curve(rms, duration, step=5.0):
    out = []
    for t in np.arange(0, duration, step):
        seg = rms[int(t * FPS_A):int((t + step) * FPS_A)]
        if len(seg):
            out.append((round(float(t), 1), round(float(seg.mean()), 5)))
    return out


def draw(results, out_img):
    W, row_h, left = 1240, 210, 210
    H = 48 + len(results) * row_h
    img = Image.new("RGB", (W, H), (246, 246, 248))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 15)
        small = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 12)
    except OSError:
        font = small = ImageFont.load_default()
    d.text((12, 12), "演唱会现场原声 · 波形包络（蓝）/ 频谱通量 onset（红）",
           fill=(25, 25, 25), font=font)
    for i, (label, a) in enumerate(results):
        y = 48 + i * row_h
        d.text((12, y + 8), label, fill=(20, 20, 20), font=small)
        for j, line in enumerate([
            f"BPM {a['beat']['bpm']}",
            f"节拍显著度 {a['beat']['salience']}",
            f"周期性 {a['beat']['periodicity']}",
            f"时长 {a['duration']}s",
        ]):
            d.text((12, y + 32 + j * 20), line, fill=(90, 90, 90), font=small)
        x0, plot_w = left, W - left - 16
        dur = a["duration"]
        for s in range(0, int(dur) + 1, 10):
            px = x0 + int(plot_w * s / dur)
            d.line([(px, y + 4), (px, y + 182)], fill=(226, 226, 230), width=1)
            d.text((px + 2, y + 166), f"{s}s", fill=(150, 150, 150), font=small)
        rms = a["_rms"]
        idx = np.linspace(0, len(rms) - 1, plot_w).astype(int)
        env = rms[idx] / (np.percentile(rms, 99) + 1e-9)
        mid = y + 48
        pts = [(x0 + j, int(mid - env[j] * 34)) for j in range(plot_w)]
        pts += [(x0 + j, int(mid + env[j] * 34)) for j in range(plot_w - 1, -1, -1)]
        d.polygon(pts, fill=(64, 108, 176))
        flx = a["_flux"][idx]
        base = y + 152
        d.line([(x0 + j, int(base - flx[j] * 44)) for j in range(plot_w)],
               fill=(206, 74, 62), width=1)
    img.save(out_img, quality=90)
    print("对比图: " + out_img)


def main():
    os.makedirs(WORK, exist_ok=True)
    results, payload = [], []
    for key, label, path in VIDEOS:
        f32 = os.path.join(WORK, f"audio_{key}.f32")
        x = decode(path, f32)
        duration = len(x) / SR
        flux, rms = flux_and_rms(x)
        # 对 B 试多个 60s 窗口，找出能量递增且节拍最清晰的一段
        windows = []
        if duration >= 60:
            for off in np.arange(0, duration - 60 + 0.01, 5.0):
                b = beat_info(flux, float(off), float(off) + 60.0)
                e = rms[int(off * FPS_A):int((off + 60) * FPS_A)]
                first, last = e[:int(10 * FPS_A)].mean(), e[-int(10 * FPS_A):].mean()
                windows.append({"offset": round(float(off), 1), **b,
                                "energy_first10": round(float(first), 5),
                                "energy_last10": round(float(last), 5),
                                "rise": round(float(last / (first + 1e-9)), 3)})
        beat = beat_info(flux, 0.0, min(60.0, duration))
        row = {
            "key": key, "label": label, "path": path,
            "duration": round(duration, 3), "beat": beat,
            "energy_every_5s": energy_curve(rms, duration),
            "bpm": beat["bpm"], "salience": beat["salience"],
            "rms_mean": round(float(rms.mean()), 5),
            "silence_ratio": round(float((rms < np.percentile(rms, 20)).mean()), 4),
            "windows": windows,
        }
        payload.append(row)
        results.append((f"[{key}] {label}", {**row, "_rms": rms, "_flux": flux}))
        print(f"[{key}] {label} 时长={duration:.2f}s BPM={beat['bpm']} "
              f"显著度={beat['salience']} 周期={beat['periodicity']} "
              f"相位={beat['phase']}s 均值RMS={row['rms_mean']}")
        if windows:
            best = max(windows, key=lambda w: w["salience"] * 0.6 + min(w["rise"], 3) * 0.4)
            print(f"    推荐 60s 窗口 offset={best['offset']}s "
                  f"(显著度 {best['salience']} / 首尾能量比 {best['rise']})")

    draw(results, os.path.join(WORK, "audio_compare.jpg"))
    with open(os.path.join(WORK, "audio_scores.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("评分数据: " + os.path.join(WORK, "audio_scores.json"))


if __name__ == "__main__":
    main()
