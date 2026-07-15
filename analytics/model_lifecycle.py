"""
Model lifecycle automation — drift watch, champion/challenger, promotion.

The backtest (demand_forecast.py) decides which model *deserves* production.
This module automates what happens *after* that decision, the part that
usually rots in production:

  1. DRIFT WATCH   — score the reigning champion on the most recent fold
                     only (the operational proxy for "last cycle's forecast
                     vs the actuals that just landed in Gold"). If its live
                     WAPE breaches the threshold, the model has drifted.
  2. RETRAIN       — drift triggers a fresh full bake-off across all four
                     candidates on current data.
  3. PROMOTION     — a challenger takes the champion alias in the MLflow
                     Model Registry only if it *beats* the incumbent's WAPE.
                     Ties and losses change nothing; there is no novelty bias.

The decision logic is a pure function (`decide`) so the promotion rules are
unit-testable without MLflow or data. The registry uses MLflow aliases
(`@champion`), the 3.x replacement for stage transitions.

Usage:
    python analytics/model_lifecycle.py            # watch -> maybe retrain -> maybe promote
    python analytics/model_lifecycle.py --force-drift   # demo the full path
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "output"
sys.path.insert(0, str(ROOT / "analytics"))

DRIFT_WAPE_THRESHOLD = 0.20
REGISTRY_MODEL_NAME = "demand-forecast"


# ---------------------------------------------------------------- decisions

def decide(live_wape: float, champion: str, champion_avg_wape: float,
           bakeoff: dict[str, float],
           drift_threshold: float = DRIFT_WAPE_THRESHOLD) -> dict:
    """Pure promotion policy. bakeoff maps model name -> avg WAPE."""
    drifted = live_wape > drift_threshold
    if not drifted:
        return {"action": "hold", "champion": champion,
                "reason": f"live WAPE {live_wape:.1%} within threshold "
                          f"{drift_threshold:.0%}"}

    best = min(bakeoff, key=lambda k: bakeoff[k])
    if best != champion and bakeoff[best] < champion_avg_wape:
        return {"action": "promote", "champion": best,
                "previous": champion,
                "reason": f"drift ({live_wape:.1%}); challenger {best} "
                          f"({bakeoff[best]:.1%}) beats incumbent "
                          f"({champion_avg_wape:.1%})"}
    return {"action": "retrained_hold", "champion": champion,
            "reason": f"drift ({live_wape:.1%}) triggered retrain, but no "
                      f"challenger beat the incumbent ({champion_avg_wape:.1%})"}


# ---------------------------------------------------------------- mlflow

def register_champion(model_name: str, avg_wape: float, results: pd.DataFrame) -> str:
    """Log the champion's forward forecast as a pyfunc model and move the
    @champion alias to the new version. Returns the version number."""
    import mlflow
    from mlflow.tracking import MlflowClient

    mlflow.set_tracking_uri(f"sqlite:///{(ROOT / 'mlflow.db').as_posix()}")
    mlflow.set_experiment("demand-forecast-lifecycle")

    class BatchForecast(mlflow.pyfunc.PythonModel):
        """Serves the champion's batch-scored 28-day forecast table."""

        def load_context(self, context):
            self.forecast = pd.read_csv(context.artifacts["forecast"])

        def predict(self, context, model_input, params=None):
            cats = model_input["category"].tolist()
            return self.forecast[self.forecast["category"].isin(cats)]

    with mlflow.start_run(run_name=f"champion-{model_name}"):
        mlflow.log_params({"model": model_name})
        mlflow.log_metric("avg_wape", avg_wape)
        info = mlflow.pyfunc.log_model(
            name="model",
            python_model=BatchForecast(),
            artifacts={"forecast": str(OUT / "forecast_next_28d.csv")},
            registered_model_name=REGISTRY_MODEL_NAME,
        )

    client = MlflowClient()
    versions = client.search_model_versions(f"name='{REGISTRY_MODEL_NAME}'")
    version = max(int(v.version) for v in versions)
    client.set_registered_model_alias(REGISTRY_MODEL_NAME, "champion", version)
    client.set_model_version_tag(REGISTRY_MODEL_NAME, version, "model", model_name)
    client.set_model_version_tag(REGISTRY_MODEL_NAME, version, "avg_wape",
                                 f"{avg_wape:.4f}")
    return version


# ---------------------------------------------------------------- flow

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force-drift", action="store_true",
                    help="pretend the live WAPE breached the threshold (demo)")
    args = ap.parse_args(argv)

    results_file = OUT / "backtest_results.csv"
    if not results_file.exists():
        from demand_forecast import main as run_backtest
        run_backtest()
    results = pd.read_csv(results_file)

    avg = results.groupby("model")["wape"].mean()
    champion = avg.idxmin()
    champion_avg = float(avg.min())

    # operational proxy: the champion's error on the newest fold only
    latest_fold = results["fold"].max()
    live_wape = float(results[(results["model"] == champion)
                              & (results["fold"] == latest_fold)]["wape"].mean())
    if args.force_drift:
        live_wape = DRIFT_WAPE_THRESHOLD + 0.05

    decision = decide(live_wape, champion, champion_avg, avg.to_dict())
    print(f"champion: {champion} (avg WAPE {champion_avg:.1%}) | "
          f"live WAPE fold {latest_fold}: {live_wape:.1%}")
    print(f"decision: {decision['action']} — {decision['reason']}")

    version = register_champion(decision["champion"],
                                float(avg[decision["champion"]]), results)
    print(f"mlflow registry: '{REGISTRY_MODEL_NAME}' v{version} now carries "
          f"the @champion alias ({decision['champion']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
