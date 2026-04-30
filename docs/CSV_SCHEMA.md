# CSV 数据库 Schema

> 评测系统的跨 run 持久化数据库。两个 CSV 文件，一个辅助文件。

---

## 1. 文件位置

```
/Users/ianian/Nalana-eval/db/
├── runs.csv                  ← 每次 run 的汇总（每模型一行）
├── attempts.csv              ← 每个 attempt 的细粒度数据
├── judge_vs_human.csv        ← 判官 vs 人审差异长期积累
└── judge_cache.sqlite        ← 判官调用缓存（不是 CSV，但同一目录）
```

`db/` 目录在 `.gitignore` 中——文件存在本地，不进 git 历史。

---

## 2. `runs.csv`

每次 `nalana-eval` 运行产生**每模型一行**（`--models gpt-5,claude-sonnet-4-6` 跑一次产生 2 行）。

### 完整字段表

| 列名 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `run_id` | string | `7a3f9b2c` | 8 位 hex，与 run folder 同名 |
| `run_group_id` | string | `b2e4f1a8` | 同一次 CLI 调用的所有模型共享，便于分组 |
| `timestamp_utc` | ISO8601 | `2026-04-25T14:30:22Z` | run 完成时间 |
| `model_id` | string | `gpt-5` | LLM 模型名 |
| `judge_model` | string | `gpt-4o` | LLM-as-Judge 用的模型；`""` 表示 `--no-judge` |
| `system_prompt_version` | string | `eval-default` | `eval-default` 或 `nalana-prod` |
| `prompt_template_version` | string | `benchmark-constraint-eval-v1` | schema.py 里的常量 |
| `temperature` | float | `0.7` | LLM 采样温度 |
| `seed` | int | `42` | 随机种子 |
| `pass_at_k` | int | `3` | 每个 case 跑几次 |
| `total_cases` | int | `200` | 这次实际跑的 case 数 |
| `total_attempts` | int | `600` | = total_cases × pass_at_k |
| `difficulty_dist` | json string | `{"Short":80,"Medium":80,"Long":40}` | 实际跑的 difficulty 分布 |
| `category_dist` | json string | `{"Object Creation":60,"Transformations":50,...}` | category 分布 |
| `execution_success_rate` | float | `0.95` | parse + safety + execute 全过的 case 比例 |
| `hard_pass_rate` | float | `0.78` | 硬约束全部通过的 case 比例 |
| `topology_pass_rate` | float | `0.85` | 拓扑约束通过的 case 比例 |
| `avg_soft_score` | float | `0.72` | 软约束加权分均值 |
| `pass_at_1` | float | `0.65` | 第 0 次 attempt 通过的 case 比例 |
| `pass_at_3` | float | `0.91` | k=3 中至少 1 次通过的 case 比例 |
| `avg_judge_semantic` | float (nullable) | `3.8` | 判官语义匹配分均值（5 分制）；NaN if no-judge |
| `avg_judge_aesthetic` | float (nullable) | `3.5` | |
| `avg_judge_professional` | float (nullable) | `3.2` | |
| `judge_reliable` | bool | `true` | 诱饵全部 ≤ 2 分时为 true |
| `judge_honeypot_catch_rate` | float (nullable) | `0.95` | 诱饵被正确低分识别的比例 |
| `judge_calibration_drift` | float (nullable) | `0.1` | 与最近一次校准的偏差 |
| `avg_model_latency_ms` | float | `1450.0` | LLM 调用平均耗时 |
| `avg_execution_latency_ms` | float | `120.0` | Blender 执行平均耗时 |
| `total_cost_usd` | float | `4.21` | 这次 run 的总 API 成本（model + judge） |
| `total_duration_s` | float | `387.5` | 整次 run 总耗时 |
| `report_md_path` | string | `artifacts/run_<id>/report.md` | 相对路径 |
| `report_json_path` | string | `artifacts/run_<id>/report.json` | |
| `git_commit` | string | `a3f9b2c` | 跑这次 run 时 repo 的 commit hash（前 7 位） |
| `cli_args` | json string | `{"cases":200,"models":["gpt-5"],...}` | 完整 CLI 参数快照 |
| `notes` | string | `""` | 可选人工备注 |

### 字段总数：35

### 写入规则

- `runs.csv` 是 append-only。每次 run 完成时追加一行，**永不修改历史行**。
- 表头由 `csv_db.py` 在文件不存在时写入。
- 如果某个字段对该 run 不适用（如 `--no-judge` 时的所有 `*_judge_*` 字段），写空字符串 `""`，CSV 读取时识别为 NaN。

---

## 3. `attempts.csv`

每个 case 的每次 attempt 一行。一次 200 用例 × pass@3 的 run 产生 600 行。

### 完整字段表

