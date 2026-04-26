# LLM-as-Judge 校准集（Calibration Set）

> 校准集用于检测 LLM 评委的**系统性偏差**。这份文档教你建立、维护、解读校准集结果。

---

## 1. 为什么要有校准集

LLM 评委有训练偏好。比如 GPT-4o 见过的"专业 3D 苹果"大多是写实风格，所以它默认会**用写实标准评卡通**，结果卡通苹果在它眼里永远低分。

仅靠 prompt 工程（"按 detected_style 自身标准评分，不要跨风格"）不能 100% 消除这种偏见。我们需要一个**外部基准**来定期验证判官是否真的做到了"风格中立"。

**核心想法**：

> 给判官 20 张已知好的卡通建模 + 20 张已知好的写实建模 + 20 张 low-poly。
> 如果判官真的"风格中立"，三组在各自标准下的均分应该差不多（误差 ±0.3 以内）。
> 如果某一组系统性低 1 分，说明判官有偏见——要么换 judge model，要么调 prompt。

---

## 2. 校准集长什么样

```
calibration/
├── README.md                       ← 你正在读
├── reference_images/               ← 参考图（gitignored）
│   ├── cartoon/                    ← 已知"好的卡通建模"
│   │   ├── apple_cartoon_01.png
│   │   ├── apple_cartoon_02.png
│   │   ├── chair_cartoon_01.png
│   │   └── ... (20-30 张)
│   ├── realistic/                  ← 已知"好的写实建模"
│   │   ├── apple_real_01.png
│   │   └── ... (20-30 张)
│   ├── low-poly/                   ← 已知"好的 low-poly 建模"
│   │   ├── apple_lp_01.png
│   │   └── ... (20-30 张)
│   ├── stylized/
│   │   └── ...
│   └── geometric/                  ← 已知"好的几何建模"（cube/sphere 等）
│       └── ...
├── reference_metadata.json         ← 每张图的 prompt + concept 标注
├── calibrate.py                    ← 校准命令实现
└── baseline_results/               ← 校准基线（gitignored）
    ├── gpt-4o_2026-04-25.json
    ├── claude-sonnet-4-6_2026-04-25.json
    └── ...
```

---

## 3. 如何建立校准集（一次性工作，约 2-4 小时）

### Step 1：搜集参考图

每个风格 20-30 张高质量参考图。来源：

- **ArtStation** / **Sketchfab** 公开作品（注意版权——只用于内部校准，不分发）
- **Polyhaven** / **CGTrader** 免费资源
- 团队内美术成员制作的"标准答案"

**选图标准**：

- **代表性**：清晰展现该风格的特征（卡通要可爱夸张、写实要细节比例、low-poly 要块面感）
- **对象多样性**：苹果、椅子、桌子、动物、建筑——不要全是一种 concept
- **质量稳定**：所有图都应该是"好"的，不要混入差作（差作要单独建集，见 §6）

### Step 2：命名规范

文件名格式：`<concept>_<style_short>_<seq>.png`

例：
- `apple_cartoon_01.png`
- `apple_cartoon_02.png`
- `chair_realistic_01.png`
- `house_lp_03.png` (low-poly 用 lp)

### Step 3：写 metadata

每张图对应一条 `reference_metadata.json` 记录：

```json
{
  "calibration_set_version": "1.0",
  "created_at": "2026-04-25",
  "items": [
    {
      "image": "cartoon/apple_cartoon_01.png",
      "concept": "apple",
      "concept_aliases": ["fruit"],
      "style": "cartoon",
      "expected_quality": "good",      // good / mediocre / bad（见 §6）
      "source": "artstation.com/...",  // 可选
      "notes": "经典卡通苹果，有柄有叶，清晰边界"
    },
    ...
  ]
}
```

### Step 4：跑首次校准

```bash
python -m nalana_eval.cli calibrate \
    --judge-model gpt-4o \
    --calibration-dir calibration/ \
    --output calibration/baseline_results/gpt-4o_$(date +%Y-%m-%d).json
```

### Step 5：分析基线

输出长这样：

