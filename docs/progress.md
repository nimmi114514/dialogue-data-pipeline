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

- S4 泄漏组与 train/validation/test 划分已在后续记录完成。
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

## 2026-10-10 S4 泄漏组与划分

### 已完成

- 新增 `split.py`，用并查集基于 `group_id` 和 `content_hash` 构建泄漏组。
- `cleaned.jsonl` 中新增 `leakage_group_id` 和 `split`。
- `check` / `run` 新增导出 `train.jsonl`、`validation.jsonl`、`test.jsonl`。
- SQLite `records` 表新增 `leakage_group_id` 和 `split`。
- API `records` 返回 split 信息，新增 `/api/runs/{run_id}/stats/split`。
- Dashboard 新增 split distribution 图表，cleaned records 表显示 split。
- SQL 分析新增 split 分布和 split 内 topic 分布。
- 测试扩展到 16 条，覆盖稳定划分、同组不跨集合、跨 group_id 相同内容关联、少于 3 组错误、SQLite/API split 输出。

### 实际运行命令

```bash
python -m pytest
python -m dialogue_pipeline run --input data/samples/raw_dialogues.jsonl --config configs/default.json --output artifacts/s4-run --db artifacts/s4.sqlite
python -m dialogue_pipeline check --input data/samples/web_demo_dialogues.jsonl --output artifacts/s4-web-demo-check
```

### 当前结果

- 测试：`16 passed`。
- 样例 `raw_dialogues.jsonl`：`kept=13 duplicate=1 quarantined=10`。
- 泄漏组数量：`11`。
- split 数量：`train=11`、`validation=1`、`test=1`。
- 小数据比例偏差较大，但没有拆分泄漏组。

### 待完成

- 质量报告 `quality_report.json` / `quality_report.md`。
- 人工标注 CSV 导出和导入。

## 2026-10-10 质量报告

### 实现

- 新增 `report.py`，生成 JSON 和 Markdown 质量报告，统计处置、冲突、规则、清洗事件、主题、来源、字符长度、集合和泄漏组。
- 比例保留分子、分母；零分母写 null / N/A；未导入人工标签明确标识，决策计数为零。
- 报告提供四条含数字、含义与局限的观察，以及计数和跨集合重叠检查。
- 合并 CLI/API 文件导出到 `export.py`，check、run、Web 上传自动生成报告。
- 新增只读 `report --db --version --output` 命令、API 报告下载接口、网页 JSON/Markdown 下载入口。
- CI 增加报告逐字节一致性检查和 `sample-quality-reports` artifact 上传步骤；尚未在远程执行本次 workflow。
- README 和本地私有 spec 更新技术说明及运行方式；spec 仍被 gitignore 排除。

### 实际验证

```bash
python -m pytest --ignore=tests/test_api.py -q
python -m dialogue_pipeline run --input data/samples/raw_dialogues.jsonl --output artifacts/report-demo --db artifacts/report-demo.sqlite
python -m dialogue_pipeline report --db artifacts/report-demo.sqlite --version YOUR_DATASET_VERSION --output artifacts/report-from-db
cd frontend && npm run build
```

- 非 HTTP 测试 `21 passed`；覆盖空文件、全部隔离、规则重叠、切分失败、非法版本、只读数据库、文件/数据库报告一致、目标比例默认值。
- 样例保留 13 条、重复 1 条、隔离 10 条；报告与 SQL 的主题、规则统计一致。
- 文件报告与 SQLite 重建报告逐字节一致；原始 JSONL 删除后仍可重建报告。
- 直接调用 API 函数验证上传、JSON/Markdown 响应、下载文件名、记录查询和未知运行 404，通过。
- 前端构建通过；仍有现有的主包超过 500 kB 提示。

### 环境限制与后续

- 本次环境禁止网络 socket：全量 pytest 在 TestClient 上阻塞，已终止；2 条 HTTP 集成测试未完成。直接函数验证不能替代 HTTP 集成测试。
- uvicorn 和 Vite 启动均被环境拒绝，未完成浏览器截图或点击验证。
- `.git` 为只读，`git add` 无法创建 index.lock，本次未提交或推送。
- 下一步：人工审核 CSV 模板与原子导入、manifest、审核通过子集及 SFT sidecar；同时完善独立组不足时的 CLI 退出策略。

## 2026-10-10 审核闭环与项目范围

### 实现与取舍

