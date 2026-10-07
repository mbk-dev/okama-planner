# Joint monthly scenarios

`okama_planner.scenarios` samples aligned monthly observations for multiple
assets. It makes no network requests and performs no currency conversion.
All observations must already be in the plan currency. The first observation
belongs to `start_month`; later observations represent consecutive months.
Calendar alignment is the caller's responsibility. `start_month` must use the
`YYYY-MM` format with a month from `01` to `12`; `currency` must contain exactly
three uppercase Latin letters. Currency codes are checked for format only,
without a supported-currency whitelist.

```python
from okama_planner.scenarios import JointHistory, sample_joint_returns, weighted_returns

history = JointHistory(
    start_month="2020-01",
    currency="USD",
    method="synchronized_bootstrap",
    asset_returns={
        "A": (0.01, -0.02, 0.03, 0.00, 0.02, -0.01) * 2,
        "B": (-0.01, 0.02, -0.03, 0.00, -0.02, 0.01) * 2,
    },
)
scenarios = sample_joint_returns(history, months=120, paths=1000, seed=42)
portfolio = weighted_returns(scenarios, {"A": 0.5, "B": 0.5})
# portfolio has shape (120, 1000) and is zero for these opposite returns.
```

The method is required explicitly. Every asset must have a nonempty name and
at least 12 observations. Lengths must match; each monthly simple return must
be finite and at least -1. A return of -1 represents a total loss.
`JointHistory` is a frozen Pydantic model. Its observations are tuples and are
copied from caller input. Pydantic freezing does not freeze the nested asset
mapping; avoid editing that mapping. Sampling revalidates a snapshot before
using it.

The sampler draws one historical row with replacement for each forecast month
and path. Every asset uses that same row. This preserves the observed
within-month cross-asset relationships, including identical or opposite asset
returns. It does not preserve serial dependence between historical months.
Use the same `JointScenarios` object for all portfolio segments in a comparison.
Sampling independent histories for each segment would lose their dependence.

`JointScenarios.assets` is a sorted tuple of asset names. `returns` has shape
`(months, paths, assets)`, and `row_indices` has shape `(months, paths)` with
zero-based indices into the history. Both arrays returned by the sampler have
immutable backing storage. Positive integer dimensions and a nonnegative
integer seed are required; booleans are rejected. A local NumPy generator leaves
the global NumPy random state unchanged. With the same history, seed and
sampling dimensions, results repeat in the same NumPy environment, regardless
of the input asset mapping's key order.

`history_sha256` identifies the normalized history: start month, currency,
explicit method and sorted asset observations. It does not include seed or
sample dimensions and is not a unique identifier for a sampled run. The digest
uses SHA-256 over canonical UTF-8 JSON with sorted keys, compact separators,
finite numeric values and signed zero normalized to zero.

`weighted_returns` returns shape `(months, paths)` and assumes monthly
rebalancing to the supplied weights. Omitted assets have weight zero. Weights
must be finite, nonnegative and sum to one within an absolute tolerance of
`1e-12`, with no relative tolerance. Weights are used as supplied, without
normalization. Unknown assets are rejected even if their supplied weight is
zero. Invalid weights raise `ValueError`. The function changes neither its
weights mapping nor the scenario arrays. Fees, taxes and actual capital
allocation belong to the consuming simulation.
