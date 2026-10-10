# dialogue-data-pipeline

本项目是一个本地运行的中文对话数据处理流水线，用于把原始 JSONL 对话数据转换为可追溯、可检查、可继续入库或分析的结构化结果。

## 技术背景

对话数据在进入训练、评测、人工审核或分析系统前，通常需要先完成基础的数据治理：

- 逐行读取 JSONL，避免单条坏数据阻塞整个文件处理。
- 校验字段结构、消息角色顺序和文本类型。
- 对可解释的文本问题做规范化和模拟脱敏。
- 识别重复内容和冲突 ID。
- 保留异常数据及原因，方便后续修复或追溯。

项目使用 Python 标准库实现核心流程，CLI 使用 `argparse`，测试使用 `pytest`。当前数据样例均为模拟中文对话，`source=synthetic`。

## 目标需求

流水线期望满足以下需求：

- 输入为 UTF-8 JSONL，每个非空物理行是一条对话记录。
- 坏 JSON、结构错误、重复内容和 ID 冲突都不会被静默丢弃。
- 每条异常记录保留原始文本、行号、规则 ID、字段路径和中文原因。
- 合格记录经过文本规范化、模拟邮箱/手机号脱敏和内容哈希计算。
- 精确重复内容只保留第一条，其余记录为 `duplicate`。
- 同一个 `sample_id` 对应不同内容时，相关记录全部隔离为 `SAMPLE_ID_CONFLICT`。
- 输出结果写入 JSONL 文件，也可以持久化到 SQLite 供 SQL 分析使用。

## 数据格式

输入文件示例：

```json
{"sample_id":"schedule_001","group_id":"schedule_family_01","source":"synthetic","topic":"schedule","language":"zh","messages":[{"role":"user","content":"我今晚有两小时，想安排学习和休息。"},{"role":"assistant","content":"可以先学习45分钟，休息15分钟，再学习45分钟，最后用15分钟整理笔记。"}]}
```

必需字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `sample_id` | string | 样本 ID |
| `group_id` | string | 对话家族或模板组 ID |
| `source` | string | 数据来源，样例中为 `synthetic` |
| `topic` | string | 主题，需在配置词表中 |
| `language` | string | 当前接受 `zh` |
| `messages` | array | 有序消息列表 |

消息字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `role` | string | `system`、`user` 或 `assistant` |
| `content` | string | 消息文本，清理首尾空白后不能为空 |

角色规则：

- 可选第一条 `system`。
- 第一条非 `system` 消息必须是 `user`。
- 之后严格 `user` / `assistant` 交替。
- 最后一条必须是 `assistant`。

## 处理流程

```text
raw_dialogues.jsonl
        |
        v
逐行读取 JSONL
        |
        |-- JSON 解析失败 -> rejected.jsonl
        |
        v
结构验证
        |
        |-- 字段、类型、角色顺序错误 -> rejected.jsonl
        |
        v
文本规范化与模拟脱敏
        |
        |-- Unicode NFC
        |-- 换行统一为 \n
        |-- 清理消息首尾空白
        |-- 邮箱 -> [EMAIL]
        |-- 手机号 -> [PHONE]
        |
        v
内容哈希与去重
        |
        |-- 重复内容 -> rejected.jsonl, status=duplicate
        |-- 同 ID 不同内容 -> rejected.jsonl, status=quarantined
        |
        v
cleaned.jsonl + summary.json
        |
        v
SQLite datasets / runs / records / dispositions
```

## 项目结构

```text
dialogue-data-pipeline/
  configs/default.json
  data/samples/raw_dialogues.jsonl
  data/samples/expected_cases.json
  src/dialogue_pipeline/
    __main__.py
    pipeline.py
    ingest.py
    validate.py
    clean.py
    deduplicate.py
    storage.py
  sql/analysis.sql
  tests/
  docs/
  pyproject.toml
```

## 安装

建议使用 Python 3.11 或更高版本。

```bash
python -m pip install -e ".[dev]"
```

如果只运行 CLI，也可以不安装包，直接使用：

```bash
PYTHONPATH=src python -m dialogue_pipeline --help
```

## 运行文件检查

使用样例数据运行检查：

```bash
python -m dialogue_pipeline check \
  --input data/samples/raw_dialogues.jsonl \
  --output artifacts/check
```

未安装包时：

