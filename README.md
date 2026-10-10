# dialogue-data-pipeline

本项目是一个本地运行的中文对话数据处理流水线，用于把原始 JSONL 对话数据转换为可追溯、可检查、可继续入库或分析的结构化结果。

## 技术背景

对话数据在进入训练、评测、人工审核或分析系统前，通常需要先完成基础的数据治理：

- 逐行读取 JSONL，避免单条坏数据阻塞整个文件处理。
- 校验字段结构、消息角色顺序和文本类型。
- 对可解释的文本问题做规范化和模拟脱敏。
- 识别重复内容和冲突 ID。
- 保留异常数据及原因，方便后续修复或追溯。

项目核心流水线使用 Python 标准库实现，CLI 使用 `argparse`，API 使用 FastAPI，前端使用 React + Vite。当前数据样例均为模拟中文对话，`source=synthetic`。

## 目标需求

流水线期望满足以下需求：

- 输入为 UTF-8 JSONL，每个非空物理行是一条对话记录。
- 坏 JSON、结构错误、重复内容和 ID 冲突都不会被静默丢弃。
- 每条异常记录保留原始文本、行号、规则 ID、字段路径和中文原因。
- 合格记录经过文本规范化、模拟邮箱/手机号脱敏和内容哈希计算。
- 精确重复内容只保留第一条，其余记录为 `duplicate`。
- 同一个 `sample_id` 对应不同内容时，相关记录全部隔离为 `SAMPLE_ID_CONFLICT`。
- 按泄漏组稳定划分 `train` / `validation` / `test`，同一组不会跨集合。
- 输出结果写入 JSONL 文件，也可以持久化到 SQLite 供 SQL 分析使用。
- 提供本地 Web Dashboard，支持上传 JSONL、运行流水线并查看统计图和明细表。
- 自动生成 JSON 与 Markdown 质量报告，保留指标分母、统计口径与一致性检查。
- 使用 CSV 导入人工审核标签，只导出有效人工接受的样本和训练消息。

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
泄漏组与 split 划分
        |
        |-- group_id + content_hash 连通分量
        |-- 固定 seed
        |-- 按组分配 train / validation / test
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
    api.py
    pipeline.py
    ingest.py
    validate.py
    clean.py
    deduplicate.py
    split.py
    storage.py
    report.py
    export.py
    review.py
  frontend/
    src/
  sql/analysis.sql
  tests/
  docs/
  pyproject.toml
```

## 安装

建议使用 Python 3.11 或更高版本。

```bash
python -m pip install -e ".[api,dev]"
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

## 运行 Web Dashboard

开发环境需要两个进程：

```bash
# terminal 1: backend API
uvicorn dialogue_pipeline.api:app --reload
```

```bash
# terminal 2: frontend
cd frontend
npm install
npm run dev
```

然后打开：

```text
http://localhost:5173
```

如果本机配置了 HTTP proxy，访问本地服务时设置：

```bash
export NO_PROXY=127.0.0.1,localhost
```

前端会把 `/api` 请求代理到 `http://127.0.0.1:8000`。后端会把上传文件、运行产物和 dashboard SQLite 写到：

```text
artifacts/web/
```

选择运行记录后，可在数据版本旁下载 JSON 或 Markdown 质量报告。报告从该版本的数据库记录生成，历史运行也可使用。

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

从已有数据库重新生成报告，无需原始 JSONL；`--version` 使用运行输出中的完整版本号：

```bash
python -m dialogue_pipeline report \
  --db artifacts/pipeline.sqlite \
  --version YOUR_DATASET_VERSION \
  --output artifacts/report
```

`report` 以只读方式打开数据库，不新增运行记录。数据库或版本不存在时返回退出码 `1`。

## 人工审核与导出

先运行 `run` 写入 SQLite，再使用输出的完整 `dataset_version` 导出审核模板和消息上下文：

```bash
python -m dialogue_pipeline labels-template \
  --db artifacts/pipeline.sqlite --version YOUR_DATASET_VERSION \
  --output artifacts/review-work
```

打开 `labels_template.csv`，按 `sample_id` 查阅 `review_samples.jsonl` 中的消息；填写 relevant、complete、decision、reviewer、label_origin 和 notes。未审行留空。具体约定见 [审核指南](docs/annotation-guide.md)。

