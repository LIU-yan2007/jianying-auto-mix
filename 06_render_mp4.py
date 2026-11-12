# -*- coding: utf-8 -*-
"""按 edit_plan.json 渲染 1920x1080 / 30fps / 严格 60 秒 MP4 成片。

与剪映草稿共用同一批预裁剪片段：切点、取景、调色、灯闪脉冲完全一致。
xfade 不缩短时间轴：第 k 次转场 offset = 前面各组标称时长之和 - T_k，
且第 k 组多取 T_k 秒（来自 clip 的 EXTRA 余量）→ 输出 = 累计 + G_k。
片头淡入 / 片尾淡出已烘焙在 clip 内，此处不再重复叠加。
"""
import json
import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import WORK, FFMPEG as FF, require_ffmpeg  # noqa: E402

require_ffmpeg()
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
PLAN = os.path.join(PROJECT_DIR, "edit_plan.json")
MANIFEST = os.path.join(WORK, "manifest.json")
EXPORTS = os.path.join(PROJECT_DIR, "exports")

WIDTH, HEIGHT, FPS = 1920, 1080, 30


def main():
    with open(PLAN, "r", encoding="utf-8") as f:
        plan = json.load(f)
    with open(MANIFEST, "r", encoding="utf-8") as f:
        man = json.load(f)
    os.makedirs(EXPORTS, exist_ok=True)
    segs = plan["segments"]
    total = plan["total_seconds"]
    out = os.path.join(EXPORTS, plan["name"] + ".mp4")

    bounds = [0] + [s["i"] for s in segs if s.get("transition") and s["i"] > 0] + [len(segs)]
    groups = [segs[bounds[k]:bounds[k + 1]] for k in range(len(bounds) - 1)]
    tks, xtypes = [None], [None]
    for k in range(1, len(bounds) - 1):
        tr = segs[bounds[k]]["transition"]
        tks.append(tr["dur"])
        xtypes.append(tr["xfade"])
    print(f"分组 {len(groups)} 组 / xfade {len(groups)-1} 次: "
          + ", ".join(f"{len(g)}段" for g in groups))

    inputs, filters, group_labels = [], [], []
    for s in segs:
        inputs += ["-i", man["clips"][str(s["i"])]]
    audio_idx = len(segs)
    inputs += ["-i", man["bgm"]]
    text_idx = [audio_idx + 1 + j for j in range(len(man["texts"]))]
    for p in man["texts"]:
        inputs += ["-loop", "1", "-framerate", str(FPS), "-i", p]

    # 每组末片段多取 T 秒供 xfade 重叠；只生成一份输出标签，
    # 否则基础 [vN] 会成为 filtergraph 未连接输出（ffmpeg 8.0 直接报错）。
    extra_last = {}
    for k in range(1, len(groups)):
        extra_last[groups[k][-1]["i"]] = tks[k]

    for s in segs:
        i = s["i"]
        d = s["dur"] + extra_last.get(i, 0.0)
        lbl = f"v{i}x" if i in extra_last else f"v{i}"
        filters.append(
            f"[{i}:v]trim=duration={d:.3f},setpts=PTS-STARTPTS,settb=AVTB,"
            f"scale={WIDTH}:{HEIGHT},fps={FPS},format=yuv420p[{lbl}]"
        )

    acc = 0.0
    for k, g in enumerate(groups):
        labels = [f"[v{s['i']}x]" if s["i"] in extra_last else f"[v{s['i']}]" for s in g]
        gl = f"[g{k}]"
        filters.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0,settb=AVTB{gl}")
        group_labels.append((gl, sum(s["dur"] for s in g), tks[k] if k >= 1 else 0.0))

    chain = group_labels[0][0]
    for k in range(1, len(group_labels)):
        acc += group_labels[k - 1][1]
        T, xtype = tks[k], xtypes[k]
        offset = max(0.0, acc - T)
        out_lbl = f"[x{k}]"
        filters.append(
            f"{chain}{group_labels[k][0]}xfade=transition={xtype}:"
            f"duration={T}:offset={offset:.3f}{out_lbl}"
        )
        chain = out_lbl

    for j, t in enumerate(plan["texts"]):
        tlbl, olbl = f"[t{j}]", f"[o{j}]"
        filters.append(
            f"[{text_idx[j]}:v]format=rgba,"
            f"fade=t=in:st={t['start']:.3f}:d=0.30:alpha=1,"
            f"fade=t=out:st={t['end']-0.35:.3f}:d=0.35:alpha=1{tlbl}"
        )
        filters.append(
            f"{chain}{tlbl}overlay=0:0:"
            f"enable='between(t,{t['start']},{t['end']})'{olbl}"
        )
        chain = olbl
    filters.append(f"{chain}format=yuv420p[vout]")
    filters.append(f"[{audio_idx}:a]atrim=0:{total},asetpts=PTS-STARTPTS[aout]")

    cmd = [FF, "-hide_banner", "-loglevel", "error", "-stats"] + inputs + [
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "[aout]",
        "-t", str(total), "-r", str(FPS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", out, "-y",
    ]
    print(f"渲染中（{len(segs)} 片段 / {len(filters)} 个滤镜 / {len(cmd)} 参数）...")
    p = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
    if p.returncode != 0:
        print(p.stderr[-4000:])
        raise RuntimeError("MP4 渲染失败")
    print(f"成片: {out} ({os.path.getsize(out)//1024//1024} MB)")


if __name__ == "__main__":
    main()
