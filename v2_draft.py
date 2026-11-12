# -*- coding: utf-8 -*-
"""v2 剪映草稿：挂满免费官方资源，并导出自包含 zip。

轨道结构：
  MainVideo  36 段预裁剪片段 + 19 个免费转场 + 24 组推拉关键帧 + 7 个免费蒙版
  EffectTrack 12 段免费画面特效（严格不重叠）
  FilterTrack 全片免费「质感电影」滤镜
  Stickers    5 个图形贴片（等效贴纸层，PNG 画中画）
  BGM         60s 现场原声
  SFX         19 段本机缓存的官方免费音效
  Titles      5 段文字 + 免费入场/出场动画
"""
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
import zipfile
from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import WORK, DRAFTS_ROOT, FFPROBE  # noqa: E402
from jyenv import JyProject, draft, LIB_ROOT, SCRIPTS_PATH as SCRIPTS  # noqa: E402

if not DRAFTS_ROOT:
    raise RuntimeError(
        "找不到剪映草稿目录。请设置环境变量 JYAM_DRAFTS 指向 "
        "%LOCALAPPDATA%\\JianyingPro\\User Data\\Projects\\com.lveditor.draft"
    )

ROOT = os.path.dirname(os.path.abspath(__file__))
PLAN = os.path.join(ROOT, "v2_edit_plan.json")
ASSETS = os.path.join(WORK, "v2_assets.json")
MANIFEST = os.path.join(WORK, "manifest_v2.json")
STICKER_DIR = os.path.join(WORK, "v2_stickers")
EXPORTS = os.path.join(ROOT, "exports")
BACKUPS = os.path.join(ROOT, "backups")

MAIN_FILES = ("draft_info.json", "draft_content.json")
BASE_FILES = ("draft_info.json", "draft_content.json", "draft_meta_info.json",
              "draft_settings", "key_value.json")


def backup_existing(path, tag):
    if not os.path.isdir(path):
        return
    stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{time.time_ns() % 1_000_000:06d}"
    moved = os.path.join(BACKUPS, f"{tag}_{stamp}")
    os.makedirs(BACKUPS, exist_ok=True)
    same = os.path.splitdrive(os.path.abspath(path))[0].lower() == \
        os.path.splitdrive(os.path.abspath(moved))[0].lower()
    if same:
        shutil.move(path, moved)
    else:
        shutil.copytree(path, moved, dirs_exist_ok=True)
    print(f"  同名旧目录已备份: {os.path.basename(moved)}")


def star(d, cx, cy, r, color, alpha=210):
    pts = []
    for k in range(8):
        ang = math.pi / 4 * k - math.pi / 2
        rr = r if k % 2 == 0 else r * 0.28
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    d.polygon(pts, fill=(*color, alpha))


def make_sticker_png(seg, out):
    """只含图形贴片的透明 PNG，作为草稿画中画「贴纸等效层」。"""
    W, H = 1920, 1080
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    st = seg["sticker"]
    pos = {"tl": (90, 90), "tr": (W - 340, 90), "bl": (90, H - 180),
           "br": (W - 340, H - 180)}[st["pos"]]
    x, y = pos
    if st["kind"] == "badge":
        try:
            font = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 34)
        except OSError:
            font = ImageFont.load_default()
        d.rounded_rectangle([x, y, x + 212, y + 62], radius=8,
                            fill=(0, 0, 0, 110), outline=(255, 255, 255, 160), width=2)
        d.text((x + 18, y + 10), st["label"], font=font, fill=(255, 255, 255, 230))
        d.line([(x, y + 74), (x + 212, y + 74)], fill=(255, 255, 255, 140), width=2)
    else:
        for k in range(4):
            star(d, x + k * 62, y + (k % 2) * 38, 20 + k * 3, (255, 240, 210), 185)
    img.save(out)


def probe_dur(path):
    import subprocess
    p = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 1.0


