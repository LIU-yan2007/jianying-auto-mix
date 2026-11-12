# -*- coding: utf-8 -*-
"""《同一束光》60 秒三幕式卡点分镜 —— 草稿与 MP4 共读的唯一事实来源。

创意逻辑：
  幕 I  灯未亮 0-16s   冷品紫 / 4s 慢切 / 全景与空座，镜头缓慢横移
  幕 II 声浪起 16-38s  冷暖交替 / 2s 中速切 / 取景逐步推近舞台
  幕 III 不散场 38-60s 炽红 / 1s 快切 / 灯闪脉冲与密集闪白转场
  129.2 BPM 网格吸附 BGM 真实频谱通量峰值；源区间按逐秒画面评分择优避开死黑。
"""
import json
import os
import sys

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import WORK, as_dict, bgm_key  # noqa: E402

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(PROJECT_DIR, "edit_plan.json")

SR, HOP = 22050, 512
FPS_A = SR / HOP
TOTAL = 60.0
WIDTH, HEIGHT, FPS = 1920, 1080, 30
DURATION_US = 60_000_000
BPM = 129.2
SRC_W, SRC_H = 960, 544

VIDEOS = as_dict()
BGM_KEY = bgm_key()

# 已在本机剪映验证过的免费转场名 ↔ ffmpeg xfade 类型
TRANSITIONS = [
    {"jy": "叠化", "xfade": "fade", "dur": 0.45},
    {"jy": "闪白", "xfade": "fadewhite", "dur": 0.35},
    {"jy": "向右拉伸", "xfade": "wiperight", "dur": 0.45},
    {"jy": "色彩溶解", "xfade": "distance", "dur": 0.45},
    {"jy": "闪黑", "xfade": "fadeblack", "dur": 0.30},
    {"jy": "泛白", "xfade": "fadewhite", "dur": 0.35},
]


def flux_of(path, seconds=TOTAL):
    x = np.fromfile(path, dtype=np.float32)
    n = len(x) // HOP
    fr = x[:n * HOP].reshape(n, HOP) * np.hanning(HOP)
    spec = np.abs(np.fft.rfft(fr, axis=1))
    flux = np.maximum(np.diff(spec, axis=0, prepend=spec[:1]), 0).sum(axis=1)
    return flux[:int(seconds * FPS_A)] / (flux[:int(seconds * FPS_A)].max() + 1e-9)


def snap(t, flux, window=0.18):
    lo = max(1, int((t - window) * FPS_A))
    hi = min(len(flux), int((t + window) * FPS_A))
    if hi <= lo:
        return t
    k = lo + int(np.argmax(flux[lo:hi]))
    if flux[k] > np.percentile(flux, 55):
        return round(k / FPS_A, 3)
    return t


def build_cuts(flux):
    raw = [4.0, 8.0, 12.0, 16.0]                    # 幕 I：4s
    raw += [float(t) for t in range(18, 38, 2)]     # 幕 II：2s
    raw += [float(t) for t in range(39, 60, 1)]     # 幕 III：1s
    cuts = [0.0] + [snap(t, flux) for t in raw] + [TOTAL]
    clean = [cuts[0]]
    for c in cuts[1:-1]:
        if c - clean[-1] >= 0.62:
            clean.append(c)
    clean.append(TOTAL)
    return clean


def even(v):
    return int(round(v / 2.0)) * 2


def crop_for(zoom, cx, cy):
    """按 16:9 从 960x544 里取一个窗口。

    源画面下部有一道斜贯的看台栏杆（纯黑）。取景窗口一律贴顶，并把变焦
    拉到 1.34 以上缩短窗口高度，把栏杆压到成片最底部 10~15%，
    让它变成前景剪影与字幕安全区，而不是斜穿画面中部的硬伤。
    """
    cw = even(SRC_W / zoom)
    ch = even(cw * HEIGHT / WIDTH)
    x = even(min(max(cx * SRC_W - cw / 2, 0), SRC_W - cw))
    y = 0
    return {"cw": cw, "ch": ch, "x": x, "y": y}


