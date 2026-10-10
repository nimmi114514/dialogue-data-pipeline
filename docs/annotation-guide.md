# 对话审核指南

审核对象是自动校验、清洗、去重后保留的完整对话。CSV 中的 `sample_id` 可在同目录 `review_samples.jsonl` 或网页明细中找到对应消息。

先阅读用户问题和回答，再填写判断。结构正确不代表回答正确；没有把握时使用 `unsure` 并写明需要核查的内容。

## 字段

| 字段 | 填写规则 |
| --- | --- |
| `dataset_version` | 保留模板原值，标识这批处理数据 |
| `sample_id` | 保留模板原值，定位样本 |
| `content_hash` | 保留模板原值，防止把旧判断用到新内容上 |
| `relevant` | `yes`：回应了问题；`no`：偏题；`unsure`：无法判断 |
| `complete` | `yes`：覆盖明确要求；`no`：遗漏关键要求；`unsure`：无法判断 |
| `decision` | `accept`、`reject` 或 `unsure` |
| `reviewer` | 实际审核者的别名 |
| `label_origin` | 实际人工判断填 `human`；程序、AI 或演示判断填 `synthetic_demo` |
| `notes` | `reject` / `unsure` 必填具体原因；`accept` 可留空 |

`accept` 必须同时满足 `relevant=yes` 与 `complete=yes`。还应确认没有已知的明显事实错误、危险建议或与问题矛盾的内容；两个 yes 不会强制系统把 decision 改为 accept。

判断示例：用户要求“一小时内的三步复习计划”，回答给出了可执行、总计一小时的三步，可考虑 yes / yes / accept；只给泛泛建议，可能是 yes / no / reject，并注明“缺少三步安排和时长”；回答包含无法核查的事实，可以填 unsure 并写明疑点。

## 操作

1. 用 `labels-template --db ... --version ... --output artifacts/review-work` 导出模板。
2. 在 CSV 编辑器中打开 `labels_template.csv`，通过 sample_id 查阅完整消息。保留 UTF-8 编码和列名；notes 内含逗号或换行时由编辑器正确加引号。
3. 填写已读样本的六个审核字段。未审样本的审核字段全部留空，不要预填为 accept。
4. 用 `labels-import --db ... --version ... --input artifacts/review-work/labels_template.csv` 导入。任何一行错误都会使整批不写入，错误信息包含 CSV 物理行号。
5. 重新运行 `report`，或在网页下载该版本的最新报告。使用 `export-reviewed` 导出审核通过的数据。

可以分批审核。空白审核行不会删除数据库中已有判断；相同版本和样本的新有效标签会覆盖旧标签。修改已审核判断时重新填写该行后导入。模板每行只能出现一次。

## 指标与导出

人工审核覆盖率 = 有效 human 标签数 / 保留样本数；人工接受率 = human+accept 数 / 有效 human 标签数。reject 和 unsure 也属于已审核。没有人工标签时，接受率为 N/A。

`synthetic_demo` 可以验证导入流程，但不计入人工审核指标，也不进入审核通过文件。系统只校验 label_origin 的声明，不能证明填写者真的完成了审核；演示或 AI 生成内容必须如实标记。

`export-reviewed` 保留原来的 train / validation / test 归属。只有有效 human+accept 记录进入相应 reviewed 文件；`sft_train.jsonl` 只从 reviewed_train 生成，sidecar 将训练行映射回样本和输入行。未审核、reject、unsure 和演示标签均不会进入训练载荷。

审核通过仅表示按本指南检查过，不保证所有事实正确或适用于所有场景。SFT 文件仍需训练平台自己的 tokenizer 和 chat template；本项目不执行训练或宣称模型效果提升。