```json
{
  "judge_model": "gpt-4o",
  "calibrated_at": "2026-04-25T15:00:00Z",
  "by_style": {
    "cartoon": {
      "n_samples": 25,
      "scores_under_own_standard": {
        "concept_recognizability": { "mean": 4.1, "stddev": 0.5 },
        "style_execution": { "mean": 3.8, "stddev": 0.6 },
        "geometric_quality": { "mean": 3.5, "stddev": 0.7 }
      },
      "judged_under_standard_breakdown": {
        "cartoon": 23,    // 23/25 张被正确识别为 cartoon
        "stylized": 2     // 2 张被错认为 stylized（轻度误判）
      }
    },
    "realistic": {
      "n_samples": 25,
      "scores_under_own_standard": {
        "concept_recognizability": { "mean": 4.2, "stddev": 0.4 },
        "style_execution": { "mean": 3.9, "stddev": 0.5 },
        "geometric_quality": { "mean": 4.0, "stddev": 0.6 }
      },
      ...
    },
    "low-poly": {
      ...
    }
  },
  "cross_style_drift": {
    "max_pairwise_diff": 0.4,
    "drift_pairs": [
      ["cartoon.style_execution", "realistic.style_execution", 0.4]
    ],
    "warning": null    // 或 "DRIFT_EXCEEDS_THRESHOLD" 当 > 0.5
  },
  "recommendation": "Within acceptable drift (±0.5). No action needed."
}
```

**解读**：

- `cross_style_drift.max_pairwise_diff > 0.5` → **判官有偏见**，要换 model 或调 prompt
- `judged_under_standard_breakdown` 大部分集中在自己风格 → 判官"先识别再评分"机制工作正常
- 如果某个风格 `geometric_quality` 显著低于其他风格 → 该风格的标准定义可能太严，要调 `prompts/judge_prompt.md`

---

## 4. CLI 用法

### 4.1 完整校准

```bash
python -m nalana_eval.cli calibrate --judge-model gpt-4o
```

跑所有风格、所有图片，输出 baseline JSON。耗时约 5-10 分钟（取决于图片数量）。

### 4.2 单风格校准

```bash
python -m nalana_eval.cli calibrate --judge-model gpt-4o --style cartoon
```

只跑 cartoon 文件夹，快速验证某个风格。

### 4.3 对比基线

```bash
python -m nalana_eval.cli calibrate --judge-model gpt-4o --compare-baseline calibration/baseline_results/gpt-4o_2026-03-01.json
```

跑当前判官 + 加载历史基线，输出"漂移多少"对比报告。

### 4.4 双判官对比

```bash
python -m nalana_eval.cli calibrate --judge-model gpt-4o,claude-sonnet-4-6
```

对每张图两个判官都打分，输出**判官间一致性**报告（哪些 case 两个判官分歧大）。

---

## 5. 解读结果：什么时候要采取行动

### 5.1 健康指标

| 指标 | 健康范围 | 说明 |
|---|---|---|
| `cross_style_drift.max_pairwise_diff` | ≤ 0.3 | 跨风格偏差，越小越中立 |
| 任意风格 `style_execution.stddev` | ≤ 0.8 | 单风格内打分一致性 |
| `judged_under_standard_breakdown` 主对角线占比 | ≥ 0.85 | 判官识别风格的准确度 |
| 判官间一致性（双判官时） | Pearson ρ ≥ 0.7 | 两个判官打分相关性 |

### 5.2 危险信号 + 应对

| 信号 | 可能原因 | 行动 |
|---|---|---|
| 某风格均分系统性低 1+ 分 | 判官对该风格有偏见 | 调 `prompts/judge_prompt.md` 加强"按 detected_style 自身标准"指令；考虑换判官 |
| 风格识别错配率 > 20% | 判官无法稳定识别风格 | 调 prompt 加更多风格描述；或换更强的多模态判官 |
| 单风格 stddev > 1.5 | 判官打分极不稳定 | 增加 `--judge-runs` 从 3 到 5；查看判官 raw response 找原因 |
| 跨判官一致性低 | 不同判官对该任务标准不同 | 在文档里说明用"哪个判官"做主基线；不能跨判官比较 |

### 5.3 不应反应过度

