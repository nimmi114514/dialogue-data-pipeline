# 设计记录

## S1 模块边界

- `ingest.py`：逐行读取 JSONL，记录物理行号、输入文件 SHA-256、空白行数和 JSON 解析错误。
- `validate.py`：验证单条记录的结构规则，不访问其他记录，不判断回答质量。
- `clean.py`：对结构合格记录做规范化、模拟脱敏、内容哈希和长度检查。
- `deduplicate.py`：处理跨记录的精确重复和 `sample_id` 冲突。
- `pipeline.py`：编排读取、验证、清洗、去重，生成文件输出和数据库写入共用的处理结果。
- `storage.py`：使用 SQLite 保存数据版本、运行记录、保留样本和每条输入最终处置。
- `api.py`：FastAPI 薄后端，负责上传文件、调用 pipeline、写入 SQLite，并提供 dashboard 查询接口。
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

`dataset_version` 由输入文件哈希、配置哈希和源码哈希生成。同一版本重复运行时，`records` 和 `dispositions` 会先按 `dataset_version` 删除再重写，因此不会翻倍；`runs` 表保留每次运行历史。

当前实现使用 Python 标准库 `sqlite3` 和参数化 SQL。写入包在事务中完成，避免部分表成功、部分表失败后被误认为完整结果。

## Web Dashboard

可视化采用前后端分离的本地开发模式：

- FastAPI 后端运行在 `http://127.0.0.1:8000`。
- React/Vite 前端运行在 `http://localhost:5173`。
- 前端通过 Vite proxy 把 `/api` 请求转发到 FastAPI。

核心数据处理仍然只在 Python pipeline 中实现。React 不重新实现 JSONL 解析、结构验证、清洗、脱敏或去重，避免前后端出现两套规则。

API 层只做薄封装：

- 接收 `.jsonl` 上传。
- 保存上传文件到 `artifacts/web/uploads/`。
- 调用 `process_input()`。
- 调用 `save_result()` 写入 `artifacts/web/dashboard.sqlite`。
- 提供 runs、records、rejected 和统计查询接口。

React 前端只负责展示和交互：

- 上传 JSONL。
- 展示 summary cards。
- 展示 status/topic/rule 图表。
- 展示 cleaned 和 rejected 表格。
- 点击行查看详情 JSON。

## 后续设计点

- S4：泄漏组连通分量、稳定划分和导出。
- S5：人工标签 CSV 校验、审核通过导出和质量报告。