def grade_for(act, p):
    """幕 I 冷紫 → 幕 III 炽红的连续色彩弧线。p=幕内进度 0..1。"""
    if act == 1:
        return (f"eq=contrast={1.08 + 0.03*p:.3f}:saturation={1.10 + 0.05*p:.3f}:gamma=1.050,"
                f"colorbalance=bs={0.09 - 0.02*p:.3f}:bm=0.020:"
                f"rh={-0.06 + 0.02*p:.3f}:bh=0.025,vignette=PI/4.2")
    if act == 2:
        return (f"eq=contrast={1.11 + 0.03*p:.3f}:saturation={1.16 + 0.06*p:.3f}:gamma=1.045,"
                f"colorbalance=bs={0.03 - 0.05*p:.3f}:bm={0.01 - 0.02*p:.3f}:"
                f"rs={0.01 + 0.03*p:.3f}:rh={-0.01 + 0.06*p:.3f},vignette=PI/4.2")
    return (f"eq=contrast={1.14 + 0.04*p:.3f}:saturation={1.22 + 0.08*p:.3f}:gamma=1.040,"
            f"colorbalance=rs={0.04 + 0.02*p:.3f}:rm=0.030:rh=0.070:"
            f"bs=-0.030:bm=-0.020,vignette=PI/4.2")


def act_of(start):
    if start < 16.0:
        return 1
    if start < 38.0:
        return 2
    return 3