```bash
PYTHONPATH=src python -m dialogue_pipeline check \
  --input data/samples/raw_dialogues.jsonl \
  --output artifacts/check
```

样例输出：

```text
check completed: kept=13 duplicate=1 quarantined=10 blank_lines=1 output=artifacts/check
```

## 运行并写入 SQLite

`run` 命令会执行同样的数据处理流程，并把结果写入本地 SQLite 数据库：

```bash
python -m dialogue_pipeline run \
  --input data/samples/raw_dialogues.jsonl \
  --config configs/default.json \
  --output artifacts/run \
  --db artifacts/pipeline.sqlite
```

样例输出：

```text
run completed: dataset_version=... kept=13 duplicate=1 quarantined=10 blank_lines=1 output=artifacts/run db=artifacts/pipeline.sqlite run_id=...
```

同一份输入、同一份配置和同一份源码重复运行时，`records` 和 `dispositions` 会按同一个 `dataset_version` 替换写入，不会重复膨胀；`runs` 会保留每次运行记录。

严格模式会在存在数据规则问题时返回退出码 `2`：

```bash
python -m dialogue_pipeline check \
  --input data/samples/raw_dialogues.jsonl \
  --output artifacts/check-strict \
  --strict
```

## 输出文件

运行后生成：

```text
artifacts/check/
  cleaned.jsonl
  accepted.jsonl
  rejected.jsonl
  summary.json
```

| 文件 | 说明 |
| --- | --- |
| `cleaned.jsonl` | 最终保留的清洗后记录 |
| `accepted.jsonl` | 与 `cleaned.jsonl` 相同，保留兼容命名 |
| `rejected.jsonl` | JSON 错误、结构错误、重复内容和冲突记录 |
| `summary.json` | 输入行数、保留数、隔离数、重复数、规则计数和清洗事件计数 |

`cleaned.jsonl` 中每条记录包含：

- 原始文件路径
- 原始文件 SHA-256
- 输入行号
- `sample_id`
- `group_id`
- `topic`
- `content_hash`
- `char_count`
- `cleaning_events`
- 清洗后的 `record`

`rejected.jsonl` 中每条记录包含：

- 原始文件路径
- 输入行号
- 原始文本
- `status`
- `reasons`
- 可选的 `canonical_sample_id`
- 可选的 `content_hash`

## SQLite 表

默认数据库路径由 `--db` 指定，例如：

```text
artifacts/pipeline.sqlite
```

核心表：

| 表 | 说明 |
| --- | --- |
| `datasets` | 数据版本、输入哈希、配置哈希、源码哈希、摘要 |
| `runs` | 每次运行的 `run_id`、时间和状态 |
| `records` | 最终保留的清洗后样本 |
| `dispositions` | 每条非空输入行的最终处置，包含 `kept`、`duplicate`、`quarantined` |

`dataset_version` 由输入文件哈希、配置哈希和源码哈希计算得到，用于区分不同处理版本。

SQL 示例位于：

```text
sql/analysis.sql
```

包含：

- 数据版本摘要。
- 按 topic 统计保留样本数。
- source 分布。
- `kept` / `duplicate` / `quarantined` 状态统计。
- 规则出现次数。
- 最近运行记录。

## 配置

默认配置位于：

```text
configs/default.json
```

主要配置项：

| 配置 | 说明 |
| --- | --- |
| `allowed_topics` | 允许的主题词表 |
| `allowed_language` | 允许的语言 |
| `max_message_chars` | 单条消息最大字符数 |
| `max_dialogue_chars` | 整段对话最大字符数 |
| `email_pattern` | 模拟邮箱识别正则 |
| `phone_pattern` | 模拟手机号识别正则 |

## 测试

```bash
python -m pytest
```

测试覆盖：

- 坏 JSON 后继续读取。
- 空白行计数。
- 合法多轮对话。
- 非法角色顺序。
- 类型错误和空内容。
- 文本规范化与模拟脱敏。
- 内容哈希和精确去重。
- 同 `sample_id` 不同内容冲突。
- SQLite 写入。
- 重复运行不重复插入记录。
- SQL topic 统计与 Python summary 对照。

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 命令成功完成；允许存在已隔离的数据问题 |
| `1` | 系统错误，例如输入文件不存在或配置无法读取 |
| `2` | `--strict` 模式下发现数据规则问题 |
