"""Mortgage amortisation, checked against numbers computed by hand from the closed form."""

from __future__ import annotations

import pytest

from okama_planner.inputs import LiabilityIn
from okama_planner.ledger.mortgage import (
    Instalment,
    PaymentTooSmallError,
    amortisation_schedule,
    amortisation_table,
    liability_track,
    mortgage_lines,
)

# 1 000 000 at 12% a year (1% a month), paying 100 000 a month.
PRINCIPAL = 1_000_000.0
ANNUAL_RATE = 0.12
PAYMENT = 100_000.0


def test_the_first_payment_splits_into_interest_and_principal() -> None:
    schedule = amortisation_schedule(PRINCIPAL, ANNUAL_RATE, PAYMENT)

    assert schedule[0] == pytest.approx(PAYMENT)
    # 1 000 000 * 0.01 = 10 000 interest, so 90 000 goes to principal.
    assert sum(schedule) - PRINCIPAL > 0  # the excess is exactly the interest paid


def test_the_loan_closes_early_and_the_last_payment_is_partial() -> None:
    schedule = amortisation_schedule(PRINCIPAL, ANNUAL_RATE, PAYMENT)

    # Closed form: the balance after ten full payments, then one month of interest on it.
    balance_after_10 = PRINCIPAL * 1.01**10 - PAYMENT * (1.01**10 - 1) / 0.01
    expected_last = balance_after_10 * 1.01

    assert len(schedule) == 11
    assert schedule[-1] == pytest.approx(expected_last)
    assert expected_last == pytest.approx(58_984.88, abs=0.01)


def test_a_payment_short_of_the_term_runs_to_payoff_instead_of_dropping_the_balance() -> None:
    """Synthetic loan: continue to actual payoff rather than a declared ten-month term."""
    schedule = amortisation_schedule(1000.0, 0.12, 90.0)
    assert len(schedule) == 12
    r = 0.01
    balance_after_11 = 1000.0 * (1 + r) ** 11 - 90.0 * ((1 + r) ** 11 - 1) / r
    assert schedule[-1] == pytest.approx(balance_after_11 * (1 + r))
    assert sum(schedule) == pytest.approx(11 * 90.0 + balance_after_11 * (1 + r))


def test_a_payment_that_never_covers_the_interest_fails_loudly() -> None:
    with pytest.raises(PaymentTooSmallError, match="never covers interest"):
        amortisation_schedule(PRINCIPAL, ANNUAL_RATE, monthly_payment=9_000.0)


def test_a_payment_exactly_equal_to_the_first_months_interest_also_fails() -> None:
    """The boundary: `<=`, not `<`. Equal to the interest, the loan never actually amortises —

    every payment would be entirely interest, principal never drops, and the schedule — which
    runs until the balance is cleared, with no term to stop it — would never end.
    """
    # 1 000 000 * 0.01 = 10 000.0 exactly, the first month's interest.
    with pytest.raises(PaymentTooSmallError, match="never covers interest"):
        amortisation_schedule(PRINCIPAL, ANNUAL_RATE, monthly_payment=10_000.0)


def test_a_zero_rate_loan_is_pure_principal() -> None:
    schedule = amortisation_schedule(500_000.0, 0.0, 100_000.0)

    assert len(schedule) == 5
    assert sum(schedule) == pytest.approx(500_000.0)


def test_mortgage_lines_are_negative_start_late_and_are_never_indexed() -> None:
    liability = LiabilityIn(
        label="Ипотека",
        principal=PRINCIPAL,
        annual_rate=ANNUAL_RATE,
        monthly_payment=PAYMENT,
        term_months=360,
        start_month="2026-10",
    )
    lines = mortgage_lines(liability, t0="2026-08", months=720)

    assert len(lines) == 11
    assert lines[0].month == "2026-10"
    assert lines[0].amount == pytest.approx(-PAYMENT)
    assert lines[-1].month == "2027-08"
    # Nominal for the life of the loan: no rate was applied to any payment.
    assert {line.resolved_rate for line in lines} == {None}
    assert {line.line_kind for line in lines} == {"mortgage_payment"}


def test_payments_past_the_horizon_are_dropped() -> None:
    liability = LiabilityIn(
        label="Ипотека",
        principal=PRINCIPAL,
        annual_rate=ANNUAL_RATE,
        monthly_payment=PAYMENT,
        term_months=360,
        start_month="2026-08",
    )
    lines = mortgage_lines(liability, t0="2026-08", months=5)

    assert len(lines) == 5