- 按求职练手目标优先完成可演示、可解释、有测试依据的数据闭环；保留 SQLite、CLI、FastAPI、React 和 GitHub Actions 的现有架构。
- 增加 labels 表和 `labels-template` / `labels-import` / `export-reviewed` 三个命令，模板附完整对话上下文。
- 整批验证和 upsert 使用同一事务；校验失败及中途写入失败均回滚。重复导入不增加标签数，相同版本重跑保留已有判断。
- 报告区分有效人工标签、演示标签和失效标签；网页报告下载随数据库中的最新标签更新。
- 审核导出保持原集合，只包含有效 human+accept；SFT 仅来自 train，sidecar 保存输入行血缘。
- review_version 绑定数据版本、标签快照和导出源码；导出使用临时目录成功后整体发布，review_manifest 记录文件哈希。
- CI 增加空白模板导入和空训练载荷检查。README 仅保留技术说明，项目范围和面试解释补进本地私有 spec。

### 实际验证

- `python -m pytest --ignore=tests/test_api.py -q`：`42 passed`。
- 测试包括非法/重复/过期标签、CSV 结构错误、批量验证不写入、数据库中途失败回滚、幂等导入、重跑标签保留、演示数据排除、训练/验证/测试隔离、快照变更、哈希核对、导出失败不发布。
- 本地 `artifacts/review-practice/` 已运行 run、labels-template、空模板 labels-import 和 export-reviewed；13 条待审核样本、零条人工标签，空训练文件符合预期。
- 直接 API 函数验证上传后 JSON/Markdown 报告与文件输出一致，通过。未运行浏览器或 HTTP 集成测试。
- 本次未改前端代码，不重复构建。受现有环境的 socket 和 `.git` 只读限制，2 条 HTTP 测试及提交推送仍未完成；未在远程执行 CI。

### 后续收尾

- 开发者亲自审核 3–5 条，手算指标并核对导出；没有替开发者生成 human 标签。
- 完善 split 失败退出策略、自动处理输出的原子发布和完整运行 manifest。
- 优先补一键本地启动与端到端演示，再按具体岗位需要决定额外增强。

## 2026-10-10 本地启动与完整测试复核

- 执行环境权限调整后，端口监听限制解除。uvicorn 在 `127.0.0.1:8000`、Vite 在 `127.0.0.1:5173` 成功启动。
- 后端 `/api/health`、前端首页及经 Vite 代理的 `/api/health` 均返回 HTTP 200。
- 经前端代理上传 `web_demo_dialogues.jsonl`，实际结果为保留 6 条、重复 1 条、隔离 8 条；Markdown 报告下载返回 HTTP 200。
- `python -m pytest -q`：`44 passed`，此前未完成的 2 条 HTTP 集成测试也已通过。仍有一条 Starlette TestClient 依赖弃用提示。
- 本次没有浏览器截图或交互点击验证；HTTP 连通检查不能替代完整浏览器验收。
- Git 工作区恢复可写，准备将质量报告、审核闭环、CI 和对应文档一并提交。私有 spec 和运行产物继续排除。

## 2026-10-10 公开数据、Pandas 与 Token 预算

- 按公开数据实践、Pandas/SQL、固定 tokenizer 的顺序实现；未增加页面，分页保留为开发者练习。
- 新增 OASST1 固定 revision 适配器和专用配置。保存许可、数据卡、下载哈希、筛选计数、消息链、根节点及上游 split；按消息 ID 固定抽样，根节点绑定 group_id。
- 从 1,933 条合格中文路径中抽取 1,000 条、370 个根；流水线保留 981、重复 5、隔离 14，最终 366 个泄漏组，train/validation/test 为 784/99/98。
- 新增 analyze，Pandas 对照主题、同样本字符长度、精确重复和人工审核结果，五类指标与同一 SQLite 只读快照核对，实际全部通过。
- 新增 labels-template 的 --sample-size / --seed，导出 50 条未填写审核记录和选择清单。实际人工审核为零；未代填个人审核或学习记录。
- 新增 token-budget，固定 Qwen tokenizer revision 和 transformers 4.57.6，记录文件哈希。981 条保留样本的 512 输入超限为 38，加入 256 输出预留后为 152；1024 对应 6 / 12；2048、4096 为 0 / 0。不下载权重、不推理、不截断。
- 公开数据、缓存和审核模板均保存在 artifacts；公开文档只记录方法、汇总统计和未完成的真实人工审核边界。故障注入样例仍仅用于测试。
- 可选依赖放入 analysis extra，基础流水线继续使用原来的标准库架构。CI 安装分析依赖运行离线测试，不在 CI 下载公开数据或模型文件。
- 验证：`python -m pytest -q` 为 `51 passed`；适配器实际下载、CLI 全流程、真实 tokenizer 计数和 sql/practice.sql 全部运行。现有 TestClient 弃用提示仍存在；未重复构建未改动的前端。
- 详细命令、实际发现和限制见 docs/data-practice.md。开发者仍需亲自审核、修改规则、写 SQL、记录学习过程，之后才能形成个人实践结论。
