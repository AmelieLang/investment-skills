# Alpha Dawn 离线研究适配候选包

本包只服务 `alpha-dawn-framework`。这是T3第2轮修正，契约版本v1.1。年度预测首期从估值日次日开始，后续期间从上一期间结束的次日开始；重叠、间隔及首期遗漏会阻断EV。原生方法输出、新增质量评分、条件DCF、证据覆盖和不确定性分别保留；没有买卖总分、发送通道或交易能力。两份已提交候选字节另存未修改，此包尚未部署或验证投资收益。

## 本地使用

使用 Python 3.11+ 和标准库，无需安装依赖、配置模型API或联网。

```text
python adapter.py examples/synthetic-complete.input.json --output result.json
python adapter.py examples/apple-fy2023-public-gaps.input.json --output historical-result.json
```

双击 `dashboard.html` 即可查看完整合成示例和公共历史缺口，或导入适配器的结果JSON。文件包含样例、样式和脚本，独立离线打开；来源URI显示为文字，不自动访问。

```text
python -m unittest discover -s tests -v
node tests/dashboard_security.cjs
```

`adapter.py` 接收 `validate` 或 `compute`；其他操作（包括 send/trade）立即返回 `OPERATION_NOT_ALLOWED` 和退出码2。validate会验证并进行同一套纯计算预检，不能触发外部动作。结果ID按完整输入的规范JSON哈希确定，重复结果不累计；同ID不同内容的仪表盘导入被拒绝。

## 规则与边界

- `config/anchors.v1.json` 保留25个锚点、25/20/25/15/15权重。档位和证据充分性属于分析者判断；聚合才是确定性的。相容正面锚点可同时成立并选择最高支持档；真正的不利冲突、未排除的重大低档问题或反证使分项为null。仅经营经济性4、竞争优势4需要历史逆境；现金与资本效率4、治理4不增加历史压力门槛。财务韧性的前瞻压力明确标为假设。
- `config/observation-window.v1.json`及请求的quality_window预声明最近三个已披露完整财年及最新中期，或明确理由的case-specific覆盖范围；必须在评估前冻结。相应要求检查精确期间证据，缺失窗口不能形成完整质量判断。声明和未满足期间在结果中单列。
- `config/requirements.v1.json` 固定27项等权需求。缺失、时间不合格或未解决矛盾不能算满足；文档可获取率另列。已观察贡献和可能区间不重新归一化。
- 严重风险优先显示，主展示总分被阻断；分项和纯算术值只用于审计。原生弃权不能由新增分数覆盖。
- 事实必须声明期间、单位、来源、发布时间及版本日期。精确时间或季度起点未知时使用null并停止相关分支，不能把检索日期当作发布时间。
- 缺价格只影响相对价格比较；缺FX只影响跨币种结果；缺股数仍保留EV/股权桥；缺ADS比例仍保留普通股模型值。
- FCFF=EBIT×(1−税率)+D&A−Capex−Δ营运资本。使用ACT/365F、显式WACC和终值增长。税率[0,1]；DCF WACC>0、g>-1、WACC>g。观测利率可负，与DCF参数域不同。
- 币种金额可用currency或million_currency，内部转换为模型币种基本单位。普通股分母是ordinary_shares；一ADS对应普通股数使用ordinary_per_quote_unit。便利换算汇率不能用于即期换算。
- EV→股权七类索取权必须全部列出；有证据的零有效，未知不视作零。`included_in`明确已包含的索取权，只计一次。保留负现金流、净现金和负股权桥；负模型值不成为可交易目标价。
- 每年预测必须声明未来年度period及现金流日期。EBIT、税、D&A、Capex、ΔNWC的定义及目标期间必须对应；季度或陈旧actual不能直接冒充年度预测。历史actual只能经明确标记的forecast/carry_forward假设作为锚点；已发布guidance/estimate必须匹配真实目标期间。引用不合格事实的假设不能绕过时间门槛。
- 当P或V非正，保留带符号现金流、EV、股权与单位算术，但两个比较比率均为null，并显示困境/非正域诊断，不解读成可交易价格。

## 示例的含义

完整例为虚构企业和虚构分析者判断，不对应现实股票。公共例仅录入Apple于2023-11-02发布的2023财年第四季度公告中的营收观察（89.5十亿美元）；精确发布时间、数据版本时间和季度起点未从该有限材料补造。原生框架未运行、质量及DCF均有明确缺口。这不是完整Apple研究或历史收益回测。

公共来源：https://www.apple.com/newsroom/2023/11/apple-reports-fourth-quarter-results/

## 方法、许可与适配映射

原生底层固定为 `finterm-ai/investment-skills`，commit `7235d3411601036cc79137fa0aec0d587f2c8e19`，路径 `skills/buffett-investment-framework/`，MIT，Copyright (c) 2026 finterm.ai。`method-manifest.json`记录每个固定上游文件的Git blob及SHA-256。`vendor/`是未修改的只读审查资料；适配器和测试不导入、不运行其脚本。

原生financial-analysis是证据受限的财务分析，不提供综合股票评分、交易动作或强制估值。`native_output`原样深复制并单独哈希；样例中的abstain/not_run只是明确标记的契约夹具，不冒充运行结果。

详见 `SOURCE_MAP.md`。Macro-analysis只作为未启用的可选宏观署名记录；项目阈值不归因于Dalio本人。包不含私人电子书内容、名称、路径或现有项目资料。R1另附实际合成/公共仪表盘PNG用于私有验收；它们不包含无关桌面内容。

未来同事bot交接只提出 `HANDOFF_ISOLATION_PROPOSAL.md` 与 `schema/handoff.proposal.v1.json`。同事名称与角色未指定；没有实现三bot编排或live权限隔离，也没有修改已有配置。`skills.include`不是访问边界。

## 重建候选文件

以下均为本包自行编写的脚本，不执行上游代码：

```text
python scripts/build_contract.py
python adapter.py examples/synthetic-complete.input.json --output examples/synthetic-complete.result.json
python adapter.py examples/apple-fy2023-public-gaps.input.json --output examples/apple-fy2023-public-gaps.result.json
python adapter.py examples/synthetic-hard-risk.input.json --output examples/synthetic-hard-risk.result.json
python scripts/build_dashboard.py
```

Request及Result schema使用JSON Schema 2020-12的明确子集；标准库验证器支持type/const/enum/required/properties/additionalProperties/items/长度/模式/范围/日期/内部ref，并另外执行时间、引用、期间、矛盾和数学域校验。仪表盘在render/cache前验证完整嵌套结果schema，并检查冻结需求ID/分组、计数、硬风险优先、比较域及聚合一致性。这是离线结构与语义一致性校验，不是输入真实性认证。重建示例会记录UTC评估时间；同一个完整输入的计算仍确定。