| 列名 | 类型 | 说明 |
|---|---|---|
| `run_id` | string | foreign key → runs.csv |
| `case_id` | string | 测试用例 ID（如 `CV-OBJ-042`） |
| `attempt_index` | int | 0-based |
| `model_id` | string | 冗余存储（方便单表查询） |
| `category` | enum | `Object Creation` / `Transformations` / ... |
| `difficulty` | enum | `Short` / `Medium` / `Long` |
| `task_family` | enum | `primitive_creation` / ... |
| `prompt_used` | string | 这次 attempt 实际用的 prompt 变体 |
| `parse_success` | bool | LLM 输出是否能解析为合法 JSON ops |
| `safety_success` | bool | 是否通过 allowlist 检查 |
| `execution_success` | bool | Blender 是否无报错执行完所有 ops |
| `passed_hard_constraints` | bool | 所有硬约束通过 |
| `passed_topology` | bool | 拓扑约束通过 |
| `pass_overall` | bool | = passed_hard_constraints AND passed_topology |
| `soft_score` | float | 0-1 加权 |
| `failure_class` | enum | `NONE` / `PARSE_ERROR` / `EXECUTION_ERROR` / `CONSTRAINT_FAILED` / `TOPOLOGY_FAILED` / `SAFETY_BLOCKED` / `WORKER_TIMEOUT` |
| `failure_reason` | string | 简短人类可读描述 |
| `total_objects` | int | 场景对象总数 |
| `total_mesh_objects` | int | mesh 类型对象数 |
| `total_vertices` | int | 所有 mesh 总顶点数 |
| `total_faces` | int | 所有 mesh 总面数 |
| `quad_ratio` | float | 四边面占比 [0, 1] |
| `manifold` | bool | 全场景所有 mesh 都流形 |
| `bbox_min_x/y/z` | float | 场景合并 bbox 最小角 |
| `bbox_max_x/y/z` | float | 场景合并 bbox 最大角 |
| `judge_semantic` | float (nullable) | 判官语义分（中位数）；NaN if skip |
| `judge_aesthetic` | float (nullable) | |
| `judge_professional` | float (nullable) | |
| `judge_stddev` | float (nullable) | 3 次评分的标准差 |
| `judge_judged_under_standard` | string (nullable) | 判官实际用的尺子（如 `"cartoon"`） |
| `judge_detected_style` | string (nullable) | |
| `judge_detected_concept` | string (nullable) | |
| `judge_style_alignment_pass` | bool (nullable) | |
| `judge_concept_alignment_pass` | bool (nullable) | |
| `judge_confidence` | float (nullable) | 判官自评置信度 |
| `judge_human_override` | enum (nullable) | `pending` / `agree` / `disagree` / `partial` / `""`（未 review） |
| `judge_human_corrected_semantic` | float (nullable) | 人审改后的分 |
| `judge_human_corrected_aesthetic` | float (nullable) | |
| `judge_human_corrected_professional` | float (nullable) | |
| `judge_human_reviewer` | string (nullable) | 人审者名字 |
| `judge_human_review_timestamp` | ISO8601 (nullable) | |
| `judge_human_note` | string (nullable) | 人审备注 |
| `model_latency_ms` | float | 单次 LLM 调用耗时 |
| `execution_latency_ms` | float | 单次 Blender 执行耗时 |
| `model_cost_usd` | float | LLM 调用成本 |
| `judge_cost_usd` | float | 判官调用成本 |
| `screenshot_path` | string | 相对路径 `artifacts/run_<id>/screenshots/...` |
| `scene_stats_path` | string | 相对路径 `artifacts/run_<id>/scene_stats/...` |
| `is_honeypot` | bool | 是否为诱饵用例 |
| `had_retry_context` | bool | 这条 attempt 的 prompt 是否被加过"上次失败摘要"。仅当 `--retry-with-feedback` 启用、attempt_index ≥ 1、且上次失败不是 API 配置错时为 true。详见 ADR-004。 |
| `iterations_taken` | int | 这条 attempt 在所属 case 内的 1-indexed 迭代号（= attempt_index + 1）。冗余但便于 SQL 聚合。 |

### 字段总数：~52

### 写入规则

- Append-only。Attempt 创建时追加，**永不删除**。
- **唯一例外**：`judge_human_*` 字段族在人审 `nalana-eval review --collect` 时被更新（用 in-place 改写实现，需要先读全表 → 修改对应行 → 全表覆盖写）。
- 因为只在 review 时修改，不影响 benchmark 期间的写入性能。

---

## 4. `judge_vs_human.csv`

每条记录对应一次"人审觉得判官打错了"的事件。长期积累，未来用于微调判官 prompt。

### 字段表

