"""Collect dated Okama macro data and base-currency portfolio samples for synthetic examples."""

import argparse
import json
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import okama as ok
import pandas as pd
from okama.common.helpers.helpers import Float

CURRENCIES = {
    "USD": ("US_EFFR.RATE", "USDRUB.FX"),
    "RUB": ("RUS_CBR.RATE", None),
    "CNY": ("CHN_LPR1.RATE", "CNYRUB.CBR"),
    "EUR": ("EU_DFR.RATE", "EURRUB.CBR"),
}


def collect(currency: str, as_of: str, last_month: str) -> dict[str, Any]:
    """Keep original symbols, observation dates and methods alongside values."""
    symbol, fx = CURRENCIES[currency]
    inflation = ok.Inflation(f"{currency}.INFL", first_date="2016-09", last_date="2026-08")
    table = inflation.describe(years=(10,))
    mean = float(table.loc[(table.property == "annual inflation") & (table.period == "10 years"),
                           f"{currency}.INFL"].iloc[0])
    entry = {
        "currency": currency, "inflation_rate": mean, "inflation_period": ["2016-09", "2026-08"],
        "inflation_method": "okama.Inflation.describe(years=(10,)): annual inflation, geometric annual mean",
        "risk_free_rate": None, "rate_symbol": symbol, "rate_date": None,
        "fx_rub_per_unit": 1.0, "fx_date": as_of, "portfolios": {},
    }
    for field, code, endpoint in (("risk_free_rate", symbol, "macro"), ("fx_rub_per_unit", fx, "close")):
        if code is None:
            continue
        url = f"https://api.okama.io/api/ts/{endpoint}/{code}?first_date=2026-10-01&last_date={as_of}&period=D"
        with urlopen(url, timeout=30) as response:
            series = pd.read_csv(StringIO(response.read().decode()), index_col=0).iloc[:, 0].dropna()
        entry[field] = float(series.iloc[-1])
        entry["rate_date" if endpoint == "macro" else "fx_date"] = str(series.index[-1])
        entry[f"{field}_source"] = url
    if currency == "CNY":
        entry["rate_kind"] = "one-year lending prime rate (user-selected reference)"
    for stage, weights in (("accumulation", [.6, .3, .1]), ("withdrawal", [.3, .6, .1])):
        portfolio = ok.Portfolio(["SPY.US", "AGG.US", "GLD.US"], weights=weights, ccy=currency,
                                 first_date="2016-09", last_date=last_month, inflation=False)
        returns = portfolio.ror
        entry["portfolios"][stage] = {
            "assets": ["SPY.US", "AGG.US", "GLD.US"], "weights": weights, "currency": currency,
            "start_month": str(returns.index[0]), "end_month": str(returns.index[-1]),
            "monthly_returns": [float(value) for value in returns],
            "annual_return": float(Float.annualize_return(returns.mean())),
            "annual_risk": float(Float.annualize_risk(returns.std(), returns.mean())),
            "cagr": float(portfolio.get_cagr().iloc[-1, 0]), "rebalancing": "monthly",
            "method": "okama.Portfolio: monthly total returns converted to base currency; "
                      "Monte Carlo normal moments annualized using okama.common.helpers.helpers.Float",
        }
    return entry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "tmp" / "currency-assumptions")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    snapshots = {"as_of": "2026-10-09", "currencies": {}}
    for currency in CURRENCIES:
        snapshots["currencies"][currency] = collect(currency, "2026-10-09", "2026-09")
    path = args.output_dir / "currency-assumptions.json"
    path.write_text(json.dumps(snapshots, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