def load_scores():
    with open(os.path.join(WORK, "frame_scores.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def pick_source(scores, key, cursor, dur, threshold=0.44):
    """从 cursor 附近挑画面评分最高的一秒，自动绕开死黑区间。"""
    rows = scores[key]["rows"]
    limit = VIDEOS[key]["duration"] - dur - 0.85
    limit = max(0.5, limit)
    c = cursor % limit
    best_t, best_s = c, -1.0
    for delta in np.arange(-1.6, 1.61, 0.8):
        t = min(max(c + delta, 0.0), limit)
        s = rows[min(int(t), len(rows) - 1)]["score"]
        if s > best_s:
            best_t, best_s = t, s
    # 落在低分区就退到该源的高分候选
    if best_s < threshold:
        cands = [i for i, r in enumerate(rows[:int(limit) + 1]) if r["score"] >= threshold + 0.08]
        if cands:
            best_t = float(min(cands, key=lambda i: abs(i - c)))
    return round(float(min(best_t, limit)), 3)


def main():
    scores = load_scores()
    flux = flux_of(os.path.join(WORK, "audio_B.f32"))
    cuts = build_cuts(flux)
    print(f"卡点切点 {len(cuts)} 个 → 片段 {len(cuts)-1} 个 | BPM {BPM}")

    segments = []
    cursor = {"A": 0.0, "B": 2.0}
    step = {"A": 4.3, "B": 6.1}
    used = {"A": 0.0, "B": 0.0}
    trans_iter = 0
    n = len(cuts) - 1

    for i in range(n):
        start, end = cuts[i], cuts[i + 1]
        dur = round(end - start, 3)
        act = act_of(start)
        p = ((start - 0.0) / 16.0) if act == 1 else (
            ((start - 16.0) / 22.0) if act == 2 else ((start - 38.0) / 22.0))
        p = min(max(p, 0.0), 1.0)

        # 配额：幕 I 全 A；幕 II A/B 交替；幕 III 以 B 为主，间或插 A 大屏回眸
        if act == 1:
            key = "A"
        elif act == 2:
            key = "A" if (i % 3 == 0 and used["A"] + dur <= 27.0) else "B"
        else:
            key = "A" if (i % 9 == 4 and used["A"] + dur <= 30.0) else "B"

        src_start = pick_source(scores, key, cursor[key], dur)
        cursor[key] += step[key]
        used[key] += dur

        # 镜头：幕 I 缓慢横移 + 轻推近；幕 III 大幅跳变制造冲击
        if act == 1:
            cx = 0.40 + 0.20 * p
            cy = 0.0
            zoom = 1.34 + 0.06 * p
        elif act == 2:
            cx = 0.40 + 0.22 * ((i % 5) / 4.0)
            cy = 0.0
            zoom = 1.38 + 0.08 * p
        else:
            cx = 0.34 + 0.32 * ((i * 7 % 11) / 10.0)
            cy = 0.0
            zoom = 1.40 + 0.10 * ((i * 3 % 9) / 8.0)

        # 转场：两幕交界必闪白；幕 III 用密集灯闪，前两幕用叠化/拉幕轮换
        trans = None
        boundary = (abs(start - 16.0) < 0.35 or abs(start - 38.0) < 0.35)
        hit = boundary or (act == 3 and i % 4 == 1) or (act < 3 and i % 5 == 3)
        if i > 0 and hit:
            if boundary or act == 3:
                tr = ({"jy": "闪白", "xfade": "fadewhite", "dur": 0.35}
                      if (i // 4) % 2 == 0 else
                      {"jy": "泛白", "xfade": "fadewhite", "dur": 0.35})
            else:
                tr = TRANSITIONS[trans_iter % len(TRANSITIONS)]
            trans_iter += 1
            trans = tr

        # 幕 III 每 3 段来一次灯闪脉冲（从白场淡入 0.13s）
        pulse = bool(act == 3 and i % 3 == 1)

        segments.append({
            "i": i, "start": round(start, 3), "end": round(end, 3), "dur": dur,
            "src": key, "src_start": src_start, "act": act,
            "crop": crop_for(zoom, cx, cy), "zoom": round(zoom, 3),
            "grade": grade_for(act, p),
            "pulse": pulse, "transition": trans,
        })

    plan = {
        "name": "同一束光_演唱会60秒",
        "title": "同一束光",
        "width": WIDTH, "height": HEIGHT, "fps": FPS,
        "duration_us": DURATION_US, "total_seconds": TOTAL,
        "bpm": BPM,
        "videos": VIDEOS,
        "bgm": {
            "path": VIDEOS[BGM_KEY]["path"], "source_offset": 0.0,
            "duration": TOTAL, "fade_in": 1.2, "fade_out": 2.5,
            "note": "取 BGM 素材原声前 60s；加场馆混响与低频增强",
        },
        "cuts": cuts,
        "segments": segments,
        "transitions_count": trans_iter,
        "texts": [
            {"text": "同 一 束 光", "start": 0.5, "end": 3.3, "size": 15.0, "y": 0.0},
            {"text": "几万人，在等同一句", "start": 3.6, "end": 6.0, "size": 9.0, "y": -0.55},
            {"text": "然后，第一束光落下来", "start": 16.8, "end": 19.4, "size": 9.0, "y": -0.55},
            {"text": "全场，一起亮了", "start": 38.7, "end": 41.2, "size": 9.0, "y": -0.55},
            {"text": "这一夜  ·  不散场", "start": 56.2, "end": 59.7, "size": 12.0, "y": 0.0},
        ],
        "analysis": {
            "acts": "I 0-16s 冷紫慢切 / II 16-38s 冷暖交替 / III 38-60s 炽红快切",
            "source_usage_seconds": {k: round(v, 2) for k, v in used.items()},
            "bgm": "B 段现场原声 0-60s，129.2 BPM，flux 峰值吸附",
            "reframe": "逐片段 16:9 变焦重取景，避开看台黑边并制造运镜",
            "grade": "冷品紫 → 中性 → 炽红的连续色彩弧线 + 统一暗角",
        },
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    print(f"片段 {len(segments)} | 转场 {trans_iter} | 灯闪脉冲 {sum(s['pulse'] for s in segments)}")
    print(f"源用量 A={used['A']:.2f}s / B={used['B']:.2f}s")
    print(f"各幕片段数: " + ", ".join(
        f"幕{a}={sum(1 for s in segments if s['act']==a)}" for a in (1, 2, 3)))
    print(f"总长 {segments[-1]['end']}s | 分镜表 {OUT}")


if __name__ == "__main__":
    main()
