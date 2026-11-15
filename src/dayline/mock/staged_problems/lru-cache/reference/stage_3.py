"""An in-memory LRU cache.

Keep the public API (the class name and method signatures) as the stages
describe it: the hidden tests import ``LRUCache`` from this file.
"""

import time


class _Node:
    __slots__ = ("key", "value", "expires_at", "size", "prev", "next")

    def __init__(self, key=None, value=None, expires_at=None, size=0):
        self.key = key
        self.value = value
        self.expires_at = expires_at
        self.size = size
        self.prev = None
        self.next = None


class LRUCache:
    def __init__(self, capacity: int, clock=time.monotonic) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = capacity
        self._clock = clock
        self._map = {}
        self._total = 0
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
        if node.expires_at is not None and self._clock() >= node.expires_at:
            self._remove(node)
            return None
        self._unlink(node)
        self._push_front(node)
        return node.value

    def put(self, key, value, ttl=None, size=1) -> None:
        if size > self.capacity:
            raise ValueError(f"size {size} is larger than the capacity {self.capacity}")
        node = self._map.get(key)
        if node is not None:
            self._remove(node)
        while self._total + size > self.capacity:
            self._remove(self._tail.prev)
        expires_at = None if ttl is None else self._clock() + ttl
        node = _Node(key, value, expires_at, size)
        self._map[key] = node
        self._total += size
        self._push_front(node)

    def _remove(self, node):
        self._unlink(node)
        del self._map[node.key]
        self._total -= node.size

    def _unlink(self, node):
        node.prev.next = node.next
        node.next.prev = node.prev

    def _push_front(self, node):
        node.prev = self._head
        node.next = self._head.next
        self._head.next.prev = node
        self._head.next = node
