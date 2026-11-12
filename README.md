# jianying-auto-mix

把几段演唱会现场素材，自动剪成一条 60 秒卡点成片——同时产出**可编辑的剪映草稿**和**渲染好的 MP4**，两个交付物切点完全一致。

不是「随机切片 + 套模板」。分镜由音频频谱和画面质量共同决定：BPM 从音轨实测、切点吸附到节拍网格、源区间按逐秒画面评分挑选以避开死黑，三幕节奏按秒数手工编排。

---

## 它解决什么

手工剪一条 60 秒混剪，通常要来回听几十遍音轨找拍点、在时间轴上反复试切点、再把成片拖进剪映调细节。这套脚本把可量化的部分自动化：

| 环节 | 自动化方式 |
|---|---|
| 找 BPM 和拍点 | 频谱通量做 onset 检测，自相关算周期 |
| 选 BGM 段落 | 多窗口扫描，按节拍显著度 + 能量递增打分 |
| 挑可用画面 | 逐秒打分亮度/非黑占比/色彩能量/细节度 |
| 排分镜 | 三幕式结构，每幕指定切镜间隔与色彩基调 |
| 出草稿 | 直接写剪映工程文件，打开即可继续改 |
| 出成片 | ffmpeg 用同一批预裁剪片段渲染，保证与草稿一致 |

**核心约束：草稿和 MP4 必须长得一样。** 两者共用同一批物理预裁剪片段（切点、调色、运镜、灯闪脉冲都烘焙进片段本身），而不是各算一遍。所以你在剪映里微调草稿，参照的基准就是那条 MP4。

---

## 流水线

```
        sources.json（你的素材清单）
                 │
     ┌───────────┴───────────┐
     ▼                       ▼
01_analyze_audio        02_scan_frames
  音轨 → BPM / 相位        画面 → 逐秒可用性评分
  能量曲线 / 窗口打分        亮度·非黑占比·色彩·细节
     │                       │
     └───────────┬───────────┘
                 ▼
          03_build_plan.py
      三幕式分镜 + 卡点网格吸附
                 │
              edit_plan.json  ← 唯一事实来源
                 │
        ┌────────┴────────┐
        ▼                 ▼
  04_prepare          05_build_draft
  预裁剪 36 段片段      写剪映草稿工程
        │                 │
        ├─────────────────┤
        ▼                 ▼
  06_render_mp4      草稿 zip（自包含）
  渲染 1080p MP4
        │                 │
        └────────┬────────┘
                 ▼
          07_verify.py
     ffprobe 查规格 + 抽帧目视 + 直读 zip 原始 JSON 交叉复核
```

`edit_plan.json` 是枢纽：分镜、切点、调色、转场全在里面，改它就能改片子。`samples/` 下有一份真实产出可以对着看。

`v2_*.py` 是在 v1 基础上加官方免费资源（转场/特效/滤镜/贴纸/音效）的增强版，分镜骨架沿用 v1。

---

## 依赖

