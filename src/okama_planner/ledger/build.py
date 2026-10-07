"""Stitch the ledger together. Every rule lives in its own module; this file only orders them."""

from __future__ import annotations


from okama_planner.asset_classes import AssetClass
from okama_planner.horizon import InvalidPlanHorizonError, effective_horizon_years
from okama_planner.inputs import AssetIn, PlanInputs
from okama_planner.ledger.budget import budget_lines
from okama_planner.ledger.buffer import BufferResult, run_buffer, split_buffer
from okama_planner.ledger.calendar import horizon_months, month_index, month_key, year_index
from okama_planner.ledger.goal_savings import run_goal_savings
from okama_planner.ledger.goals import AcquiredAsset, AssetSale, expand_goals, is_savings_goal
from okama_planner.ledger.mortgage import liability_track, mortgage_lines
from okama_planner.ledger.types import Ledger, LedgerLine, ReservePurpose
from okama_planner.rates import RateSubject, resolve_rate

_FREE_FLOW_KINDS = frozenset({"income", "expense", "mortgage_payment", "goal_outflow", "asset_sale"})


RetirementBeyondHorizonError = InvalidPlanHorizonError


class ConflictingReserveRatesError(ValueError):
    """Two reserve assets carry different rates; summing their balances needs exactly one."""


class UnknownAssetClassError(ValueError):
    """An asset's class is outside the known set — its money would otherwise vanish untracked."""


class SavingsAssetRateError(ValueError):
    """A savings asset carries its own rate; the purchase reserve has only ``buffer_rate``."""


class UnknownSoldAssetError(ValueError):
    """A goal replaces an asset the plan has no single ``non_working`` asset for."""


class DuplicateAssetSaleError(ValueError):
    """Two goals sell the same asset; it can only leave the balance once."""


_VALID_ASSET_CLASSES = frozenset(member.value for member in AssetClass)


def _monthly_factor(annual_rate: float) -> float:
    return (1.0 + annual_rate) ** (1.0 / 12.0)


def _liability_totals(inputs: PlanInputs, months: int) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Sum the balance and principal repaid across all liabilities for each month."""
    liability_balance = [0.0] * months
    principal_repaid = [0.0] * months
    for liability in inputs.liabilities:
        balance, repaid = liability_track(liability, inputs.t0, months)
        for n in range(months):
            liability_balance[n] += balance[n]
            principal_repaid[n] += repaid[n]
    return tuple(liability_balance), tuple(principal_repaid)


def _kept_budget_lines(
    inputs: PlanInputs, budget: tuple[LedgerLine, ...], retirement_index: int
) -> tuple[LedgerLine, ...]:
    """The budget lines the ledger keeps. With a pension goal and the rule the family expenses
    stop being expenses the month retirement starts: from then on they are the pension goal's
    stream — a share of them, or the goal's own sum — and never withdrawn beside it."""
    replaced = inputs.pension_replaces_expenses and any(
        goal.kind == "retirement_income" for goal in inputs.goals
    )
    if not replaced:
        return budget
    return tuple(
        line
        for line in budget
        if not (line.line_kind == "expense" and month_index(inputs.t0, line.month) >= retirement_index)
    )


def _validate_assets(inputs: PlanInputs) -> None:
    for asset in inputs.assets:
        if asset.asset_class not in _VALID_ASSET_CLASSES:
            raise UnknownAssetClassError(
                f"{asset.label}: unknown asset_class {asset.asset_class!r}; "
                f"expected one of {sorted(_VALID_ASSET_CLASSES)!r}"
            )
        if asset.asset_class == AssetClass.SAVINGS.value and asset.growth_rate is not None:
            raise SavingsAssetRateError(
                f"{asset.label}: a savings asset grows at buffer_rate and cannot carry "
                f"its own growth_rate {asset.growth_rate!r}"
            )