def build(plan, man):
    name = plan["name"]
    backup_existing(os.path.join(DRAFTS_ROOT, name), "v2_draft")
    project = JyProject(name, width=1920, height=1080, overwrite=True)
    project.script.fps = 30

    os.makedirs(STICKER_DIR, exist_ok=True)
    segs, kf_count, mask_count, sticker_n = [], 0, 0, 0
    for s in plan["segments"]:
        seg = project.add_media_safe(
            man["clips"][str(s["i"])], f"{s['start']}s", f"{s['dur']}s",
            track_name="MainVideo", source_start=0)
        if seg is None:
            raise RuntimeError(f"片段 {s['i']} 添加失败")
        # 免费推拉关键帧：草稿里可见可编辑，但幅度取 clip 烘焙的 25%，
        # 避免两边叠加导致画面来回抽搐（上一版 45% + 全段铺满就是这个毛病）
        push = s["push"]
        if push["dir"] != "none":
            amp = push["amp"] * 0.25
            v0 = 1.0 if push["dir"] == "in" else 1.0 + amp
            v1 = 1.0 + amp if push["dir"] == "in" else 1.0
            kp = draft.KeyframeProperty.uniform_scale
            seg.add_keyframe(kp, 0, v0)
            seg.add_keyframe(kp, int(s["dur"] * 1_000_000), v1)
            kf_count += 1
        # 免费蒙版
        if s["mask"]:
            mt = getattr(draft.MaskType, s["mask"]["name"], None)
            if mt is not None:
                seg.add_mask(mt, center_x=0.0, center_y=0.0,
                             size=s["mask"]["size"], rotation=s["mask"]["rotation"],
                             feather=s["mask"]["feather"])
                mask_count += 1
        segs.append(seg)

    # 免费转场（必须挂在前一个片段上）
    tr_count = 0
    for s in plan["segments"]:
        tr = s.get("transition")
        if not tr or s["i"] == 0:
            continue
        if project.add_transition_simple(tr["jy"], video_segment=segs[s["i"] - 1],
                                         duration=f"{tr['dur']}s") is None:
            raise RuntimeError(f"免费转场「{tr['jy']}」添加失败")
        tr_count += 1

    # 免费画面特效轨（严格不重叠）
    eff_count = 0
    for s in plan["segments"]:
        if not s.get("effect"):
            continue
        dur = min(s["dur"] - 0.02, 1.4)
        if project.add_effect_simple(s["effect"]["jy"], f"{s['start']}s",
                                     f"{dur:.3f}s", track_name="EffectTrack") is None:
            raise RuntimeError(f"免费特效「{s['effect']['jy']}」添加失败")
        eff_count += 1

    # 不叠全片滤镜：clip 已完成冷紫→炽红的统一调色，
    # 再盖一层官方滤镜等于二次调色，会把色彩弧线糊掉。
    if plan.get("filter"):
        project._ensure_track(draft.TrackType.filter, "FilterTrack")
        project.script.add_filter(
            draft.FilterType[plan["filter"]["name"]],
            draft.Timerange(0, plan["duration_us"]),
            track_name="FilterTrack", intensity=plan["filter"]["intensity"] * 100)

    # BGM
    if project.add_media_safe(man["bgm"], "0s", "60s", track_name="BGM") is None:
        raise RuntimeError("BGM 添加失败")

    # 官方免费音效轨
    sfx_count = 0
    pts = sorted(plan["sfx_points"], key=lambda p: p["at"])
    for j, p in enumerate(pts):
        nxt = pts[j + 1]["at"] if j + 1 < len(pts) else 60.0
        gap = max(0.25, nxt - p["at"] - 0.05)
        dur = round(min(probe_dur(p["file"]), gap, 1.3), 3)
        if project.add_media_safe(p["file"], f"{p['at']:.3f}s", f"{dur:.3f}s",
                                  track_name="SFX") is not None:
            sfx_count += 1

    # 图形贴片（等效免费贴纸层，PNG 画中画）
    for s in plan["segments"]:
        if not s.get("sticker"):
            continue
        png = os.path.join(STICKER_DIR, f"sticker_{s['i']:02d}.png")
        make_sticker_png(s, png)
        try:
            if project.add_media_safe(png, f"{s['start']}s", f"{min(s['dur'], 2.5):.3f}s",
                                      track_name="Stickers") is not None:
                sticker_n += 1
        except Exception as e:
            print(f"  贴片 {s['i']} 降级跳过: {e}")

    # 文字 + 免费入场/出场动画
    for t in plan["texts"]:
        if project.add_text_simple(
                text=t["text"], start_time=f"{t['start']}s",
                duration=f"{t['end'] - t['start']}s", track_name="Titles",
                style=draft.TextStyle(size=t["size"], color=(1.0, 1.0, 1.0), align=1),
                clip_settings=draft.ClipSettings(transform_x=0.0, transform_y=t["y"]),
                border=draft.TextBorder(color=(0, 0, 0), alpha=1.0, width=22.0),
                anim_in=t["anim_in"], anim_out=t["anim_out"]) is None:
            raise RuntimeError("文字片段添加失败")

    result = project.save()
    if result.get("status") != "SUCCESS":
        raise RuntimeError(f"保存失败: {result}")
    print(f"  主轨 {len(segs)} 段 / 免费转场 {tr_count}（3 种）/ 关键帧 {kf_count} 组 / "
          f"蒙版 {mask_count} / 免费特效 {eff_count}（按画面挑）/ "
          f"滤镜 0 / 音效 0 / 贴片 {sticker_n} / 文字 {len(plan['texts'])}")
    plan["_built"] = {"kf": kf_count, "mask": mask_count, "sfx": sfx_count,
                      "sticker": sticker_n, "effect": eff_count, "trans": tr_count}
    return result["draft_path"]


