"""The promotion policy must be boring: no novelty bias, no demotion on ties."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analytics.model_lifecycle import decide  # noqa: E402

BAKEOFF = {"moving_avg_28d": 0.185, "gradient_boosted": 0.196,
           "holt_winters": 0.197, "seasonal_naive": 0.243}


def test_healthy_champion_is_held():
    d = decide(live_wape=0.19, champion="moving_avg_28d",
               champion_avg_wape=0.185, bakeoff=BAKEOFF)
    assert d["action"] == "hold"
    assert d["champion"] == "moving_avg_28d"


def test_drift_without_better_challenger_keeps_incumbent():
    d = decide(live_wape=0.25, champion="moving_avg_28d",
               champion_avg_wape=0.185, bakeoff=BAKEOFF)
    assert d["action"] == "retrained_hold"
    assert d["champion"] == "moving_avg_28d", "a drifted champion still beats a worse challenger"


def test_drift_with_better_challenger_promotes():
    bakeoff = dict(BAKEOFF, gradient_boosted=0.15)  # challenger now wins
    d = decide(live_wape=0.25, champion="moving_avg_28d",
               champion_avg_wape=0.185, bakeoff=bakeoff)
    assert d["action"] == "promote"
    assert d["champion"] == "gradient_boosted"
    assert d["previous"] == "moving_avg_28d"


def test_challenger_must_strictly_beat_champion():
    bakeoff = dict(BAKEOFF, gradient_boosted=0.185)  # exact tie
    d = decide(live_wape=0.25, champion="moving_avg_28d",
               champion_avg_wape=0.185, bakeoff=bakeoff)
    assert d["action"] == "retrained_hold", "ties never trigger a swap"
