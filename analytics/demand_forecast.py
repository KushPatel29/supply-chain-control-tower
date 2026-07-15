"""
Demand forecasting with honest backtesting.

Forecasts daily shipped units per product category and — more importantly —
proves which model deserves to be trusted, using rolling-origin backtesting
(the evaluation a demand planner actually needs, as opposed to a single
train/test split that can flatter a lucky model).

Models compared:
  - Seasonal naive (same weekday last week) — the baseline to beat.
  - Moving average (28-day).
  - Holt-Winters triple exponential smoothing (weekly seasonality,
    statsmodels ExponentialSmoothing).
  - Gradient-boosted trees (sklearn HistGradientBoostingRegressor — the
    LightGBM-style challenger) on calendar + lag/rolling features. Direct
    (non-recursive) forecasting: every lag is >= the 28-day horizon, so all
    features for future dates resolve inside the training window.

Every backtest run is logged to MLflow (local SQLite store):
    mlflow ui --backend-store-uri sqlite:///mlflow.db

Outputs (to analytics/output/):
  - backtest_results.csv    per-model, per-fold WAPE/MAPE
  - forecast_next_28d.csv   28-day forward forecast per category (best model)
  - forecast_vs_actual.png  README chart: last fold, forecast vs actual

Usage:
    python analytics/demand_forecast.py
"""

import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

warnings.filterwarnings("ignore")  # statsmodels convergence chatter

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "output"
OUT.mkdir(exist_ok=True)

HORIZON = 28          # forecast 4 weeks ahead
N_FOLDS = 4           # rolling-origin backtest folds
SEASON = 7            # weekly seasonality in daily data


def load_daily_demand() -> pd.DataFrame:
    orders = pd.read_csv(ROOT / "data" / "bronze" / "fact_orders.csv",
                         parse_dates=["order_date"])
    products = pd.read_csv(ROOT / "data" / "bronze" / "dim_product.csv")
    df = orders.merge(products[["product_id", "category"]], on="product_id")
    daily = (df.groupby(["category", "order_date"])["qty_shipped"]
               .sum().rename("units").reset_index())
    # dense calendar per category so gaps count as zero demand
    full = []
    for cat, g in daily.groupby("category"):
        idx = pd.date_range(g["order_date"].min(), g["order_date"].max(), freq="D")
        s = g.set_index("order_date")["units"].reindex(idx, fill_value=0.0)
        full.append(pd.DataFrame({"category": cat, "date": idx, "units": s.values}))
    return pd.concat(full, ignore_index=True)


# ---------------------------------------------------------------- models

def seasonal_naive(train: pd.Series, horizon: int) -> np.ndarray:
    last_week = train.values[-SEASON:]
    return np.resize(last_week, horizon)


def moving_average(train: pd.Series, horizon: int) -> np.ndarray:
    return np.full(horizon, train.values[-28:].mean())


def holt_winters(train: pd.Series, horizon: int) -> np.ndarray:
    model = ExponentialSmoothing(
        train.values, trend="add", seasonal="add",
        seasonal_periods=SEASON, initialization_method="estimated")
    fitted = model.fit(optimized=True)
    return np.clip(fitted.forecast(horizon), 0, None)


def _gb_features(dates: pd.DatetimeIndex, history: pd.Series) -> pd.DataFrame:
    """Calendar + lag features. All lags are >= HORIZON days so a 28-day-ahead
    forecast never needs its own predictions (direct, not recursive)."""
    feats = pd.DataFrame(index=dates)
    feats["dayofweek"] = dates.dayofweek
    feats["day"] = dates.day
    feats["month"] = dates.month
    for lag in (28, 35, 42):
        feats[f"lag_{lag}"] = history.reindex(dates - pd.Timedelta(days=lag)).values
    roll28 = history.rolling(28).mean()
    feats["rollmean_28_lag28"] = roll28.reindex(dates - pd.Timedelta(days=28)).values
    return feats


def gradient_boosted(train: pd.Series, horizon: int) -> np.ndarray:
    from sklearn.ensemble import HistGradientBoostingRegressor
    X = _gb_features(train.index, train)
    mask = X.notna().all(axis=1)
    model = HistGradientBoostingRegressor(random_state=42, max_depth=4)
    model.fit(X[mask], train[mask])
    future = pd.date_range(train.index[-1] + pd.Timedelta(days=1), periods=horizon)
    Xf = _gb_features(future, train)
    return np.clip(model.predict(Xf), 0, None)


MODELS = {
    "seasonal_naive": seasonal_naive,
    "moving_avg_28d": moving_average,
    "holt_winters": holt_winters,
    "gradient_boosted": gradient_boosted,
}


def wape(actual: np.ndarray, forecast: np.ndarray) -> float:
    return float(np.abs(actual - forecast).sum() / np.abs(actual).sum())


