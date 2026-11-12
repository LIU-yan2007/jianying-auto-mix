# -*- coding: utf-8 -*-
"""按 edit_plan.json 生成《同一束光》剪映草稿，并导出完整自包含 zip。

四层时长统一（沿用本机已验证的工程规范）：
  1 draft_info.json 顶层 duration/fps  2 draft_content.json 字节一致
  3 主视频轨片段首尾相接铺满 0-60000000µs + 音频轨满轨
  4 draft_meta_info.json tm_duration = 60000000
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import WORK, DRAFTS_ROOT  # noqa: E402
from jyenv import JyProject, draft, LIB_ROOT, SCRIPTS_PATH  # noqa: E402

if not DRAFTS_ROOT:
    raise RuntimeError(
        "找不到剪映草稿目录。请设置环境变量 JYAM_DRAFTS 指向 "
        "%LOCALAPPDATA%\\JianyingPro\\User Data\\Projects\\com.lveditor.draft"
    )

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
PLAN = os.path.join(PROJECT_DIR, "edit_plan.json")
MANIFEST = os.path.join(WORK, "manifest.json")
EXPORTS = os.path.join(PROJECT_DIR, "exports")
BACKUPS = os.path.join(PROJECT_DIR, "backups")

MAIN_FILES = ("draft_info.json", "draft_content.json")
BASE_FILES = ("draft_info.json", "draft_content.json", "draft_meta_info.json",
              "draft_settings", "key_value.json")


def backup_existing(path, tag):
    if not os.path.isdir(path):
        return
    stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{time.time_ns() % 1_000_000:06d}"
    moved = os.path.join(BACKUPS, f"{tag}_{stamp}")
    os.makedirs(BACKUPS, exist_ok=True)
    same = (os.path.splitdrive(os.path.abspath(path))[0].lower()
            == os.path.splitdrive(os.path.abspath(moved))[0].lower())
    if same:
        shutil.move(path, moved)
    else:
        shutil.copytree(path, moved, dirs_exist_ok=True)
    print(f"  同名旧目录已备份: {moved}")


def build(plan, manifest):
    name = plan["name"]
    backup_existing(os.path.join(DRAFTS_ROOT, name), "concert_draft")
    project = JyProject(name, width=plan["width"], height=plan["height"], overwrite=True)
    project.script.fps = plan["fps"]

    segs = []
    for s in plan["segments"]:
        clip = manifest["clips"][str(s["i"])]
        seg = project.add_media_safe(
            clip, start_time=f"{s['start']}s", duration=f"{s['dur']}s",
            track_name="MainVideo", source_start=0,
        )
        if seg is None:
            raise RuntimeError(f"片段 {s['i']} 添加失败")
        segs.append(seg)

    # 剪映转场必须挂在前一个片段上
    applied = 0
    for s in plan["segments"]:
        tr = s.get("transition")
        if not tr or s["i"] == 0:
            continue
        got = project.add_transition_simple(tr["jy"], video_segment=segs[s["i"] - 1],
                                            duration=f"{tr['dur']}s")
        if got is None:
            raise RuntimeError(f"转场「{tr['jy']}」添加失败")
        applied += 1

    # 音频必须走 add_media_safe 才会 stage 素材，否则 zip 解压后断链
    audio = project.add_media_safe(manifest["bgm"], "0s", f"{plan['total_seconds']}s",
                                   track_name="BGM")
    if audio is None:
        raise RuntimeError("BGM 音频添加失败")

    for t in plan["texts"]:
        txt = project.add_text_simple(
            text=t["text"], start_time=f"{t['start']}s",
            duration=f"{t['end'] - t['start']}s", track_name="Titles",
            style=draft.TextStyle(size=t["size"], color=(1.0, 1.0, 1.0), align=1),
            clip_settings=draft.ClipSettings(transform_x=0.0, transform_y=t["y"]),
            border=draft.TextBorder(color=(0.0, 0.0, 0.0), alpha=1.0, width=22.0),
        )
        if txt is None:
            raise RuntimeError("文字片段添加失败")

    result = project.save()
    if result.get("status") != "SUCCESS":
        raise RuntimeError(f"保存失败: {result}")
    print(f"  片段 {len(segs)} / 转场 {applied} / 音频 1 轨 / 字幕 {len(plan['texts'])} 段")
    return result["draft_path"]


def normalize_timeline(draft_path, plan):
    total = plan["duration_us"]
    info_path = os.path.join(draft_path, "draft_info.json")
    with open(info_path, "r", encoding="utf-8") as f:
        info = json.load(f)

    info["duration"] = total
    info["fps"] = plan["fps"]
    for track in info["tracks"]:
        track["flag"] = 0
        for seg in track["segments"]:
            seg["visible"] = True
            seg.pop("locked", None)
            seg.pop("is_locked", None)

    vseg = sorted([t for t in info["tracks"] if t["type"] == "video"][0]["segments"],
                  key=lambda s: s["target_timerange"]["start"])
    cursor = 0
    for k, seg in enumerate(vseg):
        d = round(plan["segments"][k]["dur"] * 1_000_000)
        if k == len(vseg) - 1:
            d = total - cursor
        seg["target_timerange"] = {"start": cursor, "duration": d}
        if seg.get("source_timerange"):
            seg["source_timerange"] = {"start": 0, "duration": d}
        cursor += d
    assert cursor == total, f"主轨道累计 {cursor} != {total}"

    aseg = [t for t in info["tracks"] if t["type"] == "audio"][0]["segments"]
    for s in aseg:
        s["target_timerange"] = {"start": 0, "duration": total}
        if s.get("source_timerange"):
            s["source_timerange"] = {"start": 0, "duration": total}

    tseg = sorted([t for t in info["tracks"] if t["type"] == "text"][0]["segments"],
                  key=lambda s: s["target_timerange"]["start"])
    for s, tpl in zip(tseg, plan["texts"]):
        st = round(tpl["start"] * 1_000_000)
        d = round((tpl["end"] - tpl["start"]) * 1_000_000)
        s["target_timerange"] = {"start": st, "duration": d}

    payload = json.dumps(info, ensure_ascii=False, separators=(",", ":"))
    for n in MAIN_FILES:
        with open(os.path.join(draft_path, n), "w", encoding="utf-8") as f:
            f.write(payload)

    meta_path = os.path.join(draft_path, "draft_meta_info.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta["tm_duration"] = total
    for k, v in list(meta.items()):
        if "duration" in k.lower() and isinstance(v, (int, float)) and k != "tm_duration":
            if v in (0, 5_000_000):
                meta[k] = total
    meta["draft_name"] = plan["name"]
    meta["draft_fold_path"] = draft_path.replace("\\", "/")
    meta["draft_root_path"] = DRAFTS_ROOT.replace("\\", "/")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    print("  四层时长统一到 60s / 30fps，轨道可见未锁定")


def verify(draft_path, plan, label="草稿"):
    total = plan["duration_us"]
    entries = set(os.listdir(draft_path))
    for r in BASE_FILES + ("materials",):
        assert r in entries, f"{label} 缺少 {r}"
    raw = [open(os.path.join(draft_path, n), "rb").read() for n in MAIN_FILES]
    assert raw[0] == raw[1], f"{label} 双主文件字节不一致"
    info = json.loads(raw[0].decode("utf-8"))
    meta = json.load(open(os.path.join(draft_path, "draft_meta_info.json"), encoding="utf-8"))

    assert info["duration"] == total, f"{label} 全局时长 {info['duration']}"
    assert info["fps"] == plan["fps"]
    assert info["canvas_config"]["width"] == plan["width"]
    assert info["canvas_config"]["height"] == plan["height"]
    assert meta["tm_duration"] == total, f"{label} tm_duration {meta['tm_duration']}"

    vt = [t for t in info["tracks"] if t["type"] == "video"]
    at = [t for t in info["tracks"] if t["type"] == "audio"]
    tt = [t for t in info["tracks"] if t["type"] == "text"]
    assert len(vt) == 1 and len(vt[0]["segments"]) == len(plan["segments"]), \
        f"{label} 主轨道片段数不符"
    assert len(at) == 1 and len(at[0]["segments"]) == 1, f"{label} 音频轨异常"
    assert len(tt) == 1 and len(tt[0]["segments"]) == len(plan["texts"]), f"{label} 文字轨异常"

    ordered = sorted(vt[0]["segments"], key=lambda s: s["target_timerange"]["start"])
    cursor = 0
    for s in ordered:
        tr = s["target_timerange"]
        assert tr["start"] == cursor, f"{label} 主轨道有缺口/重叠: {tr['start']} != {cursor}"
        assert tr["duration"] > 0
        assert s.get("visible") is True and not s.get("locked")
        cursor = tr["start"] + tr["duration"]
    assert cursor == total, f"{label} 主轨道总长 {cursor} != {total}"

    aud = at[0]["segments"][0]["target_timerange"]
    assert aud == {"start": 0, "duration": total}, f"{label} 音频不是满轨: {aud}"

    for t in info["tracks"]:
        assert t["flag"] == 0, f"{label} 轨道 {t['name']} 被隐藏"

    trans = info["materials"].get("transitions", [])
    assert len(trans) == plan["transitions_count"], \
        f"{label} 转场数 {len(trans)} != {plan['transitions_count']}"
    refs = set()
    for s in vt[0]["segments"]:
        refs.update(s.get("extra_material_refs", []))
    for tr in trans:
        assert tr["id"] in refs, f"{label} 转场 {tr['name']} 未被片段引用"

    vids = info["materials"]["videos"]
    assert len(vids) >= 2, f"{label} 视频素材不足"
    for v in vids:
        assert "materials" in v["path"].replace("\\", "/").lower()
        assert os.path.isfile(v["path"]), f"{label} 素材断链 {v['path']}"
    for a in info["materials"]["audios"]:
        assert os.path.isfile(a["path"]), f"{label} 音频断链 {a['path']}"

    for ts, tmpl in zip(sorted(tt[0]["segments"], key=lambda s: s["target_timerange"]["start"]),
                        plan["texts"]):
        mat = [m for m in info["materials"]["texts"] if m["id"] == ts["material_id"]][0]
        c = json.loads(mat["content"])
        assert c["text"] == tmpl["text"]
        assert c["styles"][0]["fill"]["content"]["solid"]["color"] == [1.0, 1.0, 1.0]
        assert mat["alignment"] == 1

    assert b'5000000' not in raw[0], f"{label} 残留 5 秒默认值"
    print(f"  {label} 验收通过 | 60s / 30fps / 1920x1080 | {len(ordered)} 片段首尾相接 | "
          f"{len(trans)} 转场 | 音频+字幕轨可见可编辑 | 素材自包含")


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
    src_mat = os.path.join(draft_path, "materials")
    dst_mat = os.path.join(target_dir, "materials")
    os.makedirs(dst_mat, exist_ok=True)
    for n in os.listdir(src_mat):
        p = os.path.join(src_mat, n)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(dst_mat, n))

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
    meta_path = os.path.join(target_dir, "draft_meta_info.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta["draft_fold_path"] = asset_root.replace("\\", "/")
    meta["draft_root_path"] = (LIB_ROOT or os.path.dirname(asset_root)).replace("\\", "/")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    return target_dir


def export(draft_path, plan):
    os.makedirs(EXPORTS, exist_ok=True)
    name = plan["name"]
    deploy_dir = os.path.join(LIB_ROOT, name)
    asset_root = deploy_dir if os.path.isdir(LIB_ROOT) else None

    if asset_root:
        dep = make_self_contained(draft_path, deploy_dir, "concert_deploy", asset_root)
        verify(dep, plan, label="草稿库部署副本")

    export_dir = os.path.join(EXPORTS, name)
    make_self_contained(draft_path, export_dir, "concert_export", asset_root or export_dir)
    verify(export_dir, plan, label="导出目录副本")

    rel_files = list(BASE_FILES) + [
        "materials/" + n for n in os.listdir(os.path.join(export_dir, "materials"))
        if os.path.isfile(os.path.join(export_dir, "materials", n))
    ]
    zip_path = os.path.join(EXPORTS, name + "_剪映草稿.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in rel_files:
            zf.write(os.path.join(export_dir, rel), name + "/" + rel)
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.testzip() is None, "zip CRC 校验失败"
        names = zf.namelist()
        tmp = tempfile.mkdtemp(prefix="jy_concert_import_")
        zf.extractall(tmp)
    extracted = os.path.join(tmp, name)
    verify(extracted, plan, label="解压模拟导入")
    assert fingerprint(export_dir, set(rel_files)) == fingerprint(extracted, set(rel_files)), \
        "zip 解压后逐文件 MD5 不一致"
    print(f"\n  zip: {zip_path}")
    print(f"  {len(names)} 条目 / {os.path.getsize(zip_path)//1024//1024} MB，MD5 + CRC 全通过")
    return zip_path


def main():
    with open(PLAN, "r", encoding="utf-8") as f:
        plan = json.load(f)
    with open(MANIFEST, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    print(f"草稿: {plan['name']} | {plan['width']}x{plan['height']} / {plan['fps']}fps / 60s")
    path = build(plan, manifest)
    normalize_timeline(path, plan)
    verify(path, plan, label="源草稿")
    export(path, plan)
    print("完成。")


if __name__ == "__main__":
    main()