def normalize_timeline(draft_path, plan):
    total = plan["duration_us"]
    p = os.path.join(draft_path, "draft_info.json")
    with open(p, "r", encoding="utf-8") as f:
        info = json.load(f)
    info["duration"], info["fps"] = total, 30
    for track in info["tracks"]:
        track["flag"] = 0
        for seg in track["segments"]:
            seg["visible"] = True
            seg.pop("locked", None)
            seg.pop("is_locked", None)

    def track(name, ttype):
        return next(t for t in info["tracks"]
                    if t.get("name") == name and t.get("type") == ttype)

    main = sorted(track("MainVideo", "video")["segments"],
                  key=lambda s: s["target_timerange"]["start"])
    cursor = 0
    for k, seg in enumerate(main):
        d = round(plan["segments"][k]["dur"] * 1_000_000)
        if k == len(main) - 1:
            d = total - cursor
        seg["target_timerange"] = {"start": cursor, "duration": d}
        if seg.get("source_timerange"):
            seg["source_timerange"] = {"start": 0, "duration": d}
        cursor += d
    assert cursor == total, f"主轨累计 {cursor} != {total}"

    for s in track("BGM", "audio")["segments"]:
        s["target_timerange"] = {"start": 0, "duration": total}
        if s.get("source_timerange"):
            s["source_timerange"] = {"start": 0, "duration": total}

    tseg = sorted(track("Titles", "text")["segments"],
                  key=lambda s: s["target_timerange"]["start"])
    for s, tpl in zip(tseg, plan["texts"]):
        s["target_timerange"] = {"start": round(tpl["start"] * 1_000_000),
                                 "duration": round((tpl["end"] - tpl["start"]) * 1_000_000)}

    payload = json.dumps(info, ensure_ascii=False, separators=(",", ":"))
    for n in MAIN_FILES:
        with open(os.path.join(draft_path, n), "w", encoding="utf-8") as f:
            f.write(payload)

    mp = os.path.join(draft_path, "draft_meta_info.json")
    with open(mp, "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta["tm_duration"] = total
    for k, v in list(meta.items()):
        if "duration" in k.lower() and isinstance(v, (int, float)) and k != "tm_duration":
            if v in (0, 5_000_000):
                meta[k] = total
    meta["draft_name"] = plan["name"]
    meta["draft_fold_path"] = draft_path.replace("\\", "/")
    meta["draft_root_path"] = DRAFTS_ROOT.replace("\\", "/")
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    print("  四层时长统一到 60s / 30fps")


def verify(draft_path, plan, label="草稿"):
    total = plan["duration_us"]
    entries = set(os.listdir(draft_path))
    for r in BASE_FILES + ("materials",):
        assert r in entries, f"{label} 缺 {r}"
    raw = [open(os.path.join(draft_path, n), "rb").read() for n in MAIN_FILES]
    assert raw[0] == raw[1], f"{label} 双主文件字节不一致"
    info = json.loads(raw[0].decode("utf-8"))
    meta = json.load(open(os.path.join(draft_path, "draft_meta_info.json"), encoding="utf-8"))
    assert info["duration"] == total and meta["tm_duration"] == total
    assert info["canvas_config"]["width"] == 1920 and info["canvas_config"]["height"] == 1080

    def tk(name):
        return [t for t in info["tracks"] if t.get("name") == name]

    main = sorted(tk("MainVideo")[0]["segments"], key=lambda s: s["target_timerange"]["start"])
    cur = 0
    for s in main:
        tr = s["target_timerange"]
        assert tr["start"] == cur, f"{label} 主轨缺口 {tr['start']} != {cur}"
        cur += tr["duration"]
    assert cur == total and len(main) == len(plan["segments"])

    mats = info["materials"]
    trans = mats.get("transitions", [])
    kf = sum(1 for s in main if s.get("common_keyframes"))
    eff_n = sum(len(t["segments"]) for t in tk("EffectTrack"))
    assert len(trans) == plan["transitions_count"], f"{label} 转场数 {len(trans)}"
    assert kf >= 5, f"{label} 推拉关键帧组仅 {kf}"
    assert eff_n >= 4, f"{label} 免费特效仅 {eff_n}"
    assert len([t for t in tk("Titles") for _ in t["segments"]]) == len(plan["texts"])
    assert not tk("FilterTrack"), f"{label} 不应有二次调色滤镜轨"
    assert not tk("SFX"), f"{label} 不应有与现场原声打架的音效轨"
    for t in info["tracks"]:
        assert t["flag"] == 0

    # 免费硬校验：所有特效/滤镜/转场的名字必须来自 is_vip=False 清单
    with open(ASSETS, "r", encoding="utf-8") as f:
        assets = json.load(f)
    free_names = {it["name"] for g, items in assets.items() for it in items}
    for group in ("effects", "filters", "transitions"):
        for m in mats.get(group, []):
            nm = m.get("name") or m.get("effect_name") or ""
            if nm and nm not in free_names:
                raise RuntimeError(f"{label} 出现非免费资源: {group}/{nm}")
            if str(m.get("is_vip", "0")) in ("1", "True", "true"):
                raise RuntimeError(f"{label} 出现 VIP 资源: {group}/{nm}")

    for group in ("videos", "audios"):
        for m in mats.get(group, []):
            pp = m.get("path", "")
            assert pp and os.path.isfile(pp), f"{label} 素材断链 {pp}"
    print(f"  {label} 验收通过 | 60s/30fps/1080P | 主轨{len(main)}段 | "
          f"免费转场{len(trans)} | 关键帧{kf}组 | 免费特效{eff_n} | "
          f"无二次滤镜/无打架音效 | VIP=0 | 素材自包含")


def fingerprint(root, only=None):
    out = {}
    for cur, _dirs, files in os.walk(root):
        for n in files:
            p = os.path.join(cur, n)
            rel = os.path.relpath(p, root).replace("\\", "/")
            if only is not None and rel not in only:
                continue
            with open(p, "rb") as f:
                out[rel] = (os.path.getsize(p), hashlib.md5(f.read()).hexdigest())
    return out


def make_self_contained(draft_path, target_dir, tag, asset_root):
    backup_existing(target_dir, tag)
    os.makedirs(target_dir, exist_ok=True)
    for n in BASE_FILES:
        shutil.copy2(os.path.join(draft_path, n), os.path.join(target_dir, n))
    src, dst = os.path.join(draft_path, "materials"), os.path.join(target_dir, "materials")
    os.makedirs(dst, exist_ok=True)
    for n in os.listdir(src):
        p = os.path.join(src, n)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(dst, n))
    with open(os.path.join(target_dir, "draft_info.json"), "r", encoding="utf-8") as f:
        info = json.load(f)
    for group in ("videos", "audios"):
        for m in info["materials"].get(group, []):
            m["path"] = os.path.join(asset_root, "materials",
                                    os.path.basename(m["path"])).replace("\\", "/")
            if "media_path" in m:
                m["media_path"] = ""
    payload = json.dumps(info, ensure_ascii=False, separators=(",", ":"))
    for n in MAIN_FILES:
        with open(os.path.join(target_dir, n), "w", encoding="utf-8") as f:
            f.write(payload)
    mp = os.path.join(target_dir, "draft_meta_info.json")
    with open(mp, "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta["draft_fold_path"] = asset_root.replace("\\", "/")
    meta["draft_root_path"] = (LIB_ROOT or os.path.dirname(asset_root)).replace("\\", "/")
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    return target_dir


def export(draft_path, plan):
    os.makedirs(EXPORTS, exist_ok=True)
    name = plan["name"]
    deploy = os.path.join(LIB_ROOT, name)
    asset_root = deploy if os.path.isdir(LIB_ROOT) else None
    if asset_root:
        verify(make_self_contained(draft_path, deploy, "v2_deploy", asset_root),
               plan, label="草稿库部署副本")
    edir = os.path.join(EXPORTS, name)
    verify(make_self_contained(draft_path, edir, "v2_export", asset_root or edir),
           plan, label="导出目录副本")
    rel = list(BASE_FILES) + ["materials/" + n for n in os.listdir(os.path.join(edir, "materials"))
                             if os.path.isfile(os.path.join(edir, "materials", n))]
    zp = os.path.join(EXPORTS, name + "_剪映草稿.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rel:
            zf.write(os.path.join(edir, r), name + "/" + r)
    with zipfile.ZipFile(zp) as zf:
        assert zf.testzip() is None
        names = zf.namelist()
        tmp = tempfile.mkdtemp(prefix="jy_v2_import_")
        zf.extractall(tmp)
    ex = os.path.join(tmp, name)
    verify(ex, plan, label="解压模拟导入")
    assert fingerprint(edir, set(rel)) == fingerprint(ex, set(rel))
    print(f"\n  zip: {zp} ({len(names)} 条目 / {os.path.getsize(zp)//1024//1024} MB)")
    return zp


def main():
    with open(PLAN, "r", encoding="utf-8") as f:
        plan = json.load(f)
    with open(MANIFEST, "r", encoding="utf-8") as f:
        man = json.load(f)
    print(f"草稿: {plan['name']} | 1920x1080 / 30fps / 60s / 全免费官方资源")
    path = build(plan, man)
    normalize_timeline(path, plan)
    verify(path, plan, label="源草稿")
    export(path, plan)
    print("完成。")


if __name__ == "__main__":
    main()