| 列名 | 说明 |
|---|---|
| `event_timestamp_utc` | ISO8601 |
| `run_id` | |
| `case_id` | |
| `attempt_index` | |
| `judge_model` | |
| `judge_judged_under_standard` | 判官当时用的尺子 |
| `judge_semantic` / `judge_aesthetic` / `judge_professional` | 判官原始分 |
| `human_corrected_semantic` / `human_corrected_aesthetic` / `human_corrected_professional` | 人审改后分 |
| `delta_semantic` / `delta_aesthetic` / `delta_professional` | human - judge |
| `human_reviewer` | |
| `human_note` | |
| `screenshot_path` | 用于回溯 |
| `prompt_used` | 用于回溯 |
| `case_style_intent_explicit` | 该 case 是否明确指定风格 |

### 写入规则

- Append-only。每次 `review --collect` 触发新事件时追加。
- 同一 attempt 多次 review 产生多条记录（不合并）——保留所有 reviewer 的反馈。

---

## 5. 使用示例

### 5.1 用 Excel / Numbers 看

```bash
open /Users/ianian/Nalana-eval/db/runs.csv      # macOS
xdg-open /Users/ianian/Nalana-eval/db/runs.csv  # Linux
```

### 5.2 用 DuckDB 跑 SQL

```bash
brew install duckdb

duckdb -c "SELECT model_id, AVG(hard_pass_rate) AS avg_pass FROM 'db/runs.csv' GROUP BY model_id"

# 找最近 10 次 gpt-5 的 hard pass 趋势
duckdb -c "
  SELECT timestamp_utc, hard_pass_rate
  FROM 'db/runs.csv'
  WHERE model_id = 'gpt-5'
  ORDER BY timestamp_utc DESC
  LIMIT 10
"

# 跨表 join：找某个 case 的所有失败原因
duckdb -c "
  SELECT a.run_id, a.attempt_index, a.failure_class, a.failure_reason
  FROM 'db/attempts.csv' a
  WHERE a.case_id = 'CV-OBJ-042' AND NOT a.pass_overall
  ORDER BY a.run_id DESC
"
```

### 5.3 用 nalana-eval-history

```bash
python -m nalana_eval.cli history --model gpt-5 --last 10
python -m nalana_eval.cli history --compare gpt-5,claude-sonnet-4-6
python -m nalana_eval.cli history --case CV-OBJ-042
```

### 5.4 用 pandas

```python
import pandas as pd

runs = pd.read_csv("db/runs.csv")
attempts = pd.read_csv("db/attempts.csv")

# 计算每个 model 的平均 hard pass rate
runs.groupby("model_id")["hard_pass_rate"].mean()

# 找出判官和人审分歧最大的用例
delta = attempts[attempts["judge_human_override"] == "disagree"]
delta["semantic_delta"] = delta["judge_human_corrected_semantic"] - delta["judge_semantic"]
delta.sort_values("semantic_delta", ascending=False).head(10)
```

---

## 6. CSV 文件大小估算

| 量级 | 单文件大小 |
|---|---|
| 1 次 run（200 案 × 3 attempt） | runs.csv +1 行 (~2 KB) / attempts.csv +600 行 (~150 KB) |
| 100 次 run（半年使用） | runs.csv ~200 KB / attempts.csv ~15 MB |
| 1000 次 run | runs.csv ~2 MB / attempts.csv ~150 MB |

**100 次 run 以内**：CSV 完全够用（在 Excel 里都能开）。

**>500 次 run**：考虑切到 SQLite（见下）。

---

## 7. 升级到 SQLite 的迁移路径

如果未来发现 CSV 太大、查询太慢，可以无痛迁到 SQLite：

```python
# 一次性迁移脚本
import pandas as pd
import sqlite3

conn = sqlite3.connect("db/nalana_eval.sqlite")
pd.read_csv("db/runs.csv").to_sql("runs", conn, index=False)
pd.read_csv("db/attempts.csv").to_sql("attempts", conn, index=False)
pd.read_csv("db/judge_vs_human.csv").to_sql("judge_vs_human", conn, index=False)
conn.commit()
```

`csv_db.py` 提供一个 SQLite 后端的等价实现，CLI 通过 `--db-backend sqlite` 切换。**Phase F 之后的演进任务**，不必现在做。

---

## 8. 备份建议

`db/` 在 `.gitignore` 中，不会自动备份。建议：

- **定期手动归档**：每月 cp `db/` 到 `db_archive_<yyyy-mm>/`
- **云同步**：把 `db/` 软链接到 Dropbox/iCloud 文件夹（注意：判官缓存 SQLite 同步可能有锁问题，最好排除）
- **跨人共享 baseline run**：把那次的 `db/runs.csv` 单行 + 对应 `attempts.csv` 行 commit 到一个 `baselines/` 文件夹（破例进 git）

---

**Schema 文档结束。`csv_db.py` 实现时 import 本文档列出的字段名作为常量，避免硬编码字符串。**
