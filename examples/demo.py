"""Run two synthetic forecasts offline; this is a usage example, not a product CLI."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from okama_planner import ForecastRequest, forecast


def main() -> None:
    source = Path(__file__).parent
    request = json.loads((source / "family.json").read_text())
    deferred = deepcopy(request)
    deferred["plan"]["goals"][0]["target_year"] = 2029
    output = Path.cwd() / "tmp" / "planner-demo"
    output.mkdir(parents=True, exist_ok=True)
    for name, data in (("baseline", request), ("deferred", deferred)):
        result = forecast(data)
        (output / f"{name}-result.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        (output / f"{name}-request.json").write_text(json.dumps(data, indent=2) + "\n")
        print(f"{name}: {json.dumps(result['metrics'], sort_keys=True)}")
    (output / "request-schema.json").write_text(
        json.dumps(ForecastRequest.model_json_schema(), indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
