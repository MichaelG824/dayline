"""An in-memory LRU cache.

Keep the public API (the class name and method signatures) as the stages
describe it: the hidden tests import ``LRUCache`` from this file.
"""


class LRUCache:
    def __init__(self, capacity: int) -> None:
        raise NotImplementedError

    def get(self, key):
        """The cached value for ``key``, or ``None`` if it is not cached."""
        raise NotImplementedError

    def put(self, key, value) -> None:
        raise NotImplementedError
