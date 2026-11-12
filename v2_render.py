# -*- coding: utf-8 -*-
"""v2 最终成片：1920x1080 / 30fps / 48000Hz / H264+AAC / MP4 / 严格 60 秒。

与剪映草稿共用同一批预裁剪片段：19 个免费转场用 xfade 模拟、开场镜面蒙版用
双幕布拉开、官方音效已混进 bgm_v2.m4a、文字用带免费动画等效的淡入淡出。
"""
import json
import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.abspath(__file__))
from config import WORK, FFMPEG as FF, require_ffmpeg  # noqa: E402

require_ffmpeg()
PLAN = os.path.join(ROOT, "v2_edit_plan.json")
MANIFEST = os.path.join(WORK, "manifest_v2.json")
EXPORTS = os.path.join(ROOT, "exports")
W, H, FPS = 1920, 1080, 30
CURTAIN_SEC = 0.7


def main():
    with open(PLAN, "r", encoding="utf-8") as f:
        plan = json.load(f)
    with open(MANIFEST, "r", encoding="utf-8") as f:
        man = json.load(f)
    os.makedirs(EXPORTS, exist_ok=True)
    segs, total = plan["segments"], plan["total_seconds"]
    out = os.path.join(EXPORTS, plan["name"] + ".mp4")

    bounds = [0] + [s["i"] for s in segs if s.get("transition") and s["i"] > 0] + [len(segs)]
    groups = [segs[bounds[k]:bounds[k + 1]] for k in range(len(bounds) - 1)]
    tks, xtypes = [None], [None]
    for k in range(1, len(bounds) - 1):
        tr = segs[bounds[k]]["transition"]
        tks.append(tr["dur"])
        xtypes.append(tr["xfade"])
    print(f"分组 {len(groups)} 组 / 免费转场 xfade {len(groups)-1} 次")

    inputs, filters = [], []
    for s in segs:
        inputs += ["-i", man["clips"][str(s["i"])]]
    audio_idx = len(segs)
    inputs += ["-i", man["bgm"]]
    text_idx = [audio_idx + 1 + j for j in range(len(man["texts"]))]
    for p in man["texts"]:
        inputs += ["-loop", "1", "-framerate", str(FPS), "-i", p]
    curtain_idx = [audio_idx + 1 + len(man["texts"]) + j for j in range(2)]
    for p in man["curtains"]:
        inputs += ["-loop", "1", "-framerate", str(FPS), "-i", p]

    # 每组末片段多取 T 秒供 xfade 重叠
    extra_last = {}
    for k in range(1, len(groups)):
        extra_last[groups[k][-1]["i"]] = tks[k]

    for s in segs:
        i = s["i"]
        d = s["dur"] + extra_last.get(i, 0.0)
        lbl = f"v{i}x" if i in extra_last else f"v{i}"
        filters.append(
            f"[{i}:v]trim=duration={d:.3f},setpts=PTS-STARTPTS,settb=AVTB,"
            f"scale={W}:{H},fps={FPS},format=yuv420p[{lbl}]")

    acc, group_labels = 0.0, []
    for k, g in enumerate(groups):
        labels = [f"[v{s['i']}x]" if s["i"] in extra_last else f"[v{s['i']}" for s in g]
        labels = [l if l.endswith("]") else l + "]" for l in labels]
        gl = f"[g{k}]"
        filters.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0,settb=AVTB{gl}")
        group_labels.append((gl, sum(s["dur"] for s in g), tks[k] if k >= 1 else 0.0))

    chain = group_labels[0][0]
    for k in range(1, len(group_labels)):
        acc += group_labels[k - 1][1]
        T, xtype = tks[k], xtypes[k]
        offset = max(0.0, acc - T)
        ol = f"[x{k}]"
        filters.append(f"{chain}{group_labels[k][0]}xfade=transition={xtype}:"
                       f"duration={T}:offset={offset:.3f}{ol}")
        chain = ol

    # 开场：镜面蒙版等效，两片幕布向两侧拉开
    L, R = curtain_idx
    filters.append(
        f"[{L}:v]format=rgba,scale={W//2}:{H}[cl];"
        f"{chain}[cl]overlay=x='0-{W//2}*min(t/{CURTAIN_SEC},1)':y=0:"
        f"enable='lt(t,{CURTAIN_SEC})'[c1]")
    chain = "[c1]"
    filters.append(
        f"[{R}:v]format=rgba,scale={W//2}:{H}[cr];"
        f"{chain}[cr]overlay=x='{W//2}+{W//2}*min(t/{CURTAIN_SEC},1)':y=0:"
        f"enable='lt(t,{CURTAIN_SEC})'[c2]")
    chain = "[c2]"

    # 文字（免费动画等效：alpha 淡入淡出）
    for j, t in enumerate(plan["texts"]):
        tl, ol = f"[t{j}]", f"[o{j}]"
        filters.append(
            f"[{text_idx[j]}:v]format=rgba,"
            f"fade=t=in:st={t['start']:.3f}:d=0.30:alpha=1,"
            f"fade=t=out:st={t['end']-0.35:.3f}:d=0.35:alpha=1{tl}")
        filters.append(f"{chain}{tl}overlay=0:0:"
                       f"enable='between(t,{t['start']},{t['end']})'{ol}")
        chain = ol
    filters.append(f"{chain}format=yuv420p[vout]")
    filters.append(f"[{audio_idx}:a]atrim=0:{total},asetpts=PTS-STARTPTS,"
                   f"aresample=48000,aformat=channel_layouts=stereo[aout]")

    with open(os.path.join(WORK, "v2_filters.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(filters))
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-stats"] + inputs + [
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "[aout]",
        "-t", str(total), "-r", str(FPS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-ar", "48000", "-ac", "2", "-movflags", "+faststart", out, "-y"]
    print(f"渲染中（{len(segs)} 片段 / {len(filters)} 个滤镜 / {len(cmd)} 参数）...")
    p = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
    if p.returncode != 0:
        print(p.stderr[-5000:])
        raise RuntimeError("MP4 渲染失败")
    print(f"成片: {out} ({os.path.getsize(out)//1024//1024} MB)")


if __name__ == "__main__":
    main()
