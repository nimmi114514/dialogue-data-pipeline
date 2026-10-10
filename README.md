# dialogue-data-pipeline

中文对话数据流水线学习项目，用一个可本地运行的小型工程演示对话数据从原始 JSONL 到结构检查、清洗脱敏、去重隔离和质量记录的早期处理流程。

这个项目面向初级数据工程相关岗位准备，重点不是训练模型，而是把数据工程中经常被问到、也容易被忽略的基础问题做清楚：数据从哪里来、格式是否稳定、坏数据如何隔离、每条输入如何追溯、统计结果是否来自真实运行。

## 项目背景

对话数据在进入微调、评测或人工审核之前，通常会遇到这些问题：

- 原始文件里混有坏 JSON 行，导致一次读取直接失败。
- 字段缺失、类型错误、空内容、非法角色顺序等结构问题没有被明确记录。
- 结构检查、内容质量审核和模型效果评估被混在一起，难以解释问题来源。
- 清洗或筛选后无法追溯到原始文件和具体行号。
- 运行结果只写在 README 里，没有可复现的产出文件。

本项目当前实现到 S2：读取本地 JSONL，对每条中文对话做结构验证，再对结构合格的数据进行规范化、模拟邮箱/手机号脱敏、内容哈希、精确去重和 `sample_id` 冲突隔离。后续阶段会逐步加入 SQLite、SQL 分析、泄漏组划分、人工标注和质量报告。

## 当前已实现

S1 读取与验证：

- 逐行读取 UTF-8 JSONL。
- 记录输入文件 SHA-256、物理行号、空白行数和候选行数。
- 单行 JSON 解析失败时写入异常结果，并继续处理后续行。
- 验证单条对话记录的基础结构：
  - 必需字段：`sample_id`、`group_id`、`source`、`topic`、`language`、`messages`
  - 字符串字段不能为空
  - `topic` 必须在配置词表中
  - 第一版只接受 `language=zh`
  - `messages` 必须是数组
  - 每条消息必须包含合法 `role` 和字符串 `content`
  - 可选第一条 `system`
  - 之后必须严格 `user` / `assistant` 交替
  - 末条消息必须是 `assistant`
- 输出：
  - `accepted.jsonl`
  - `rejected.jsonl`
  - `summary.json`
- 添加基础 pytest 测试，覆盖坏 JSON 后继续读取、空行计数、合法多轮对话、非法角色顺序、类型错误和空内容。

S2 清洗与去重：

- 对结构合格的消息内容做 Unicode NFC 规范化。
- 统一换行符为 `\n`。
- 清理消息首尾空白，但保留消息内部换行和格式。
- 用配置里的正则规则把模拟邮箱替换为 `[EMAIL]`。
- 用配置里的正则规则把模拟手机号替换为 `[PHONE]`。
- 基于规范化后的 `messages` 计算稳定 SHA-256 内容哈希。
- 对规范化和脱敏后的完全相同对话做精确去重，保留输入顺序中最早的一条。
- 对同一个 `sample_id` 对应多个不同内容哈希的记录全部隔离，避免按偶然顺序保留错误内容。

当前还没有实现 SQLite、SQL 分析、划分、人工审核和看板；这些会按阶段推进，不在 README 里伪装成已完成。

## 项目结构

```text
dialogue-data-pipeline/
  configs/
    default.json
  data/
    samples/
      raw_dialogues.jsonl
      expected_cases.json
  docs/
    annotation-guide.md
    design.md
    learning-log.md
    progress.md
  src/
    dialogue_pipeline/
      __init__.py
      __main__.py
      clean.py
      deduplicate.py
      ingest.py
      validate.py
  tests/
    test_ingest_validate.py
  pyproject.toml
  README.md
```

## 数据说明

仓库内样例数据位于 `data/samples/raw_dialogues.jsonl`，全部为模拟中文对话，字段中明确写有 `source=synthetic`。这些数据只用于验证工程流程，不代表真实用户数据，也不用于证明模型能力。

样例覆盖：

- 正常单轮对话
- 正常多轮对话
- 可选首条 `system` 消息
- 坏 JSON 行
- 缺少 assistant 的对话
- 数字类型的 `content`
- 空白内容
- 非法角色顺序
- 不支持语言
- 未知主题
- `messages` 类型错误
- 同 `sample_id` 不同内容冲突
- 首尾空白清理后的重复内容
- 含模拟邮箱和手机号的脱敏样例

当前样例预期：

```text
candidate_lines = 24
blank_lines = 1
kept_count = 13
duplicate_count = 1
quarantined_count = 10
rejected_count = 11
```

## 环境要求

建议使用 Python 3.11 或更高版本。当前本地验证环境是 Python 3.12.11。

S1 主流程只依赖 Python 标准库。测试依赖 `pytest`。

## 安装

在项目根目录执行：

```bash
python -m pip install -e ".[dev]"
```

如果只想运行 CLI，不安装开发依赖，也可以使用 `PYTHONPATH=src` 的方式运行。

## 运行

### 结构检查

安装后运行：

```bash
python -m dialogue_pipeline check \
  --input data/samples/raw_dialogues.jsonl \
  --output artifacts/check
```

未安装包时运行：

```bash
PYTHONPATH=src python -m dialogue_pipeline check \
  --input data/samples/raw_dialogues.jsonl \
  --output artifacts/check
```

