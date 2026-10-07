# Retirement consumption utility

`okama_planner.utility` provides pure certainty-equivalent (CE) and Gamma
calculations, plus a callback-based equivalent-alpha solver. These helpers are
not connected to the forecast engine, MCP tools, or reports. They do not obtain
consumption from wealth percentiles or promised withdrawals.

Supply a finite, nonnegative NumPy array of shape **(months, paths)**. Both
dimensions must be positive. Each column is an equally likely shared market
trajectory; each row is one month in a fixed common retirement horizon. Values
are **actually funded real monthly consumption** in the same currency and price
basis for both plans. The caller must establish which taxes, fees, guaranteed
income, and household cash are included in these values. No mortality or
survival-probability assumptions are made here.

## Explicit preferences and certainty equivalent

All three `ConsumptionPreferences` fields are mandatory and finite:

- `elasticity > 0`: intertemporal substitution parameter;
- `risk_tolerance > 0`: tolerance of risk across paths;
- `annual_discount_rate > -1`: annual effective subjective discount rate.

No preference values are selected automatically. The model is frozen and
rejects extra fields. Higher elasticity and risk tolerance increase the
corresponding power-mean exponents. Preference sensitivity is a model choice,
separate from sampling uncertainty.

For month `m = 1, …, H`, use normalized time weights proportional to
`(1 + annual_discount_rate) ** (-m / 12)`. With
`p = (elasticity - 1) / elasticity`, the equivalent monthly consumption for
path `i` is the weighted power mean:

```text
II_i = (sum_m w_m * c_mi**p) ** (1/p)
```

Then use equally weighted paths and `r = (risk_tolerance - 1) / risk_tolerance`:

```text
CE = (sum_i II_i**r / paths) ** (1/r)
```

A zero exponent uses the geometric mean. At zero consumption, a nonpositive
power mean is zero by continuous extension; positive powers retain the zero's
weight. Depleted paths are never removed or replaced with an epsilon. A single
zero month therefore makes its path equivalent zero when `elasticity <= 1`;
a single zero path makes CE zero when `risk_tolerance <= 1`.

The implementation uses logarithms, extended-precision intermediate arithmetic,
and a cancellation-resistant geometric limit. Every mean, including the
geometric limit, is bounded to its input range to contain floating point
roundoff at the finite-number boundary. It does not mutate inputs.
`CEResult` contains `value`, `path_equivalents`, `zero_paths` (the number of
zero path equivalents), and `months`. The path-equivalent array has immutable
backing storage.

Independent controls: with zero discount and both preferences `0.5`, the matrix
`[[1, 2], [3, 4]]` has path equivalents `[1.5, 8/3]` and CE `1.92`. With both
preferences `1`, its CE is `24**0.25`. With annual discount `4095`, two monthly
values `[1, 4]` have normalized time weights `[2/3, 1/3]` and harmonic CE `4/3`.

## Gamma and paired-path uncertainty

`compare_consumption` requires identical shapes and returns:

```text
gamma = variant_ce / baseline_ce - 1
```

The result contains `baseline_ce`, `variant_ce`, `gamma`, `reason`,
`standard_error`, `confidence_interval`, and `undefined_replicates`. All scalar
numeric fields are finite or `None`. When baseline CE is zero, `gamma=None` and
`reason="zero_baseline_ce"`, including identical all-zero plans. A ratio beyond
finite float range gives `reason="nonfinite_gamma"`. Positive identical plans
have Gamma zero; doubling consumption gives Gamma one.

`bootstrap_replicates=0` disables sampling uncertainty. At least two replicates
are required when enabled. Counts must be nonboolean integers; seeds must be
nonnegative nonboolean integers. Validation applies even when bootstrap is off.
A local NumPy generator resamples path indices with replacement, using the same
indices for both matrices. It never changes the global random state. Each
replicate recomputes CE and Gamma. The reported standard error is the sample
standard deviation (`ddof=1`) and the confidence interval uses the 2.5th and
97.5th percentiles. These estimate uncertainty over supplied independent paths;
they do not estimate preference or model uncertainty.

An undefined point Gamma suppresses both uncertainty statistics even if every
bootstrap replicate happens to be defined. Bootstrap still runs and preserves
the actual count of undefined replicates. Any undefined replicate also
suppresses both uncertainty statistics and is counted
in `undefined_replicates`. No undefined replicate is silently omitted. Statistics
that cannot be represented as finite floats are also unavailable. Identical
positive plans have standard error zero and interval `(0, 0)`.

## Equivalent alpha

`equivalent_alpha` solves
`CE(evaluate_baseline(alpha)) - target_ce = 0` with SciPy's Brent solver.
`target_ce` must be finite and positive, `bracket` must be a tuple of finite
increasing endpoints, `tolerance` must be finite and positive, and
`max_iterations` must be a positive nonboolean integer. Tolerance is the
solver's absolute **alpha** tolerance, not a bound on consumption residual;
the result reports the actual residual separately. SciPy's relative tolerance
also applies.

The callback receives an annual expected-return shift and supplies funded
consumption. **The caller must document and implement its exact annual-return
overlay convention**, retain shared market paths, and hold all non-return
inputs fixed. This module does not invent a monthly return transformation or
rerun an investment engine. Matrix shapes must agree across all callback
evaluations. Determinism, units, and shared-path identity are caller obligations;
shape checks alone cannot establish them.

`AlphaResult` contains `alpha`, `residual`, `reason`, and `iterations`. A target
matching CE at alpha zero returns exactly zero if zero is inside the bracket.
Endpoint roots return their endpoint with zero solver iterations. Negative
alpha is supported. A zero callback CE is mathematically valid, although a
positive target has no root if all bracket evaluations are zero.

Unavailable roots have `alpha=None`, `residual=None`, and an explicit reason:
`no_root`, `invalid_consumption`, `inconsistent_shape`, `invalid_ce`,
`callback_error`, or `iteration_limit`. For failures before a completed solve,
`iterations=0`; iteration exhaustion reports the solver iteration count.
Invalid solver arguments raise `ValueError`. The solver requires a bracketed
continuous objective; it neither establishes monotonicity nor searches outside
the bracket. It returns one bracketed root, without asserting uniqueness.

## Method source and limits

The nested power means follow Appendix A of Blanchett and Kaplan's
[2013 Morningstar Gamma paper](https://www.morningstar.com/content/dam/marketing/shared/research/foundational/677796-AlphaBetaGamma.pdf).
A fixed horizon without mortality weights, monthly annual-rate discounting,
and paired-path bootstrap are explicit adaptations used by this module.
The paper's published Gamma and alpha figures are not constants for other plans.
This helper supplies arithmetic over caller-provided funded consumption; it
provides no complete forecast integration or investment recommendation.
