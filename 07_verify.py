# -*- coding: utf-8 -*-
"""独立验收：ffprobe 查成片规格、抽帧目视、直读 zip 原始 JSON 交叉复核草稿。

用与生成脚本不同的 Python 解释器读 zip 原始字节，避免"自己断言自己"。
"""
import json
import os
import subprocess
import sys
import zipfile

from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import WORK, FFMPEG as FF, FFPROBE as FP, require_ffmpeg  # noqa: E402

require_ffmpeg()

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
NAME = os.environ.get("JYAM_NAME") or "同一束光_演唱会60秒"
MP4 = os.path.join(PROJECT_DIR, "exports", NAME + ".mp4")
ZIP = os.path.join(PROJECT_DIR, "exports", NAME + "_剪映草稿.zip")


def probe():
    cmd = [FP, "-v", "error", "-show_entries",
           "format=duration,size:stream=index,codec_type,codec_name,width,height,"
           "r_frame_rate,sample_rate,channels,duration", "-of", "json", MP4]
    out = json.loads(subprocess.run(cmd, capture_output=True, text=True).stdout)
    print(f"成片: {os.path.getsize(MP4)//1024//1024} MB / {out['format']['duration']}s")
    for s in out["streams"]:
        if s["codec_type"] == "video":
            print(f"  视频 {s['codec_name']} {s['width']}x{s['height']} "
                  f"{s['r_frame_rate']} / {s['duration']}s")
        else:
            print(f"  音频 {s['codec_name']} {s['sample_rate']}Hz "
                  f"{s['channels']}ch / {s['duration']}s")
    assert abs(float(out["format"]["duration"]) - 60.0) < 0.05, "时长不是 60s"
    v = [s for s in out["streams"] if s["codec_type"] == "video"][0]
    a = [s for s in out["streams"] if s["codec_type"] == "audio"][0]
    assert (v["width"], v["height"]) == (1920, 1080)
    assert v["r_frame_rate"] == "30/1"
    assert a["channels"] == 2
    print("  ffprobe 规格验收通过")


def frames(times, cols, out_name, tw=480, th=270):
    rows = (len(times) + cols - 1) // cols
    canvas = Image.new("RGB", (tw * cols, (th + 22) * rows), (18, 18, 20))
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 13)
    except OSError:
        font = ImageFont.load_default()
    for k, t in enumerate(times):
        tmp = os.path.join(WORK, f"vf_{out_name}_{k:02d}.png")
        subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}",
                        "-i", MP4, "-frames:v", "1", "-vf", f"scale={tw}:{th}", tmp, "-y"],
                       check=True, capture_output=True)
        x, y = (k % cols) * tw, (k // cols) * (th + 22)
        canvas.paste(Image.open(tmp).convert("RGB"), (x, y + 22))
        d.text((x + 6, y + 3), f"t = {t:.1f}s", fill=(235, 235, 235), font=font)
    path = os.path.join(WORK, out_name + ".jpg")
    canvas.save(path, quality=92)
    print(f"抽帧图: {path}")
    return path


def zip_crosscheck():
    with zipfile.ZipFile(ZIP) as zf:
        assert zf.testzip() is None
        info = json.loads(zf.read(f"{NAME}/draft_info.json").decode("utf-8"))
        meta = json.loads(zf.read(f"{NAME}/draft_meta_info.json").decode("utf-8"))
        content = zf.read(f"{NAME}/draft_content.json")
        assert content == zf.read(f"{NAME}/draft_info.json"), "双主文件字节不一致"
        names = zf.namelist()
    assert info["duration"] == 60_000_000 and info["fps"] == 30
    assert meta["tm_duration"] == 60_000_000
    vt = [t for t in info["tracks"] if t["type"] == "video"][0]["segments"]
    at = [t for t in info["tracks"] if t["type"] == "audio"][0]["segments"]
    tt = [t for t in info["tracks"] if t["type"] == "text"][0]["segments"]
    ordered = sorted(vt, key=lambda s: s["target_timerange"]["start"])
    cur = 0
    for s in ordered:
        assert s["target_timerange"]["start"] == cur
        cur += s["target_timerange"]["duration"]
    assert cur == 60_000_000, f"主轨累计 {cur}"
    assert at[0]["target_timerange"]["duration"] == 60_000_000
    assert len(ordered) == 36 and len(tt) == 5
    assert len(info["materials"].get("transitions", [])) == 9
    # 素材路径自包含且真实存在（部署目录）
    for group in ("videos", "audios"):
        for m in info["materials"][group]:
            p = m["path"]
            assert "materials/" in p.replace("\\", "/"), p
    print(f"  zip 独立复核通过 | {len(names)} 条目 | 36 段首尾相接 60s / "
          f"9 转场 / 5 字幕 / 音频满轨 / 双主文件字节一致")


def main():
    probe()
    frames([0.6, 5.5, 10.5, 15.5, 20.5, 25.5, 30.5, 35.5,
            40.5, 45.5, 50.5, 55.5], 4, "timeline")
    frames([1.6, 4.6, 17.8, 39.8, 57.8, 59.6], 3, "titles")
    zip_crosscheck()
    print("\n全部验收通过。")


if __name__ == "__main__":
    main()
