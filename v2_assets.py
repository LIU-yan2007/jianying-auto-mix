# -*- coding: utf-8 -*-
"""从剪映官方 metadata 枚举中程序化筛出 is_vip=False 的免费资源，导出可用清单。

只认 metadata/*.py 里 EffectMeta/AnimationMeta/TransitionMeta 的第 2 个参数 is_vip；
data/*.csv 与 AVAILABLE_ASSETS.md 的 Free 列全部误标，绝不采信。
"""
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import WORK  # noqa: E402
from jyenv import SCRIPTS_PATH  # noqa: E402

META = os.path.join(SCRIPTS_PATH, "vendor", "pyJianYingDraft", "metadata")
OUT = os.path.join(WORK, "v2_assets.json")

FILES = {
    "transition": "transition_meta.py",
    "scene_effect": "video_scene_effect.py",
    "character_effect": "video_character_effect.py",
    "filter": "filter_meta.py",
    "text_intro": "text_intro.py",
    "text_outro": "text_outro.py",
    "text_loop": "text_loop.py",
    "video_intro": "video_intro.py",
    "video_outro": "video_outro.py",
    "mask": "mask_meta.py",
}

# 只取名字里带这些关键词的资源，避免清单过大；用于本片风格
WANT = {
    "transition": ["闪白", "叠化", "横向模糊", "竖向模糊", "模糊", "色彩溶解",
                   "向上擦除", "向下擦除", "向左擦除", "向右擦除", "渐变擦除",
                   "中心旋转", "横向拉幕", "竖向拉幕", "逆时针旋转", "画笔擦除"],
    "scene_effect": ["丁达尔光线", "动感模糊", "斜向模糊", "光斑虚化", "光斑飘落",
                     "光晕", "星光闪耀", "星光闪闪", "星星闪烁", "仙尘闪闪",
                     "定格闪烁", "CCD闪光", "彩虹光晕", "文字闪动", "哈苏胶片",
                     "回忆胶片", "冲屏闪粉", "柔光", "暗角", "曝光"],
    "filter": ["青橙电影", "质感电影", "质感暗调", "暗调氛围", "情绪电影",
               "情感电影", "赛博朋克", "复古工业", "高清4K电影"],
    "text_intro": ["逐字显影", "打字机_I", "复古打字机", "渐显", "冲屏位移",
                   "向上滑动", "向上露出", "居中打字", "向上翻转"],
    "text_outro": ["渐隐", "向上消失", "淡出", "缩小消失", "向下消失"],
    "text_loop": ["闪烁", "呼吸", "摆动", "波动", "发光"],
    "video_intro": ["渐显", "缩放", "推进", "向左", "向右", "向上", "旋转"],
    "video_outro": ["渐隐", "缩小", "旋转"],
    "mask": ["线性", "镜面", "圆形", "矩形", "爱心", "星形"],
}

# EffectMeta/TransitionMeta: 名, is_vip, resource_id, effect_id, md5
# AnimationMeta          : 名, is_vip, duration(数字), resource_id, effect_id, md5
LINE_EFFECT = re.compile(
    r'^\s*([^\s=]+)\s*=\s*(EffectMeta|TransitionMeta)\('
    r'\s*"([^"]*)"\s*,\s*(True|False)\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"',
)
LINE_ANIM = re.compile(
    r'^\s*([^\s=]+)\s*=\s*AnimationMeta\('
    r'\s*"([^"]*)"\s*,\s*(True|False)\s*,\s*[\d.]+\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"',
)


def parse(path, keywords=None):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            m = LINE_EFFECT.match(line)
            if m:
                key, cls, name, vip, rid, eid = m.groups()
            else:
                m = LINE_ANIM.match(line)
                if not m:
                    continue
                key, name, vip, rid, eid = m.groups()
            if vip != "False":
                continue
            if keywords and not any(k in name for k in keywords):
                continue
            out.append({"key": key, "name": name, "resource_id": rid,
                        "effect_id": eid, "line": ln})
    return out


def main():
    result = {}
    for group, fn in FILES.items():
        p = os.path.join(META, fn)
        if not os.path.isfile(p):
            continue
        kw = WANT.get(group)
        # mask_meta 无 is_vip 字段，单独处理
        if group == "mask":
            items = []
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    m = re.match(r'^\s*(\w+)\s*=\s*MaskMeta\(\s*"([^"]+)"', line)
                    if m:
                        items.append({"key": m.group(1), "name": m.group(2)})
            result[group] = items
        else:
            result[group] = parse(p, kw)
        print(f"  {group:18s} 免费可选 {len(result[group]):3d} 个")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("清单: " + OUT)

    # 硬断言：选中的每一个都必须是 is_vip=False，且带上官方 resource_id
    total = sum(len(v) for k, v in result.items() if k != "mask")
    for group, items in result.items():
        if group == "mask":
            continue
        for it in items:
            assert it["resource_id"], f"{group}/{it['name']} 缺 resource_id"
    print(f"共 {total} 个免费官方资源可用，全部带官方 resource_id，零 VIP")


if __name__ == "__main__":
    main()