def mape(actual: np.ndarray, forecast: np.ndarray) -> float:
    mask = actual != 0
    return float(np.mean(np.abs((actual[mask] - forecast[mask]) / actual[mask])))


# ---------------------------------------------------------------- backtest

def rolling_backtest(demand: pd.DataFrame) -> pd.DataFrame:
    """Rolling-origin evaluation: for each fold, train on everything before
    the cutoff, forecast HORIZON days, score against actuals."""
    rows = []
    for cat, g in demand.groupby("category"):
        series = g.set_index("date")["units"]
        for fold in range(N_FOLDS):
            cutoff = len(series) - HORIZON * (N_FOLDS - fold)
            train, actual = series.iloc[:cutoff], series.iloc[cutoff:cutoff + HORIZON]
            for name, fn in MODELS.items():
                fc = fn(train, HORIZON)
                rows.append({
                    "category": cat, "fold": fold + 1, "model": name,
                    "train_days": len(train),
                    "wape": round(wape(actual.values, fc), 4),
                    "mape": round(mape(actual.values, fc), 4),
                })
    return pd.DataFrame(rows)


def log_to_mlflow(results: pd.DataFrame, best_model: str) -> None:
    """One MLflow run per model per backtest execution (import-optional)."""
    try:
        import mlflow
    except ImportError:
        print("mlflow not installed - skipping experiment tracking")
        return
    mlflow.set_tracking_uri(f"sqlite:///{(ROOT / 'mlflow.db').as_posix()}")
    mlflow.set_experiment("demand-forecast-backtest")
    agg = results.groupby("model").agg(avg_wape=("wape", "mean"),
                                       avg_mape=("mape", "mean")).reset_index()
    for _, r in agg.iterrows():
        with mlflow.start_run(run_name=r["model"]):
            mlflow.log_params({"horizon_days": HORIZON, "n_folds": N_FOLDS,
                               "seasonality": SEASON})
            mlflow.log_metrics({"avg_wape": r["avg_wape"], "avg_mape": r["avg_mape"],
                                "is_champion": float(r["model"] == best_model)})
    print(f"mlflow: logged {len(agg)} runs -> {ROOT / 'mlflow.db'}")


def main():
    demand = load_daily_demand()
    results = rolling_backtest(demand)
    results.to_csv(OUT / "backtest_results.csv", index=False)

    summary = (results.groupby("model")["wape"].mean().sort_values()
               .rename("avg_wape").reset_index())
    best_model = summary.iloc[0]["model"]
    log_to_mlflow(results, best_model)
    print("Rolling-origin backtest (avg WAPE across categories x folds):")
    for _, r in summary.iterrows():
        marker = "  <-- winner" if r["model"] == best_model else ""
        print(f"  {r['model']:<16} {r['avg_wape']:.1%}{marker}")

    # forward forecast with the winning model
    fwd = []
    for cat, g in demand.groupby("category"):
        series = g.set_index("date")["units"]
        fc = MODELS[best_model](series, HORIZON)
        dates = pd.date_range(series.index[-1] + pd.Timedelta(days=1), periods=HORIZON)
        fwd.append(pd.DataFrame({
            "category": cat, "date": dates.date,
            "forecast_units": np.round(fc, 1), "model": best_model}))
    pd.concat(fwd, ignore_index=True).to_csv(OUT / "forecast_next_28d.csv", index=False)

    # README chart: last fold, biggest category, all three models vs actual
    biggest = demand.groupby("category")["units"].sum().idxmax()
    series = demand[demand["category"] == biggest].set_index("date")["units"]
    cutoff = len(series) - HORIZON
    train, actual = series.iloc[:cutoff], series.iloc[cutoff:]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ctx = series.iloc[-HORIZON * 3:]
    ax.plot(ctx.index[:-HORIZON], ctx.values[:-HORIZON], color="#5A6570",
            lw=1.2, label="history")
    ax.plot(actual.index, actual.values, color="#12436D", lw=2, label="actual")
    palette = {"seasonal_naive": "#A285D1", "moving_avg_28d": "#F46A25",
               "holt_winters": "#28A197", "gradient_boosted": "#801650"}
    for name, fn in MODELS.items():
        fc = fn(train, HORIZON)
        w = wape(actual.values, fc)
        ax.plot(actual.index, fc, color=palette[name], lw=1.6, ls="--",
                label=f"{name} (WAPE {w:.0%})")
    ax.set_title(f"Demand forecast backtest — {biggest} (final 28-day fold)",
                 fontsize=11, fontweight="bold", color="#12436D", loc="left")
    ax.set_ylabel("units shipped/day")
    ax.legend(frameon=False, fontsize=8, ncol=2)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "forecast_vs_actual.png", dpi=130)
    print(f"\nwrote backtest_results.csv, forecast_next_28d.csv ({best_model}), "
          f"forecast_vs_actual.png -> {OUT}")


if __name__ == "__main__":
    main()
