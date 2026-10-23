"""Isolated console EXE acceptance harness, not a production strategy entry point."""

from dataclasses import asdict
import json
from pathlib import Path
import sys
import tempfile

import pandas as pd

from stock_tool.application.scenario_research import (
    ALGORITHM,
    Rules,
    ScenarioBlocked,
    digest,
    run,
)
from stock_tool.application.scenario_store import replay, save


def main():
    dates = pd.bdate_range("2020-01-01", periods=30).strftime("%Y-%m-%d").tolist()
    closes = [100 + i * 0.1 for i in range(24)] + [105, 106, 106, 100, 100, 100]
    prices = [
        {
            "date": d,
            "market": "TWSE",
            "symbol": "SYNTH_SMOKE",
            "open": c,
            "high": c + 0.5,
            "low": c - 0.5,
            "close": c,
            "volume": 200 if i == 24 else 100,
        }
        for i, (d, c) in enumerate(zip(dates, closes))
    ]
    identity = {"market": "TWSE", "symbol": "SYNTH_SMOKE", "type": "ordinary_share"}
    request = {
        "purpose": "synthetic_validation",
        "identity": identity,
        "prices": prices,
        "rules": asdict(Rules()),
        "evaluation_start": dates[24],
        "evaluation_end": dates[-1],
        "allocation": 0.25,
        "initial_cash": 100000.0,
        "costs": {
            "commission_rate": 0.001425,
            "tax_rate": 0.003,
            "slippage_rate": 0.001,
            "min_commission": 1.0,
        },
        "qualification": {
            "binding": {
                "identity": identity,
                "warmup_start": dates[0],
                "evaluation_start": dates[24],
                "evaluation_end": dates[-1],
                "prices_digest": digest(prices),
                "algorithm": ALGORITHM,
            },
            "status": "synthetic_only",
            "coverage": "synthetic_only",
            "source": "deterministic_fixture",
            "calendar": dates,
            "initial_state": "listed_unrestricted",
            "actions": [],
        },
    }
    if len(sys.argv) == 3 and sys.argv[1] == "--replay":
        result = replay(Path(sys.argv[2]))
        print(json.dumps({"replayed": True, "formal_research": result["formal_research"]}))
        return
    root = Path(tempfile.mkdtemp(prefix="stocktool-scenario-synthetic-"))
    path = save(root, request)
    result = replay(path)
    counts = result["result"]["variants"]["control"]["counts"]
    assert counts["fill_count"] == 2 and counts["closed_round_trip_count"] == 1
    assert counts["open_positions"] == 0
    request["purpose"] = "formal_research"
    try:
        run(request)
    except ScenarioBlocked:
        blocked = True
    else:
        raise AssertionError("formal gate unexpectedly open")
    print(
        json.dumps(
            {
                "synthetic_smoke": "PASS",
                "formal_gate_blocked": blocked,
                "package": str(path),
                "counts": counts,
            }
        )
    )


if __name__ == "__main__":
    main()