```bash
python -m dialogue_pipeline labels-import \
  --db artifacts/pipeline.sqlite --version YOUR_DATASET_VERSION \
  --input artifacts/review-work/labels_template.csv

python -m dialogue_pipeline export-reviewed \
  --db artifacts/pipeline.sqlite --version YOUR_DATASET_VERSION \
  --output artifacts/reviewed-v1
```

导入校验版本、内容哈希、枚举、审核人、重复行和决策约束；整批通过才写入。相同样本的新标签覆盖旧标签，空白行不删除旧判断。重新生成报告或从网页下载报告后可查看更新的审核指标；之前导出的报告文件保持原来的快照。

审核导出包含 `reviewed_train.jsonl`、`reviewed_validation.jsonl`、`reviewed_test.jsonl`、`sft_train.jsonl`、`sft_train.sidecar.jsonl`、标签快照、质量报告和 `review_manifest.json`。只有 `human+accept` 样本进入审核通过文件；SFT 只取训练集合。没有人工接受样本时，载荷为空，清单明确说明原因。`synthetic_demo` 标签仅供演示，不计入人工审核。

每次导出使用一个新的输出目录，成功后整体发布。数据版本标识自动处理结果；`review_version` 由数据版本、有效标签快照和导出源码哈希决定。清单记录文件 SHA-256；同一快照重导出载荷一致，标签修改不会重新随机划分数据。

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
  train.jsonl
  validation.jsonl
  test.jsonl
  summary.json
  quality_report.json
  quality_report.md
```

| 文件 | 说明 |
| --- | --- |
| `cleaned.jsonl` | 最终保留的清洗后记录 |
| `accepted.jsonl` | 与 `cleaned.jsonl` 相同，保留兼容命名 |
| `rejected.jsonl` | JSON 错误、结构错误、重复内容和冲突记录 |
| `train.jsonl` | 训练集合，按泄漏组划分 |
| `validation.jsonl` | 验证集合，按泄漏组划分 |
| `test.jsonl` | 测试集合，按泄漏组划分 |
| `summary.json` | 输入行数、保留数、隔离数、重复数、规则计数和清洗事件计数 |
| `quality_report.json` | 处置、规则、清洗、主题、来源、字符长度、集合分布和一致性检查 |
| `quality_report.md` | 同一报告的人可读版本，包含有分子和分母的数据观察 |

报告中的保留比例表示通过自动处理规则的比例，不能代表回答正确率。规则次数可重叠；冲突行数属于隔离行数的子集；清洗修改次数包含后续被去重或隔离的候选记录。人工审核覆盖率和接受率仅统计有效 human 标签；无人工标签时接受率为 `null`（Markdown 为 `N/A`），所有零分母指标都使用该约定。

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
- `leakage_group_id`
- `split`
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
| `labels` | 绑定数据版本、样本与内容哈希的最新审核判断 |

`dataset_version` 由输入文件哈希、配置哈希和源码哈希计算得到，用于区分不同处理版本。

`records` 中的 `split` 和 `leakage_group_id` 用于检查 train / validation / test 划分。相同 `leakage_group_id` 不应跨集合。

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
| `split_seed` | 稳定划分随机种子 |
| `split_ratios` | train / validation / test 目标比例 |

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
- FastAPI 上传和查询接口。
- 泄漏组划分和 split 稳定性。
- 报告零分母、规则重叠、切分失败和 SQLite 只读复现。

前端构建：

```bash
cd frontend
npm run build
```

## CI

GitHub Actions 配置位于：

```text
.github/workflows/ci.yml
```

CI 在 push 到 `main` 和 pull request 时运行两个 job：

| Job | 内容 |
| --- | --- |
| `Python tests` | 运行 `pytest` 和样例 CLI，核对文件与数据库报告一致，上传报告产物 |
| `Frontend build` | 使用 Node 24，执行 `npm ci` 和 `npm run build` |

Python job 成功后，可在该次 Actions 运行的 Artifacts 中下载 `sample-quality-reports`，包含样例的 JSON 和 Markdown 报告。

本地复刻 CI：

```bash
python -m pytest
python -m dialogue_pipeline check --input data/samples/raw_dialogues.jsonl --output artifacts/ci-check-local
python -m dialogue_pipeline run --input data/samples/raw_dialogues.jsonl --config configs/default.json --output artifacts/ci-run-local --db artifacts/ci-local.sqlite

cd frontend
npm ci
npm run build
```

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 命令成功完成；允许存在已隔离的数据问题 |
| `1` | 系统错误，例如输入文件不存在或配置无法读取 |
| `2` | `--strict` 模式下发现数据规则问题 |
