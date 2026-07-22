"""Hand-verified cascade tests for the three spec scenarios (Phase 1 gate).
Expected values computed by hand from config/cascade_params.yaml + data/spr.json:

  import=4.7 mb/d, commercial=9.0d*4.7=42.3 mb, SPR=5.33 MMT*7.33=39.0689 mb,
  buffer=81.3689 mb, landed=deficit_pct*1.8, retail=[0.30,0.70]*landed.
"""
import pytest

from backend.engines.cascade import CorridorShock, run_cascade, single


def test_buffer_constants():
    r = single("hormuz", 0.0, 1)   # zero severity -> no deficit, but buffers computed
    assert r.commercial_stock_mb == pytest.approx(42.3, abs=1e-6)
    assert r.spr_usable_mb == pytest.approx(39.0689, abs=1e-3)
    assert r.inventory_buffer_mb == pytest.approx(81.3689, abs=1e-3)


def test_hormuz_50pct_14d():
    r = single("hormuz", 0.5, 14)
    assert r.gross_blocked_mb_d == pytest.approx(0.987, abs=1e-3)      # 4.7*0.42*0.5
    assert r.deficit_mb_d == pytest.approx(0.83895, abs=1e-4)          # *0.85
    assert r.deficit_pct == pytest.approx(17.85, abs=1e-2)
    assert r.inventory_days_remaining == pytest.approx(96.989, abs=0.05)
    assert r.net_shortfall_mb == pytest.approx(0.0, abs=1e-6)          # buffer covers 14d easily
    assert r.landed_cost_pressure_usd_bbl == pytest.approx(32.13, abs=1e-2)
    assert r.retail_pressure_usd_bbl["low"] == pytest.approx(9.639, abs=1e-2)
    assert r.retail_pressure_usd_bbl["high"] == pytest.approx(22.491, abs=1e-2)
    assert not r.drawdown_rate_binding                                 # 0.84 < SPR+import rate


def test_red_sea_full_30d():
    r = single("bab_el_mandeb", 1.0, 30)
    assert r.gross_blocked_mb_d == pytest.approx(0.376, abs=1e-3)      # 4.7*0.08*1.0
    assert r.deficit_mb_d == pytest.approx(0.1128, abs=1e-4)           # *0.30 (reroutable-heavy)
    assert r.deficit_pct == pytest.approx(2.4, abs=1e-2)
    assert r.inventory_days_remaining == pytest.approx(721.35, abs=1.0)
    assert r.net_shortfall_mb == pytest.approx(0.0, abs=1e-6)
    assert r.landed_cost_pressure_usd_bbl == pytest.approx(4.32, abs=1e-2)
    # Red Sea reroutes well -> most volume recoverable at freight premium, not a hard deficit
    assert len(r.reroute) == 1 and r.reroute[0]["extra_transit_days"] == 14


def test_combined_hormuz_and_red_sea():
    r = run_cascade([
        CorridorShock("hormuz", 0.6, 14),
        CorridorShock("bab_el_mandeb", 1.0, 14),
    ])
    # Hormuz 4.7*0.42*0.6*0.85=1.00674 ; BEM 4.7*0.08*1.0*0.30=0.1128 ; sum=1.11954
    assert r.deficit_mb_d == pytest.approx(1.11954, abs=1e-4)
    assert r.deficit_pct == pytest.approx(23.82, abs=1e-2)
    assert r.landed_cost_pressure_usd_bbl == pytest.approx(42.876, abs=1e-2)
    assert r.retail_pressure_usd_bbl["low"] == pytest.approx(12.863, abs=1e-2)
    assert r.retail_pressure_usd_bbl["high"] == pytest.approx(30.013, abs=1e-2)
    assert r.inventory_days_remaining == pytest.approx(72.68, abs=0.1)
    # two corridors affected -> gulf + red-sea suppliers surfaced
    ids = {s["supplier_id"] for s in r.affected_suppliers}
    assert {"iraq", "saudi_arabia", "uae", "kuwait"} & ids            # Hormuz suppliers present


def test_full_closure_more_severe_than_half():
    half = single("hormuz", 0.5, 14)
    full = single("hormuz", 1.0, 14)
    assert full.deficit_mb_d > half.deficit_mb_d
    assert full.landed_cost_pressure_usd_bbl > half.landed_cost_pressure_usd_bbl


def test_reroute_reference_corridor_ignored():
    r = single("cape_good_hope", 1.0, 14)   # reroute-reference -> no deficit
    assert r.deficit_mb_d == pytest.approx(0.0, abs=1e-9)


def test_refinery_run_impacts_are_engine_allocated():
    r = single("hormuz", 0.5, 14)
    assert len(r.refinery_impacts) == 8
    assert sum(x["run_rate_impact_mb_d"] for x in r.refinery_impacts) == pytest.approx(
        r.deficit_mb_d, abs=5e-5)
    assert all(x["allocation_basis"] == "supplier-grade compatibility exposure"
               for x in r.refinery_impacts)
    assert all(x["modeled_run_mb_d"] <= x["baseline_run_mb_d"] for x in r.refinery_impacts)