下列情况**不需要**调整：

- 单条图分数明显偏离均值（个例，正常）
- 偏差从 0.2 涨到 0.25（仍在健康区间）
- 不同风格之间均分有 0.1-0.2 微小差异（统计噪声）

---

## 6. 进阶：负样本校准集

除了"已知好的"图，也可以建"已知差的"图（手工劣化、bug 输出、明显错误）。

```
calibration/reference_images/
├── _negative/                      ← 已知差的样本
│   ├── empty_scene_01.png          ← 空场景
│   ├── unrelated_blob_01.png       ← 跟 prompt 无关
│   └── distorted_apple_01.png      ← 扭曲变形的苹果
```

`reference_metadata.json` 标 `expected_quality: "bad"`。

跑校准时加 `--include-negative`，检查判官能不能识别出差作（应该普遍打 ≤ 2 分）。

**这其实就是 honeypot 的离线版**——主 benchmark 里 honeypot 是运行时插入，校准集里 negative samples 是离线建立基线。

---

## 7. 维护节奏

### 7.1 何时重跑校准

| 触发 | 频率 | 备注 |
|---|---|---|
| 换判官模型 | 立即 | 必须重新建立 baseline |
| 改判官 prompt | 立即 | 必须验证改动效果 |
| 主流判官 model 升级（如 gpt-4o-2024-12 → gpt-4o-2025-04） | 立即 | provider 可能改了内在偏好 |
| 没有任何变化 | 每月 1 次 | 防止"判官能力悄悄变化"（OpenAI/Anthropic 偶尔会无声更新） |

### 7.2 baseline 归档

每次校准结果写到 `calibration/baseline_results/<judge_model>_<date>.json`。**不要覆盖旧文件**——保留所有历史 baseline 用于趋势分析。

### 7.3 命中率监控

如果某次主 benchmark 出 `judge_calibration_drift > 0.3`（单 run 与最近基线偏差），系统会在 report 里 flag。这种情况下应该：

1. 重跑校准集
2. 看是判官还是数据问题（如最近 case 多了某个新风格，判官不熟）
3. 必要时回滚到上一个稳定 judge prompt

---

## 8. 法律 & 数据合规

参考图大多来自互联网。**不要在外部分享 `reference_images/` 文件夹**——可能涉及版权。校准集是**内部基线工具**，属于团队私有数据。

如果要分享 baseline 给外部（比如发布博客对比 GPT-4o vs Claude），只分享 JSON 数值结果，不分享原图。

---

## 9. 起步检查清单

第一次建校准集前自查：

- [ ] 准备好 5 个风格 × 20-30 张参考图（共 100-150 张）
- [ ] 每张图有清晰的 metadata（concept, style, source）
- [ ] 图都已下载到本地，不依赖外部 URL（避免 link rot）
- [ ] 已经读完 `prompts/judge_prompt.md` 了解判官的 prompt 结构
- [ ] 已经准备好 judge model 的 API key
- [ ] 跑通一次 `--style cartoon` 单风格校准（约 2 分钟）作为冒烟测试
- [ ] 跑完整校准并 commit baseline JSON 到 `baseline_results/`

---

## 10. FAQ

**Q：要不要把 `reference_images/` 进 git？**
A：不建议。版权不明 + 体积大（100 MB+）。用 LFS 或单独的 cloud bucket 备份。

**Q：参考图要多大尺寸？**
A：和主 benchmark 渲染输出一致即可（800×600）。判官按"看到的图"评分，所以要保持视觉一致。

**Q：要不要训练自己的判官？**
A：远期目标，需要数千条人工标注数据。当前阶段用 GPT-4o + 校准集已经够用。

**Q：判官分数和 calibration baseline 偏差多少算"必须修"？**
A：单次 run 偏差 0.3 是黄灯（值得调查），0.5 是红灯（必须修复）。

**Q：能不能让校准集本身参与 LLM 训练（DPO）？**
A：不能。校准集是**外部基准**，参与训练会污染基准。它是判官的"考试题"，不是"训练题"。

---

**校准集文档结束。下次跑 `nalana-eval calibrate` 看健康指标即可。**
