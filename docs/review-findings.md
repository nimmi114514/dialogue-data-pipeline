# 样本审核与发现

## 范围和结果

2026-10-11，检查 OASST1 中文抽样中自动保留的 50 条完整对话路径，包括所有 assistant 回合，不只看末条回答。按 `sha256(42:sample_id)` 排序取前 50 条；来自 46 个泄漏组，不是 50 个完全独立的对话家族。

输入 SHA-256：`002de4c55cc84e6890b7fd8fc538ca2f52e73a92de607eacb0a5b96b898710ec`。本次处理版本：`037b686bba7c051c15b8690e45292d68206d95f4463a7a23f60f660b45bc9c95`。源码变化会改变处理版本，复现时从自己的 summary 读取版本；判断只有在输入哈希、样本 ID 和内容哈希均匹配时才能重新绑定。

| 判断 | 条数 | 占已审 50 条 |
| --- | ---: | ---: |
| accept | 19 | 38% |
| reject | 14 | 28% |
| unsure | 17 | 34% |

覆盖 50/981（5.10%）保留样本。按原有切分导出接受记录：train 13、validation 5、test 1；`sft_train.jsonl` 只有 13 条训练记录，没有混入验证或测试集。

按自动弱主题统计，Pandas 与同一 SQLite 快照的 SQL 聚合一致：

| 主题 | 保留数 | 已审数 | 接受 | 拒绝 | 待确认 | 已审拒绝比例 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| explanation | 233 | 13 | 2 | 4 | 7 | 4/13 |
| leisure | 11 | 0 | 0 | 0 | 0 | N/A |
| other | 600 | 29 | 12 | 7 | 10 | 7/29 |
| schedule | 14 | 1 | 1 | 0 | 0 | 0/1 |
| study | 52 | 2 | 1 | 1 | 0 | 1/2 |
| writing | 71 | 5 | 3 | 2 | 0 | 2/5 |

`study` 的比例最高，但分母只有 2，不能据此认为学习类数据最差。`writing` 的两个拒绝样本分别是用追问替代已明确要求的故事，以及代码引用未定义变量；后者也暴露了关键词主题误分。`other` 的拒绝样本包含遗漏任务要求、事实错误及错误概念解释，不能归因为单一问题。

## 自动规则漏掉了什么

以下 ID 均可在 [逐条记录](../data/reviews/oasst1-review50.json) 中查到完整判断和理由，原文可在复现后的 `review_samples.jsonl` 或 Dashboard 中查看。

