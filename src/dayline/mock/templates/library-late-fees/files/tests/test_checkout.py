from datetime import date

import pytest

from library.service import LibraryError, LibraryService

DAY = date(2026, 3, 2)


def test_checkout_creates_an_open_loan(library: LibraryService) -> None:
    loan = library.checkout("b1", "ana", DAY)
    assert loan.is_open and loan.checked_out == DAY


def test_unknown_book_or_member_is_rejected(library: LibraryService) -> None:
    with pytest.raises(LibraryError):
        library.checkout("nope", "ana", DAY)
    with pytest.raises(LibraryError):
        library.checkout("b1", "nobody", DAY)


def test_a_book_can_be_borrowed_again_after_it_is_returned(library: LibraryService) -> None:
    loan = library.checkout("b1", "ana", DAY)
    library.return_book(loan.id, DAY)
    assert library.checkout("b1", "ben", DAY).is_open


def test_two_members_cannot_hold_the_same_copy(library: LibraryService) -> None:
    library.checkout("b1", "ana", DAY)
    with pytest.raises(LibraryError):
        library.checkout("b1", "ben", DAY)
