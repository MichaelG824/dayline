from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class Book:
    id: str
    title: str


@dataclass
class Member:
    id: str
    name: str


@dataclass
class Loan:
    id: str
    book_id: str
    member_id: str
    checked_out: date
    returned: date | None = None

    @property
    def is_open(self) -> bool:
        return self.returned is None
