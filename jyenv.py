# -*- coding: utf-8 -*-
"""装载 jianying-editor 依赖（MIT，作者 luoluoluo22）。

草稿生成那两步需要这个外部技能来写剪映工程文件。这里统一做三件事：
  1 把 ffmpeg / ffprobe 所在目录挂到 PATH，下游脚本可直接按名字调用
  2 把技能的 scripts/ 加入 sys.path，才能 import jy_wrapper / pyJianYingDraft
  3 校验拿到的 pyJianYingDraft 确实是技能内置副本，不是环境里碰巧装的别的版本

技能目录默认 ~/.workbuddy/skills/jianying-editor，可用 JYAM_JY_SKILL 覆盖。
"""
import os
import sys

from config import FFMPEG, FFPROBE, require_ffmpeg

SKILL_ROOT = os.environ.get("JYAM_JY_SKILL") or os.path.join(
    os.path.expanduser("~"), ".workbuddy", "skills", "jianying-editor")

# 剪映「素材库草稿」目录，可选。留空则跳过库部署，只产出导出目录。
LIB_ROOT = os.environ.get("JYAM_LIB", "")


def _bootstrap():
    require_ffmpeg()
    for exe in (FFMPEG, FFPROBE):
        d = os.path.dirname(exe)
        if d and d not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")

    scripts = os.path.join(SKILL_ROOT, "scripts")
    if not os.path.isdir(scripts):
        raise RuntimeError(
            f"找不到 jianying-editor 技能：{SKILL_ROOT}\n"
            "草稿生成需要它（MIT 许可）。安装后或用 JYAM_JY_SKILL 指向它的目录。\n"
            "仓库：https://github.com/luoluoluo22/jianying-editor"
        )
    os.environ["JY_SKILL_ROOT"] = SKILL_ROOT
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return scripts


SCRIPTS_PATH = _bootstrap()

try:
    from jy_wrapper import JyProject          # noqa: E402,F401
    import pyJianYingDraft as draft           # noqa: E402,F401
except ImportError as exc:                    # pragma: no cover
    raise RuntimeError(
        f"jianying-editor 依赖不完整（{SKILL_ROOT}）：{exc}\n"
        "请确认技能完整安装，scripts/ 下应有 jy_wrapper.py 与 vendor/pyJianYingDraft。"
    ) from exc

# 防止串到环境里另一个 pyJianYingDraft，那样草稿结构与技能预期不一致
_EXPECTED = os.path.abspath(os.path.join(SCRIPTS_PATH, "vendor", "pyJianYingDraft"))
if os.path.normcase(os.path.abspath(os.path.dirname(draft.__file__))) != os.path.normcase(_EXPECTED):
    raise RuntimeError(
        f"pyJianYingDraft 来源不对：{draft.__file__}\n预期技能内置副本：{_EXPECTED}"
    )

__all__ = ["JyProject", "draft", "SCRIPTS_PATH", "SKILL_ROOT", "LIB_ROOT"]
