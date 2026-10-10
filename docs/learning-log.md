# 学习记录

## 技术说明

### JSONL、dict 和 list

JSONL 是每个非空物理行一条 JSON 记录。本项目把一条记录解析成 Python `dict`，其中 `messages` 是一个 `list`，列表里的每条消息又是一个 `dict`。

一个最小合法样例：

```json
{"sample_id":"study_001","group_id":"study_family_01","source":"synthetic","topic":"study","language":"zh","messages":[{"role":"user","content":"什么是 JSONL？"},{"role":"assistant","content":"每行一个 JSON 对象。"}]}
```

读取层只关心“这一行是不是合法 JSON 对象”。验证层才检查 `sample_id`、`messages`、`role`、`content` 等字段是否符合项目规则。

### 为什么坏 JSON 后还能继续

JSONL 的好处是每行独立。第 14 行坏了，不应该导致第 15 行之后的正常记录全部丢失。`read_jsonl` 在单行解析失败时记录 `JSON_PARSE_ERROR`，然后继续读取下一行。

### 结构检查不等于回答质量检查

结构检查能判断 `messages` 是否是数组、`content` 是否是字符串、角色是否交替。它不能判断回答是否真的有用、是否跑题，后者属于人工审核阶段。

## S1 练习

1. 在 `data/samples/raw_dialogues.jsonl` 末尾新增一条合法的 `topic=study` 对话，运行 `python -m dialogue_pipeline check --input data/samples/raw_dialogues.jsonl --output artifacts/check-practice`，观察 `accepted_count` 是否加 1。
2. 把一条合法样例的最后一条 `assistant` 改成 `user`，再次运行 check，查看 `rejected.jsonl` 中对应行的 `rule_id` 和 `field_path`。

## S2 练习

1. 复制一条合法记录，换一个新的 `sample_id`，但只给消息内容前后加空格。运行 check，观察它是否进入 `DUPLICATE_CONTENT`。
2. 新增两条相同 `sample_id` 但不同 `messages` 的记录。运行 check，确认两条都被 `SAMPLE_ID_CONFLICT` 隔离，而不是保留第一条。
3. 在一条合法记录里加入模拟邮箱和手机号，观察 `cleaned.jsonl` 中是否被替换为 `[EMAIL]` 和 `[PHONE]`。

## S3 练习

1. 运行两次 `python -m dialogue_pipeline run --input data/samples/raw_dialogues.jsonl --config configs/default.json --output artifacts/run-practice --db artifacts/practice.sqlite`，然后查询 `records` 数量，确认不会翻倍。
2. 修改 `sql/analysis.sql` 中 topic 统计的 `ORDER BY`，按 topic 名称升序输出。
3. 自己写一条 SQL：从 `dispositions` 表统计 `status='quarantined'` 的行数。

## S4 练习

1. 打开 `artifacts/s4-run/train.jsonl`、`validation.jsonl`、`test.jsonl`，确认同一个 `leakage_group_id` 没有出现在多个文件中。
2. 修改 `configs/default.json` 的 `split_seed`，重新运行 `run`，观察 split 分配是否变化。
3. 新增两条不同 `group_id` 但相同消息内容的样本，运行 check，观察它们是否得到相同的 `leakage_group_id`。

## 质量报告：实现说明

报告分成三步：`build_report(summary, records, dispositions, config)` 统计最终记录，`render_markdown(report)` 将同一份数据转成人可读文本，`load_report(db_path, dataset_version)` 从 SQLite 的一致性快照重新统计。文件处理和网页使用同一个生成器，避免两套统计口径。

样例中保留率为 13/24，即 54.17%；分母包含坏 JSON，排除空白行。隔离 10 条、重复 1 条，与保留 13 条互斥，加起来是 24。规则可能在同一条记录上出现多次，因此规则次数相加不能当作隔离条数。

审核覆盖率的分母是保留样本数，人工接受率的分母是有效人工审核数；分母为零时显示 N/A。自动规则不能判断回答正确性。

报告练习：

1. 比较 `quality_report.json` 的 `counts` 与 `dispositions` 的 `GROUP BY status` 查询结果。
2. 用空文件运行 check，观察保留率为什么是 null，而不是 0%。
3. 用只有一个合法家族的文件运行 check，查看报告中的 `unassigned`、`split_error` 和 `split_complete`。

## 人工审核闭环：实现说明

这一阶段的工程重点是事务、版本和数据血缘。`labels-import` 在一个 SQLite 事务里锁定当前记录，验证整份 CSV，之后才执行 upsert；任意验证或写入失败都会回滚。相同版本中每个样本只保留最新标签，重复导入不会增加行数。

标签同时绑定 dataset_version、sample_id、content_hash，避免同名样本内容变化后误用旧判断。数据版本标识自动处理结果；review_version 标识数据版本、标签快照和导出代码的组合。更新标签只筛选原来的集合，不重新随机切分。

审核导出先写入临时目录，全部成功才发布到新目录。review_manifest 记录每个文件的哈希；sidecar 将 SFT 第 N 行映射回 sample_id、内容哈希及输入文件行号。这能回答“训练里的这条消息从哪里来、经过了哪次审核”。

SQLite 足以支持本项目的单机演示、关系查询和原子导入。只有出现多人并发写入、远程共享或长期托管需求时，再根据实际需求评估独立数据库服务。

审核练习：

1. 阅读并审核 3–5 条模板记录，导入后手算覆盖率和接受率，再与报告核对。
2. 复制模板用于实验，改错一条 content_hash，观察导入失败后已有标签是否保持不变。
3. 写 SQL 按 label_origin、decision 统计 labels，解释为什么 synthetic_demo 的 accept 不进入训练文件。
