# 学习记录

## Codex 解释

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

## 开发者亲自验证

待填写。建议每次自己修改样例、运行命令、观察输出后，把命令和发现写在这里。

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
