# 进度记录

## 2026-10-10 S1 读取与验证

### 已完成

- 阅读 `dialogue-data-pipeline-spec.md`，确认首次只实现 S1，不提前实现全部阶段。
- 检查本地环境：Python 3.12.11；当前目录不是 Git 仓库；初始目录只有规格文档和 `.codex`。
- 创建最小项目骨架：`pyproject.toml`、`configs/default.json`、`src/dialogue_pipeline/`、`tests/`、`docs/`。
- 创建模拟中文 JSONL 样例：22 条非空候选行、1 条空白行；覆盖正常单轮、多轮、可选 system、坏 JSON、类型错误、空内容、非法角色顺序、不支持语言和未知主题。
- 实现 `python -m dialogue_pipeline check`，输出通过记录、拒绝记录和摘要。

### 实际运行命令

```bash
PYTHONPATH=src python -m dialogue_pipeline check --input data/samples/raw_dialogues.jsonl --output artifacts/check
python -m pip install -e .[dev]
python -m pytest
python -m dialogue_pipeline check --input data/samples/raw_dialogues.jsonl --output artifacts/check-installed
```

### 当前结果

- CLI 检查输出：`accepted=14 rejected=8 blank_lines=1`。
- `artifacts/check/summary.json`：`candidate_lines=22`、`blank_lines=1`、`accepted_count=14`、`rejected_count=8`。
- 规则计数：`JSON_PARSE_ERROR=1`、`INVALID_TYPE=2`、`EMPTY_CONTENT=1`、`INVALID_ROLE_SEQUENCE=3`、`UNKNOWN_TOPIC=1`、`UNSUPPORTED_LANGUAGE=1`。
- 测试：`4 passed in 0.20s`。

### 待完成

- S2 清洗与去重已在后续记录完成。
- 初始化 Git 仓库并提交前检查公开内容。

## 2026-10-10 S2 清洗与去重

### 已完成

- 新增 `clean.py`：NFC 规范化、换行统一、消息首尾空白清理、模拟邮箱/手机号脱敏、内容哈希。
- 新增 `deduplicate.py`：按内容哈希精确去重；同 `sample_id` 不同内容全部隔离。
- `check` 命令现在输出 `cleaned.jsonl`、兼容用 `accepted.jsonl`、`rejected.jsonl` 和 `summary.json`。
- 样例数据扩展到 24 条非空候选行，新增首尾空白重复样例和模拟联系方式脱敏样例。
- 测试扩展到 7 条，覆盖清洗、哈希和去重冲突。

### 实际运行命令

```bash
python -m pytest
python -m dialogue_pipeline check --input data/samples/raw_dialogues.jsonl --output artifacts/check-s2
```

### 当前结果

- CLI 检查输出：`kept=13 duplicate=1 quarantined=10 blank_lines=1`。
- `artifacts/check-s2/summary.json`：`candidate_lines=24`、`blank_lines=1`、`kept_count=13`、`duplicate_count=1`、`quarantined_count=10`、`rejected_count=11`。
- 清洗事件计数：`NORMALIZED_TEXT=2`、`REDACTED_EMAIL=2`、`REDACTED_PHONE=2`。
- 规则计数新增：`DUPLICATE_CONTENT=1`、`SAMPLE_ID_CONFLICT=2`。
- 测试：`7 passed in 0.25s`。

### 待完成

- S3 SQLite 与 SQL：版本表、记录表、处置表、重复运行不翻倍、基础 SQL 分析。
- 对 README 做一次全新 clone 后复现检查。
