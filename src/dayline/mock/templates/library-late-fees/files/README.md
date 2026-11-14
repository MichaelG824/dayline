# Library checkout

A small library lending service. Run the tests with `pytest`.

## Part 1 - the bug

Members report that two people can check out the same copy of a book.
`tests/test_checkout.py` reproduces it.
Fix it without breaking the other tests.

## Part 2 - late fees

Add `LibraryService.late_fee(loan_id, today)`:

- A loan is due 14 days after checkout.
- Each full day late costs **$0.25**.
- The fee is capped at **$10.00** per loan.
- A loan returned on time, or still out but not yet due, owes nothing.
- Return the fee in cents, as an `int`.

`tests/test_late_fees.py` describes the expected behaviour.

## Talk through

- How would you stop the double checkout if two requests arrived at the same moment?
- Where should money be rounded, and why?
