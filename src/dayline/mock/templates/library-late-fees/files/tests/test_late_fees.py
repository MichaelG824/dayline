from datetime import date, timedelta

from library.service import LibraryService

OUT = date(2026, 3, 2)


def _loan(library: LibraryService) -> str:
    return library.checkout("b1", "ana", OUT).id


def test_no_fee_before_the_due_date(library: LibraryService) -> None:
    assert library.late_fee(_loan(library), OUT + timedelta(days=14)) == 0


def test_each_full_day_late_costs_25_cents(library: LibraryService) -> None:
    assert library.late_fee(_loan(library), OUT + timedelta(days=17)) == 75


def test_fee_is_capped_at_ten_dollars(library: LibraryService) -> None:
    assert library.late_fee(_loan(library), OUT + timedelta(days=200)) == 1000


def test_fee_stops_growing_once_returned(library: LibraryService) -> None:
    loan_id = _loan(library)
    library.return_book(loan_id, OUT + timedelta(days=16))
    assert library.late_fee(loan_id, OUT + timedelta(days=30)) == 50
