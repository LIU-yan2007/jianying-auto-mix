# -*- coding: utf-8 -*-
"""v2 预处理：36 片段（推拉关键帧 + 光效/贴片装饰）、官方音效分层混音、幕布素材。

所有视觉装饰都烘焙进 clip，剪映草稿与 MP4 共用同一批片段，切点完全一致。
"""
import concurrent.futures as cf
import json
import math
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont, ImageFilter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.abspath(__file__))

from config import WORK, FFMPEG as FF, require_ffmpeg  # noqa: E402

require_ffmpeg()

CLIPS = os.path.join(WORK, "v2_clips")
DECO = os.path.join(WORK, "v2_deco")
PLAN = os.path.join(ROOT, "v2_edit_plan.json")
V1_BGM = os.path.join(WORK, "bgm.m4a")

EXTRA = 0.8
W, H, FPS = 1920, 1080, 30


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败:\n{' '.join(cmd[:10])}\n{p.stderr[-1000:]}")
    return p


def radial_glow(img, cx, cy, radius, color, strength):
    """在 RGBA 图上叠一个径向渐变光斑。"""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    steps = 26
    for k in range(steps, 0, -1):
        r = radius * k / steps
        a = int(strength * (1 - k / steps) ** 2 * 255)
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  fill=(color[0], color[1], color[2], a))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(18)))


def draw_star(d, cx, cy, r, color, alpha=210):
    pts = []
    for k in range(8):
        ang = math.pi / 4 * k - math.pi / 2
        rr = r if k % 2 == 0 else r * 0.28
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    d.polygon(pts, fill=(*color, alpha))


def make_deco(seg, out):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    eff, st = seg.get("effect"), seg.get("sticker")
    if eff and eff["overlay"] not in ("blur", "flash"):
        kind = eff["overlay"]
        a = eff["alpha"]
        if kind == "beam":
            for cx, cy, r in [(1320, 180, 330), (1580, 420, 240)]:
                radial_glow(img, cx, cy, r, (255, 226, 178), a)
        elif kind == "bokeh":
            for cx, cy, r in [(300, 300, 150), (1560, 720, 190), (900, 180, 120)]:
                radial_glow(img, cx, cy, r, (255, 190, 210), a * 0.8)
        elif kind == "halo":
            radial_glow(img, 960, 540, 620, (255, 210, 180), a * 0.75)
        elif kind == "star":
            d = ImageDraw.Draw(img)
            for cx, cy, r in [(320, 240, 34), (1600, 300, 26), (1420, 820, 30),
                              (620, 760, 20), (1100, 200, 22)]:
                draw_star(d, cx, cy, r, (255, 245, 220), int(a * 620))
    if st:
        d = ImageDraw.Draw(img)
        pos = {"tl": (90, 90), "tr": (W - 330, 90), "bl": (90, H - 170),
               "br": (W - 330, H - 170)}[st["pos"]]
        if st["kind"] == "badge":
            label = st["label"]
            try:
                font = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 34)
            except OSError:
                font = ImageFont.load_default()
            x, y = pos
            d.rounded_rectangle([x, y, x + 210, y + 62], radius=8,
                                fill=(0, 0, 0, 120), outline=(255, 255, 255, 150), width=2)
            d.text((x + 18, y + 10), label, font=font, fill=(255, 255, 255, 225))
            d.line([(x, y + 74), (x + 210, y + 74)], fill=(255, 255, 255, 130), width=2)
        else:
            x, y = pos
            for k in range(4):
                draw_star(d, x + k * 62, y + (k % 2) * 38, 20 + k * 3,
                          (255, 240, 210), 175)
    img.save(out)


def make_clip(seg, plan, last_index):
    src = plan["videos"][seg["src"]]["path"]
    out = os.path.join(CLIPS, f"{seg['i']:02d}_{seg['src']}.mp4")
    deco = os.path.join(DECO, f"deco_{seg['i']:02d}.png")
    dur = seg["dur"] + EXTRA
    c = seg["crop"]

    chain = [f"crop={c['cw']}:{c['ch']}:{c['x']}:{c['y']}",
             f"scale={W}:{H}:flags=lanczos", seg["grade"], f"fps={FPS}"]

    # 关键帧推拉的成片等效：zoompan 逐帧缩放
    push = seg["push"]
    if push["dir"] != "none":
        amp, rate = push["amp"], push["amp"] / max(1.0, dur * FPS)
        if push["dir"] == "in":
            z = f"min(zoom+{rate:.6f},{1 + amp:.4f})"
        else:
            z = f"if(eq(on,1),{1 + amp:.4f},max(zoom-{rate:.6f},1.0))"
        chain.append(f"zoompan=z='{z}':d=1:"
                     f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                     f"s={W}x{H}:fps={FPS}")
    else:
        chain.append(f"scale={W}:{H}")

    # 片头淡入 / 片尾淡出 / 免费特效里的闪光
    if seg["i"] == 0:
        chain.append("fade=t=in:st=0:d=0.5:color=black")
    eff = seg.get("effect")
    if eff and eff["overlay"] in ("blur", "flash"):
        chain.append("fade=t=in:st=0:d=0.12:color=white")
    if seg["i"] == last_index:
        chain.append(f"fade=t=out:st={max(0.1, seg['dur'] - 0.65):.3f}:d=0.65:color=black")
    chain += ["setsar=1", "format=yuv420p"]

    fg = (f"[0:v]{','.join(chain)}[base];"
          f"[1:v]format=rgba,scale={W}:{H}[dc];"
          f"[base][dc]overlay=0:0:shortest=1[out]")
    run([FF, "-hide_banner", "-loglevel", "error",
         "-ss", f"{seg['src_start']:.3f}", "-i", src, "-t", f"{dur:.3f}",
         "-loop", "1", "-framerate", str(FPS), "-i", deco,
         "-filter_complex", fg, "-map", "[out]", "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", out, "-y"])
    return out, os.path.getsize(out)


