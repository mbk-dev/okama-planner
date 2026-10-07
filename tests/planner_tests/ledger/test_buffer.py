"""The buffer: a deficit is funded from money set aside earlier, not by selling the portfolio."""

from __future__ import annotations

import pytest

from okama_planner.ledger.buffer import run_buffer, split_buffer
from okama_planner.ledger.types import ReservePurpose


def test_a_surplus_tops_the_buffer_up_first_and_invests_the_remainder() -> None:
    # Lookahead 2: month 0 sees the -150 of month 2, so it targets 150 and can only set aside 100.
    result = run_buffer([100.0, 100.0, -150.0, 50.0], t0="2026-08", lookahead_months=2, buffer_rate=0.0)

    assert result.balance == pytest.approx([100.0, 150.0, 0.0, 0.0])
    assert result.portfolio_flow == pytest.approx([0.0, 50.0, 0.0, 50.0])


def test_the_buffer_absorbs_the_deficit_so_the_portfolio_is_untouched() -> None:
    result = run_buffer([100.0, 100.0, -150.0, 50.0], t0="2026-08", lookahead_months=2, buffer_rate=0.0)

    assert result.portfolio_flow[2] == pytest.approx(0.0)
    assert [line.line_kind for line in result.lines if line.month == "2026-10"] == ["buffer_out"]


def test_a_shortfall_is_withdrawn_from_the_portfolio_and_never_vanishes() -> None:
    # Lookahead 1: month 0 targets 200 but only has 50 to set aside.
    result = run_buffer([50.0, -200.0], t0="2026-08", lookahead_months=1, buffer_rate=0.0)

    assert result.balance == pytest.approx([50.0, 0.0])
    assert result.portfolio_flow == pytest.approx([0.0, -150.0])


def test_the_buffer_earns_its_rate_month_by_month() -> None:
    # A -200 deficit two months out keeps the target above the balance, so nothing is released
    # and the growth survives into month 1.
    result = run_buffer([100.0, 0.0, -200.0], t0="2026-08", lookahead_months=2, buffer_rate=0.12)

    monthly_factor = 1.12 ** (1 / 12)
    assert result.balance[0] == pytest.approx(100.0)
    assert result.balance[1] == pytest.approx(100.0 * monthly_factor)
    assert result.balance[1] == pytest.approx(100.948879, abs=1e-5)


def test_a_zero_target_sends_the_whole_surplus_to_the_portfolio() -> None:
    result = run_buffer([100.0, 100.0], t0="2026-08", lookahead_months=12, buffer_rate=0.0)

    assert result.balance == pytest.approx([0.0, 0.0])
    assert result.portfolio_flow == pytest.approx([100.0, 100.0])


def test_an_opening_balance_above_the_target_is_released_to_the_portfolio() -> None:
    result = run_buffer([0.0, 0.0], t0="2026-08", lookahead_months=1, buffer_rate=0.0, opening_balance=500.0)

    assert result.balance == pytest.approx([0.0, 0.0])
    assert result.portfolio_flow == pytest.approx([500.0, 0.0])


def test_lines_carry_the_month_key_and_the_right_kinds() -> None:
    result = run_buffer([100.0, -50.0], t0="2026-08", lookahead_months=1, buffer_rate=0.0)

    kinds = {(line.month, line.line_kind) for line in result.lines}
    assert ("2026-08", "buffer_in") in kinds
    assert ("2026-09", "buffer_out") in kinds


def test_line_amounts_and_labels_are_hand_computed_not_just_kind_and_month() -> None:
    """The persisted rows are read by later phases — kind and month alone do not pin them.

    Hand-traced: month 0 sets aside 100 of the 100 free (target 150 from the -150 two months
    out), month 1 tops up the remaining 50 needed, month 2's -150 deficit is paid entirely from
    the 150 banked, month 3's window is empty so nothing moves and no line is emitted.
    """
    result = run_buffer([100.0, 100.0, -150.0, 50.0], t0="2026-08", lookahead_months=2, buffer_rate=0.0)

    by_month = {line.month: line for line in result.lines}
    assert len(result.lines) == 3
    assert set(by_month) == {"2026-08", "2026-09", "2026-10"}

    assert by_month["2026-08"].line_kind == "buffer_in"
    assert by_month["2026-08"].amount == pytest.approx(100.0)
    assert by_month["2026-08"].label == "Резерв на покупку"

    assert by_month["2026-09"].line_kind == "buffer_in"
    assert by_month["2026-09"].amount == pytest.approx(50.0)

    assert by_month["2026-10"].line_kind == "buffer_out"
    assert by_month["2026-10"].amount == pytest.approx(-150.0)
    assert by_month["2026-10"].label == "Резерв на покупку"


def test_a_funded_shortfall_emits_a_negative_buffer_out() -> None:
    """The 'funded from the buffer' shape of buffer_out, distinct from the 'released' shape."""
    result = run_buffer([50.0, -200.0], t0="2026-08", lookahead_months=1, buffer_rate=0.0)

    line = next(line for line in result.lines if line.month == "2026-09")
    assert line.line_kind == "buffer_out"
    # 50 was banked in month 0; the 200 deficit draws exactly that much from the buffer.
    assert line.amount == pytest.approx(-50.0)


def test_a_released_excess_also_emits_a_negative_buffer_out() -> None:
    """The 'released back to the portfolio because the target dropped' shape of buffer_out."""
    result = run_buffer([0.0, 0.0], t0="2026-08", lookahead_months=1, buffer_rate=0.0, opening_balance=500.0)

    line = next(line for line in result.lines if line.month == "2026-08")
    assert line.line_kind == "buffer_out"
    assert line.amount == pytest.approx(-500.0)
    assert line.label == "Резерв на покупку"


