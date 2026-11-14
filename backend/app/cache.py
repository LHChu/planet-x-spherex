"""Small, bounded process-local PNG cache. No FITS or permanent files."""
import threading
import time
import uuid
from collections import OrderedDict


class ImageCache:
    def __init__(self, ttl=600, max_entries=32, max_bytes=16 * 1024 * 1024):
        self.ttl = ttl
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._items = OrderedDict()
        self._lock = threading.Lock()

    def _prune(self):
        now = time.monotonic()
        for key, (expires, _, _) in list(self._items.items()):
            if expires <= now:
                del self._items[key]

    def put(self, black, white):
        if len(black) + len(white) > self.max_bytes:
            raise ValueError("PNG pair exceeds cache capacity")
        with self._lock:
            self._prune()
            while self._items and (len(self._items) >= self.max_entries or
                    sum(len(b) + len(w) for _, b, w in self._items.values()) + len(black) + len(white) > self.max_bytes):
                self._items.popitem(last=False)
            key = uuid.uuid4().hex
            self._items[key] = (time.monotonic() + self.ttl, black, white)
            return key

    def get(self, key):
        inverse = key.endswith("-inverse")
        base = key.removesuffix("-inverse")
        with self._lock:
            self._prune()
            item = self._items.get(base)
            return None if item is None else item[2 if inverse else 1]
