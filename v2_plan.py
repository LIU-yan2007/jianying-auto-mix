# -*- coding: utf-8 -*-
"""v2 重做版分镜：官方资源按「画面/音乐适配」分配，不再取模撒资源。

上一版的错误：19 处官方音效按 RMS 包络盲选、按转场取模重复塞进现场原声；
特效/蒙版/贴片按 i%N 轮换，爱心星形蒙版、仙尘闪闪、ACT 角标都往演唱会画面上挂；
clip 烘焙一遍 + 草稿再挂一遍 = 三四层叠加。这一版全部改为按内容挑选。

保留 v1 的卡点切点、源区间、取景与冷紫→炽红色彩弧线。
"""
import json
import os
import sys

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.abspath(__file__))

from config import WORK  # noqa: E402

V1 = os.path.join(ROOT, "edit_plan.json")
ASSETS = os.path.join(WORK, "v2_assets.json")
SCORES = os.path.join(WORK, "frame_scores.json")
OUT = os.path.join(ROOT, "v2_edit_plan.json")
NAME = "同一束光_演唱会60秒_官方资源版"

SR, HOP = 22050, 512
FPS_A = SR / HOP

# 只保留 3 种转场（专业共识：一条片子 ≤3 种），且只在真重拍/幕间
TRANS = {
    "flash": {"jy": "闪白", "xfade": "fadewhite", "dur": 0.30},
    "dissolve": {"jy": "叠化", "xfade": "fade", "dur": 0.34},
    "push": {"jy": "向右擦除", "xfade": "wiperight", "dur": 0.30},
}

# 只保留与舞台灯光同类的免费画面特效，去掉可爱/装饰系
EFFECTS = {
    "丁达尔光线": {"overlay": "beam", "alpha": 0.26},
    "光斑虚化": {"overlay": "bokeh", "alpha": 0.28},
    "动感模糊": {"overlay": "blur", "alpha": 0.0},
    "定格闪烁": {"overlay": "flash", "alpha": 0.0},
    "光晕": {"overlay": "halo", "alpha": 0.24},
}

TEXT_ANIMS = ["逐字显影", "渐显", "向上滑动", "向上露出", "冲屏位移"]
TEXT_OUT = "渐隐"


def flux_of(path, seconds=60.0):
    x = np.fromfile(path, dtype=np.float32)
    n = len(x) // HOP
    fr = x[:n * HOP].reshape(n, HOP) * np.hanning(HOP)
    spec = np.abs(np.fft.rfft(fr, axis=1))
    f = np.maximum(np.diff(spec, axis=0, prepend=spec[:1]), 0).sum(axis=1)
    f = f[:int(seconds * FPS_A)]
    return f / (f.max() + 1e-9)


def frame_stats(src, src_start, dur, scores):
    rows = scores[src]["rows"]
    i = int(src_start)
    w = rows[i:i + max(1, int(dur))] or [rows[min(i, len(rows) - 1)]]
    return {"lum": float(np.mean([r["lum"] for r in w])),
            "sat": float(np.mean([r["sat"] for r in w])),
            "detail": float(np.mean([r["detail"] for r in w]))}


