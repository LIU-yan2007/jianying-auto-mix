# -*- coding: utf-8 -*-
"""v2 独立验收：ffprobe 规格、抽帧目视、直读 zip 原始 JSON 交叉复核。"""
import json
import os
import subprocess
import sys
import zipfile

from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.abspath(__file__))
from config import WORK, FFMPEG as FF, FFPROBE as FP, require_ffmpeg  # noqa: E402

require_ffmpeg()
PLAN = os.path.join(ROOT, "v2_edit_plan.json")
NAME = json.load(open(PLAN, encoding="utf-8"))["name"]
MP4 = os.path.join(ROOT, "exports", NAME + ".mp4")
ZIP = os.path.join(ROOT, "exports", NAME + "_剪映草稿.zip")


def probe():
    cmd = [FP, "-v", "error", "-show_entries",
           "format=duration,format_name:stream=index,codec_type,codec_name,width,height,"
           "r_frame_rate,sample_rate,channels,duration", "-of", "json", MP4]
    out = json.loads(subprocess.run(cmd, capture_output=True, text=True).stdout)
    print(f"成片: {os.path.getsize(MP4)//1024//1024} MB / {out['format']['duration']}s / "
          f"{out['format']['format_name']}")
    for s in out["streams"]:
        if s["codec_type"] == "video":
            print(f"  视频 {s['codec_name']} {s['width']}x{s['height']} {s['r_frame_rate']}")
        else:
            print(f"  音频 {s['codec_name']} {s['sample_rate']}Hz {s['channels']}ch")
    assert abs(float(out["format"]["duration"]) - 60.0) < 0.05
    v = [s for s in out["streams"] if s["codec_type"] == "video"][0]
    a = [s for s in out["streams"] if s["codec_type"] == "audio"][0]
    assert (v["width"], v["height"], v["r_frame_rate"]) == (1920, 1080, "30/1")
    assert a["sample_rate"] == "48000" and a["channels"] == 2
    assert "mp4" in out["format"]["format_name"]
    print("  规格验收通过: 1080P / MP4 / 48000Hz / 30fps / 60s")


def frames(times, cols, tag, tw=480, th=270):
    rows = (len(times) + cols - 1) // cols
    canvas = Image.new("RGB", (tw * cols, (th + 22) * rows), (18, 18, 20))
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 13)
    except OSError:
        font = ImageFont.load_default()
    for k, t in enumerate(times):
        tmp = os.path.join(WORK, f"v2vf_{tag}_{k:02d}.png")
        subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}",
                        "-i", MP4, "-frames:v", "1", "-vf", f"scale={tw}:{th}", tmp, "-y"],
                       check=True, capture_output=True)
        x, y = (k % cols) * tw, (k // cols) * (th + 22)
        canvas.paste(Image.open(tmp).convert("RGB"), (x, y + 22))
        d.text((x + 6, y + 3), f"t = {t:.1f}s", fill=(235, 235, 235), font=font)
    p = os.path.join(WORK, tag + ".jpg")
    canvas.save(p, quality=92)
    print(f"抽帧图: {p}")
    return p


def zip_check():
    with zipfile.ZipFile(ZIP) as zf:
        assert zf.testzip() is None
        info = json.loads(zf.read(f"{NAME}/draft_info.json").decode("utf-8"))
        meta = json.loads(zf.read(f"{NAME}/draft_meta_info.json").decode("utf-8"))
        assert zf.read(f"{NAME}/draft_content.json") == zf.read(f"{NAME}/draft_info.json")
        names = zf.namelist()
    plan = json.load(open(PLAN, encoding="utf-8"))
    assert info["duration"] == 60_000_000 and meta["tm_duration"] == 60_000_000
    main = sorted(next(t for t in info["tracks"] if t.get("name") == "MainVideo")["segments"],
                  key=lambda s: s["target_timerange"]["start"])
    cur = 0
    for s in main:
        assert s["target_timerange"]["start"] == cur
        cur += s["target_timerange"]["duration"]
    assert cur == 60_000_000 and len(main) == len(plan["segments"])
    assert len(info["materials"].get("transitions", [])) == plan["transitions_count"]
    kf = sum(1 for s in main if s.get("common_keyframes"))
    eff = sum(len(t["segments"]) for t in info["tracks"] if t.get("name") == "EffectTrack")
    assert kf >= 5 and eff >= 4
    assert not any(t.get("name") == "FilterTrack" for t in info["tracks"])
    assert not any(t.get("name") == "SFX" for t in info["tracks"])
    # VIP 独立复核
    assets = json.load(open(os.path.join(WORK, "v2_assets.json"), encoding="utf-8"))
    free = {it["name"] for g, items in assets.items() for it in items}
    for g in ("effects", "filters", "transitions"):
        for m in info["materials"].get(g, []):
            nm = m.get("name") or ""
            assert not nm or nm in free, f"非免费资源 {g}/{nm}"
            assert str(m.get("is_vip", "0")) not in ("1", "True"), f"VIP {g}/{nm}"
    print(f"  zip 独立复核通过 | {len(names)} 条目 | 主轨{len(main)}段 60s | "
          f"免费转场{plan['transitions_count']} | 关键帧{kf}组 | 免费特效{eff} | "
          f"无二次滤镜/无打架音效 | VIP=0")


def main():
    probe()
    frames([0.9, 4.5, 9.5, 14.5, 19.5, 24.5, 29.5, 34.5,
            39.5, 44.5, 49.5, 55.5], 4, "v2_timeline")
    frames([1.8, 17.8, 39.5, 57.8, 59.6, 30.0], 3, "v2_titles")
    zip_check()
    print("\n全部验收通过。")


if __name__ == "__main__":
    main()
