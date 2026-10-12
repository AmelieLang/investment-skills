# T3 第1轮集中修正

首轮ZIP SHA-256：914305985cf734d68672bfeae0b1f698b1183eb2bbcde374cfb023612f24eceb。首轮本地目录/ZIP保留，Library使用同一身份的新版本。

| 审查项 | 修正与证据 |
|---|---|
| R1-01 | 锚点文字及权重不改；正面锚点可相容嵌套，选最高支持档。不利冲突/重大未解决反证阻断。仅经营经济性4、竞争优势4要求历史逆境；资本效率4、治理4无额外压力门槛。回归覆盖2+3相容、负面冲突、真实历史/假设区分及两项4档的正确边界。 |
| R1-02 | P/V非正时保留带符号模型算术，两个比较比率null且有NONPOSITIVE_COMPARISON_DOMAIN。回归覆盖零/负值及前端伪造比率。 |
| R1-03 | 预测流量绑定未来年度period和明确财务定义。历史actual不能直接充作预测；允许显式forecast/carry_forward或期间匹配的guidance。默认观察窗与override预声明，质量证据按精确期间检查；缺期或单日数据不假装完整。 |
| R1-04 | render/cache前执行嵌套Result schema，检查冻结需求ID/分组与计数；由两个硬风险数组交叉核对派生状态/总分，并检查比较域。回归覆盖两个原审查探针、缺失/畸形nested记录、非正模型值比率。不是输入真实性认证。 |
| R1-05 | qa/visual内实际PNG展示1440px完整、600px公共缺口、1440px严重风险。qa/visual-qa.json记录对应最终HTML哈希和图片哈希。只显示公开/合成仪表盘，不含其他桌面内容。 |
| R1-06 | HANDOFF_ISOLATION_PROPOSAL.md与typed schema描述本bot信封、独立工作/state namespace、来源allowlist、拒绝共享可变状态及执行载荷。同事名字和角色不指定；没有部署或测试live隔离/三bot编排。 |

`CHANGES.patch`为完整新增diff（含PNG的Git binary patch）；`R1_CHANGES.patch`为相对首轮目录的集中差异。哈希在MANIFEST.sha256.json。原生输出、13个MIT上游文件和原T2结果未改写或重新执行。
