from __future__ import annotations

import itertools
from datetime import date

from library.models import Book, Loan, Member

LOAN_DAYS = 14


class LibraryError(Exception):
    pass


class LibraryService:
    def __init__(self) -> None:
        self.books: dict[str, Book] = {}
        self.members: dict[str, Member] = {}
        self.loans: dict[str, Loan] = {}
        self._ids = itertools.count(1)

    def add_book(self, book: Book) -> None:
        self.books[book.id] = book

    def add_member(self, member: Member) -> None:
        self.members[member.id] = member

    def checkout(self, book_id: str, member_id: str, today: date) -> Loan:
        if book_id not in self.books:
            raise LibraryError(f"No book {book_id}")
        if member_id not in self.members:
            raise LibraryError(f"No member {member_id}")
        for loan in self.loans.values():
            if loan.book_id == book_id and loan.member_id == member_id and loan.is_open:
                raise LibraryError("You already have this book")
        loan = Loan(id=f"L{next(self._ids)}", book_id=book_id, member_id=member_id, checked_out=today)
        self.loans[loan.id] = loan
        return loan

    def return_book(self, loan_id: str, today: date) -> Loan:
        loan = self.loans.get(loan_id)
        if loan is None:
            raise LibraryError(f"No loan {loan_id}")
        if not loan.is_open:
            raise LibraryError("Already returned")
        loan.returned = today
        return loan

    def late_fee(self, loan_id: str, today: date) -> int:
        raise NotImplementedError
