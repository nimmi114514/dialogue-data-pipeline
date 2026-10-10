# 公开中文对话数据实践

## 来源和边界

使用 [OpenAssistant/OASST1 官方数据集](https://huggingface.co/datasets/OpenAssistant/oasst1)，固定 revision `fdf72ae0827c1cda404aff25b6603abec9e3399b`。[数据卡和许可](https://huggingface.co/datasets/OpenAssistant/oasst1/tree/fdf72ae0827c1cda404aff25b6603abec9e3399b) 标明 Apache-2.0。下载文件、上游 LICENSE / README、SHA-256、原始消息 ID 和抽样方式保存在本地 artifacts；不将完整对话原文提交 Git。数据中出现第三方转载声明的样本，另行保留授权疑问，不由数据卡许可直接推定可用。

适配器从消息表重建根节点到 assistant 的完整路径，要求路径元数据为 zh、角色交替、无删除或负面上游审核标记。每个 assistant 节点生成一个样本，共享根节点的路径使用相同 group_id。固定 seed 后按消息 ID 的哈希排序抽样，便于重现。

本次用的是上游 ready-for-export 消息，已有筛选；lang=zh 是上游标签，不是独立语言检测。原始 train / validation 来源保留在 lineage 文件中，本项目为演示重新按家族切分，不把这个结果当作官方 benchmark 划分。上游审核和 rank 不作为本项目的人工审核标签。

主题使用根问题的固定关键词规则，未匹配归为 other。这是弱标注，不是人工主题真值。配置 `configs/oasst1.json` 接受 other，其余长度和分组规则与默认配置一致；模拟脱敏使用清洗模块默认规则。网页上传可选择 OASST1 profile，或使用 `catalog-add --profile oasst1` 登记本地文件后从下拉框选择。

## 复现

从仓库根目录运行，Python 3.11+：

```bash
python -m pip install -e ".[api,dev,analysis]"

python -m dialogue_pipeline import-oasst \
  --output artifacts/oasst-practice/source --limit 1000 --seed 42

python -m dialogue_pipeline run \
  --input artifacts/oasst-practice/source/dialogues.jsonl \
  --config configs/oasst1.json \
  --output artifacts/oasst-practice/processed \
  --db artifacts/oasst-practice/pipeline.sqlite

PRACTICE_VERSION=$(python -c 'import json; print(json.load(open("artifacts/oasst-practice/processed/summary.json"))["dataset_version"])')

python -m dialogue_pipeline labels-template \
  --db artifacts/oasst-practice/pipeline.sqlite --version "$PRACTICE_VERSION" \
  --output artifacts/oasst-practice/review-50 --sample-size 50 --seed 42

python -m dialogue_pipeline labels-replay \
  --db artifacts/oasst-practice/pipeline.sqlite --version "$PRACTICE_VERSION" \
  --input data/reviews/oasst1-review50.json --output artifacts/oasst-practice/labels.csv

python -m dialogue_pipeline labels-import \
  --db artifacts/oasst-practice/pipeline.sqlite --version "$PRACTICE_VERSION" \
  --input artifacts/oasst-practice/labels.csv

python -m dialogue_pipeline analyze \
  --input artifacts/oasst-practice/source/dialogues.jsonl \
  --db artifacts/oasst-practice/pipeline.sqlite --version "$PRACTICE_VERSION" \
  --label-origin project_review --output artifacts/oasst-practice/analysis

python -m dialogue_pipeline export-reviewed \
  --db artifacts/oasst-practice/pipeline.sqlite --version "$PRACTICE_VERSION" \
  --label-origin project_review --output artifacts/oasst-practice/reviewed-export

python -m dialogue_pipeline token-budget \
  --db artifacts/oasst-practice/pipeline.sqlite --version "$PRACTICE_VERSION" \
  --output artifacts/oasst-practice/tokens \
  --budgets 512 1024 2048 4096 --output-reserve 256
```

import-oasst 要求新的输出目录，避免覆盖来源快照；复现时用新的目录或复用已经下载的 source。网络受限于 Hugging Face Xet 时，可以在下载命令前设置 `HF_HUB_DISABLE_XET=1`，通过 HTTPS 获取文件。

基础流水线仍用标准库和 SQLite；Pandas 只在分析中做对照。主题、处置、长度、规范化重复和所选类别的有效审核决策均与同一个只读 SQLite 快照核对，结果不一致时分析失败。`sql/practice.sql` 给出可检查、可修改的独立 SQL。

## 实际自动统计：2026-10-10

数据版本：`ec43aedd1c2818ef64d4151bba37d9acd38bc11f3c5790b8889dd158c12416f2`。这是当前代码和配置的运行结果；修改代码、配置后版本应改变。

- 上游 parquet 共 88,838 条消息，其中 2,124 条为中文 assistant；本适配器排除包含上游删除或负面审核标记的 191 条路径，剩 1,933 条候选路径。
- 固定抽取 1,000 条路径，涉及 370 个原始根节点。流水线保留 981 条、精确重复 5 条、隔离 14 条；保留率 981/1000，即 98.1%。这只描述本次已预筛选、已抽样的数据。
- 隔离记录触发 MESSAGE_TOO_LONG 共 15 次、DIALOGUE_TOO_LONG 共 2 次；规则可在同一行重叠，不能将 17 次规则当作 17 条隔离数据。
- 保留样本形成 366 个泄漏组，train / validation / test 分别 784 / 99 / 98 条。
- 全部原始样本平均 464.345 字符；同一批最终保留样本清洗前平均 411.1845、清洗后 411.1498 字符。整体均值变化主要与筛选和去重有关，不能说清洗把文本大幅压缩了。
- 同一批 986 条规范化候选，清洗前后精确重复冗余均为 5 条，最终保留数据为 0 条。本次没有观察到清洗新增的精确重复，不能推广到其他规则或输入。
- 原始样本 608/1000 被归为 other，说明关键词主题覆盖有限。其余为 explanation 237、writing 75、study 55、schedule 14、leisure 11；这不是人工主题真值。

Pandas 产物：`analysis.md`、`analysis.json`、`topic_comparison.csv`、`length_summary.csv`、`duplicate_comparison.csv`、`project_review_by_topic.csv`、`rejection_notes.csv`。

## Token 预算结果

使用 [Qwen2.5-0.5B-Instruct 官方 tokenizer](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct)，固定 revision `7ae557604adf67be50417f59c2c2f167def9a775` 和 transformers 4.57.6。仅下载 tokenizer 文件，不下载模型权重。使用官方 [chat template API](https://huggingface.co/docs/transformers/v4.57.1/en/chat_templating)，记录文件 SHA-256 和库版本。

下面的分母均为已通过字符长度等规则的 981 条保留样本，不包含先被隔离的长样本：

| 预算 | 推理输入超限 | 输入+256 输出预留超限 | 完整 SFT 超限 |
| --- | --- | --- | --- |
| 512 | 38/981，3.87% | 152/981，15.49% | 134/981，13.66% |
| 1024 | 6/981，0.61% | 12/981，1.22% | 21/981，2.14% |
| 2048 | 0/981，0% | 0/981，0% | 0/981，0% |
| 4096 | 0/981，0% | 0/981，0% | 0/981，0% |

推理输入包含模板和 generation marker，排除最后一条 assistant 目标回答；完整 SFT 包含回答与结束标记。预留输出是固定场景假设，不是对实际回答长度的预测。预算等于 token 数时不算超限。

512 的纯输入超限率只有 3.87%，但预留 256 输出后是 15.49%，说明输入长度合格不意味着能留下足够输出空间。超过预算的 sample_id 和具体长度在 `token_overflow.csv`；可沿 source/lineage.jsonl 回查原始树，评估是否按完整轮次减少历史或重新设计样本，不自动截断回答。

结果仅说明该 tokenizer、模板、保留样本和预算设定下的适配压力，不证明端侧设备能运行模型；没有测量内存、延迟、吞吐或模型效果。

## 样本审核结果：2026-10-11

固定抽样 50 条，阅读完整路径，判断为接受 19 条、拒绝 14 条、待确认 17 条。按原有集合导出接受数据为 train 13、validation 5、test 1，SFT 文件只包含 train。逐条判断见 [审核记录](../data/reviews/oasst1-review50.json)；按主题统计、other 子类型、疑难判断和长度规则取舍见 [样本审核与发现](review-findings.md)。

这些判断已通过 `labels-replay` 核对原始输入与内容哈希，再导入数据库并重新分析。本次复现使用安装 `.[api,dev,analysis]` 的干净环境，token-budget 直接成功；2026-10-10 的自动统计口径与此处相同，代码版本变化不影响本次的 981/5/14 处置计数。

比较主题拒绝率时列出每个主题的已审分母，结合 rejection_notes 中的样本与原因。抽样涉及 46 个泄漏组，不能当作 50 个完全独立的家族；小分母主题不支持总体质量排名。

故意制造异常的 data/samples 文件继续只用于测试，不将其异常比例混入本报告。
