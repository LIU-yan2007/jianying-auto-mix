# -*- coding: utf-8 -*-
"""集中配置：所有外部路径在这里解析，脚本里不再出现绝对路径。

优先级：环境变量 > sources.json / 自动探测 > 明确报错。

环境变量：
    JYAM_WORK      中间产物目录（默认系统 temp/jyam）
    JYAM_FFMPEG    ffmpeg 可执行文件
    JYAM_FFPROBE   ffprobe 可执行文件
    JYAM_DRAFTS    剪映草稿根目录（com.lveditor.draft）
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.environ.get("JYAM_SOURCES") or os.path.join(ROOT, "sources.json")

WORK = os.environ.get("JYAM_WORK") or os.path.join(tempfile.gettempdir(), "jyam")


# ---------------------------------------------------------------- 可执行文件

def _which(name):
    return shutil.which(name) or shutil.which(name + ".exe")


def _snapany(name):
    """探一下 SnapAny 随附的 ffmpeg（Windows 上很多人是这么装的）。"""
    base = os.path.join(os.path.expanduser("~"), "AppData", "Roaming",
                        "SnapAny", "tools", name)
    if not os.path.isdir(base):
        return None
    for ver in sorted(os.listdir(base), reverse=True):
        exe = os.path.join(base, ver, name + ".exe")
        if os.path.isfile(exe):
            return exe
    return None


def _resolve_bin(env_key, name):
    val = os.environ.get(env_key)
    if val and os.path.isfile(val):
        return val
    return _which(name) or _snapany(name)


FFMPEG = _resolve_bin("JYAM_FFMPEG", "ffmpeg")
FFPROBE = _resolve_bin("JYAM_FFPROBE", "ffprobe")


def require_ffmpeg():
    """在真正要用 ffmpeg 的地方调用，报错信息写得让人能自己修。"""
    missing = [n for n, v in (("ffmpeg", FFMPEG), ("ffprobe", FFPROBE)) if not v]
    if missing:
        raise RuntimeError(
            "找不到 " + " / ".join(missing) + "。\n"
            "请先安装 FFmpeg 并加入 PATH，或设置环境变量：\n"
            "  Windows:  set JYAM_FFMPEG=D:\\path\\to\\ffmpeg.exe\n"
            "  macOS/Linux:  export JYAM_FFMPEG=/usr/local/bin/ffmpeg\n"
            "下载地址：https://ffmpeg.org/download.html"
        )
    return FFMPEG, FFPROBE


# ---------------------------------------------------------------- 剪映草稿目录

def _drafts_root():
    env = os.environ.get("JYAM_DRAFTS")
    if env:
        return env
    if sys.platform == "win32":
        cand = os.path.join(os.environ.get("LOCALAPPDATA", ""), "JianyingPro",
                            "User Data", "Projects", "com.lveditor.draft")
        if os.path.isdir(cand):
            return cand
    return ""   # 非 Windows 或未安装剪映：只有草稿相关脚本需要它


DRAFTS_ROOT = _drafts_root()


# ---------------------------------------------------------------- 素材清单

def load_sources():
    """读取 sources.json，返回有序 dict：{key: {path, name, duration}}。

    duration 可省略，省略时用 ffprobe 实测。
    """
    if not os.path.isfile(SOURCES_FILE):
        raise FileNotFoundError(
            f"缺少素材清单 {SOURCES_FILE}\n"
            "请复制 sources.example.json 为 sources.json 并填入你自己的视频路径。"
        )
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    out = {}
    for item in raw.get("videos", []):
        key = item["key"]
        path = os.path.expanduser(item["path"])
        dur = item.get("duration")
        if dur is None:
            dur = _probe_duration(path)
        out[key] = {"path": path, "name": item.get("name", key),
                    "duration": float(dur)}
    if not out:
        raise ValueError(f"{SOURCES_FILE} 里 videos 为空")
    return out


def _probe_duration(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"素材不存在：{path}")
    _, fp = require_ffmpeg()
    p = subprocess.run(
        [fp, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True)
    try:
        return float(p.stdout.strip())
    except ValueError:
        raise RuntimeError(f"ffprobe 读不出时长：{path}\n{p.stderr[-400:]}")


# 各脚本按自己习惯的形态取用，body 代码无需改动
def as_tuples(with_label=True):
    """01 要 (key, label, path)，02 要 (key, path)。"""
    src = load_sources()
    if with_label:
        return [(k, v["name"], v["path"]) for k, v in src.items()]
    return [(k, v["path"]) for k, v in src.items()]


def as_dict():
    return load_sources()


def bgm_key():
    """BGM 取哪条素材的音轨。sources.json 的 bgm_source 指定，缺省用第一条。"""
    src = load_sources()
    key = None
    if os.path.isfile(SOURCES_FILE):
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            key = json.load(f).get("bgm_source")
    return key if key in src else next(iter(src))


# ---------------------------------------------------------------- 自检入口

if __name__ == "__main__":
    print(f"仓库根目录   : {ROOT}")
    print(f"中间产物目录 : {WORK}")
    print(f"ffmpeg       : {FFMPEG or '【未找到】'}")
    print(f"ffprobe      : {FFPROBE or '【未找到】'}")
    print(f"剪映草稿目录 : {DRAFTS_ROOT or '【未找到，草稿相关脚本不可用】'}")
    try:
        src = load_sources()
        print(f"素材清单     : {SOURCES_FILE}")
        for k, v in src.items():
            print(f"  [{k}] {v['name']}  {v['duration']:.2f}s  {v['path']}")
    except Exception as e:  # noqa: BLE001
        print(f"素材清单     : {e}")
