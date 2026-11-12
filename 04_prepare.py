# -*- coding: utf-8 -*-
"""按 edit_plan.json 预处理 36 个统一规格片段 + 现场原声 BGM + 字幕 PNG。

草稿与 MP4 共用同一批预裁剪片段，保证两个交付物切点/调色/运镜完全一致。
每个 clip 物理时长 = 标称时长 + EXTRA，多出的余量供 ffmpeg xfade 重叠。
片头淡入、片尾淡出与灯闪脉冲都烘焙进 clip，剪映草稿里同样可见。
"""
import concurrent.futures as cf
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import WORK, FFMPEG as FF, require_ffmpeg  # noqa: E402

require_ffmpeg()

CLIPS = os.path.join(WORK, "clips")
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
PLAN = os.path.join(PROJECT_DIR, "edit_plan.json")

EXTRA = 0.8
WIDTH, HEIGHT, FPS = 1920, 1080, 30


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {' '.join(cmd[:9])}\n{p.stderr[-900:]}")
    return p


def make_clip(seg, vids, last_index):
    src = vids[seg["src"]]["path"]
    out = os.path.join(CLIPS, f"{seg['i']:02d}_{seg['src']}.mp4")
    dur = seg["dur"] + EXTRA
    c = seg["crop"]
    chain = [
        f"crop={c['cw']}:{c['ch']}:{c['x']}:{c['y']}",
        f"scale={WIDTH}:{HEIGHT}:flags=lanczos",
        seg["grade"],
    ]
    if seg["i"] == 0:
        chain.append("fade=t=in:st=0:d=0.6:color=black")
    if seg.get("pulse"):
        chain.append("fade=t=in:st=0:d=0.13:color=white")
    if seg["i"] == last_index:
        chain.append(f"fade=t=out:st={max(0.1, seg['dur'] - 0.65):.3f}:d=0.65:color=black")
    chain += ["setsar=1", f"fps={FPS}", "format=yuv420p"]
    vf = ",".join(chain)
    run([FF, "-hide_banner", "-loglevel", "error",
         "-ss", f"{seg['src_start']:.3f}", "-i", src, "-t", f"{dur:.3f}",
         "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         out, "-y"])
    return out, os.path.getsize(out)


def make_bgm(plan):
    bgm = plan["bgm"]
    out = os.path.join(WORK, "bgm.m4a")
    total = plan["total_seconds"]
    af = (f"bass=g=3:f=110,"
          f"aecho=0.8:0.9:60:0.15,"
          f"volume=1.12,"
          f"afade=t=in:st=0:d={bgm['fade_in']},"
          f"afade=t=out:st={total - bgm['fade_out']}:d={bgm['fade_out']}")
    run([FF, "-hide_banner", "-loglevel", "error",
         "-ss", f"{bgm['source_offset']:.3f}", "-i", bgm["path"],
         "-t", str(total), "-vn", "-ac", "2", "-ar", "48000",
         "-af", af, "-c:a", "aac", "-b:a", "192k", out, "-y"])
    return out, os.path.getsize(out)


def make_text_png(text, size_px, y_ratio, out):
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", size_px)
    except OSError:
        try:
            font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", size_px)
        except OSError:
            font = ImageFont.load_default()
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    x = (WIDTH - tw) // 2 - box[0]
    y = int(HEIGHT * y_ratio - th / 2) - box[1]
    # 黑色描边 + 投影：舞台白屏/灯闪爆亮时白字依然读得清
    d.text((x + 4, y + 4), text, font=font, fill=(0, 0, 0, 175),
           stroke_width=3, stroke_fill=(0, 0, 0, 120))
    d.text((x, y), text, font=font, fill=(255, 255, 255, 248),
           stroke_width=3, stroke_fill=(0, 0, 0, 225))
    img.save(out)


def main():
    with open(PLAN, "r", encoding="utf-8") as f:
        plan = json.load(f)
    os.makedirs(CLIPS, exist_ok=True)
    segs, vids = plan["segments"], plan["videos"]
    last_index = segs[-1]["i"]

    print(f"预处理 {len(segs)} 个片段（4 并发，逐片段独立取景/调色）...")
    results = {}
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(make_clip, s, vids, last_index): s["i"] for s in segs}
        for fu in cf.as_completed(futs):
            i = futs[fu]
            path, size = fu.result()
            results[i] = path
            print(f"  clip {i:02d} ok  {size//1024} KB", end="\r")
    print(f"\n片段完成 {len(results)}/{len(segs)}，共 "
          f"{sum(os.path.getsize(p) for p in results.values())//1024//1024} MB")

    bgm_path, bgm_size = make_bgm(plan)
    print(f"BGM: {bgm_path} ({bgm_size//1024} KB)")

    texts = []
    for j, t in enumerate(plan["texts"]):
        out = os.path.join(WORK, f"text_{j}.png")
        px = 100 if t["size"] >= 12 else 58
        y_ratio = 0.5 if t["y"] == 0 else 0.79
        make_text_png(t["text"], px, y_ratio, out)
        texts.append(out)
    print(f"字幕 PNG: {len(texts)} 张")

    manifest = {
        "clips": {str(k): v for k, v in sorted(results.items())},
        "bgm": bgm_path,
        "texts": texts,
        "extra": EXTRA,
    }
    with open(os.path.join(WORK, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("清单: " + os.path.join(WORK, "manifest.json"))


if __name__ == "__main__":
    main()
