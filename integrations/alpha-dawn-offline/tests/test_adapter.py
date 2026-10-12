import copy
import hashlib
import io
import json
import math
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import adapter


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.data = adapter.read_json(ROOT / "examples/synthetic-complete.input.json")

    def fact(self, key):
        return next(f for f in self.data["facts"] if f["id"] == key)

    def scenario(self, name="base"):
        result = adapter.process(self.data)
        return next(s for s in result["valuation"]["scenarios"] if s["name"] == name)

    def test_frozen_anchors_and_requirements(self):
        anchors = adapter.read_json(ROOT / "config/anchors.v1.json")
        req = adapter.read_json(ROOT / "config/requirements.v1.json")
        self.assertEqual([c["weight"] for c in anchors["components"]], [25,20,25,15,15])
        self.assertEqual(sum(len(c["anchors"]) for c in anchors["components"]), 25)
        self.assertEqual(len(req["items"]), 27)
        self.assertTrue(all(r["weight"] == 1 for r in req["items"]))

    def test_complete_synthetic_native_abstention_is_immutable(self):
        before = copy.deepcopy(self.data)
        result = adapter.process(self.data)
        self.assertEqual(result["quality"]["total"], 75)
        self.assertEqual(result["evidence_coverage"]["satisfied"], 27)
        self.assertEqual(result["native_output"], self.data["native_output"])
        self.assertEqual(self.data, before)
        self.assertEqual(result["native_output"]["status"], "abstain")
        self.assertIsNone(result["valuation"]["recommendation"])

    def test_missing_component_no_renormalization(self):
        self.data["quality_assessments"] = self.data["quality_assessments"][:-1]
        result = adapter.process(self.data)["quality"]
        self.assertIsNone(result["total"])
        self.assertEqual(result["observed_contribution"], 63.75)
        self.assertEqual(result["possible_range"], [63.75,78.75])

    def test_zero_score_is_observed(self):
        reviews = self.data["quality_assessments"][0]["anchor_reviews"]
        for a in reviews:
            a["status"] = "supported" if a["level"] == 0 else "unknown"
        result = adapter.process(self.data)["quality"]
        self.assertEqual(result["components"][0]["score"], 0)
        self.assertEqual(result["observed_weight"], 100)
        self.assertEqual(result["total"], 56.25)

    def test_unknown_lower_anchor_cannot_be_skipped(self):
        self.data["quality_assessments"][0]["anchor_reviews"][1]["status"] = "unknown"
        self.assertIsNone(adapter.process(self.data)["quality"]["components"][0]["score"])

    def test_adverse_and_positive_supported_bands_conflict(self):
        self.data["quality_assessments"][0]["anchor_reviews"][0]["status"] = "supported"
        self.assertIsNone(adapter.process(self.data)["quality"]["components"][0]["score"])

    def test_hypothetical_stress_cannot_replace_history(self):
        review = self.data["quality_assessments"][0]["anchor_reviews"]
        review[3]["status"], review[4]["status"] = "supported", "supported"
        review[4]["evidence_ids"] = ["e.Q03"]
        self.fact("e.Q03")["evidence_kind"] = "hypothetical"
        self.assertIsNone(adapter.process(self.data)["quality"]["components"][0]["score"])
        self.fact("e.Q03")["evidence_kind"] = "historical_stress"
        self.assertEqual(adapter.process(self.data)["quality"]["components"][0]["score"], 4)

    def test_unresolved_counterevidence_blocks_component(self):
        self.data["quality_assessments"][0]["anchor_reviews"][3]["counter_evidence_ids"] = ["e.Q02"]
        self.assertIsNone(adapter.process(self.data)["quality"]["components"][0]["score"])

    def test_conflict_does_not_count_as_support(self):
        self.data["contradictions"] = [{"id":"conflict", "fact_ids":["e.Q01", "e.Q02"], "requirement_ids":["Q01","Q02"],
                                      "status":"unresolved", "reason":"synthetic conflicting accounts", "resolution_reason":"", "resolution_fact_ids":[]}]
        result = adapter.process(self.data)
        self.assertEqual(result["evidence_coverage"]["satisfied"], 25)
        self.assertIsNone(result["quality"]["total"])
        self.assertEqual(result["evidence_coverage"]["document_availability"]["available"], len(self.data["facts"]))

    def test_critical_risk_cannot_be_averaged_away(self):
        self.data["hard_risks"] = [{"code":"PAYMENT_DEFAULT", "status":"confirmed", "evidence_ids":["e.Q10"],
                                  "affected_fact_ids":[], "rationale":"synthetic default", "resolution_condition":"verified cure"}]
        quality = adapter.process(self.data)["quality"]
        self.assertEqual(quality["status"], "blocked_by_hard_risk")
        self.assertIsNone(quality["total"])
        self.assertEqual(quality["arithmetic_total"], 75)

    def test_unknown_and_future_publication(self):
        self.fact("e.Q01")["published_at"] = None
        self.fact("e.Q04")["published_at"] = "2026-10-14T00:00:00Z"
        result = adapter.process(self.data)
        self.assertEqual(result["evidence_coverage"]["satisfied"], 25)
        self.assertIsNone(result["quality"]["components"][0]["score"])
        self.assertIsNone(result["quality"]["components"][1]["score"])

    def test_later_revision_is_not_historical_available_data(self):
        self.fact("e.Q01")["vintage_at"] = "2026-10-14T00:00:00Z"
        self.assertEqual(adapter.process(self.data)["evidence_coverage"]["satisfied"], 26)

    def test_unknown_start_and_future_actual_period(self):
        self.fact("e.Q01")["period"]["start"] = None
        self.fact("e.Q02")["period"]["end"] = "2027-01-01"
        self.assertEqual(adapter.process(self.data)["evidence_coverage"]["satisfied"], 25)

    def test_future_forecast_period_can_be_known_before_cutoff(self):
        self.fact("e.V03")["kind"] = "guidance"
        self.fact("e.V03")["period"]["end"] = "2027-12-31"
        self.assertEqual(adapter.process(self.data)["evidence_coverage"]["satisfied"], 27)

    def test_assumption_cannot_launder_future_evidence(self):
        self.fact("e.V03")["published_at"] = "2026-11-01T00:00:00Z"
        self.assertIsNone(self.scenario()["ev"])

    def test_exact_fcff_dcf_and_security_bridge(self):
        row = self.scenario()
        # FCFF=110*.8+10-15-5=78 million; PV + TV = 975 million.
        self.assertAlmostEqual(row["ev"], 975000000, places=5)
        self.assertAlmostEqual(row["equity"], 875000000, places=5)
        self.assertAlmostEqual(row["ordinary_value"], 8.75)
        self.assertAlmostEqual(row["quote_value_model_currency"], 70)
        self.assertAlmostEqual(row["quote_value"], 70/7.2)
        self.assertAlmostEqual(row["upside_vs_price"], (70/7.2)/8-1)

    def test_missing_price_does_not_block_absolute_dcf(self):
        self.fact("price")["value"] = None
        row = self.scenario()
        self.assertIsNotNone(row["quote_value"])
        self.assertIsNone(row["upside_vs_price"])

    def test_missing_fx_preserves_same_currency_values(self):
        self.fact("fx")["value"] = None
        row = self.scenario()
        self.assertIsNotNone(row["ordinary_value"])
        self.assertIsNotNone(row["quote_value_model_currency"])
        self.assertIsNone(row["quote_value"])
        self.data["security"]["quote_currency"] = "CNY"
        self.fact("price")["currency"] = "CNY"
        self.assertIsNotNone(self.scenario()["quote_value"])

    def test_missing_shares_and_ratio_have_limited_blocking_scope(self):
        self.fact("shares")["value"] = None
        row = self.scenario()
        self.assertIsNotNone(row["equity"])
        self.assertIsNone(row["ordinary_value"])
        self.fact("shares")["value"] = 100000000
        self.fact("ratio")["value"] = None
        row = self.scenario()
        self.assertIsNotNone(row["ordinary_value"])
        self.assertIsNone(row["quote_value_model_currency"])

    def test_nonpositive_denominators_and_price(self):
        for key in ("shares", "ratio", "fx", "price"):
            with self.subTest(key=key):
                original = self.fact(key)["value"]
                self.fact(key)["value"] = 0
                self.assertTrue(self.scenario()["diagnostics"])
                self.fact(key)["value"] = original

    def test_convenience_fx_and_fx_date_refused(self):
        self.fact("fx")["metric"] = "fx_convenience"
        self.assertIsNone(self.scenario()["quote_value"])
        self.fact("fx")["metric"] = "fx_spot"
        self.fact("fx")["observed_at"] = "2026-10-11T00:00:00Z"
        self.assertIsNone(self.scenario()["quote_value"])

    def test_ads_price_unit_and_currency_mismatch(self):
        self.fact("price")["metric"] = "price_ordinary"
        self.assertIsNone(self.scenario()["upside_vs_price"])
        self.fact("price")["metric"] = "price_ADS"
        self.fact("price")["currency"] = "CNY"
        self.assertIsNone(self.scenario()["upside_vs_price"])

    def test_zero_claim_is_valid_but_missing_is_not(self):
        self.assertIsNotNone(self.scenario()["equity"])
        self.fact("claim.preferred")["value"] = None
        row = self.scenario()
        self.assertIsNotNone(row["ev"])
        self.assertIsNone(row["equity"])

    def test_signed_cashflow_equity_and_net_cash_are_preserved(self):
        for a in self.data["assumptions"]:
            if a["id"].endswith(".ebit"):
                a["value"] = -100
        row = self.scenario()
        self.assertLess(row["fcff"][0]["fcff"], 0)
        self.assertLess(row["equity"], 0)
        self.fact("claim.cash")["value"] = 300
        self.assertEqual(self.scenario()["net_cash"], 100000000)

    def test_duplicate_claim_rejected_and_included_lease_counted_once(self):
        self.data["valuation"]["bridge"].append(copy.deepcopy(self.data["valuation"]["bridge"][0]))
        with self.assertRaises(adapter.Rejected):
            adapter.process(self.data)
        self.data["valuation"]["bridge"].pop()
        self.fact("claim.lease_liabilities")["value"] = 20
        entry = next(e for e in self.data["valuation"]["bridge"] if e["role"] == "lease_liabilities")
        entry["included_in"] = "gross_debt"
        self.assertAlmostEqual(self.scenario()["equity"], 875000000, places=5)

    def test_rate_and_tax_domains(self):
        for suffix, value in (("wacc",0), ("g",.1), ("tax",1.1)):
            with self.subTest(suffix=suffix):
                item = next(a for a in self.data["assumptions"] if a["id"] == "base."+suffix)
                original = item["value"]
                item["value"] = value
                self.assertIsNone(self.scenario()["ev"])
                item["value"] = original

    def test_reversed_cashflow_dates(self):
        self.data["valuation"]["scenarios"][0]["forecast"][0]["cashflow_date"] = "2026-10-12"
        self.assertIsNone(self.scenario("bear")["ev"])

    def test_nonfinite_duplicate_json_and_malformed_output(self):
        for text in ('{"x":NaN}', '{"x":Infinity}', '{"x":1e309}', '{"x":1,"x":2}', '```json\n{}\n```', '[{'):
            with self.subTest(text=text), self.assertRaises(adapter.Rejected):
                adapter.strict_loads(text)
        self.data["facts"][0]["value"] = float("inf")
        with self.assertRaises(adapter.Rejected):
            adapter.process(self.data)

    def test_unknown_fields_and_duplicate_ids(self):
        self.data["tool_calls"] = [{"name":"send"}]
        with self.assertRaises(adapter.Rejected):
            adapter.process(self.data)
        del self.data["tool_calls"]
        self.data["facts"].append(copy.deepcopy(self.data["facts"][0]))
        with self.assertRaises(adapter.Rejected):
            adapter.process(self.data)

    def test_source_text_is_data_not_a_command(self):
        payload = '</script><img src=x onerror="globalThis.pwned=1">; send/trade; __import__("os").system("bad")'
        self.fact("e.Q01")["value"] = payload
        self.data["native_output"]["raw_note"] = payload
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), patch.object(subprocess, "Popen", side_effect=AssertionError("process forbidden")):
            result = adapter.process(self.data)
        self.assertEqual(result["native_output"]["raw_note"], payload)
        self.assertEqual(result["evidence_receipt"][0]["value"], payload)

    def test_actual_send_and_trade_calls_rejected_without_side_effects(self):
        with patch.object(socket.socket, "connect") as connect, patch.object(subprocess, "Popen") as spawn:
            for operation in ("send", "trade", "botmux", "schedule"):
                with self.subTest(operation=operation), self.assertRaises(adapter.Rejected) as caught:
                    adapter.process({"operation":operation})
                self.assertEqual(caught.exception.code, "OPERATION_NOT_ALLOWED")
            self.assertEqual(connect.call_count, 0)
            self.assertEqual(spawn.call_count, 0)

    def test_duplicate_results_are_identical(self):
        a, b = adapter.process(self.data), adapter.process(self.data)
        self.assertEqual(a, b)
        self.assertEqual(a["result_id"], b["result_id"])

    def test_public_history_is_explicitly_incomplete(self):
        request = adapter.read_json(ROOT / "examples/apple-fy2023-public-gaps.input.json")
        result = adapter.process(request)
        self.assertIsNone(result["quality"]["total"])
        self.assertEqual(result["evidence_coverage"]["satisfied"], 0)
        self.assertTrue(all(s["ev"] is None for s in result["valuation"]["scenarios"]))
        self.assertEqual(result["native_output"]["status"], "not_run")

    def test_upstream_integrity_without_executing_it(self):
        manifest = adapter.read_json(ROOT / "method-manifest.json")
        self.assertEqual(manifest["commit"], "7235d3411601036cc79137fa0aec0d587f2c8e19")
        self.assertEqual(manifest["license"]["spdx"], "MIT")
        for f in manifest["files"]:
            path = ROOT / "vendor/finterm" / f["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), f["sha256"])
            blob = path.read_bytes()
            self.assertEqual(hashlib.sha1(b"blob "+str(len(blob)).encode()+b"\0"+blob).hexdigest(),f["git_blob_sha"])

    def test_r1_compatible_nested_positive_support(self):
        reviews=self.data["quality_assessments"][0]["anchor_reviews"]
        self.assertEqual(reviews[2]["status"],"supported")
        self.assertEqual(reviews[3]["status"],"supported")
        self.assertEqual(adapter.process(self.data)["quality"]["components"][0]["score"],3)

    def test_r1_refuted_profitability_conflicts_with_repeated_profitability(self):
        self.data["quality_assessments"][0]["anchor_reviews"][2]["status"]="refuted"
        self.assertIsNone(adapter.process(self.data)["quality"]["components"][0]["score"])

    def test_r1_capital_and_governance_four_do_not_require_historical_stress(self):
        for identifier in ("capital","governance"):
            judgment=next(j for j in self.data["quality_assessments"] if j["id"]==identifier)
            judgment["anchor_reviews"][4]["status"]="supported"
            judgment["anchor_reviews"][4]["evidence_ids"]=judgment["anchor_reviews"][3]["evidence_ids"]
        components=adapter.process(self.data)["quality"]["components"]
        self.assertEqual(components[2]["score"],4)
        self.assertEqual(components[4]["score"],4)
        self.assertIsNone(components[2]["historical_stress_requirement"])
        self.assertIsNone(components[4]["historical_stress_requirement"])

    def test_r1_negative_value_has_no_comparison_ratios(self):
        for assumption in self.data["assumptions"]:
            if assumption["id"].endswith(".ebit"):assumption["value"]=-100
        for row in adapter.process(self.data)["valuation"]["scenarios"]:
            self.assertLess(row["equity"],0)
            self.assertIsNone(row["upside_vs_price"])
            self.assertIsNone(row["margin_to_model_value"])
            self.assertEqual(row["comparison_status"],"nonpositive_domain")
            self.assertTrue(any(d["code"]=="NONPOSITIVE_COMPARISON_DOMAIN" for d in row["diagnostics"]))

    def test_r1_zero_value_has_no_comparison_ratios(self):
        for assumption in self.data["assumptions"]:
            if assumption["id"].endswith(".ebit"):assumption["value"]=12.5
        for fact in self.data["facts"]:
            if fact["id"].startswith("claim."):fact["value"]=0
        row=self.scenario()
        self.assertEqual(row["quote_value"],0)
        self.assertIsNone(row["upside_vs_price"])
        self.assertIsNone(row["margin_to_model_value"])

    def test_r1_historical_actual_cannot_be_direct_forecast(self):
        historical=copy.deepcopy(self.fact("claim.cash"))
        historical.update(id="old.ebit",value=110,metric="reported_ebit",financial_definition="operating_ebit",
                          period={"start":"2015-01-01","end":"2015-12-31","frequency":"annual"})
        self.data["facts"].append(historical)
        self.data["valuation"]["scenarios"][1]["forecast"][0]["ebit_ref"]={"fact_id":"old.ebit"}
        row=self.scenario()
        self.assertIsNone(row["ev"])
        self.assertTrue(any(d["code"]=="FORECAST_PERIOD_MISMATCH" for d in row["diagnostics"]))

    def test_r1_explicit_carry_forward_assumption_is_distinct(self):
        assumption=next(a for a in self.data["assumptions"] if a["id"]=="base.ebit")
        assumption["assumption_type"]="carry_forward"
        assumption["rationale"]="Synthetic explicit future-period carry-forward hypothesis, not a reported historical flow."
        self.assertIsNotNone(self.scenario()["ev"])

    def test_r1_compatible_published_guidance_admitted(self):
        guidance=copy.deepcopy(self.fact("claim.cash"))
        target=self.data["valuation"]["scenarios"][1]["forecast"][0]["period"]
        guidance.update(id="guide.ebit",value=110,metric="guided_ebit",kind="guidance",financial_definition="operating_ebit",period=copy.deepcopy(target))
        self.data["facts"].append(guidance)
        self.data["valuation"]["scenarios"][1]["forecast"][0]["ebit_ref"]={"fact_id":"guide.ebit"}
        self.assertAlmostEqual(self.scenario()["ev"],975000000,places=4)
        guidance["period"]["frequency"]="quarterly"
        self.assertIsNone(self.scenario()["ev"])

    def test_r1_wrong_financial_definition_is_blocked(self):
        next(a for a in self.data["assumptions"] if a["id"]=="base.ebit")["financial_definition"]="capital_expenditure"
        self.assertIsNone(self.scenario()["ev"])

    def test_r1_one_day_does_not_meet_multi_year_window(self):
        for fact in self.data["facts"]:fact["period"]={"start":"2026-09-30","end":"2026-09-30","frequency":"instant"}
        result=adapter.process(self.data)
        self.assertIsNone(result["quality"]["total"])
        self.assertLess(result["evidence_coverage"]["satisfied"],27)
        self.assertEqual(result["quality"]["observation_window"]["status"],"unmet")

    def test_r1_missing_annual_period_blocks_window_component(self):
        self.fact("e.Q03")["periods_observed"] = self.fact("e.Q03")["periods_observed"][1:]
        result=adapter.process(self.data)
        self.assertIsNone(result["quality"]["components"][0]["score"])
        receipt=next(r for r in result["evidence_coverage"]["requirements"] if r["id"]=="Q03")
        self.assertFalse(receipt["satisfied"])
        self.assertEqual(receipt["window_status"],"unmet")

    def test_r1_window_override_requires_predeclared_reason(self):
        self.data["quality_window"]["mode"]="case_specific"
        self.data["quality_window"]["override_reason"]=""
        self.assertIsNone(adapter.process(self.data)["quality"]["total"])

    def test_r1_quarter_assumption_cannot_be_annual_flow(self):
        next(a for a in self.data["assumptions"] if a["id"]=="base.ebit")["period"]["frequency"]="quarterly"
        self.assertIsNone(self.scenario()["ev"])

    def test_r1_proposed_handoff_rejects_shared_mutable_or_executable_envelope(self):
        schema=adapter.read_json(ROOT/"schema/handoff.proposal.v1.json")
        envelope={"contract_version":"alpha-dawn-handoff/proposal-v1","message_type":"analysis_input","bot_id":"alpha-dawn-framework",
                  "peer_bot_id":None,"request_id":"synth.req","case_id":"synth.case","cutoff_at":"2026-10-12T12:00:00Z",
                  "payload_kind":"frozen_facts_json","payload_sha256":"a"*64,"sources":[],"input_allowlist_ids":[],
                  "workspace_namespace":"alpha-dawn-framework","state_namespace":"alpha-dawn-framework",
                  "shared_mutable_state":False,"executable_payload":False}
        adapter.validate_schema(envelope,schema,{})
        for field in ("shared_mutable_state","executable_payload"):
            probe=copy.deepcopy(envelope);probe[field]=True
            with self.assertRaises(adapter.Rejected):adapter.validate_schema(probe,schema,{})

    def test_r1_annual_cannot_substitute_for_latest_interim(self):
        self.data["quality_window"]["latest_interim"]=copy.deepcopy(self.data["quality_window"]["fiscal_years"][-1])
        with self.assertRaises(adapter.Rejected):adapter.process(self.data)

    def add_forecast_period(self, start, end, replace_first=False):
        scenario = self.data["valuation"]["scenarios"][1]
        year = copy.deepcopy(scenario["forecast"][0])
        year["period"] = {"start": start, "end": end, "frequency": "annual"}
        year["cashflow_date"] = end
        for key in ("ebit_ref", "tax_ref", "da_ref", "capex_ref", "nwc_change_ref"):
            source_id = year[key]["assumption_id"]
            assumption = copy.deepcopy(next(a for a in self.data["assumptions"] if a["id"] == source_id))
            assumption["id"] += ".timeline"
            assumption["period"] = copy.deepcopy(year["period"])
            self.data["assumptions"].append(assumption)
            year[key] = {"assumption_id": assumption["id"]}
        if replace_first:
            scenario["forecast"][0] = year
        else:
            scenario["forecast"].append(year)

    def test_r2_consecutive_two_year_forecast_is_valid(self):
        self.add_forecast_period("2027-10-13", "2028-10-12")
        row = self.scenario()
        expected = 78000000 / 1.1 + (78000000 + 78000000 * 1.02 / .08) / 1.1 ** (731 / 365)
        self.assertAlmostEqual(row["ev"], expected, places=5)
        self.assertEqual(len(row["fcff"]), 2)
        self.assertEqual([r["fcff"] for r in row["fcff"]], [78000000, 78000000])
        self.assertFalse(row["diagnostics"])

    def test_r2_exact_overlapping_annual_forecasts_are_rejected(self):
        self.add_forecast_period("2027-01-01", "2027-12-31")
        row = self.scenario()
        self.assertIsNone(row["ev"])
        self.assertIsNone(row["equity"])
        self.assertTrue(any(d["code"] == "NONCONSECUTIVE_FORECAST_PERIODS" for d in row["diagnostics"]))

    def test_r2_gap_between_annual_forecasts_is_rejected(self):
        self.add_forecast_period("2027-10-14", "2028-10-13")
        row = self.scenario()
        self.assertIsNone(row["ev"])
        self.assertTrue(any(d["code"] == "NONCONSECUTIVE_FORECAST_PERIODS" for d in row["diagnostics"]))

    def test_r2_initial_omitted_interval_is_rejected(self):
        self.add_forecast_period("2026-10-14", "2027-10-13", replace_first=True)
        row = self.scenario()
        self.assertIsNone(row["ev"])
        self.assertTrue(any(d["code"] == "NONCONSECUTIVE_FORECAST_PERIODS" for d in row["diagnostics"]))

    def test_r1_actual_period_cannot_postdate_its_publication(self):
        self.fact("e.Q03")["published_at"]="2024-01-01T00:00:00Z"
        result=adapter.process(self.data)
        self.assertIsNone(result["quality"]["components"][0]["score"])
        bad=next(f for f in result["uncertainty"]["ineligible_facts"] if f["id"]=="e.Q03")
        self.assertIn("ACTUAL_PERIOD_AFTER_PUBLICATION",bad["reasons"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