def build_ledger(inputs: PlanInputs) -> Ledger:
    """Turn the frozen input into the monthly ledger of nominal amounts."""
    months = horizon_months(effective_horizon_years(inputs))
    keys = tuple(month_key(inputs.t0, n) for n in range(months))
    retirement_index = year_index(inputs.t0, inputs.retirement_year)

    _validate_assets(inputs)

    budget = budget_lines(inputs.budget_items, inputs.t0, months, retirement_index, inputs.rates)
    lines: list[LedgerLine] = list(_kept_budget_lines(inputs, budget, retirement_index))
    for liability in inputs.liabilities:
        lines.extend(mortgage_lines(liability, inputs.t0, months))
    expansion = expand_goals(
        inputs.goals,
        inputs.t0,
        months,
        retirement_index,
        inputs.rates,
        expenses=budget if inputs.pension_replaces_expenses else None,
    )
    lines.extend(expansion.lines)
    sale_lines = _asset_sale_lines(inputs, keys, expansion.sold)
    lines.extend(sale_lines)

    free_flow = [0.0] * months
    index_of = {key: n for n, key in enumerate(keys)}
    for line in lines:
        if line.line_kind in _FREE_FLOW_KINDS:
            free_flow[index_of[line.month]] += line.amount
    purchases = _savings_purchases(inputs, index_of, expansion.lines, expansion.sold, sale_lines)
    savings = _savings_outflows(months, purchases)

    reserve_lines, reserve_balance = _run_reserve(inputs, months, keys, expansion.reserve_targets)
    for line in reserve_lines:
        free_flow[index_of[line.month]] += line.amount
    lines.extend(reserve_lines)
    savings_on_hand = sum(
        asset.amount for asset in inputs.assets if asset.asset_class == AssetClass.SAVINGS.value
    )
    buffer_result, buffer_by_goal, goal_shares = _purchase_buffer(
        inputs,
        free_flow,
        purchases,
        savings,
        savings_on_hand,
        retirement_index,
    )
    lines.extend(buffer_result.lines)

    flow_lines = tuple(
        LedgerLine(keys[n], "portfolio_flow", "Поток в портфель", amount)
        for n, amount in enumerate(buffer_result.portfolio_flow)
    )
    lines.extend(flow_lines)

    liability_balance, principal_repaid = _liability_totals(inputs, months)

    return Ledger(
        t0=inputs.t0,
        months=keys,
        lines=tuple(lines),
        portfolio_flow={line.month: line.amount for line in flow_lines},
        buffer_balance=buffer_result.balance,
        reserve_balance=reserve_balance,
        non_working_balance=_non_working_track(inputs, months, expansion.acquired, expansion.sold),
        liability_balance=tuple(liability_balance),
        principal_repaid=tuple(principal_repaid),
        buffer_by_goal=buffer_by_goal,
        goal_portfolio_shares=goal_shares,
    )


def _purchase_buffer(
    inputs: PlanInputs,
    free_flow: list[float],
    purchases: list[tuple[str, int, float]],
    savings: list[float] | None,
    opening: float,
    retirement_index: int,
) -> tuple[BufferResult, tuple[ReservePurpose, ...], dict[str, float]]:
    if inputs.savings_mode == "separate":
        result, parts, shares = run_goal_savings(
            inputs,
            free_flow,
            purchases,
            opening,
            retirement_index,
        )
        # A purchase paid entirely by an asset sale also costs its own account/portfolio zero.
        all_shares = {goal.label: 0.0 for goal in inputs.goals if is_savings_goal(goal, inputs)}
        all_shares.update(shares)
        return result, parts, all_shares
    result = run_buffer(
        free_flow,
        inputs.t0,
        inputs.buffer_lookahead_months,
        inputs.rates.buffer_rate,
        opening_balance=opening,
        savings_outflows=savings,
        retirement_month=retirement_index if inputs.reserves_until_retirement else None,
    )
    parts = split_buffer(result.balance, purchases) if inputs.reserves_until_retirement else ()
    return result, parts, {}


def _savings_purchases(
    inputs: PlanInputs,
    index_of: dict[str, int],
    goal_lines: tuple[LedgerLine, ...],
    sold: tuple[AssetSale, ...],
    sale_lines: list[LedgerLine],
) -> list[tuple[str, int, float]]:
    """Each savings goal as ``(label, month, amount the buffer saves for it)``: its outflow, net of
    the proceeds of the asset it replaces (the old car pays part of the new one, so only the rest
    is put aside). A purchase fully paid off by that sale saves nothing and is left out — adding a
    zero to the savings series the buffer targets would not change it, but keeping the entry would
    give it a ``ReservePurpose`` of its own in the workbook."""
    savings_labels = {goal.label for goal in inputs.goals if is_savings_goal(goal, inputs)}
    proceeds = {sale.goal_label: line.amount for sale, line in zip(sold, sale_lines, strict=True)}
    purchases = []
    for line in goal_lines:
        if line.line_kind != "goal_outflow" or line.label not in savings_labels:
            continue
        amount = max(0.0, -line.amount - proceeds.get(line.label, 0.0))
        if amount > 0.0:
            purchases.append((line.label, index_of[line.month], amount))
    return purchases


def _savings_outflows(months: int, purchases: list[tuple[str, int, float]]) -> list[float] | None:
    """What the buffer saves for from the first month, per month. None when no goal qualifies."""
    if not purchases:
        return None
    series = [0.0] * months
    for _, month, amount in purchases:
        series[month] += amount
    return series


