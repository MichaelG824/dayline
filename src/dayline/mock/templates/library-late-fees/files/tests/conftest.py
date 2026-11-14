import pytest

from library.models import Book, Member
from library.service import LibraryService


@pytest.fixture
def library() -> LibraryService:
    service = LibraryService()
    service.add_book(Book(id="b1", title="Dune"))
    service.add_member(Member(id="ana", name="Ana"))
    service.add_member(Member(id="ben", name="Ben"))
    return service