成功时会看到类似输出：

```text
check completed: kept=13 duplicate=1 quarantined=10 blank_lines=1 output=artifacts/check
```

### 严格模式

默认情况下，存在数据质量问题但程序成功完成时退出码为 `0`，因为异常记录已经被隔离并写入输出。可以使用 `--strict` 让任何数据规则问题返回退出码 `2`：

```bash
python -m dialogue_pipeline check \
  --input data/samples/raw_dialogues.jsonl \
  --output artifacts/check-strict \
  --strict
```

## 输出文件

运行后会在指定输出目录生成：

```text
artifacts/check/
  cleaned.jsonl
  accepted.jsonl
  rejected.jsonl
  summary.json
```

`cleaned.jsonl` 和 `accepted.jsonl` 保存最终保留记录。`accepted.jsonl` 暂时保留为兼容名称，后续核心流程会以 `cleaned.jsonl` 为主。

`cleaned.jsonl` 示例结构：

```json
{
  "char_count": 31,
  "cleaning_events": [],
  "content_hash": "...",
  "line_number": 1,
  "record": {
    "sample_id": "schedule_001",
    "group_id": "schedule_family_01",
    "source": "synthetic",
    "topic": "schedule",
    "language": "zh",
    "messages": []
  },
  "source_file_hash": "...",
  "source_path": "data/samples/raw_dialogues.jsonl"
}
```

`rejected.jsonl` 会保留原始行文本、最终处置状态和规则原因，例如：

```json
{
  "line_number": 14,
  "raw_text": "...",
  "status": "quarantined",
  "reasons": [
    {
      "rule_id": "JSON_PARSE_ERROR",
      "field_path": "$",
      "reason": "JSON 解析失败：Expecting ',' delimiter"
    }
  ]
}
```

`summary.json` 会记录候选行、空白行、保留数量、重复数量、隔离数量、规则计数和清洗事件计数。

## 运行测试

```bash
python -m pytest
```

当前验证结果：

```text
7 passed
```

## 如何实现

### 读取层

`src/dialogue_pipeline/ingest.py` 负责读取 JSONL。

它不会一次性假设整个文件都合法，而是逐行处理：

1. 空白行只计入 `blank_lines`。
2. 非空行计入 `candidate_lines`。
3. 每行单独 `json.loads`。
4. 解析失败时写入 `JSON_PARSE_ERROR`，继续下一行。
5. 成功解析但不是 JSON 对象时写入 `INVALID_TYPE`。
6. 成功解析为对象后交给验证层。

### 验证层

`src/dialogue_pipeline/validate.py` 只验证单条记录结构，不检查跨记录重复，也不判断回答质量。

验证失败会返回机器可读的规则 ID、字段路径和中文原因。这样后续写入数据库、质量报告或看板时，不需要重新猜测错误类型。

### 清洗层

`src/dialogue_pipeline/clean.py` 对结构合格的记录做可解释的自动处理：

1. 规范化 Unicode。
2. 统一换行。
3. 清理消息首尾空白。
4. 替换模拟邮箱和手机号。
5. 计算只基于 `messages` 的稳定内容哈希。

项目不会把数字 `content` 自动转成字符串，也不会自动补全缺失的 assistant，因为这类修复属于猜测式转换，容易掩盖上游数据问题。

### 去重层

`src/dialogue_pipeline/deduplicate.py` 处理跨记录关系：

1. 如果同一个 `sample_id` 对应多个不同内容哈希，相关记录全部隔离为 `SAMPLE_ID_CONFLICT`。
2. 如果不同记录的规范化内容哈希相同，只保留输入顺序中最早的一条，其余标记为 `DUPLICATE_CONTENT`。

### CLI 层

`src/dialogue_pipeline/__main__.py` 提供 `check` 命令：

1. 读取配置。
2. 调用 JSONL 读取。
3. 对成功解析的记录执行结构验证。
4. 对结构合格记录做清洗、脱敏和内容哈希。
5. 处理 `sample_id` 冲突和精确重复。
6. 写出保留记录、隔离/重复记录和摘要。
7. 根据是否开启 `--strict` 返回不同退出码。

## 规则边界

当前阶段已经做到结构检查、规则清洗、模拟脱敏和精确去重。

当前通过检查不代表：

- 回答一定有帮助。
- 回答事实一定正确。
- 数据适合直接训练模型。
- 训练集、验证集和测试集之间没有泄漏。

例如一条问答虽然结构正确，也可能回答跑题；这类问题属于后续人工审核阶段。

## 后续计划

- S3：SQLite 存储、事务写入、重复运行不重复插入、SQL 分析。
- S4：泄漏组归并、稳定 train/validation/test 划分、基础导出。
- S5：人工标签 CSV、标签校验、审核通过数据导出、质量报告。
- S6：只读 Streamlit 看板、完整 README 复现、截图和展示材料。

## 求职展示重点

这个项目用于展示数据工程基础能力：

- 能处理半结构化 JSONL 数据。
- 能把坏数据隔离而不是让整个流程崩溃。
- 能做规则明确的规范化、脱敏和精确去重。
- 能区分结构规则、人工质量审核和模型效果评估。
- 能保留行号、输入哈希和规则 ID，方便追溯。
- 能用测试验证关键边界，而不是只手工检查一次。

项目会按真实完成范围更新，不把未实现功能写成成果。