def _run_reserve(
    inputs: PlanInputs,
    months: int,
    keys: tuple[str, ...],
    reserve_targets: tuple[tuple[int, float, int | None], ...],
) -> tuple[list[LedgerLine], tuple[float, ...]]:
    """Track the reserve fund and emit the top-ups that bring it to its targets.

    The conflict check is decided over EXPLICITLY supplied rates only. A blank
    (``growth_rate is None``) is silence, not a stated 5%: it inherits whatever single explicit
    rate the other reserve assets carry, and only falls back to ``resolve_rate``'s own default
    when nothing was stated at all. Resolving blanks to the fallback first (round 1's mistake)
    made an unrelated default "conflict" with a rate the client actually typed.
    """
    reserve_assets = [asset for asset in inputs.assets if asset.asset_class == "reserve"]
    balance = sum(asset.amount for asset in reserve_assets)
    explicit_rates = {asset.growth_rate for asset in reserve_assets if asset.growth_rate is not None}
    if len(explicit_rates) > 1:
        raise ConflictingReserveRatesError(
            f"reserve assets carry conflicting rates {sorted(explicit_rates)!r}; "
            "the reserve fund is tracked as one balance and needs exactly one stated rate"
        )
    explicit_rate = next(iter(explicit_rates), None)
    rate = resolve_rate(RateSubject.ASSET_RESERVE, explicit_rate, inputs.rates)
    factor = _monthly_factor(rate)
    # A reserve_topup is a LEVEL the fund must reach («доведение резервного фонда до целевого
    # размера»), not a contribution to add — two goals landing in the same month are both
    # satisfied by the larger target, and a plain dict(...) would keep only whichever pair the
    # goals happened to be entered last, silently dropping the other client's stated goal.
    targets: dict[int, tuple[float, int | None]] = {}
    for month, amount, goal_id in reserve_targets:
        current = targets.get(month)
        if current is None or amount > current[0]:
            targets[month] = (amount, goal_id)

    lines: list[LedgerLine] = []
    track: list[float] = []
    for n in range(months):
        if n > 0:
            balance *= factor
        target = targets.get(n)
        if target is not None and balance < target[0]:
            topup = target[0] - balance
            balance = target[0]
            lines.append(
                LedgerLine(keys[n], "reserve_topup", "Резервный фонд", -topup, rate, goal_id=target[1])
            )
        track.append(balance)
    return lines, tuple(track)


def _sold_asset(inputs: PlanInputs, sale: AssetSale) -> AssetIn:
    """The one ``non_working`` asset a sale names. Labels are not unique in the input, so a label
    matching two assets is refused rather than resolved to whichever came first."""
    matches = [asset for asset in inputs.assets if asset.label == sale.asset_label]
    non_working = [asset for asset in matches if asset.asset_class == "non_working"]
    if len(non_working) == 1:
        return non_working[0]
    if not matches:
        raise UnknownSoldAssetError(
            f"{sale.goal_label}: replaces_asset {sale.asset_label!r} names no asset of the plan"
        )
    if not non_working:
        classes = sorted({asset.asset_class for asset in matches})
        raise UnknownSoldAssetError(
            f"{sale.goal_label}: replaces_asset {sale.asset_label!r} is {classes!r}, not non_working — "
            "only property outside the portfolio can be sold into it"
        )
    raise UnknownSoldAssetError(
        f"{sale.goal_label}: replaces_asset {sale.asset_label!r} matches two or more non_working assets; "
        "give them distinct labels"
    )


def _asset_sale_lines(
    inputs: PlanInputs, keys: tuple[str, ...], sold: tuple[AssetSale, ...]
) -> list[LedgerLine]:
    """Price every sale: the asset's value in the sale month, at the asset's own rate, as an inflow.

    The proceeds are a household flow like a salary — they reach the portfolio through the free
    cash flow and the buffer; the purchase they pay for is still a full ``goal_outflow``.
    """
    lines: list[LedgerLine] = []
    seen: set[str] = set()
    for sale in sold:
        asset = _sold_asset(inputs, sale)
        if asset.label in seen:
            raise DuplicateAssetSaleError(
                f"{sale.goal_label}: asset {asset.label!r} is already sold by another goal"
            )
        seen.add(asset.label)
        rate = resolve_rate(RateSubject.ASSET_NON_WORKING, asset.growth_rate, inputs.rates)
        value = asset.amount * _monthly_factor(rate) ** sale.month_index
        lines.append(LedgerLine(keys[sale.month_index], "asset_sale", asset.label, value, rate))
    return lines


def _non_working_track(
    inputs: PlanInputs,
    months: int,
    acquired: tuple[AcquiredAsset, ...],
    sold: tuple[AssetSale, ...] = (),
) -> tuple[float, ...]:
    """Non-working assets: in the net worth, out of the portfolio, each on its own rate. A sold
    asset counts up to the month before its sale; from the sale month its value is in the ledger
    as ``asset_sale`` proceeds instead."""
    sold_until = {_sold_asset(inputs, sale).label: sale.month_index for sale in sold}
    holdings: list[tuple[int, int, float, float]] = [
        (
            0,
            sold_until.get(asset.label, months),
            asset.amount,
            resolve_rate(RateSubject.ASSET_NON_WORKING, asset.growth_rate, inputs.rates),
        )
        for asset in inputs.assets
        if asset.asset_class == "non_working"
    ]
    holdings.extend((item.month_index, months, item.value, item.growth_rate) for item in acquired)

    track = [0.0] * months
    for start, stop, value, rate in holdings:
        factor = _monthly_factor(rate)
        for n in range(start, stop):
            track[n] += value * factor ** (n - start)
    return tuple(track)