| 依赖 | 用途 | 必需性 |
|---|---|---|
| **Python ≥ 3.9** | 运行 | 必需 |
| **FFmpeg / ffprobe** | 解码、裁切、渲染 | 必需，需在 PATH 或显式指定 |
| **numpy, pillow** | 音频分析、画面打分、监看图 | 必需 |
| [**jianying-editor**](https://github.com/luoluoluo22/jianying-editor) | 写剪映工程文件（步骤 05 / v2_draft） | 仅草稿生成需要 |
| **剪映专业版** | 打开并继续编辑草稿 | 仅草稿生成需要 |

`jianying-editor` 是 MIT 许可的独立项目（作者 luoluoluo22），本仓库不复制它的代码，只依赖它写草稿。**不装它也能跑 01→04、06 拿 MP4**，只是出不了剪映草稿。

---

## 快速开始

```bash
git clone https://github.com/LIU-yan2007/jianying-auto-mix.git
cd jianying-auto-mix
pip install -r requirements.txt
```

**1. 先自检环境**，确认 ffmpeg 和剪映目录都找得到：

```bash
python config.py
```

输出应类似：

```
ffmpeg       : C:\...\ffmpeg.exe
ffprobe      : C:\...\ffprobe.exe
剪映草稿目录 : C:\Users\...\com.lveditor.draft
素材清单     : .../sources.json
  [A] 全景 · 观众席与大屏  37.04s  ...
```

**2. 填素材清单**——复制模板，改成本地路径：

```bash
cp sources.example.json sources.json
```

```json
{
  "bgm_source": "B",
  "videos": [
    { "key": "A", "path": "D:/footage/wide.mp4", "name": "全景 · 观众席" },
    { "key": "B", "path": "D:/footage/stage.mp4", "name": "特写 · 舞台" }
  ]
}
```

`key` 任意命名，脚本不假设一定叫 A/B。`bgm_source` 指定取哪条素材的音轨当 BGM，省略则取第一条。`duration` 可省，省了由 ffprobe 实测。

**3. 跑流水线：**

```bash
python 01_analyze_audio.py    # 音轨打点 → audio_scores.json
python 02_scan_frames.py      # 画面评分 → frame_scores.json
python 03_build_plan.py       # 出分镜 → edit_plan.json
python 04_prepare.py          # 预裁剪片段 → 临时目录
python 06_render_mp4.py       # 渲染 → exports/xxx.mp4
python 07_verify.py           # 验收
```

**4. 要剪映草稿的话**，跑 05（需先装 jianying-editor）：

```bash
python 05_build_draft.py      # → exports/xxx_剪映草稿.zip
```

---

## 配置

路径不写死在代码里，三处覆盖：

| 环境变量 | 作用 | 默认 |
|---|---|---|
| `JYAM_WORK` | 中间产物目录 | 系统临时目录下 `jyam/` |
| `JYAM_FFMPEG` | ffmpeg 路径 | PATH → SnapAny 随附 |
| `JYAM_FFPROBE` | ffprobe 路径 | 同上 |
| `JYAM_DRAFTS` | 剪映草稿目录 | `%LOCALAPPDATA%\JianyingPro\...\com.lveditor.draft` |
| `JYAM_JY_SKILL` | jianying-editor 技能目录 | `~/.workbuddy/skills/jianying-editor` |
| `JYAM_LIB` | 剪映素材库草稿目录（可选） | 空＝跳过库部署 |
| `JYAM_NAME` | 07 验收时的成片名 | `同一束光_演唱会60秒` |

---

## 产物

```
exports/
├── <片名>.mp4                  # 1920x1080 / 30fps / 严格 60.00s
├── <片名>_剪映草稿.zip          # 自包含：工程 JSON + 全部素材，换机可打开
└── <片名>/                     # 解包后的明文工程

<临时目录>/
├── audio_scores.json          # BPM、相位、能量曲线、窗口候选
├── frame_scores.json          # 逐秒画面评分
├── manifest.json              # 预裁剪片段清单
├── clips/                     # 36 段预裁剪片段
├── audio_compare.jpg          # 音轨波形 + onset 对比图
└── frame_scores.jpg           # 画面可用性时间轴
```

---

## 实现要点

**BPM 用自相关，不靠第三方库。** 22050Hz 单声道解码成 f32，短时傅里叶算频谱通量作为 onset 强度，再做自相关。只在 60–180 BPM 对应的延迟区间里找峰，避免倍频/半频误判。找到周期后还要枚举相位偏移，选使拍点处 onset 均值最高的那个——比单纯取周期首位准得多。

**选 BGM 段落靠打分，不靠听。** 对每个 5 秒步进的 60 秒窗口，同时算节拍显著度和首尾能量比，加权排序。能量递增的段落更适合做「越来越炸」的收尾。

**画面评分是四维加权。** ffmpeg 把每秒一帧缩到 96×54 的 rgb24 喂给 numpy，算亮度均值、非黑像素占比、色彩饱和度、梯度细节度。死黑、过曝、纯色模糊的片段会被排到后面，源区间选择时优先避开。

**三幕节奏是手排的，不是算的。** 幕 I（0–16s）冷紫、4 秒慢切、全景与空座；幕 II（16–38s）冷暖交替、2 秒中速；幕 III（38–60s）炽红、1 秒快切、灯闪脉冲。这一段是创作意图，脚本只负责把切点吸附到 BPM 网格上。想换成别的结构，改 `03_build_plan.py` 里的幕参数即可。

**草稿时长要在四层对齐。** `draft_info.json` 顶层 duration/fps、`draft_content.json` 字节一致、主视频轨片段首尾相接铺满、音频轨满轨、`draft_meta_info.json` 的 `tm_duration`——少一层剪映就会在导入时截断或补黑。

**验收故意不信任生成器。** `07_verify.py` 用 ffprobe 独立查成片规格、抽帧做目视拼图，并且**直接读 zip 里的原始 JSON 字节**复核草稿，而不是调用生成脚本自己的检查函数——避免「自己断言自己」。

---

## 已知限制

- **主力环境是 Windows。** 剪映草稿目录、字体（微软雅黑）、路径风格都按 Windows 写的。macOS 和 Linux 能跑 01→04 与 06，草稿那两步需要自己改草稿根目录和字体路径。
- **`03`/`v2_plan` 里的文案和片名是这部片子的。** 字幕、片名、色彩基调都是针对「演唱会」这个题材写死的，换题材要改 `texts` 和幕参数，不是通用模板。
- **剪映版本敏感。** 草稿 JSON 结构随剪映版本变化，较新版本可能把 `draft_content.json` 加密成二进制。仓库里的逻辑针对明文工程验证过。
- **素材版权自负。** `.gitignore` 排除了所有媒体文件，仓库里不含任何素材。换上你自己的素材再跑。

---

## 许可与致谢

本仓库代码 MIT 许可，见 [LICENSE](LICENSE)。

草稿生成依赖 [jianying-editor](https://github.com/luoluoluo22/jianying-editor)（MIT，作者 luoluoluo22），其内置的 `pyJianYingDraft` 提供了剪映工程的数据结构定义。本仓库不包含其代码。

音视频处理基于 [FFmpeg](https://ffmpeg.org/)（LGPL/GPL）。