- `oasst1_3bf92226-6086-44fa-a449-ba8d86113e76`：Python 循环变量为 `val`，输出表达式却引用未定义的 `x`。后续回合虽然有正确示例，完整路径仍包含错误，因此拒绝。JSON、角色和长度规则只能验证结构，不能发现代码语义问题。
- `oasst1_415117f4-e4af-453c-8fac-50f0b878e9ed`：列举雪景诗时混入不对应的作品并误归作者。前一个回合给出了正确诗句，不能抵消后续错误。判断应覆盖完整路径，不能仅抽查第一段。
- `oasst1_335e0463-6793-4432-8080-20dc1976d1a2`：将 GPT-2 论文年份写为 2018，并混淆 zero-shot 与 few-shot；[官方发布页](https://openai.com/index/better-language-models/) 的日期为 2019-02-14，论文讨论 zero-shot 任务迁移。拒绝依据是具体事实和概念错误，而不是回答长短。

技术、诗文、政策等内容的正确性需要额外检查，不宜用自动保留率 98.1% 表示回答正确率。接受标准也不是“越长越好”：问候、明确次数的复读以及缺少必要文档时请求补充上下文，可以合理接受；用户已经指定题材的开放式创作则不必先连续追问。

## other 的实际内容

原始输入有 608/1000 条 `other`，清洗去重后为 600/981。已审 29 条 `other` 的任务拆解如下；这些子类是本次阅读补充的观察，不是重新训练过的分类器标签。

| 内容 | 条数 |
| --- | ---: |
| 健康问题 | 4 |
| 政治讨论 | 3 |
| 问候 | 3 |
| 模型身份 | 2 |
| AI 概念、人物资料、计算机体系结构、饮食、历史资料、假设情境安全、信息抽取、语言地理、法律政策、文学、哲学、编程、推理、角色扮演、科学、文本转换、旅行 | 各 1，共 17 |

现有规则只看根问题的关键词，不能充分表达任务意图：编程请求会因为“写”进入 writing；阅读理解材料中的年份会触发 schedule；医疗问题可能完全落入 other。更合理的改进是增加任务意图和领域两个维度、用这些具体误分作为分类回归样例，先调整审核路由，不直接以主题作为拒绝规则。这里没有将弱标签悄悄改成真实主题。

## 暂缓接受的原因

17 条 `unsure` 不进入训练导出，也不作为已证实错误来计算拒绝率：

- 医疗解释、历史药物证据缺少可靠依据或适用范围，术语密集不能代替核查。
- 历史部署的模型身份、Windows 版本相关步骤、人物纪录和地区统计缺少对应版本、时间或来源；不能拿今天的条件直接判断当年的回答。
- “假设 1+1=3”与现实物体计数混用，问题存在解释空间；BERT 两样本示例也需要先区分低样本基线和完整元学习任务，不能把方法有限直接写成程序报错。
- `oasst1_6e47529c-71e2-4c39-9270-cb700c57e190` 含第三方转载及授权声明，因此暂缓接受；不在仓库复刻其长篇原文。上游数据卡的许可声明不应代替逐条内容的授权核查。

## 一条规则的取舍

对已审 50 条模拟“末条 assistant 回答不足 20 字则拦截”，不修改数据，也不实际启用规则：

| 影响 | 数量 |
| --- | ---: |
| 被规则标记 | 11/50 |
| 已接受样本被标记 | 7/19 |
| 已拒绝样本被标记 | 1/14 |
| 待确认样本被标记 | 3/17 |

它会命中一条答非所问的模型身份回答，但同时误伤正常问候、角色回应、按要求复读、简短饮食建议，以及多轮对话末尾的致谢回应。长代码和诗文事实错误仍然漏过。因此不直接提高统一最小长度，可将长度作为任务相关的提示信号，再结合全文判断。统计由 `scripts/review_diagnostics.py` 生成，明细保留 sample_id、字数和原判断。

## 完整复现

在仓库根目录执行。使用新目录，避免覆盖来源或已发布审核快照；已下载过 source 时可复用，不必重复下载。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[api,dev,analysis]"
python -m pip check

python -m dialogue_pipeline import-oasst \
  --output artifacts/reproduce/source --limit 1000 --seed 42

python -m dialogue_pipeline run \
  --input artifacts/reproduce/source/dialogues.jsonl --config configs/oasst1.json \
  --db artifacts/reproduce/pipeline.sqlite --output artifacts/reproduce/processed

VERSION=$(python -c 'import json; print(json.load(open("artifacts/reproduce/processed/summary.json"))["dataset_version"])')

python -m dialogue_pipeline labels-template \
  --db artifacts/reproduce/pipeline.sqlite --version "$VERSION" \
  --output artifacts/reproduce/review-50 --sample-size 50 --seed 42

python -m dialogue_pipeline labels-replay \
  --db artifacts/reproduce/pipeline.sqlite --version "$VERSION" \
  --input data/reviews/oasst1-review50.json --output artifacts/reproduce/labels.csv

python -m dialogue_pipeline labels-import \
  --db artifacts/reproduce/pipeline.sqlite --version "$VERSION" \
  --input artifacts/reproduce/labels.csv

python -m dialogue_pipeline analyze \
  --input artifacts/reproduce/source/dialogues.jsonl \
  --db artifacts/reproduce/pipeline.sqlite --version "$VERSION" \
  --label-origin project_review --output artifacts/reproduce/analysis

python scripts/review_diagnostics.py \
  --db artifacts/reproduce/pipeline.sqlite --version "$VERSION" \
  --output artifacts/reproduce/diagnostics

python -m dialogue_pipeline report \
  --db artifacts/reproduce/pipeline.sqlite --version "$VERSION" \
  --output artifacts/reproduce/report

python -m dialogue_pipeline export-reviewed \
  --db artifacts/reproduce/pipeline.sqlite --version "$VERSION" \
  --label-origin project_review --output artifacts/reproduce/export

python -m dialogue_pipeline token-budget \
  --db artifacts/reproduce/pipeline.sqlite --version "$VERSION" \
  --output artifacts/reproduce/tokens --budgets 512 1024 2048 4096 --output-reserve 256
```

报告输出 `project_review_by_topic.csv`、`rejection_notes.csv`、`review_diagnostics.json`；导出清单记录筛选条件、标签快照哈希和文件哈希。首次下载需网络；tokenizer 文件和元数据缓存完整后，可在 token-budget 命令前设置 `HF_HUB_OFFLINE=1` 离线重算。本次用未继承系统包的 Python 3.12 环境安装上述 extras，运行全量测试及真实 981 条 token 统计，未另行补装 Jinja2，也未加载模型权重。

## 在网页查看

`catalog-add` 将原始 JSONL 登记到 dashboard 数据库，启动 API 与前端后选择 OASST1 并运行：

```bash
python -m dialogue_pipeline catalog-add \
  --input artifacts/reproduce/source/dialogues.jsonl \
  --name "OpenAssistant OASST1 - Chinese 1000" --profile oasst1 --origin public
```

CLI 实践数据库和 dashboard 数据库是分开的。要使网页下载的质量报告包含这些判断，在网页运行该数据集后，使用页面的完整版本号，对 `artifacts/web/dashboard.sqlite` 再执行 `labels-replay` 和 `labels-import`；不要仅导入另一个数据库后期待网页自动同步。网页当前展示自动处置和消息明细，样本审核结果包含在下载的质量报告中。

## 限制

只描述该版本的固定抽样，不外推总体质量；弱主题、家族相关性、未解决事实与授权问题均保留。审核通过文件是可追溯的数据准备产物，不是经过训练验证的模型效果证明。普通流水线逐文件写产物，调用方须检查退出码和 summary；审核快照导出使用新目录整体发布。