def test_a_loan_that_started_before_t0_drops_early_payments() -> None:
    liability = LiabilityIn(
        label="Ипотека",
        principal=PRINCIPAL,
        annual_rate=ANNUAL_RATE,
        monthly_payment=PAYMENT,
        term_months=360,
        start_month="2026-06",
    )
    lines = mortgage_lines(liability, t0="2026-08", months=720)

    # Schedule has 11 payments; June and July are before t0, so 9 remain.
    assert len(lines) == 9
    # First line is the first payment on or after t0, not the loan's own start.
    assert lines[0].month == "2026-08"
    # Last line is the 11th payment (offset by the two dropped months).
    assert lines[-1].month == "2027-04"


def test_the_table_splits_every_payment_into_interest_principal_and_balance() -> None:
    table = amortisation_table(PRINCIPAL, ANNUAL_RATE, PAYMENT)

    assert len(table) == 11
    assert table[0] == Instalment(payment=100_000.0, interest=10_000.0, principal=90_000.0, balance=910_000.0)
    assert table[1].interest == pytest.approx(9_100.0)
    assert table[1].principal == pytest.approx(90_900.0)
    assert table[1].balance == pytest.approx(819_100.0)
    # The last instalment clears the debt: its principal part is the whole remaining balance.
    balance_after_10 = PRINCIPAL * 1.01**10 - PAYMENT * (1.01**10 - 1) / 0.01
    assert table[-1].principal == pytest.approx(balance_after_10)
    assert table[-1].payment == pytest.approx(balance_after_10 * 1.01)
    assert table[-1].balance == pytest.approx(0.0, abs=1e-6)


def test_the_schedule_is_the_payment_column_of_the_table() -> None:
    assert amortisation_schedule(PRINCIPAL, ANNUAL_RATE, PAYMENT) == tuple(
        instalment.payment for instalment in amortisation_table(PRINCIPAL, ANNUAL_RATE, PAYMENT)
    )


def test_the_track_is_zero_before_the_loan_starts_and_after_it_is_paid_off() -> None:
    liability = LiabilityIn(
        label="Ипотека",
        principal=PRINCIPAL,
        annual_rate=ANNUAL_RATE,
        monthly_payment=PAYMENT,
        term_months=360,
        start_month="2026-10",
    )
    balance, repaid = liability_track(liability, t0="2026-08", months=24)

    assert len(balance) == len(repaid) == 24
    # 2026-08 and 2026-09: the loan is not taken yet.
    assert balance[:2] == (0.0, 0.0) and repaid[:2] == (0.0, 0.0)
    # 2026-10 is the first instalment, 2026-11 the second.
    assert balance[2] == pytest.approx(910_000.0) and repaid[2] == pytest.approx(90_000.0)
    assert balance[3] == pytest.approx(819_100.0) and repaid[3] == pytest.approx(90_900.0)
    # 2027-08 is the eleventh and last instalment: the debt is gone, its principal is repaid.
    balance_after_10 = PRINCIPAL * 1.01**10 - PAYMENT * (1.01**10 - 1) / 0.01
    assert balance[12] == pytest.approx(0.0, abs=1e-6) and repaid[12] == pytest.approx(balance_after_10)
    assert balance[13:] == (0.0,) * 11 and repaid[13:] == (0.0,) * 11


def test_a_loan_started_before_t0_enters_the_track_mid_schedule() -> None:
    liability = LiabilityIn(
        label="Ипотека",
        principal=PRINCIPAL,
        annual_rate=ANNUAL_RATE,
        monthly_payment=PAYMENT,
        term_months=360,
        start_month="2026-06",
    )
    balance, repaid = liability_track(liability, t0="2026-08", months=12)

    # 2026-08 is the third instalment: two were paid before the plan started.
    assert balance[0] == pytest.approx(727_291.0)
    assert repaid[0] == pytest.approx(91_809.0)


def test_the_track_is_clipped_to_the_horizon() -> None:
    liability = LiabilityIn(
        label="Ипотека",
        principal=PRINCIPAL,
        annual_rate=ANNUAL_RATE,
        monthly_payment=PAYMENT,
        term_months=360,
        start_month="2026-08",
    )
    balance, repaid = liability_track(liability, t0="2026-08", months=3)

    assert balance == pytest.approx((910_000.0, 819_100.0, 727_291.0))
    assert repaid == pytest.approx((90_000.0, 90_900.0, 91_809.0))


def test_payment_must_reduce_balance_at_float_precision() -> None:
    with pytest.raises(PaymentTooSmallError, match="precision"):
        amortisation_schedule(1e9, 0.12, 10000000.000000004)
