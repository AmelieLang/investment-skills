"""Generate frozen public contracts and synthetic fixtures; owned code only."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALUATED_AT = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def write(path, data):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

components = [
    ("economics", "经营经济性", 25, ["Q01", "Q02", "Q03"], "Q03",
     ["常态单位经济持续负", "盈利主要依赖一次性因素", "正常经营盈利成立", "重复需求与盈利跨期成立", "不利环境仍保留经济性"]),
    ("moat", "竞争优势", 20, ["Q04", "Q05", "Q06"], "Q06",
     ["份额与定价持续被侵蚀", "易替换、主要靠价格竞争", "局部优势但可复制", "成本、转换成本或渠道优势有证据", "优势经竞争冲击仍保持"]),
    ("capital", "现金与资本效率", 25, ["Q07", "Q08", "Q09"], None,
     ["持续毁损资本", "利润难转现金、再投资回报不足", "常态资本回报覆盖成本", "再投资后现金回报稳定", "增长与每股现金回报共同兑现"]),
    ("resilience", "财务韧性", 15, ["Q10", "Q11", "Q12"], None,
     ["已出现偿付缺口", "生存依赖再融资", "基准情景可覆盖义务", "经营下行情景仍可覆盖", "严重压力下仍有资金余量"]),
    ("governance", "治理与资本配置", 15, ["Q13", "Q14", "Q15"], None,
     ["已证实严重利益冲突", "持续损害股东回报", "基本对齐、记录参差", "配置纪律和结果可追溯", "跨期配置有效且纠错明确"]),
]
write("config/anchors.v1.json", {
    "version": "quality-anchors/1.0.0", "origin": "custom analyst scoring, not native Buffett scoring",
    "application_version": "anchor-application/1.1.0",
    "selection": "Examine all bands. Positive levels 2/3/4 can be compatible and nested: choose the highest fully supported compatible level. Supported adverse conditions conflict with positive claims; unresolved material counterevidence blocks. If only adverse bands are supported, retain the more severe lower grade rather than hiding it with a milder one.",
    "history_rule": "historical_stress is observed history; hypothetical stress never substitutes for historical adversity",
    "components": [{"id": i, "label": label, "weight": weight, "requirements": req,
                    "historical_stress_requirement": history,
                    "window_requirement": {"economics":"Q03","moat":"Q06","capital":"Q09","resilience":"Q11","governance":"Q15"}[i],
                    "compatibility": {"adverse_levels":[0,1],"compatible_positive_levels":[2,3,4],
                                      "entailed_positive_levels":{"3":[2],"4":[2,3]} if i in ("economics","resilience") else {}},
                    "anchors": [{"level": level, "anchor_id": i + "." + str(level), "text": text} for level, text in enumerate(anchors)]}
                   for i, label, weight, req, history, anchors in components]})

quality_titles = ["商业模式、收入来源与重复需求", "同口径量价、成本与正常化单位经济", "跨期稳定性、不利期表现及边界",
                  "份额、定价与销量变化", "成本、转换成本、渠道优势的可核依据", "竞争压力及公司应对结果",
                  "利润到经营现金再到再投资后现金的调节", "投入资本、回报与资本成本比较依据", "再投资、回购、稀释对每股现金的影响",
                  "债务、到期结构与契约义务", "可用现金、受限资金与现金消耗", "基准及压力情景资金桥与假设",
                  "控制权、激励与关联交易", "审计、重述及重大诚信争议", "资本配置决策、结果及纠错记录"]
dcf_titles = ["基期经营利润、税与折旧", "资本开支、营运资本与现金调节", "经营预测的公开或历史锚点",
              "折现率参考依据", "长期经营及终值假设的对照依据", "现金、债务与其他索取权",
              "非经营资产归属及限制", "普通股、摊薄及经济权利分母"]
comparison_titles = ["价格、日期、币种与报价单位", "普通股与ADS对应关系", "币种桥及适用汇率", "分红、拆并股及其他证券单位变化"]
items = []
for prefix, group, titles in (("Q", "quality", quality_titles), ("V", "dcf", dcf_titles), ("C", "comparison", comparison_titles)):
    items += [{"id": f"{prefix}{n:02}", "group": group, "title": title, "weight": 1,
               "criterion": "Referenced fact evidence must be available, time/period/unit eligible and free of unresolved contradiction. Negative evidence can satisfy; an assumption alone cannot."}
              for n, title in enumerate(titles, 1)]
write("config/requirements.v1.json", {"version": "evidence-requirements/1.1.0", "declared_count": 27,
                                      "freeze": "before candidate output", "equal_weight": True, "items": items})
write("config/observation-window.v1.json", {"version":"quality-window/1.0.0",
    "default":"latest three disclosed full fiscal years plus latest interim",
    "annual_period_count":3,"full_fiscal_year_days":[360,371],
    "case_override":"explicit reason and dates frozen no later than evaluation; weights and anchors unchanged",
    "evidence":"calendar basis plus exact period evidence; a one-day receipt cannot represent multi-year coverage",
    "window_requirements":{"economics":"Q03","moat":"Q06","capital":"Q09","resilience":"Q11","governance":"Q15"}})

def obj(props, required=None, additional=False):
    return {"type": "object", "properties": props, "required": list(props) if required is None else required,
            "additionalProperties": additional}
def arr(item, minimum=0, maximum=1000):
    return {"type": "array", "items": item, "minItems": minimum, "maxItems": maximum}
def ref(name):
    return {"$ref": "#/$defs/" + name}
S = {"type": "string", "maxLength": 30000}
ID = {"type": "string", "pattern": "[A-Za-z0-9_.-]+", "maxLength": 150}
N = {"type": ["number", "null"]}
TIME = {"type": "string", "format": "date-time"}
NULLTIME = {"type": ["string", "null"], "format": "date-time"}
DATE = {"type": "string", "format": "date"}
CURRENCY = {"type": "string", "pattern": "[A-Z]{3}"}
IDS = arr(ID)
observed_period = obj({"start":DATE,"end":DATE,"frequency":{"enum":["annual","interim","quarterly","instant"]}})
nullable_period = {**observed_period,"type":["object","null"]}
financial_definition = {"type":["string","null"],"enum":[None,"operating_ebit","effective_cash_tax_rate","noncash_da","capital_expenditure","change_in_operating_nwc","discount_rate","terminal_growth"]}
value_ref = obj({"fact_id": ID, "assumption_id": ID}, [], False)
source = obj({"id": ID, "uri": S, "locator": S, "visibility": {"enum": ["public", "synthetic"]},
              "available": {"type": "boolean"}, "published_date": {"type": ["string", "null"], "format": "date"}})
fact = obj({"id": ID, "metric": S, "kind": {"enum": ["actual", "guidance", "estimate"]},
            "value": {"type": ["number", "string", "null"]}, "unit": S,
            "currency": {"type": ["string", "null"], "pattern": "[A-Z]{3}"},
            "period": obj({"start": {"type": ["string", "null"], "format": "date"}, "end": DATE,"frequency":{"enum":["multi_year","annual","interim","quarterly","instant"]}}),
            "periods_observed":arr(observed_period),"financial_definition":financial_definition,"observed_at": TIME,
            "published_at": NULLTIME, "vintage_at": NULLTIME,
            "evidence_kind": {"enum": ["reported", "historical", "historical_stress", "hypothetical", "calculation"]},
            "source": ref("source")})
assumption = obj({"id": ID, "value": N, "unit": S, "currency": {"type": ["string", "null"], "pattern": "[A-Z]{3}"},
                  "scenario": S, "author": S, "rationale": S, "supporting_fact_ids": IDS,
                  "period":nullable_period,"assumption_type":{"enum":["forecast","carry_forward","parameter"]},"financial_definition":financial_definition})
anchor = obj({"level": {"type": "integer", "minimum": 0, "maximum": 4},
              "status": {"enum": ["supported", "refuted", "unknown", "contradicted"]},
              "evidence_ids": IDS, "counter_evidence_ids": IDS, "rationale": S})
judgment = obj({"id": ID, "judge": S, "anchor_reviews": arr(ref("anchor"), 5, 5)})
contradiction = obj({"id": ID, "fact_ids": IDS, "requirement_ids": IDS, "status": {"enum": ["unresolved", "resolved"]},
                     "reason": S, "resolution_reason": S, "resolution_fact_ids": IDS})
hard = obj({"code": {"enum": ["PAYMENT_DEFAULT", "UNFUNDED_OBLIGATIONS", "FINANCIAL_INTEGRITY", "MINORITY_RIGHTS_ABUSE", "CORE_OPERATING_RIGHT_LOSS"]},
            "status": {"enum": ["confirmed", "suspected", "resolved"]}, "evidence_ids": IDS,
            "affected_fact_ids": IDS, "rationale": S, "resolution_condition": S})
falsifier = obj({"id": ID, "metric": S, "operator": {"enum": ["lt", "le", "gt", "ge", "eq", "observed_event"]},
                 "threshold": {"type": ["number", "string", "null"]}, "unit": S, "period": S,
                 "impact": S, "status": {"enum": ["pending", "triggered", "not_triggered"]}})
forecast = obj({"cashflow_date": DATE,"period":observed_period, **{k: ref("value_ref") for k in ("ebit_ref", "tax_ref", "da_ref", "capex_ref", "nwc_change_ref")}})
scenario = obj({"name": {"enum": ["bear", "base", "bull"]}, "forecast": arr(ref("forecast"), 0, 30),
                "wacc_ref": ref("value_ref"), "terminal_growth_ref": ref("value_ref")})
bridge = obj({"id": ID, "role": {"enum": ["cash", "non_operating_assets", "gross_debt", "lease_liabilities", "preferred", "noncontrolling_interest", "other_claims"]},
              "amount_ref": ref("value_ref"), "included_in": {"type": ["string", "null"]}})
security = obj({"listing_id": S, "quote_currency": CURRENCY, "quote_unit": {"enum": ["ADS", "ordinary"]},
                "ordinary_shares_ref": ref("value_ref"), "ordinary_per_quote_unit_ref": ref("value_ref")})
valuation = obj({"currency": CURRENCY, "scenarios": arr(ref("scenario"), 3, 3), "bridge": arr(ref("bridge"), 0, 7),
                 "price_ref": ref("value_ref"), "fx_ref": ref("value_ref")})
window_declaration = obj({"policy_id":{"const":"latest_three_fiscal_years_plus_latest_interim/v1"},
    "mode":{"enum":["default","case_specific"]},"frozen_at":TIME,"override_reason":S,
    "fiscal_years":arr(observed_period,0,3),"latest_interim":nullable_period,"calendar_basis_fact_ids":IDS})
window_declaration["properties"]["latest_interim"]={**nullable_period,"properties":{**nullable_period["properties"],"frequency":{"enum":["interim","quarterly"]}}}
native_output = obj({"status":S,"intent":S,"reason":S,"raw_text":S},[],{})
schema = obj({"schema_version": {"const": "offline-alpha-dawn/v1.1"}, "case_id": ID,
              "bot_id": {"const": "alpha-dawn-framework"}, "operation": {"enum": ["validate", "compute"]},
              "cutoff_at": TIME, "valuation_date": DATE, "evaluated_at": TIME,
              "facts": arr(ref("fact")), "assumptions": arr(ref("assumption")),"quality_window":window_declaration,
              "requirement_evidence": {"type": "object", "additionalProperties": IDS},
              "quality_assessments": arr(ref("judgment"), 0, 5), "contradictions": arr(ref("contradiction")),
              "hard_risks": arr(ref("hard")), "falsifiers": arr(ref("falsifier")),
              "security": ref("security"), "valuation": ref("valuation"),
              "native_output":native_output, "notes": arr(S)})
schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:offline-alpha-dawn:request:v1",
               "$defs": {"source": source, "fact": fact, "assumption": assumption, "value_ref": value_ref,
                         "anchor": anchor, "judgment": judgment, "contradiction": contradiction, "hard": hard,
                         "falsifier": falsifier, "forecast": forecast, "scenario": scenario,
                         "bridge": bridge, "security": security, "valuation": valuation}})
write("schema/request.v1.json", schema)
write("schema/result.v1.json", {"$schema": "https://json-schema.org/draft/2020-12/schema",
                                "type": "object", "required": ["schema_version", "result_id", "native_output", "quality", "valuation", "evidence_coverage", "uncertainty"],
                                "properties": {"schema_version": {"const": "offline-alpha-dawn/v1"}, "result_id": {"type": "string", "pattern": "[0-9a-f]{64}"},
                                               **{key: {"type": "object"} for key in ("native_output", "quality", "valuation", "evidence_coverage", "uncertainty")}}})
result_defs = dict(schema["$defs"])
nullable_string = {"type": ["string", "null"]}
integer = {"type": "integer", "minimum": 0}
result_defs["component_result"] = obj({"id": ID, "label": S, "weight": integer, "requirements": IDS,
    "window_requirement":ID,"compatibility":obj({"adverse_levels":arr(integer),"compatible_positive_levels":arr(integer),"entailed_positive_levels":{"type":"object","additionalProperties":arr(integer)}}),
    "historical_stress_requirement": nullable_string, "anchors": arr(obj({"level": integer, "anchor_id": S, "text": S}),5,5),
    "score": {"type":["integer","null"],"minimum":0,"maximum":4}, "reason": nullable_string,
    "anchor_reviews": arr(ref("anchor"),0,5), "judge": nullable_string, "judgment_type":{"const":"analyst_or_model_judgment"}})
result_defs["flag_result"] = obj({**hard["properties"], "verified_for_adapter":{"type":"boolean"}})
result_defs["requirement_result"] = obj({"id":ID,"group":{"enum":["quality","dcf","comparison"]},"title":S,
    "weight":{"const":1},"criterion":S,"evidence_ids":IDS,"satisfied":{"type":"boolean"},"failure_reason":nullable_string,
    "window_status":{"enum":["met","unmet","not_required"]},"window_missing_periods":arr(observed_period)})
window_result = obj({"declaration":window_declaration,"status":{"enum":["met","unmet"]},"reasons":arr(S),
    "components":arr(obj({"component_id":ID,"requirement_id":ID,"status":{"enum":["met","unmet"]},"missing_periods":arr(observed_period),"evidence_ids":IDS}),5,5)})
quality_result = obj({"origin":{"const":"custom_analysis_not_native_buffett"},"rubric_version":S,
    "application_version":S,"observation_window":window_result,
    "components":arr(ref("component_result"),5,5),"aggregation":S,"total":N,"arithmetic_total":N,
    "observed_contribution":{"type":"number","minimum":0,"maximum":100},"observed_weight":{"type":"number","minimum":0,"maximum":100},
    "possible_range":arr({"type":"number","minimum":0,"maximum":100},2,2),"status":{"enum":["complete","partial","blocked_by_hard_risk"]},
    "hard_risks":arr(ref("flag_result"))})
scenario_result = obj({"name":{"enum":["bear","base","bull"]},"currency":CURRENCY,
    "comparison_status":{"enum":["computed","not_computable","nonpositive_domain"]},
    **{key:N for key in ("ev","equity","ordinary_value","quote_value_model_currency","quote_value","upside_vs_price","margin_to_model_value")},
    "fcff":arr(obj({"date":DATE,"year_fraction_ACT_365F":{"type":"number"},"fcff":{"type":"number"},"present_value":{"type":"number"},"input_refs":ref("forecast")})),
    "bridge":arr(obj({**bridge["properties"],"amount":{"type":"number"},"applied_signed_amount":{"type":"number"}})),
    "diagnostics":arr(obj({"stage":S,"code":S,"detail":S})),
    **{key:{"type":"number"} for key in ("terminal_value","wacc","terminal_growth","net_cash","price")},
    "formula":S,"fx_basis":{}},
    ["name","currency","comparison_status","ev","equity","ordinary_value","quote_value_model_currency","quote_value","upside_vs_price","margin_to_model_value","fcff","bridge","diagnostics"])
count = obj({"satisfied":integer,"declared":integer})
result_schema = obj({"schema_version":{"const":"offline-alpha-dawn/v1.1"},"case_id":ID,"bot_id":{"const":"alpha-dawn-framework"},
    "result_id":{"type":"string","pattern":"[0-9a-f]{64}"},"input_hash":{"type":"string","pattern":"[0-9a-f]{64}"},
    "cutoff_at":TIME,"evaluated_at":TIME,"valuation_date":DATE,"security":ref("security"),"method_manifest":{"type":"object"},
    "native_output":native_output,"native_output_hash":{"type":"string","pattern":"[0-9a-f]{64}"},"native_execution":{"const":"not_executed_by_adapter"},
    "quality":quality_result,
    "valuation":obj({"origin":S,"model":{"const":"fcff_dcf_v1"},"currency":CURRENCY,"scenarios":arr(scenario_result,3,3),
                      "recommendation":{"type":"null"},"native_abstention_preserved":{"const":True},"interpretation":S}),
    "evidence_coverage":obj({"name":S,"satisfied":integer,"declared":{"const":27},"ratio":{"type":"number","minimum":0,"maximum":1},
                             "requirements":arr(ref("requirement_result"),27,27),
                             "document_availability":obj({"available":integer,"declared_fact_sources":integer}),
                             "modules":obj({"quality":count,"dcf":count,"comparison":count})}),
    "uncertainty":obj({"unresolved_contradictions":arr(ref("contradiction")),"ineligible_facts":arr(obj({"id":ID,"reasons":arr(S)})),
                       "assumptions":arr(ref("assumption")),"falsifiers":arr(ref("falsifier")),"hard_risks":arr(ref("flag_result")),"notes":arr(S)}),
    "evidence_receipt":arr(ref("fact")),"capabilities":obj({k:{"const":False} for k in ("network","send","trade","execute_source_text")}),
    "operation_status":{"enum":["validated","computed"]}},
    ["schema_version","case_id","bot_id","result_id","input_hash","cutoff_at","evaluated_at","valuation_date","security","method_manifest","native_output","native_output_hash","native_execution","quality","valuation","evidence_coverage","uncertainty","evidence_receipt","capabilities"])
result_schema["properties"]["method_manifest"] = obj({
    "repository":{"const":"https://github.com/finterm-ai/investment-skills"},
    "commit":{"const":"7235d3411601036cc79137fa0aec0d587f2c8e19"},
    "framework_path":{"const":"skills/buffett-investment-framework/"},
    "license":obj({"spdx":{"const":"MIT"},"copyright":S,"status":{"const":"verified"},"verified_date":DATE}),
    "files":arr(obj({"path":S,"git_blob_sha":{"type":"string","pattern":"[0-9a-f]{40}"},"sha256":{"type":"string","pattern":"[0-9a-f]{64}"},"bytes":integer}),13,13),
    "native_boundary":S,"optional_macro":obj({"repository":S,"commit":{"type":"string","pattern":"[0-9a-f]{40}"},"enabled":{"const":False},"attribution":S})})
result_schema.update({"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"urn:offline-alpha-dawn:result:v1","$defs":result_defs})
write("schema/result.v1.json",result_schema)
upstream_files = json.loads((ROOT / "upstream-files.json").read_text(encoding="utf-8-sig"))
write("method-manifest.json", {"repository": "https://github.com/finterm-ai/investment-skills",
                               "commit": "7235d3411601036cc79137fa0aec0d587f2c8e19",
                               "framework_path": "skills/buffett-investment-framework/",
                               "license": {"spdx": "MIT", "copyright": "Copyright (c) 2026 finterm.ai", "status": "verified", "verified_date": "2026-10-12"},
                               "files": upstream_files, "native_boundary": "financial-analysis is not a composite stock score, trading action or forced valuation",
                               "optional_macro": {"repository": "https://github.com/AmelieLang/Macro-analysis", "commit": "926d035f4afa52a0ac05c1d65579455ccd22e7ee",
                                                  "enabled": False, "attribution": "Macro-analysis project rubric; numeric thresholds are not attributed to Dalio himself"}})

def fact_value(identifier, value, unit="text", currency=None, metric=None, kind="actual", evidence_kind="historical"):
    return {"id": identifier, "metric": metric or identifier, "kind": kind, "value": value,
            "unit": unit, "currency": currency, "period": {"start": "2023-01-01", "end": "2026-09-30","frequency":"multi_year"},
            "periods_observed":[],"financial_definition":None,
            "observed_at": "2026-10-12T12:00:00Z", "published_at": "2026-10-12T12:00:00Z",
            "vintage_at": "2026-10-12T12:00:00Z", "evidence_kind": evidence_kind,
            "source": {"id": "synth." + identifier, "uri": "synthetic:" + identifier,
                       "locator": "Synthetic test fixture, not a real issuer claim", "visibility": "synthetic", "available": True, "published_date": "2026-10-12"}}
facts = [fact_value("e." + r["id"], "Synthetic evidence for " + r["title"], evidence_kind="hypothetical" if r["id"] == "Q12" else "historical") for r in items]
annual_periods=[{"start":f"{y}-01-01","end":f"{y}-12-31","frequency":"annual"} for y in (2023,2024,2025)]
interim_period={"start":"2026-01-01","end":"2026-09-30","frequency":"interim"}
for f in facts:
    if f["id"].startswith("e.Q") and f["id"] != "e.Q12":
        f["periods_observed"] = annual_periods+[interim_period]
facts[0]["value"]="Synthetic: paid repeat demand across FY2023-FY2025 and latest interim; no one-off subsidy dependence."
facts[1]["value"]="Synthetic: normalized operating profitability is positive, with repeat profitable units. Economics positive anchors 2 and 3 both hold."
facts[2]["value"]="Synthetic: three annual periods and latest interim confirm repeated profitability; no observed adverse historical period is supplied."
facts += [fact_value("shares", 100000000, "ordinary_shares"), fact_value("ratio", 8, "ordinary_per_quote_unit"),
          fact_value("price", 8, "currency_per_quote_unit", "USD", "price_ADS"),
          fact_value("fx", 1/7.2, "USD_per_CNY", None, "fx_spot")]
roles = ("cash", "non_operating_assets", "gross_debt", "lease_liabilities", "preferred", "noncontrolling_interest", "other_claims")
facts += [fact_value("claim." + role, 100 if role == "cash" else 200 if role == "gross_debt" else 0,
                     "million_currency", "CNY") for role in roles]
for f in facts:
    if f["id"] in ("shares","ratio","price","fx") or f["id"].startswith("claim."):
        f["period"]={"start":"2026-10-12","end":"2026-10-12","frequency":"instant"}
assumptions, scenarios = [], []
for name, ebit in (("bear", 90), ("base", 110), ("bull", 130)):
    target_period={"start":"2026-10-13","end":"2027-10-12","frequency":"annual"}
    def a(suffix, value, unit="million_currency", currency="CNY"):
        identifier = name + "." + suffix
        assumptions.append({"id": identifier, "value": value, "unit": unit, "currency": currency,
                            "scenario": name, "author": "synthetic fixture", "rationale": "Explicit synthetic future-period assumption; not historical fact", "supporting_fact_ids": ["e.V03"],
                            "period":target_period if suffix not in ("wacc","g") else None,
                            "assumption_type":"forecast" if suffix not in ("wacc","g") else "parameter",
                            "financial_definition":{"ebit":"operating_ebit","tax":"effective_cash_tax_rate","da":"noncash_da","capex":"capital_expenditure","nwc":"change_in_operating_nwc","wacc":"discount_rate","g":"terminal_growth"}[suffix]})
        return {"assumption_id": identifier}
    forecast = {"cashflow_date": "2027-10-12","period":target_period, "ebit_ref": a("ebit", ebit), "tax_ref": a("tax", .2, "fraction", None),
                "da_ref": a("da", 10), "capex_ref": a("capex", 15), "nwc_change_ref": a("nwc", 5)}
    scenarios.append({"name": name, "forecast": [forecast], "wacc_ref": a("wacc", .1, "annual_fraction", None),
                      "terminal_growth_ref": a("g", .02, "annual_fraction", None)})
sample = {"schema_version": "offline-alpha-dawn/v1.1", "operation": "compute", "case_id": "synthetic-complete",
          "bot_id": "alpha-dawn-framework", "cutoff_at": "2026-10-12T12:00:00Z", "valuation_date": "2026-10-12", "evaluated_at": EVALUATED_AT,
          "facts": facts, "assumptions": assumptions, "requirement_evidence": {r["id"]: ["e."+r["id"]] for r in items},
          "quality_window":{"policy_id":"latest_three_fiscal_years_plus_latest_interim/v1","mode":"default","frozen_at":EVALUATED_AT,
                            "override_reason":"","fiscal_years":annual_periods,"latest_interim":interim_period,"calendar_basis_fact_ids":["e.Q03"]},
          "quality_assessments": [{"id": i, "judge": "synthetic analyst fixture, not a native framework score",
                                   "anchor_reviews": [{"level": level, "status": "supported" if level in (2,3) else "refuted" if level < 2 else "unknown",
                                                       "evidence_ids": ["e."+r for r in req] if level <= 3 else [], "counter_evidence_ids": [],
                                                       "rationale": "Synthetic band assessment: no real-company judgment"} for level in range(5)]}
                                  for i, _, _, req, _, _ in components],
          "contradictions": [], "hard_risks": [], "falsifiers": [{"id": "f1", "metric": "cash_shortfall", "operator": "gt", "threshold": 0,
                                                                     "unit": "currency", "period": "next 12 months", "impact": "revisit resilience analysis", "status": "pending"}],
          "security": {"listing_id": "SYNTH-ADS", "quote_currency": "USD", "quote_unit": "ADS",
                       "ordinary_shares_ref": {"fact_id": "shares"}, "ordinary_per_quote_unit_ref": {"fact_id": "ratio"}},
          "valuation": {"currency": "CNY", "scenarios": scenarios,
                        "bridge": [{"id": role, "role": role, "amount_ref": {"fact_id": "claim."+role}, "included_in": None} for role in roles],
                        "price_ref": {"fact_id": "price"}, "fx_ref": {"fact_id": "fx"}},
          "native_output": {"status": "abstain", "intent": "financial-analysis", "reason": "Synthetic preservation fixture; upstream was not executed and no native recommendation is asserted."},
          "notes": ["All complete-case inputs and judgments are synthetic.", "27/27 means evidence declarations are complete in this fixture, not accuracy or confidence."]}
write("examples/synthetic-complete.input.json", sample)
history = json.loads(json.dumps(sample))
history.update(case_id="apple-fy2023-public-gaps", cutoff_at="2023-11-03T23:59:59Z", valuation_date="2023-11-03", evaluated_at=EVALUATED_AT,
               facts=[], assumptions=[], requirement_evidence={}, quality_assessments=[],
               notes=["Partial historical public evidence receipt; not a complete Apple analysis or backtest.", "Publication calendar date is known; exact timestamp and revision timestamp are deliberately not fabricated."])
public = fact_value("apple.q4.revenue", 89500, "million_currency", "USD", "quarterly_revenue")
public.update(period={"start": "2023-07-02", "end": "2023-09-30","frequency":"quarterly"}, observed_at="2023-11-03T23:59:59Z", published_at=None, vintage_at=None,
              evidence_kind="reported", source={"id": "apple.newsroom.20231102", "uri": "https://www.apple.com/newsroom/2023/11/apple-reports-fourth-quarter-results/",
                                                 "locator": "2023-11-02 press release: September quarter revenue $89.5 billion; period start not asserted by this limited source",
                                                 "visibility": "public", "available": True, "published_date": "2023-11-02"})
public["period"]["start"] = None
history["facts"] = [public]
history["quality_window"].update(fiscal_years=[],latest_interim=None,calendar_basis_fact_ids=[])
history["native_output"] = {"status": "not_run", "intent": "financial-analysis", "reason": "Only one public revenue observation supplied; exact filings, cash/claims, governance, moat, shares, price and valuation inputs remain absent."}
history["security"] = {"listing_id": "NASDAQ:AAPL", "quote_currency": "USD", "quote_unit": "ordinary",
                       "ordinary_shares_ref": {"fact_id": "missing.shares"}, "ordinary_per_quote_unit_ref": {"fact_id": "missing.ordinary_ratio"}}
history["valuation"]["currency"] = "USD"
history["valuation"]["price_ref"] = {"fact_id": "missing.price"}
history["valuation"]["fx_ref"] = {"fact_id": "missing.fx"}
history["valuation"]["bridge"] = []
for scenario in history["valuation"]["scenarios"]:
    scenario["forecast"] = []
write("examples/apple-fy2023-public-gaps.input.json", history)
hard_sample=json.loads(json.dumps(sample))
hard_sample["case_id"]="synthetic-hard-risk"
hard_sample["hard_risks"]=[{"code":"PAYMENT_DEFAULT","status":"confirmed","evidence_ids":["e.Q10"],"affected_fact_ids":[],
    "rationale":"Synthetic: immediately due obligation exceeds available cash; no refinancing is assumed.","resolution_condition":"Verified cure and revised obligation ledger"}]
next(f for f in hard_sample["facts"] if f["id"]=="e.Q10")["value"]="Synthetic: 200 million CNY due immediately, 100 million CNY available; payment default declared."
for a in next(q for q in hard_sample["quality_assessments"] if q["id"]=="resilience")["anchor_reviews"]:
    a["status"]="supported" if a["level"]==0 else "refuted"
    a["evidence_ids"]=["e.Q10","e.Q11","e.Q12"]
hard_sample["notes"]=["Synthetic material hard-risk view; no real issuer default claim. Main quality total must be null."]
write("examples/synthetic-hard-risk.input.json",hard_sample)
print("R1 contracts and three public/synthetic fixtures generated.")