def main():
    with open(V1, "r", encoding="utf-8") as f:
        v1 = json.load(f)
    with open(ASSETS, "r", encoding="utf-8") as f:
        assets = json.load(f)
    with open(SCORES, "r", encoding="utf-8") as f:
        scores = json.load(f)
    free = {it["name"] for g, items in assets.items() for it in items}

    flux = flux_of(os.path.join(WORK, "audio_B.f32"))
    base = v1["segments"]

    # 逐段画面特征 + 该切点处的音乐能量（真正决定哪里该加东西）
    feats = []
    for s in base:
        st = frame_stats(s["src"], s["src_start"], s["dur"], scores)
        k = int(min(max(s["start"], 0), 59.9) * FPS_A)
        energy = float(flux[max(0, k - 4):k + 5].mean())
        feats.append({"i": s["i"], "lum": st["lum"], "sat": st["sat"],
                      "detail": st["detail"], "energy": energy,
                      "beat": st["lum"] * 0.8 + st["sat"] * 0.5 + st["detail"] * 0.4,
                      "dur": s["dur"], "act": s["act"], "start": s["start"]})

    # --- 转场：两幕交界必闪白 + 音乐能量最高的 9 个真重拍（间隔 ≥3 段） ---
    tr_idx = set()
    for f in feats:
        if abs(f["start"] - 16.0) < 0.5 or abs(f["start"] - 38.0) < 0.5:
            tr_idx.add(f["i"])
    ranked = sorted([f for f in feats if f["i"] > 0],
                    key=lambda x: -x["energy"])
    for f in ranked:
        if sum(1 for t in tr_idx if abs(t - f["i"]) < 3) == 0:
            tr_idx.add(f["i"])
        if len(tr_idx) >= 11:
            break

    # --- 特效：只挂在「本来就有光」的段，取光束感最高且彼此隔开的 5 段 ---
    eff_idx = []
    for f in sorted(feats, key=lambda x: -x["beat"]):
        if f["i"] == 0 or any(abs(f["i"] - e) < 5 for e in eff_idx):
            continue
        if f["lum"] < 0.10:          # 暗场不挂光效
            continue
        eff_idx.append(f["i"])
        if len(eff_idx) == 5:
            break
    eff_idx.sort()

    # 特效类型按画面特征匹配，不轮换取模
    def effect_for(f):
        if f["dur"] < 1.3:
            return "动感模糊"
        if f["lum"] > 0.26 and f["sat"] < 0.16:
            return "光晕"
        if f["sat"] > 0.22:
            return "光斑虚化"
        if f["detail"] > 0.055:
            return "定格闪烁"
        return "丁达尔光线"

    # --- 蒙版：只 2 处，开场镜面 + 幕 II 线性 ---
    mask_idx = {0: "镜面"}
    a2 = next((f["i"] for f in feats if f["act"] == 2), None)
    if a2:
        mask_idx[a2] = "线性"

    # --- 推拉：只 9 段较长镜头，幅度克制 ---
    push_idx = []
    for act in (1, 2, 3):
        cand = sorted([f for f in feats if f["act"] == act and f["dur"] >= 1.8],
                      key=lambda x: -x["dur"])
        push_idx += [f["i"] for f in cand[:3]]
    push_idx = set(push_idx)

    segments, trans_n, eff_n, kf_n, mask_n = [], 0, 0, 0, 0
    for s in base:
        i = s["i"]
        f = feats[i]

        trans = None
        if i in tr_idx:
            boundary = abs(s["start"] - 16.0) < 0.5 or abs(s["start"] - 38.0) < 0.5
            if boundary:
                kind = "flash"
            elif s["act"] == 2 and i % 7 == 2:
                kind = "push"
            else:
                kind = "flash" if f["energy"] > np.median([x["energy"] for x in feats]) else "dissolve"
            trans = dict(TRANS[kind])
            trans_n += 1

        effect = None
        if i in eff_idx:
            nm = effect_for(f)
            effect = {"jy": nm, **EFFECTS[nm]}
            eff_n += 1

        mask = None
        if i in mask_idx:
            mask = {"name": mask_idx[i], "size": 0.72 if mask_idx[i] == "镜面" else 0.66,
                    "rotation": 0.0, "feather": 0.22}
            mask_n += 1

        push = {"dir": "none", "amp": 0.0}
        if i in push_idx:
            push = {"dir": "in" if i % 2 == 0 else "out",
                    "amp": round(0.045 + 0.012 * s["act"], 4)}
            kf_n += 1

        segments.append({
            "i": i, "start": s["start"], "end": s["end"], "dur": s["dur"],
            "src": s["src"], "src_start": s["src_start"], "act": s["act"],
            "crop": s["crop"], "zoom": s["zoom"], "grade": s["grade"],
            "push": push, "transition": trans, "mask": mask,
            "effect": effect, "sticker": None, "sfx": None,
        })

    texts = [{**t, "anim_in": TEXT_ANIMS[j % len(TEXT_ANIMS)], "anim_out": TEXT_OUT}
             for j, t in enumerate(v1["texts"])]

    # VIP 硬校验
    used = set()
    for s in segments:
        if s["transition"]:
            used.add(s["transition"]["jy"])
        if s["effect"]:
            used.add(s["effect"]["jy"])
        if s["mask"]:
            used.add(s["mask"]["name"])
    for t in texts:
        used |= {t["anim_in"], t["anim_out"]}
    missing = sorted(n for n in used if n not in free)
    if missing:
        raise RuntimeError(f"非免费资源: {missing}")

    plan = {
        "name": NAME, "width": 1920, "height": 1080, "fps": 30,
        "duration_us": 60_000_000, "total_seconds": 60.0,
        "bpm": v1["bpm"], "videos": v1["videos"], "bgm": dict(v1["bgm"]),
        "cuts": v1["cuts"], "segments": segments, "texts": texts,
        "filter": None,
        "transitions_count": trans_n, "sfx_points": [],
        "stats": {"segments": len(segments), "transitions": trans_n,
                  "effects": eff_n, "masks": mask_n, "push_keyframes": kf_n,
                  "stickers": 0, "sfx_hits": 0, "free_resources_used": sorted(used)},
        "resource_integrity": "全部 is_vip=False；资源按画面亮度/饱和度/音乐能量适配，"
                              "撤除与现场原声打架的官方音效",
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"片段 {len(segments)} | 免费转场 {trans_n}（3 种，只在重拍/幕间） | "
          f"免费特效 {eff_n}（只挂有光的画面） | 蒙版 {mask_n} | 推拉 {kf_n} | "
          f"官方音效 0 | 贴片 0 | 全片滤镜 0")
    print("特效分布:", [(s["i"], s["effect"]["jy"]) for s in segments if s["effect"]])
    print("VIP 校验通过，分镜: " + OUT)


if __name__ == "__main__":
    main()
