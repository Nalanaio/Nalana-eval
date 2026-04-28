# Nalana Production System Prompt (nalana-prod)

> Nalana 生产环境实际使用的 system prompt（从 `Nalana-datasc/voice_to_blender.py` 同步而来）。
>
> 用于测试"加了 Nalana 业务 prompt 后的不同 LLM 表现"，CLI: `--system-prompt nalana-prod`。
>
> **这个文件应该和生产代码保持同步**——Nalana 改 prompt 时这里也要更新。

---

## Prompt 内容

```
You are a Blender automation agent.
Output ONLY raw JSON (no prose, no code fences).
Each command must be of the form: {"op":"<module.op>","kwargs":{}}.
If multiple steps are implied, output a JSON array of such dicts.
Prefer creative operators (object/mesh/curve/transform/material/node/render).
Never use file/quit/addon/script/image.save operators.
```

---

## 与 eval-default 的差异

| 维度 | eval-default | nalana-prod |
|---|---|---|
| 长度 | ~40 行 | 7 行 |
| 三种 contract 都列 | ✓ | ✗（只用 LEGACY_OPS） |
| 列举 primitives | ✓ | ✗ |
| 列举 step kinds | ✓ | ✗ |
| 给 example | ✓ | ✗ |
| allowlist 详细 | ✓ | 概括："creative operators only" |

**预期效果**：

- nalana-prod 更短 → token 成本低，但模型容易自由发挥（PARSE_ERROR 可能更多）
- eval-default 更详细 → 解析成功率高，但 prompt 成本高

测试这两者下不同模型的对比，能告诉团队**生产 prompt 是否需要变长**或者**当前 prompt 是否足够**。

---

## 同步策略

每次 Nalana 生产代码改 system prompt（在 `voice_to_blender.py` 的 `gpt_to_json` 或类似函数里），**同步更新这个文件**。

如果生产 prompt 经常变（比如每周）：

- 选项 A：把这个文件改成"生产 prompt 镜像"，定期 cron 拉取
- 选项 B：加版本控制（`nalana_prod_v2026_04.md`、`nalana_prod_v2026_05.md`），CLI 加 `--system-prompt-version`
- 选项 C：不再镜像生产，独立维护一个"近似生产风格"的 prompt（最稳，但需要团队约定）

**当前选 A**：本文件镜像生产，每次改动需 commit 同步。

---

## 版本历史

| 版本 | 日期 | 变化 | 来源 |
|---|---|---|---|
| v1 | 2026-04-25 | 初版，从 voice_to_blender.py 同步 | Nalana-datasc commit |

---

## 加载方式

同 `eval_default.md`：`load_prompt_template()` 提取最后一个代码块作为 prompt 内容。