def make_audio(plan):
    """音频：以演唱会现场原声为唯一音轨。

    实测本机缓存的官方音效是 3.3-3.7kHz 高频噪声型 whoosh，叠在已有完整人声
    与鼓点的现场原声上非常突兀，故全部撤除，只保留干净的现场声。
    """
    import shutil
    out = os.path.join(WORK, "bgm_v2.m4a")
    pts = plan["sfx_points"]
    if not pts:
        shutil.copy2(V1_BGM, out)
        return out, os.path.getsize(out)
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-i", V1_BGM]
    for p in pts:
        cmd += ["-i", p["file"]]
    af = ["[0:a]aformat=sample_fmts=fltp:sample_rates=48000:"
          "channel_layouts=stereo,volume=1.0[b]"]
    for j, p in enumerate(pts):
        ms = int(p["at"] * 1000)
        af.append(f"[{j+1}:a]aformat=sample_fmts=fltp:sample_rates=48000:"
                  f"channel_layouts=stereo,adelay={ms}|{ms},"
                  f"volume={p['volume']:.2f},afade=t=out:st=0.7:d=0.35[s{j}]")
    mix = "[b]" + "".join(f"[s{j}]" for j in range(len(pts)))
    af.append(f"{mix}amix=inputs={len(pts)+1}:duration=first:normalize=0,"
              f"alimiter=limit=0.95,aresample=48000[aout]")
    cmd += ["-filter_complex", ";".join(af), "-map", "[aout]",
            "-t", str(plan["total_seconds"]), "-vn",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            out, "-y"]
    run(cmd)
    return out, os.path.getsize(out)


def make_curtains():
    """开场镜面蒙版的成片等效：两片黑色幕布向两侧拉开。"""
    paths = []
    for tag in ("left", "right"):
        p = os.path.join(WORK, f"curtain_{tag}.png")
        Image.new("RGBA", (W // 2, H), (0, 0, 0, 255)).save(p)
        paths.append(p)
    return paths


def main():
    with open(PLAN, "r", encoding="utf-8") as f:
        plan = json.load(f)
    os.makedirs(CLIPS, exist_ok=True)
    os.makedirs(DECO, exist_ok=True)
    segs = plan["segments"]
    last = segs[-1]["i"]

    print(f"生成 {len(segs)} 张装饰层（免费特效等效光效 + 图形贴片）...")
    for s in segs:
        make_deco(s, os.path.join(DECO, f"deco_{s['i']:02d}.png"))

    print(f"预处理 {len(segs)} 个片段（推拉关键帧烘焙，4 并发）...")
    results = {}
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(make_clip, s, plan, last): s["i"] for s in segs}
        for fu in cf.as_completed(futs):
            i = futs[fu]
            path, size = fu.result()
            results[i] = path
            print(f"  clip {i:02d} ok {size//1024} KB", end="\r")
    print(f"\n片段 {len(results)}/{len(segs)} 完成，共 "
          f"{sum(os.path.getsize(p) for p in results.values())//1024//1024} MB")

    bgm, bsz = make_audio(plan)
    print(f"分层音轨: {bgm} ({bsz//1024} KB) / {len(plan['sfx_points'])} 处官方音效")

    curtains = make_curtains()
    texts = [os.path.join(WORK, f"text_{j}.png") for j in range(len(plan["texts"]))]
    for p in texts:
        assert os.path.isfile(p), f"缺字幕 PNG: {p}"

    manifest = {
        "clips": {str(k): v for k, v in sorted(results.items())},
        "bgm": bgm, "texts": texts, "curtains": curtains,
        "deco": os.path.join(DECO, "deco_{i}.png"), "extra": EXTRA,
    }
    with open(os.path.join(WORK, "manifest_v2.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("清单: " + os.path.join(WORK, "manifest_v2.json"))


if __name__ == "__main__":
    main()
