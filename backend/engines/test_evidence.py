"""Evidence bundle tests. Numbers-only path (no LLM spend). Verifies engine numbers flow through
and the honesty labels are present."""
from backend.engines import evidence, risk
from backend.lib import storage


def test_bundle_numbers_match_engine():
    storage.init_db()
    b = evidence.build_bundle("hormuz", with_narrative=False)["value"]
    # index must equal the risk engine's own computation (no LLM-invented numbers)
    r = risk.compute("hormuz", risk.gather_raw("hormuz"))
    assert b["risk_index"] == r.index
    assert b["confidence"] == r.confidence
    assert b["narrative"] is None
    assert "NOT a probability" in b["index_note"]


def test_affected_suppliers_are_gulf_for_hormuz():
    b = evidence.build_bundle("hormuz", with_narrative=False)["value"]
    ids = {s["supplier_id"] for s in b["affected_suppliers"]}
    assert {"iraq", "saudi_arabia", "uae", "kuwait"} <= ids
    # a non-Hormuz supplier must not be attributed to Hormuz
    assert "russia" not in ids and "usa" not in ids


def test_expected_consequence_is_engine_computed():
    b = evidence.build_bundle("hormuz", with_narrative=False)["value"]
    ec = b["expected_consequence"]
    assert ec["deficit_mb_d"] >= 0.0
    assert "retail_pressure_usd_bbl" in ec
    assert "low" in ec["retail_pressure_usd_bbl"] and "high" in ec["retail_pressure_usd_bbl"]


def test_affected_refineries_present():
    b = evidence.build_bundle("hormuz", with_narrative=False)["value"]
    assert len(b["affected_refineries"]) >= 1
    for r in b["affected_refineries"]:
        assert r["exposed_grade_classes"]