def test_a_savings_outflow_is_saved_for_from_the_start_not_from_the_lookahead() -> None:
    # A savings goal of 150 in month 3, lookahead 1: without ``savings_outflows`` the buffer sees
    # it only in month 2 and the portfolio pays the shortfall; with it the target is 150 from
    # month 0, the surplus fills it first, and the goal never touches the portfolio.
    free = [100.0, 100.0, 100.0, -150.0]

    plain = run_buffer(free, t0="2026-08", lookahead_months=1, buffer_rate=0.0)
    assert plain.portfolio_flow == pytest.approx([100.0, 100.0, 0.0, -50.0])

    saved = run_buffer(
        free, t0="2026-08", lookahead_months=1, buffer_rate=0.0, savings_outflows=[0.0, 0.0, 0.0, 150.0]
    )
    assert saved.balance == pytest.approx([100.0, 150.0, 150.0, 0.0])
    assert saved.portfolio_flow == pytest.approx([0.0, 50.0, 100.0, 0.0])


def test_a_savings_outflow_does_not_double_count_inside_the_lookahead_window() -> None:
    # Month 1 holds a 200 salary and the 150 goal: netted it is a surplus of 50, so the near-window
    # deficit is zero and the target is the goal alone, not 150 + something.
    result = run_buffer(
        [100.0, 50.0], t0="2026-08", lookahead_months=1, buffer_rate=0.0, savings_outflows=[0.0, 150.0]
    )

    assert result.balance == pytest.approx([100.0, 0.0])
    assert result.portfolio_flow == pytest.approx([0.0, 150.0])


def test_the_window_does_not_look_past_retirement() -> None:
    # Retirement at month 3. Month 0 sees only the -30 of month 2 (month 3 is past the cut-off),
    # sets 30 aside and invests 70; month 1 needs nothing more. From month 3 the portfolio pays.
    result = run_buffer(
        [100.0, 100.0, -30.0, -50.0, -50.0],
        t0="2026-08",
        lookahead_months=3,
        buffer_rate=0.0,
        retirement_month=3,
    )

    assert result.balance == pytest.approx([30.0, 30.0, 0.0, 0.0, 0.0])
    assert result.portfolio_flow == pytest.approx([70.0, 100.0, 0.0, -50.0, -50.0])


def test_without_a_retirement_month_the_window_saves_for_the_pension_as_before() -> None:
    # The same flow, no cut-off: month 0 targets 30 + 50 = 80, month 1 targets 130.
    result = run_buffer(
        [100.0, 100.0, -30.0, -50.0, -50.0], t0="2026-08", lookahead_months=3, buffer_rate=0.0
    )

    assert result.balance == pytest.approx([80.0, 130.0, 100.0, 50.0, 0.0])
    assert result.portfolio_flow == pytest.approx([20.0, 50.0, 0.0, 0.0, 0.0])


def test_what_is_left_at_retirement_goes_to_the_portfolio() -> None:
    # 500 on hand; 300 is kept for a purchase in month 2, the retirement month, so it is still
    # there when the buffer closes. m0: target 50 + 300, the 100 deficit leaves 400, 50 released.
    # m1: the 50 deficit leaves exactly the 300 target. m2: retirement releases the 300, which
    # pays the month's -300 itself.
    result = run_buffer(
        [-100.0, -50.0, -300.0],
        t0="2026-08",
        lookahead_months=1,
        buffer_rate=0.0,
        opening_balance=500.0,
        savings_outflows=[0.0, 0.0, 300.0],
        retirement_month=2,
    )

    assert result.balance == pytest.approx([350.0, 300.0, 0.0])
    assert result.portfolio_flow == pytest.approx([50.0, 0.0, 0.0])
    october_lines = [
        (line.month, line.line_kind, line.amount) for line in result.lines if line.month == "2026-10"
    ]
    assert october_lines == [("2026-10", "buffer_out", pytest.approx(-300.0))]


def test_the_buffer_is_split_by_purchase_in_order_of_their_months() -> None:
    # The house (month 4, 300) is listed first but the car (month 2, 150) is due first.
    # m0: car 100.   m1: car 150, house 100.   m2: the car is bought — house 300, rest 100.
    # m3: house 50.  m4: the house is bought — rest 70.
    parts = split_buffer([100.0, 250.0, 400.0, 50.0, 70.0], [("Дом", 4, 300.0), ("Авто", 2, 150.0)])

    assert parts == (
        ReservePurpose("Авто", pytest.approx((100.0, 150.0, 0.0, 0.0, 0.0))),
        ReservePurpose("Дом", pytest.approx((0.0, 100.0, 300.0, 50.0, 0.0))),
        ReservePurpose(None, pytest.approx((0.0, 0.0, 100.0, 0.0, 70.0))),
    )


def test_the_parts_add_up_to_the_balance_every_month_and_none_is_negative() -> None:
    balance = [0.0, 1e-9, 5.0, 123.456, 1_000.0, 0.0]
    parts = split_buffer(balance, [("A", 3, 50.0), ("B", 3, 60.0), ("C", 5, 10_000.0)])

    for month, total in enumerate(balance):
        assert sum(part.balance[month] for part in parts) == pytest.approx(total)
        assert all(part.balance[month] >= 0.0 for part in parts)


def test_equal_months_keep_the_order_of_the_input() -> None:
    parts = split_buffer([30.0], [("Второй", 5, 20.0), ("Первый", 5, 20.0)])

    assert [(part.goal_label, part.balance) for part in parts] == [
        ("Второй", (20.0,)),
        ("Первый", (10.0,)),
        (None, (0.0,)),
    ]
