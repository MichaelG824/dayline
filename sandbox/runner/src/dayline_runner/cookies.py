"""The preview's cookie jar: one per sandbox, kept by the runner.

The previewed app runs in an opaque origin (Dayline sends it with a CSP
``sandbox``), so the browser cannot be trusted to keep its cookies: a
``fetch`` from an opaque origin is cross-origin and omits them, and browsers
that block third-party cookies drop them anyway. So the browser never sees
the app's cookies. The proxy takes ``Set-Cookie`` off every response, keeps
the cookies here, and sends the matching ones with every request, like a
browser would for an app it can talk to directly. Sessions, CSRF tokens and
logins then work whatever the browser does.

The jar ignores ``Domain`` and ``Secure`` (everything is ``localhost``) and
honours ``Path``, ``Max-Age`` and ``Expires``. Cookies set from the app's
JavaScript (``document.cookie``) cannot work in an opaque origin.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

MAX_COOKIES = 100
MAX_COOKIE_BYTES = 8192
MAX_JARS = 64


@dataclass(slots=True)
class _Cookie:
    value: str
    path: str
    expires: float | None


def _path_matches(cookie_path: str, request_path: str) -> bool:
    if request_path == cookie_path or cookie_path == "/":
        return True
    prefix = cookie_path if cookie_path.endswith("/") else cookie_path + "/"
    return request_path.startswith(prefix)


def _default_path(request_path: str) -> str:
    """RFC 6265's default: the request path up to its last slash."""
    head = request_path.split("?", 1)[0].rsplit("/", 1)[0]
    return head or "/"


class CookieJar:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._cookies: dict[tuple[str, str], _Cookie] = {}
        self._clock = clock
        self._lock = threading.Lock()

    def store(self, set_cookie: str, request_path: str) -> None:
        """Keep (or delete) the cookie in one ``Set-Cookie`` value."""
        if len(set_cookie) > MAX_COOKIE_BYTES:
            return
        pair, *attrs = set_cookie.split(";")
        name, sep, value = pair.partition("=")
        name, value = name.strip(), value.strip()
        if not sep or not name:
            return
        path = _default_path(request_path)
        max_age: float | None = None
        expires: float | None = None
        for attr in attrs:
            key, _, attr_value = attr.partition("=")
            key, attr_value = key.strip().lower(), attr_value.strip()
            if key == "path" and attr_value.startswith("/"):
                path = attr_value
            elif key == "max-age" and attr_value.lstrip("-").isdigit():
                max_age = self._clock() + int(attr_value)
            elif key == "expires":
                with contextlib.suppress(TypeError, ValueError):
                    expires = parsedate_to_datetime(attr_value).timestamp()
        # Max-Age wins over Expires, wherever each appears.
        expires = max_age if max_age is not None else expires
        with self._lock:
            if expires is not None and expires <= self._clock():
                self._cookies.pop((name, path), None)
                return
            self._cookies[(name, path)] = _Cookie(value, path, expires)
            while len(self._cookies) > MAX_COOKIES:
                self._cookies.pop(next(iter(self._cookies)))

    def header(self, request_path: str) -> str | None:
        """The ``Cookie`` header for a request to ``request_path``, if any."""
        now = self._clock()
        path = request_path.split("?", 1)[0] or "/"
        with self._lock:
            for key in [k for k, c in self._cookies.items() if c.expires and c.expires <= now]:
                del self._cookies[key]
            # Longer paths first, as browsers send them.
            matching = sorted(
                (
                    (name, c)
                    for (name, _), c in self._cookies.items()
                    if _path_matches(c.path, path)
                ),
                key=lambda item: -len(item[1].path),
            )
        return "; ".join(f"{name}={c.value}" for name, c in matching) or None


class CookieJars:
    """A jar per sandbox (the most recently used ``MAX_JARS``)."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._jars: OrderedDict[str, CookieJar] = OrderedDict()
        self._clock = clock
        self._lock = threading.Lock()

    def jar(self, sandbox_id: str) -> CookieJar:
        with self._lock:
            jar = self._jars.pop(sandbox_id, None) or CookieJar(self._clock)
            self._jars[sandbox_id] = jar
            while len(self._jars) > MAX_JARS:
                self._jars.popitem(last=False)
            return jar
