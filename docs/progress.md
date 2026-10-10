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

- S3 SQLite 与 SQL 已在后续记录完成。
- 对 README 做一次全新 clone 后复现检查。

## 2026-10-10 S3 SQLite 与 SQL

### 已完成

- 新增 `pipeline.py`，把读取、验证、清洗和去重流程抽成 `check` 与 `run` 共用的核心。
- 新增 `storage.py`，使用 Python 标准库 `sqlite3` 写入本地 SQLite。
- 新增 `run` 命令，支持 `--db artifacts/pipeline.sqlite`。
- 新增数据库表：`datasets`、`runs`、`records`、`dispositions`。
- `dispositions` 覆盖每条非空输入行，状态包括 `kept`、`duplicate`、`quarantined`。
- 新增 `sql/analysis.sql`，包含数据版本摘要、topic 分布、source 分布、处置状态统计、规则统计和运行记录查询。
- 测试扩展到 10 条，覆盖 SQLite 写入、重复运行不翻倍、SQL topic 统计与 Python summary 对照。

### 实际运行命令

```bash
python -m pytest
python -m dialogue_pipeline run --input data/samples/raw_dialogues.jsonl --config configs/default.json --output artifacts/run-s3 --db artifacts/pipeline.sqlite
```

### 当前结果

- CLI 运行输出：`kept=13 duplicate=1 quarantined=10 blank_lines=1`。
- 生成数据库：`artifacts/pipeline.sqlite`。
- 当前样例数据版本：`be9186fe3c72abe6c81f4be8e38d10e12d714f1e2a1ed06233d6d1e46b18ceca`。
- 测试：`10 passed in 0.73s`。

### 待完成

- S4 泄漏组与 train/validation/test 划分。
- 为分析 SQL 增加命令行执行或报告导出。

## 2026-10-10 Web Dashboard MVP

### 已完成

- 新增 FastAPI 后端 `src/dialogue_pipeline/api.py`。
- API 支持上传 `.jsonl`、运行现有 Python pipeline、写入 SQLite，并查询 runs、records、rejected、topic/status/rule 统计。
- 新增 React + Vite + TypeScript 前端，位于 `frontend/`。
- 前端支持上传 JSONL、显示 summary cards、status/topic/rule 图表、cleaned/rejected 表格和详情面板。
- 开发模式采用两个进程：`uvicorn dialogue_pipeline.api:app --reload` 和 `npm run dev`。
- 测试扩展到 12 条，新增 FastAPI 上传和查询接口测试。

### 实际运行命令

```bash
python -m pip install -e .[api,dev]
python -m pytest tests/test_api.py tests/test_storage.py tests/test_ingest_validate.py
cd frontend && npm install
cd frontend && npm run build
```

### 当前结果

- 后端测试：`12 passed`。
- 前端构建成功，输出到 `frontend/dist/`。
- Vite 构建提示主 bundle 超过 500 kB，MVP 阶段可接受；后续可用动态导入或手动 chunk 优化。

### 待完成

- 增加端到端浏览器测试或截图验证。
- 根据后续 S4 划分结果扩展 dashboard 图表。

## 2026-10-10 CI

### 已完成

- 新增 GitHub Actions workflow：`.github/workflows/ci.yml`。
- CI 触发条件：push 到 `main` 和 pull request。
- Python job 使用 Python 3.12，安装 `.[api,dev]`，运行 `pytest`，并运行样例 `check` / `run` 命令。
- Frontend job 使用 Node 24，执行 `npm ci` 和 `npm run build`。
- README 新增 CI 说明和本地复刻命令。

### 实际运行命令

```bash
python -m pytest
python -m dialogue_pipeline check --input data/samples/raw_dialogues.jsonl --output artifacts/ci-check-local
python -m dialogue_pipeline run --input data/samples/raw_dialogues.jsonl --config configs/default.json --output artifacts/ci-run-local --db artifacts/ci-local.sqlite
cd frontend && npm ci
cd frontend && npm run build
```

### 当前结果

- Python tests：`12 passed`。
- CLI check：`kept=13 duplicate=1 quarantined=10 blank_lines=1`。
- CLI run：`kept=13 duplicate=1 quarantined=10 blank_lines=1`。
- Frontend：`npm ci` 成功，`npm run build` 成功。
- Vite 仍提示主 bundle 超过 500 kB，暂不阻塞 CI。
