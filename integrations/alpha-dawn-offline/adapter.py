"""Offline Alpha Dawn adapter. Standard library only; no upstream code execution."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
VERSION = "offline-alpha-dawn/v1.1"
ALLOWED_OPERATIONS = {"validate", "compute"}
ROLES = {"cash": 1, "non_operating_assets": 1, "gross_debt": -1,
         "lease_liabilities": -1, "preferred": -1,
         "noncontrolling_interest": -1, "other_claims": -1}
HARD_FLAGS = {"PAYMENT_DEFAULT", "UNFUNDED_OBLIGATIONS", "FINANCIAL_INTEGRITY",
              "MINORITY_RIGHTS_ABUSE", "CORE_OPERATING_RIGHT_LOSS"}


class Rejected(ValueError):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def read_json(path):
    return strict_loads(Path(path).read_text(encoding="utf-8-sig"))


def strict_loads(text):
    if len(text.encode("utf-8")) > 2000000:
        raise Rejected("INPUT_SIZE_LIMIT", "maximum 2 MB JSON")
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise Rejected("DUPLICATE_KEY", key)
            out[key] = value
        return out
    try:
        value = json.loads(text, object_pairs_hook=pairs,
                           parse_constant=lambda x: (_ for _ in ()).throw(Rejected("NON_FINITE", x)))
    except (json.JSONDecodeError, RecursionError) as exc:
        raise Rejected("INVALID_JSON", str(exc)) from exc
    finite_tree(value)
    return value


def finite_tree(value, depth=0):
    if depth > 40:
        raise Rejected("DEPTH_LIMIT", "maximum nesting depth is 40")
    if isinstance(value, float) and not math.isfinite(value):
        raise Rejected("NON_FINITE", "all numeric inputs must be finite")
    if isinstance(value, dict):
        for v in value.values():
            finite_tree(v, depth+1)
    elif isinstance(value, list):
        for v in value:
            finite_tree(v, depth+1)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed
    except (ValueError, AttributeError) as exc:
        raise Rejected("INVALID_DATETIME", str(value)) from exc


def validate_schema(value, schema, definitions, location="$", depth=0):
    """Validate the documented JSON Schema subset used by this package."""
    if depth > 40:
        raise Rejected("DEPTH_LIMIT", location)
    if "$ref" in schema:
        return validate_schema(value, definitions[schema["$ref"].split("/")[-1]], definitions, location, depth + 1)
    kinds = schema.get("type", [])
    kinds = [kinds] if isinstance(kinds, str) else kinds
    checks = {"object": isinstance(value, dict), "array": isinstance(value, list),
              "string": isinstance(value, str), "number": isinstance(value, (int, float)) and not isinstance(value, bool),
              "integer": isinstance(value, int) and not isinstance(value, bool),
              "boolean": isinstance(value, bool), "null": value is None}
    if kinds and not any(checks[k] for k in kinds):
        raise Rejected("SCHEMA_TYPE", location)
    if "enum" in schema and value not in schema["enum"]:
        raise Rejected("SCHEMA_ENUM", location)
    if "const" in schema and value != schema["const"]:
        raise Rejected("SCHEMA_CONST", location)
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise Rejected("SCHEMA_REQUIRED", location + "." + key)
        for key, item in value.items():
            child = props.get(key, schema.get("additionalProperties", {}))
            if child is False:
                raise Rejected("SCHEMA_UNKNOWN_FIELD", location + "." + key)
            if isinstance(child, dict):
                validate_schema(item, child, definitions, location + "." + key, depth + 1)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 10000):
            raise Rejected("SCHEMA_LENGTH", location)
        for i, item in enumerate(value):
            validate_schema(item, schema.get("items", {}), definitions, f"{location}[{i}]", depth + 1)
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 100000):
            raise Rejected("SCHEMA_LENGTH", location)
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise Rejected("SCHEMA_PATTERN", location)
        if schema.get("format") == "date-time":
            timestamp(value)
        if schema.get("format") == "date":
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise Rejected("INVALID_DATE", location) from exc
    if checks["number"]:
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise Rejected("SCHEMA_RANGE", location)


def unique(items, label):
    out = {}
    for item in items:
        if item["id"] in out:
            raise Rejected("DUPLICATE_ID", label + ":" + item["id"])
        out[item["id"]] = item
    return out


def eligibility(fact, cutoff):
    reasons = []
    if fact["value"] is None or fact["value"] == "":
        reasons.append("MISSING_VALUE")
    for key in ("published_at", "vintage_at"):
        if fact[key] is None:
            reasons.append("UNKNOWN_" + key.upper())
        elif timestamp(fact[key]) > cutoff:
            reasons.append("AFTER_CUTOFF_" + key.upper())
    if fact["published_at"] and fact["vintage_at"] and timestamp(fact["vintage_at"]) < timestamp(fact["published_at"]):
        reasons.append("VINTAGE_BEFORE_PUBLICATION")
    if fact["period"]["start"] is None:
        reasons.append("UNKNOWN_PERIOD_START")
    elif date.fromisoformat(fact["period"]["start"]) > date.fromisoformat(fact["period"]["end"]):
        reasons.append("REVERSED_PERIOD")
    if fact["kind"] == "actual" and date.fromisoformat(fact["period"]["end"]) > cutoff.date():
        reasons.append("FUTURE_ACTUAL_PERIOD")
    if fact["kind"] == "actual" and fact["published_at"] and date.fromisoformat(fact["period"]["end"]) > timestamp(fact["published_at"]).date():
        reasons.append("ACTUAL_PERIOD_AFTER_PUBLICATION")
    if timestamp(fact["observed_at"]) > cutoff:
        reasons.append("FUTURE_OBSERVATION")
    if not fact["source"]["available"]:
        reasons.append("SOURCE_UNAVAILABLE")
    for observed in fact["periods_observed"]:
        if (fact["period"]["start"] is None or observed["start"] < fact["period"]["start"]
                or observed["end"] > fact["period"]["end"] or observed["start"] > observed["end"]):
            reasons.append("PERIOD_COVERAGE_OUTSIDE_REPORTED_SPAN")
            break
    if fact["source"]["visibility"] == "public":
        uri = urlsplit(fact["source"]["uri"])
        if uri.scheme != "https" or not uri.hostname or uri.username or uri.password or uri.query or uri.fragment:
            raise Rejected("PUBLIC_SOURCE_URI", fact["id"])
    return reasons


def quality_window(request, facts, eligible, config):
    """Check the predeclared window; source sufficiency remains an analyst judgment."""
    declaration = request["quality_window"]
    problems = []
    if timestamp(declaration["frozen_at"]) > timestamp(request["evaluated_at"]):
        problems.append("WINDOW_NOT_FROZEN_BEFORE_EVALUATION")
    annual = declaration["fiscal_years"]
    if declaration["mode"] == "default" and len(annual) != 3:
        problems.append("THREE_FULL_FISCAL_YEARS_NOT_DECLARED")
    if declaration["mode"] == "case_specific" and (not declaration["override_reason"].strip() or not annual):
        problems.append("UNJUSTIFIED_CASE_SPECIFIC_WINDOW")
    if declaration["latest_interim"] is None and declaration["mode"] == "default":
        problems.append("LATEST_INTERIM_NOT_DECLARED")
    if declaration["latest_interim"] is not None and declaration["latest_interim"]["frequency"] not in ("interim", "quarterly"):
        problems.append("LATEST_INTERIM_IS_NOT_AN_INTERIM_PERIOD")
    basis = declaration["calendar_basis_fact_ids"]
    if not basis or any(not eligible.get(k, False) for k in basis):
        problems.append("LATEST_DISCLOSED_CALENDAR_NOT_SUPPORTED")
    periods = annual + ([declaration["latest_interim"]] if declaration["latest_interim"] else [])
    for index, period in enumerate(annual):
        days = (date.fromisoformat(period["end"]) - date.fromisoformat(period["start"])).days + 1
        if period["frequency"] != "annual" or not 360 <= days <= 371:
            problems.append("INVALID_FULL_FISCAL_YEAR")
        if index and (date.fromisoformat(period["start"]) - date.fromisoformat(annual[index-1]["end"])).days != 1:
            problems.append("NONCONSECUTIVE_FISCAL_YEARS")
    for period in periods:
        if period["start"] > period["end"] or date.fromisoformat(period["end"]) > timestamp(request["cutoff_at"]).date():
            problems.append("WINDOW_PERIOD_AFTER_CUTOFF_OR_REVERSED")
    checks = []
    for component in config["components"]:
        requirement = component["window_requirement"]
        ids = request["requirement_evidence"].get(requirement, [])
        missing = []
        for period in periods:
            supported = any(eligible.get(k, False) and facts[k]["kind"] == "actual"
                            and facts[k]["evidence_kind"] != "hypothetical"
                            and any(all(observed[field] == period[field] for field in ("start", "end", "frequency"))
                                    for observed in facts[k]["periods_observed"]) for k in ids)
            if not supported:
                missing.append(copy.deepcopy(period))
        checks.append({"component_id": component["id"], "requirement_id": requirement,
                       "status": "unmet" if problems or missing else "met", "missing_periods": missing,
                       "evidence_ids": ids})
    return {"declaration": copy.deepcopy(declaration), "status": "unmet" if problems or any(c["status"] == "unmet" for c in checks) else "met",
            "reasons": sorted(set(problems)), "components": checks}


def process(request):
    if not isinstance(request, dict) or request.get("operation") not in ALLOWED_OPERATIONS:
        raise Rejected("OPERATION_NOT_ALLOWED", "only validate and compute are implemented; send/trade are refused")
    schema = read_json(ROOT / "schema/request.v1.json")
    validate_schema(request, schema, schema["$defs"])
    finite_tree(request)
    cutoff = timestamp(request["cutoff_at"])
    if date.fromisoformat(request["valuation_date"]) > cutoff.date():
        raise Rejected("VALUATION_AFTER_CUTOFF", request["valuation_date"])
    if timestamp(request["evaluated_at"]) < cutoff:
        raise Rejected("EVALUATION_BEFORE_CUTOFF", request["evaluated_at"])
    facts = unique(request["facts"], "facts")
    assumptions = unique(request["assumptions"], "assumptions")
    if sorted(s["name"] for s in request["valuation"]["scenarios"]) != ["base", "bear", "bull"]:
        raise Rejected("SCENARIO_SET", "exactly one bear/base/bull scenario is required")
    for assumption in assumptions.values():
        if any(k not in facts for k in assumption["supporting_fact_ids"]):
            raise Rejected("UNKNOWN_FACT", assumption["id"])
    unique(request["contradictions"], "contradictions")
    if set(facts) & set(assumptions):
        raise Rejected("DUPLICATE_ID", "fact/assumption namespace overlap")
    eligible = {k: not eligibility(v, cutoff) for k, v in facts.items()}
    reasons = {k: eligibility(v, cutoff) for k, v in facts.items()}
    requirements = read_json(ROOT / "config/requirements.v1.json")
    requirement_ids = {r["id"] for r in requirements["items"]}
    if set(request["requirement_evidence"]) - requirement_ids:
        raise Rejected("UNKNOWN_REQUIREMENT", "requirement list is frozen")
    blocked_req, blocked_facts, conflicts = set(), set(), []
    for conflict in request["contradictions"]:
        if any(k not in facts for k in conflict["fact_ids"]):
            raise Rejected("UNKNOWN_FACT", conflict["id"])
        if set(conflict["requirement_ids"]) - requirement_ids:
            raise Rejected("UNKNOWN_REQUIREMENT", conflict["id"])
        resolved = (conflict["status"] == "resolved" and bool(conflict["resolution_reason"])
                    and bool(conflict["resolution_fact_ids"])
                    and all(eligible.get(k, False) for k in conflict["resolution_fact_ids"]))
        if not resolved:
            blocked_req.update(conflict["requirement_ids"])
            blocked_facts.update(conflict["fact_ids"])
            conflicts.append(copy.deepcopy(conflict))
    flags = []
    for flag in request["hard_risks"]:
        if flag["code"] not in HARD_FLAGS or any(k not in facts for k in flag["evidence_ids"]):
            raise Rejected("INVALID_HARD_RISK", flag["code"])
        item = copy.deepcopy(flag)
        item["verified_for_adapter"] = bool(flag["evidence_ids"]) and all(eligible[k] for k in flag["evidence_ids"])
        flags.append(item)
        if flag["code"] == "FINANCIAL_INTEGRITY" and flag["status"] != "resolved":
            blocked_facts.update(flag["affected_fact_ids"])
    for k in blocked_facts:
        if k not in facts:
            raise Rejected("UNKNOWN_FACT", k)
        eligible[k] = False
        reasons[k].append("UNRESOLVED_CONFLICT_OR_INTEGRITY")
    config = read_json(ROOT / "config/anchors.v1.json")
    window = quality_window(request, facts, eligible, config)
    window_by_requirement = {c["requirement_id"]: c for c in window["components"]}
    receipt = []
    for req in requirements["items"]:
        ids = request["requirement_evidence"].get(req["id"], [])
        if any(k not in facts for k in ids):
            raise Rejected("UNKNOWN_FACT", req["id"])
        window_check = window_by_requirement.get(req["id"])
        window_status = window_check["status"] if window_check else "not_required"
        satisfied = bool(ids) and all(eligible[k] for k in ids) and req["id"] not in blocked_req and window_status != "unmet"
        receipt.append({**req, "evidence_ids": ids, "satisfied": satisfied,
                        "window_status": window_status, "window_missing_periods": window_check["missing_periods"] if window_check else [],
                        "failure_reason": None if satisfied else "missing, ineligible, contradictory, or unmet observation-window evidence"})
    receipt_by_id = {r["id"]: r for r in receipt}
    judgments = unique(request["quality_assessments"], "quality_assessments")
    if set(judgments) - {c["id"] for c in config["components"]}:
        raise Rejected("UNKNOWN_COMPONENT", "quality_assessments")
    components, contribution, missing_weight = [], 0.0, 0
    for component in config["components"]:
        judgment = judgments.get(component["id"])
        score, why = None, "MISSING_ASSESSMENT"
        reviews = []
        if judgment:
            reviews = judgment["anchor_reviews"]
            if sorted(a["level"] for a in reviews) != list(range(5)):
                raise Rejected("ANCHOR_SET", component["id"])
            for review in reviews:
                if any(k not in facts for k in review["evidence_ids"] + review["counter_evidence_ids"]):
                    raise Rejected("UNKNOWN_FACT", component["id"])
            unresolved_counter = any(a["counter_evidence_ids"] and not any(
                c["status"] == "resolved" and c["resolution_reason"] and c["resolution_fact_ids"]
                and set(a["counter_evidence_ids"]).issubset(set(c["fact_ids"]))
                and all(eligible.get(k, False) for k in c["resolution_fact_ids"])
                for c in request["contradictions"]) for a in reviews)
            by_level = {a["level"]: a for a in reviews}
            supported = [a["level"] for a in reviews if a["status"] == "supported"
                         and a["evidence_ids"] and all(eligible[k] for k in a["evidence_ids"])]
            if not all(receipt_by_id[r]["satisfied"] for r in component["requirements"]):
                why = "UNSATISFIED_COMPONENT_EVIDENCE"
            elif unresolved_counter or any(a["status"] == "contradicted" for a in reviews):
                why = "CONTRADICTORY_ANCHORS"
            elif supported:
                adverse = [n for n in supported if n in component["compatibility"]["adverse_levels"]]
                positive = [n for n in supported if n in component["compatibility"]["compatible_positive_levels"]]
                selected = max(positive) if positive else min(adverse)
                adverse_clear = all(by_level[n]["status"] == "refuted" and by_level[n]["evidence_ids"]
                                    and all(eligible[k] for k in by_level[n]["evidence_ids"])
                                    for n in component["compatibility"]["adverse_levels"]) if positive else True
                # Positive bands may coexist. A refuted entailed positive prerequisite is a real conflict.
                entailed = component["compatibility"]["entailed_positive_levels"].get(str(selected), [])
                positive_consistent = all(by_level[n]["status"] != "refuted" for n in entailed)
                stress_ok = selected != 4 or not component.get("historical_stress_requirement") or any(
                    eligible[k] and facts[k]["evidence_kind"] == "historical_stress"
                    for k in request["requirement_evidence"].get(component["historical_stress_requirement"], []))
                if adverse and positive:
                    why = "ADVERSE_POSITIVE_ANCHOR_CONFLICT"
                elif adverse_clear and positive_consistent and stress_ok:
                    score, why = selected, None
                else:
                    why = "LOWER_ANCHOR_UNRESOLVED_OR_REQUIRED_HISTORY_MISSING"
            else:
                why = "NO_SUPPORTED_ANCHOR"
        if score is None:
            missing_weight += component["weight"]
        else:
            contribution += component["weight"] * score / 4
        components.append({**component, "score": score, "reason": why, "anchor_reviews": copy.deepcopy(reviews),
                           "judge": judgment["judge"] if judgment else None,
                           "judgment_type": "analyst_or_model_judgment"})
    critical = any(f["status"] == "confirmed" and f["verified_for_adapter"] for f in flags)
    quality = {"origin": "custom_analysis_not_native_buffett", "rubric_version": config["version"],
               "observation_window": window, "application_version": config["application_version"],
               "components": components, "aggregation": "deterministic_weight_times_score_over_four",
               "total": None if missing_weight or critical else contribution,
               "arithmetic_total": None if missing_weight else contribution,
               "observed_contribution": contribution, "observed_weight": 100 - missing_weight,
               "possible_range": [contribution, contribution + missing_weight],
               "status": "blocked_by_hard_risk" if critical else "partial" if missing_weight else "complete",
               "hard_risks": flags}
    coverage = {"name": "支持性证据覆盖率（不是准确率或信心）", "satisfied": sum(r["satisfied"] for r in receipt),
                "declared": 27, "ratio": sum(r["satisfied"] for r in receipt) / 27,
                "requirements": receipt,
                "document_availability": {"available": sum(f["source"]["available"] for f in facts.values()),
                                          "declared_fact_sources": len(facts)}, "modules": {}}
    for group in ("quality", "dcf", "comparison"):
        rows = [r for r in receipt if r["group"] == group]
        coverage["modules"][group] = {"satisfied": sum(r["satisfied"] for r in rows), "declared": len(rows)}
    valuation = calculate_valuation(request, facts, assumptions, eligible)
    output = {"schema_version": VERSION, "case_id": request["case_id"], "bot_id": request["bot_id"],
              "result_id": digest(request), "input_hash": digest(request), "cutoff_at": request["cutoff_at"],
              "evaluated_at": request["evaluated_at"], "valuation_date": request["valuation_date"],
              "security": copy.deepcopy(request["security"]),
              "method_manifest": read_json(ROOT / "method-manifest.json"),
              "native_output": copy.deepcopy(request["native_output"]),
              "native_output_hash": digest(request["native_output"]), "native_execution": "not_executed_by_adapter",
              "quality": quality, "valuation": valuation, "evidence_coverage": coverage,
              "uncertainty": {"unresolved_contradictions": conflicts,
                              "ineligible_facts": [{"id": k, "reasons": v} for k, v in reasons.items() if v],
                              "assumptions": copy.deepcopy(request["assumptions"]),
                              "falsifiers": copy.deepcopy(request["falsifiers"]), "hard_risks": flags,
                              "notes": request["notes"]},
              "evidence_receipt": copy.deepcopy(request["facts"]),
              "capabilities": {"network": False, "send": False, "trade": False, "execute_source_text": False}}
    finite_tree(output)
    result_schema = read_json(ROOT / "schema/result.v1.json")
    validate_schema(output, result_schema, result_schema["$defs"])
    return output


def calculate_valuation(request, facts, assumptions, eligible):
    settings = request["valuation"]
    origin = date.fromisoformat(request["valuation_date"])
    currency = settings["currency"]

    def number(ref, unit=None, expected_currency=None, fact_only=False):
        keys = set(ref)
        if keys not in ({"fact_id"}, {"assumption_id"}):
            raise Rejected("INVALID_REFERENCE", str(ref))
        is_fact = "fact_id" in ref
        key = ref.get("fact_id", ref.get("assumption_id"))
        item = (facts if is_fact else assumptions).get(key)
        if item is None or (is_fact and not eligible[key]) or (fact_only and not is_fact):
            raise Rejected("MISSING_OR_INELIGIBLE_INPUT", key)
        if not is_fact and any(not eligible[k] for k in item["supporting_fact_ids"]):
            raise Rejected("ASSUMPTION_BASIS_INELIGIBLE", key)
        value = item["value"]
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise Rejected("NUMERIC_INPUT_REQUIRED", key)
        if unit and item["unit"] != unit:
            raise Rejected("UNIT_MISMATCH", key)
        if unit in ("fraction", "annual_fraction", "ordinary_shares", "ordinary_per_quote_unit") and item["currency"] is not None:
            raise Rejected("DIMENSIONLESS_UNIT_HAS_CURRENCY", key)
        if expected_currency is not None and item["currency"] != expected_currency:
            raise Rejected("CURRENCY_MISMATCH", key)
        return float(value), item

    def money(ref, fact_only=False):
        value, item = number(ref, expected_currency=currency, fact_only=fact_only)
        if item["unit"] not in ("currency", "million_currency"):
            raise Rejected("UNIT_MISMATCH", "currency or million_currency required")
        return value * (1000000 if item["unit"] == "million_currency" else 1)

    def forecast_item(ref, target, definition):
        _, item = number(ref)
        if item["financial_definition"] != definition:
            raise Rejected("FINANCIAL_DEFINITION_MISMATCH", definition)
        if item["period"] != target:
            raise Rejected("FORECAST_PERIOD_MISMATCH", "historical/quarterly flows require an explicit forecast or carry-forward assumption for this annual period")
        if "fact_id" in ref and item["kind"] not in ("guidance", "estimate"):
            raise Rejected("HISTORICAL_ACTUAL_NOT_FORECAST", ref["fact_id"])
        if "assumption_id" in ref and item["assumption_type"] not in ("forecast", "carry_forward"):
            raise Rejected("FORECAST_ASSUMPTION_NOT_DECLARED", ref["assumption_id"])

    bridge = settings["bridge"]
    if len({entry["id"] for entry in bridge}) != len(bridge) or len({e["role"] for e in bridge}) != len(bridge):
        raise Rejected("DUPLICATE_CLAIM", "each EV-equity claim must occur once")
    if any(e["role"] not in ROLES for e in bridge):
        raise Rejected("UNKNOWN_CLAIM", "bridge")
    bridge_ids = {e["id"] for e in bridge}
    if any(e["included_in"] is not None and (e["included_in"] not in bridge_ids or e["included_in"] == e["id"]) for e in bridge):
        raise Rejected("INVALID_CLAIM_INCLUSION", "bridge")
    seen_refs = [canonical(e["amount_ref"]) for e in bridge if e["included_in"] is None]
    if len(set(seen_refs)) != len(seen_refs):
        raise Rejected("DUPLICATE_CLAIM_REFERENCE", "bridge")
    rows = []
    for scenario in settings["scenarios"]:
        row = {"name": scenario["name"], "currency": currency, "ev": None, "equity": None,
               "ordinary_value": None, "quote_value_model_currency": None, "quote_value": None,
               "upside_vs_price": None, "margin_to_model_value": None, "fcff": [], "bridge": [], "diagnostics": []}
        row["comparison_status"] = "not_computable"
        def issue(stage, exc):
            row["diagnostics"].append({"stage": stage, "code": exc.code, "detail": exc.detail})
        try:
            wacc, _ = number(scenario["wacc_ref"], "annual_fraction")
            growth, _ = number(scenario["terminal_growth_ref"], "annual_fraction")
            if not (wacc > 0 and growth > -1 and wacc > growth):
                raise Rejected("INVALID_RATE_DOMAIN", "WACC>0, g>-1, WACC>g")
            pv, last_fcff, last_t = 0.0, None, 0.0
            previous_period_end = origin
            if not scenario["forecast"]:
                raise Rejected("MISSING_FORECAST", scenario["name"])
            for year in scenario["forecast"]:
                period = year["period"]
                days = (date.fromisoformat(period["end"]) - date.fromisoformat(period["start"])).days + 1
                if period["frequency"] != "annual" or not 360 <= days <= 371 or period["end"] != year["cashflow_date"] or date.fromisoformat(period["start"]) <= origin:
                    raise Rejected("INVALID_FORECAST_FLOW_PERIOD", "explicit future annual period ending on cashflow_date required")
                if (date.fromisoformat(period["start"]) - previous_period_end).days != 1:
                    raise Rejected("NONCONSECUTIVE_FORECAST_PERIODS", "annual forecast must start the day after " + previous_period_end.isoformat())
                previous_period_end = date.fromisoformat(period["end"])
                for key, definition in (("ebit_ref", "operating_ebit"), ("tax_ref", "effective_cash_tax_rate"),
                                        ("da_ref", "noncash_da"), ("capex_ref", "capital_expenditure"), ("nwc_change_ref", "change_in_operating_nwc")):
                    forecast_item(year[key], period, definition)
                t = (date.fromisoformat(year["cashflow_date"]) - origin).days / 365
                if t <= last_t:
                    raise Rejected("INVALID_CASHFLOW_DATES", "strictly increasing future dates required")
                tax, _ = number(year["tax_ref"], "fraction")
                if not 0 <= tax <= 1:
                    raise Rejected("INVALID_TAX_DOMAIN", "tax in [0,1]")
                fcff = money(year["ebit_ref"]) * (1-tax) + money(year["da_ref"]) - money(year["capex_ref"]) - money(year["nwc_change_ref"])
                present = fcff / (1+wacc)**t
                row["fcff"].append({"date": year["cashflow_date"], "year_fraction_ACT_365F": t,
                                    "fcff": fcff, "present_value": present, "input_refs": copy.deepcopy(year)})
                pv += present
                last_fcff, last_t = fcff, t
            terminal = last_fcff * (1+growth) / (wacc-growth)
            row.update(ev=pv + terminal / (1+wacc)**last_t, terminal_value=terminal,
                       wacc=wacc, terminal_growth=growth, formula="FCFF DCF; ACT/365F; amounts in model currency")
            finite_tree(row)
        except (Rejected, ArithmeticError) as exc:
            issue("ev", exc if isinstance(exc, Rejected) else Rejected("NON_FINITE_CALCULATION", str(exc)))
            rows.append(row)
            continue
        try:
            if {e["role"] for e in bridge} != set(ROLES):
                raise Rejected("INCOMPLETE_EQUITY_BRIDGE", "all seven claim roles need evidence, including zero")
            equity = row["ev"]
            for entry in bridge:
                amount = money(entry["amount_ref"], fact_only=True)
                if amount < 0:
                    raise Rejected("INVALID_GROSS_CLAIM", entry["id"])
                if entry["included_in"]:
                    parent = next(e for e in bridge if e["id"] == entry["included_in"])
                    if parent["included_in"] or ROLES[parent["role"]] != ROLES[entry["role"]] or amount > money(parent["amount_ref"], True):
                        raise Rejected("INVALID_CLAIM_INCLUSION", entry["id"])
                    applied = 0
                else:
                    applied = ROLES[entry["role"]] * amount
                equity += applied
                row["bridge"].append({**entry, "amount": amount, "applied_signed_amount": applied})
            row["equity"] = equity
            row["net_cash"] = money(next(e for e in bridge if e["role"] == "cash")["amount_ref"], True) - money(next(e for e in bridge if e["role"] == "gross_debt")["amount_ref"], True)
        except Rejected as exc:
            issue("equity", exc)
            rows.append(row)
            continue
        try:
            shares, _ = number(request["security"]["ordinary_shares_ref"], "ordinary_shares", fact_only=True)
            if shares <= 0:
                raise Rejected("INVALID_SHARE_DENOMINATOR", "finite positive ordinary shares required")
            row["ordinary_value"] = row["equity"] / shares
            ratio, _ = number(request["security"]["ordinary_per_quote_unit_ref"], "ordinary_per_quote_unit", fact_only=True)
            if ratio <= 0 or (request["security"]["quote_unit"] == "ordinary" and ratio != 1):
                raise Rejected("INVALID_SECURITY_RATIO", "positive ratio; ordinary unit must equal one")
            row["quote_value_model_currency"] = row["ordinary_value"] * ratio
        except Rejected as exc:
            issue("security_unit", exc)
            rows.append(row)
            continue
        try:
            if request["security"]["quote_currency"] == currency:
                fx = 1.0
                row["fx_basis"] = "verified_same_currency_identity"
            else:
                fx, fx_fact = number(settings["fx_ref"], request["security"]["quote_currency"] + "_per_" + currency, fact_only=True)
                if fx <= 0 or fx_fact["metric"] != "fx_spot" or timestamp(fx_fact["observed_at"]).date() != origin:
                    raise Rejected("INVALID_FX", "positive spot FX on valuation date; convenience rates refused")
                row["fx_basis"] = settings["fx_ref"]
            row["quote_value"] = row["quote_value_model_currency"] * fx
        except Rejected as exc:
            issue("cross_currency", exc)
            rows.append(row)
            continue
        try:
            price, price_fact = number(settings["price_ref"], "currency_per_quote_unit", request["security"]["quote_currency"], True)
            row["price"] = price
            if timestamp(price_fact["observed_at"]).date() != origin or price_fact["metric"] != "price_" + request["security"]["quote_unit"]:
                raise Rejected("INVALID_PRICE", "positive price in matching security unit on valuation date")
            if price <= 0 or row["quote_value"] <= 0:
                row["comparison_status"] = "nonpositive_domain"
                raise Rejected("NONPOSITIVE_COMPARISON_DOMAIN", "P and V must both be positive; signed distressed-model arithmetic is audit data, not a tradable target")
            row["upside_vs_price"] = row["quote_value"] / price - 1
            row["margin_to_model_value"] = (row["quote_value"] - price) / row["quote_value"]
            row["comparison_status"] = "computed"
        except Rejected as exc:
            if row["quote_value"] is not None and row["quote_value"] <= 0 and row["comparison_status"] != "nonpositive_domain":
                row["comparison_status"] = "nonpositive_domain"
                issue("price_comparison", Rejected("NONPOSITIVE_COMPARISON_DOMAIN", "Nonpositive model value: audit-only distressed result; no ratios"))
            issue("price_comparison", exc)
        rows.append(row)
    return {"origin": "custom_FCFF_not_forced_native_output", "model": "fcff_dcf_v1", "currency": currency,
            "scenarios": rows, "recommendation": None,
            "native_abstention_preserved": True, "interpretation": "conditional model values; no entry price or trading authority"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", help="JSON input file; otherwise stdin")
    parser.add_argument("--output", help="local result JSON path")
    args = parser.parse_args()
    try:
        request = strict_loads(Path(args.input).read_text(encoding="utf-8-sig") if args.input else sys.stdin.read())
        result = process(request)
        result["operation_status"] = "validated" if request["operation"] == "validate" else "computed"
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            Path(args.output).write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        return 0
    except (Rejected, OSError) as exc:
        print(json.dumps({"status": "rejected", "code": getattr(exc, "code", "FILE_ERROR"), "detail": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
