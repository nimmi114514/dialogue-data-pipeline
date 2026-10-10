# 设计记录

## S1 模块边界

- `ingest.py`：逐行读取 JSONL，记录物理行号、输入文件 SHA-256、空白行数和 JSON 解析错误。
- `validate.py`：验证单条记录的结构规则，不访问其他记录，不判断回答质量。
- `clean.py`：对结构合格记录做规范化、模拟脱敏、内容哈希和长度检查。
- `deduplicate.py`：处理跨记录的精确重复和 `sample_id` 冲突。
- `split.py`：用 `group_id` 和 `content_hash` 构建泄漏组，并稳定划分 train / validation / test。
- `pipeline.py`：编排读取、验证、清洗、去重，生成文件输出和数据库写入共用的处理结果。
- `storage.py`：使用 SQLite 保存数据版本、运行记录、保留样本和每条输入最终处置。
- `catalog.py`：保存原始 JSONL 字节与来源元数据，按内容哈希和配置名称去重。
- `api.py`：FastAPI 薄后端，负责数据集上传与选择运行、调用 pipeline、写入 SQLite，并提供 dashboard 查询接口。
- `__main__.py`：提供 `check` 和 `run` CLI。

## S1 关键取舍

读取和结构验证被分开，原因是坏 JSON 行甚至无法进入结构验证；它们只能由读取层用原始文本和行号隔离。结构验证只处理已经成功解析为 JSON 对象的记录。

`sample_id` 唯一性检查在 S2 实现。原因是 ID 冲突需要看完整输入集合，不能只看当前行。如果同一个 `sample_id` 对应多个不同内容哈希，相关记录全部隔离。

未知字段暂时不会进入输出训练载荷，因为训练载荷还未实现。后续阶段需要决定是否在元数据中保留未知字段警告。

## 清洗与哈希

输入文件 SHA-256 用于定位输入版本。

内容哈希在 S2 实现，规则是：

1. 只使用规范化后的有序 `messages` 列表。
2. 每条消息只包含 `role` 和清洗后的 `content`。
3. 不包含 `sample_id`、`topic`、`group_id` 等元数据。
4. 使用 `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))` 做稳定序列化。
5. 对 UTF-8 字节计算 SHA-256。

这样同一段对话即使出现在不同 `sample_id` 或 `group_id` 下，也会得到相同内容哈希。

## 去重取舍

去重发生在结构验证、文本规范化和模拟脱敏之后。保留规则是输入顺序中最早的一条。

同 ID 同内容可以按重复处理；同 ID 不同内容全部隔离为 `SAMPLE_ID_CONFLICT`。这个选择比“保留第一条”更保守，因为同一个 ID 指向两段不同内容时，无法确定哪条才是上游真实意图。

## SQLite 存储

`run` 命令会在文件输出之外写入 SQLite。当前表结构保持最小可用：

- `datasets`：保存 `dataset_version`、输入哈希、配置哈希、源码哈希、状态和摘要 JSON。
- `runs`：保存每次运行的 `run_id`、开始/结束时间和状态。
- `records`：保存最终保留的清洗后样本，主键为 `(dataset_version, sample_id)`。
- `dispositions`：保存每条非空输入行的最终处置，主键为 `(dataset_version, source_file_hash, line_number)`。
- `raw_sources`：保存可重复处理的原始 JSONL BLOB、文件名、来源、配置名称、SHA-256、字节数与非空行数。
- `source_runs`：连接原始数据集和处理运行，与运行结果在同一事务中写入。

`dataset_version` 由输入文件哈希、配置哈希和源码哈希生成。同一版本重复运行时，`records` 和 `dispositions` 会先按 `dataset_version` 删除再重写，因此不会翻倍；`runs` 表保留每次运行历史。

当前实现使用 Python 标准库 `sqlite3` 和参数化 SQL。写入包在事务中完成，避免部分表成功、部分表失败后被误认为完整结果。

## 泄漏组与划分

划分发生在结构验证、清洗、脱敏和精确去重之后。划分对象是最终保留记录，但泄漏组连接关系会参考所有结构合格且清洗后的候选记录，包括后来被判定为重复的记录。

泄漏组规则：

- 每条候选记录连接一个 `group_id` 节点和一个 `content_hash` 节点。
- 使用并查集求连通分量。
- 同一连通分量生成稳定的 `leakage_group_id`。
- 最终保留记录按 `leakage_group_id` 整组进入同一个 split。

划分规则：

- 默认 `split_seed=42`。
- 默认目标比例 `train=0.8`、`validation=0.1`、`test=0.1`。
- 按泄漏组划分，不拆组。
- 当独立泄漏组少于 3 个时，不生成看似完整的三集合；summary 中记录 `split_error`。
- 小样例中实际比例可能偏离目标比例，这是不拆组的正常结果。

## Web Dashboard

可视化采用前后端分离的本地开发模式：

- FastAPI 后端运行在 `http://127.0.0.1:8000`。
- React/Vite 前端运行在 `http://localhost:5173`。
- 前端通过 Vite proxy 把 `/api` 请求转发到 FastAPI。

核心数据处理仍然只在 Python pipeline 中实现。React 不重新实现 JSONL 解析、结构验证、清洗、脱敏或去重，避免前后端出现两套规则。

API 层只做薄封装：

- 接收 `.jsonl` 上传。
- 将原始字节存入 SQLite，处理时原子恢复到 `artifacts/web/uploads/`。
- 按 source_id 读取原始内容和绑定的配置，支持重复运行与原文件下载。
- 调用 `process_input()`。
- 调用 `save_result()` 写入 `artifacts/web/dashboard.sqlite`。
- 提供 sources、按数据集筛选的 runs、分页 records/rejected 和全量统计接口。

React 前端只负责展示和交互：

- 从下拉框选择已有 JSONL 数据集，查看其历史结果或重新运行。
- 选择上传配置并上传 JSONL，保存后立即运行。
- 展示 summary cards。
- 展示 status/topic/rule 图表。
- 展示 split 分布图。
- 展示 cleaned 和 rejected 分页表格，每页 50 条，总量由 API 返回。
- 查看对话、隔离原因与详情 JSON；切换数据集或运行时重置页码和选择，取消过期查询。

原始数据集、处理版本和运行记录是三种不同对象：同一输入与配置名称对应一个 source；输入、配置内容或流水线源码变化会生成新的 dataset_version；每次执行都有新的 run_id。同一版本重复运行不会让记录翻倍。原始字节保存在数据库而非仅引用路径，删除下载目录不影响再次运行；许可与上游血缘清单仍由公开数据适配器保存在原下载目录。

`catalog-add` 用于显式登记适配器下载结果，API 启动不下载远程数据。旧版上传仅在路径属于上传目录、原文件存在且哈希一致时建立来源关联，不将清洗结果伪装成原始输入。处理是同步请求，面向本地单用户和数千条样本；20 MiB 文件限制控制单次输入规模，多用户或长任务需求出现后再引入任务队列与认证。

## 后续设计点

- S5：人工标签 CSV 校验、审核通过导出和质量报告。
