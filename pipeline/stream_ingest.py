"""
Streaming ingest — Autoloader semantics, runnable on a laptop.

Real control towers don't wait for the nightly batch: order events land as
files (or Kafka/Event Hub messages) all day. The two properties that make
streaming file ingest production-safe are:

  1. incremental discovery  — only new files are processed, however often
                              the stream wakes up;
  2. exactly-once           — a file is ingested once, ever, tracked in a
                              checkpoint that survives restarts.

This module implements exactly those semantics over a landing directory,
with a file-ledger checkpoint — the same contract as Spark Structured
Streaming's file source (see notebooks/05_stream_ingest.py for the real
PySpark version that runs in Fabric; `cloudFiles`/Autoloader is the
Databricks flavor of the same idea).

Two trigger modes, mirroring Spark's:
    --drain            process everything new, then stop (trigger availableNow)
    --watch [seconds]  poll forever (processing-time trigger)

Malformed files are not fatal: schema-mismatched drops are ledgered as
rejected with a reason and never block healthy files — the streaming
counterpart of the batch quarantine pattern.

Demo:
    python pipeline/stream_ingest.py --make-demo-file 500   # simulate a source drop
    python pipeline/stream_ingest.py --drain                # ingest it, exactly once
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LANDING = ROOT / "data" / "stream_landing"
DEFAULT_LAKE = ROOT / "data" / "lake"


def _checkpoint_path(lake: Path) -> Path:
    p = lake / "checkpoints"
    p.mkdir(parents=True, exist_ok=True)
    return p / "stream_ingest.json"


def load_ledger(lake: Path) -> dict:
    cp = _checkpoint_path(lake)
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))
    return {"processed": {}, "rejected": {}}


def save_ledger(lake: Path, ledger: dict) -> None:
    _checkpoint_path(lake).write_text(json.dumps(ledger, indent=2), encoding="utf-8")


def discover_new_files(landing: Path, ledger: dict) -> list[Path]:
    """Incremental discovery: anything in the landing zone the ledger has
    never seen, in arrival order."""
    landing.mkdir(parents=True, exist_ok=True)
    seen = set(ledger["processed"]) | set(ledger["rejected"])
    return sorted(p for p in landing.glob("*.csv") if p.name not in seen)


def ingest_file(path: Path, lake: Path, ledger: dict) -> int:
    """Validate against the bronze data contract, append to the stream table,
    ledger the file. Returns rows ingested (0 if the file was rejected)."""
    from pipeline.data_contract import check_table, load_contract

    df = pd.read_csv(path)
    result = check_table(df, "fact_orders", load_contract())
    if result["breaking"]:
        # one bad drop rejects one file — the stream itself keeps flowing
        ledger["rejected"][path.name] = {
            "reason": f"contract violation: {result['breaking']}",
            "at": datetime.now(timezone.utc).isoformat(),
        }
        return 0

    target = lake / "bronze"
    target.mkdir(parents=True, exist_ok=True)
    out = target / "fact_orders_stream.parquet"
    df["_ingested_at"] = datetime.now(timezone.utc).isoformat()
    df["_source_file"] = path.name
    if out.exists():
        df = pd.concat([pd.read_parquet(out), df], ignore_index=True)
    df.to_parquet(out, index=False)

    ledger["processed"][path.name] = {
        "rows": int(len(df)),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    return len(df)


def drain(lake: Path, landing: Path = LANDING) -> dict:
    """Trigger availableNow: process every unseen file once, then stop."""
    ledger = load_ledger(lake)
    new_files = discover_new_files(landing, ledger)
    ingested = rejected = 0
    for f in new_files:
        rows = ingest_file(f, lake, ledger)
        if rows:
            ingested += 1
            print(f"[STRM] ingested  {f.name}")
        else:
            rejected += 1
            print(f"[STRM] REJECTED  {f.name} "
                  f"({ledger['rejected'][f.name]['reason']})")
    save_ledger(lake, ledger)
    print(f"[STRM] drain complete: {ingested} ingested, {rejected} rejected, "
          f"{len(ledger['processed'])} files total in ledger")
    return {"ingested": ingested, "rejected": rejected}


def make_demo_file(n_rows: int) -> Path:
    """Synthesize a source drop by sampling the batch dataset."""
    src = pd.read_csv(ROOT / "data" / "bronze" / "fact_orders.csv").sample(
        n_rows, random_state=int(time.time()) % 10_000)
    LANDING.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = LANDING / f"orders_{stamp}.csv"
    src.to_csv(out, index=False)
    print(f"[STRM] demo drop created: {out} ({n_rows} rows)")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lake-dir", default=str(DEFAULT_LAKE))
    ap.add_argument("--drain", action="store_true",
                    help="process all new files once, then exit (availableNow)")
    ap.add_argument("--watch", type=int, metavar="SECONDS",
                    help="poll the landing zone forever at this interval")
    ap.add_argument("--make-demo-file", type=int, metavar="N",
                    help="drop a synthetic N-row source file into the landing zone")
    args = ap.parse_args(argv)
    lake = Path(args.lake_dir)

    if args.make_demo_file:
        make_demo_file(args.make_demo_file)
        return 0
    if args.watch:
        print(f"[STRM] watching {LANDING} every {args.watch}s (Ctrl+C to stop)")
        while True:
            drain(lake)
            time.sleep(args.watch)
    drain(lake)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
