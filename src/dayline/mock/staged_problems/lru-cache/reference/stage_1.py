"""An in-memory LRU cache.

Keep the public API (the class name and method signatures) as the stages
describe it: the hidden tests import ``LRUCache`` from this file.
"""


class _Node:
    __slots__ = ("key", "value", "prev", "next")

    def __init__(self, key=None, value=None):
        self.key = key
        self.value = value
        self.prev = None
        self.next = None


class LRUCache:
    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = capacity
        self._map = {}
        # Sentinels: head.next is the most recently used, tail.prev the least.
        self._head = _Node()
        self._tail = _Node()
        self._head.next = self._tail
        self._tail.prev = self._head

    def get(self, key):
        """The cached value for ``key``, or ``None`` if it is not cached."""
        node = self._map.get(key)
        if node is None:
            return None
        self._unlink(node)
        self._push_front(node)
        return node.value

    def put(self, key, value) -> None:
        node = self._map.get(key)
        if node is not None:
            self._remove(node)
        while len(self._map) >= self.capacity:
            self._remove(self._tail.prev)
        node = _Node(key, value)
        self._map[key] = node
        self._push_front(node)

    def _remove(self, node):
        self._unlink(node)
        del self._map[node.key]

    def _unlink(self, node):
        node.prev.next = node.next
        node.next.prev = node.prev

    def _push_front(self, node):
        node.prev = self._head
        node.next = self._head.next
        self._head.next.prev = node
        self._head.next = node
