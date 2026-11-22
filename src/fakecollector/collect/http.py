"""Polite HTTP client: host allowlist, robots.txt, a minimum delay between requests."""

from __future__ import annotations

import logging
import socket
import time
import urllib.error
import urllib.request
import urllib.robotparser
from collections.abc import Callable
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; research-collector/1.0)"


class OfflineError(RuntimeError):
    """The network is unreachable (DNS or connection failure on every attempt)."""


class BlockedError(RuntimeError):
    """The URL is outside the allowlist or disallowed by robots.txt."""


def host_allowed(url: str, hosts: tuple[str, ...]) -> bool:
    """Return True when `url` is http(s) on one of `hosts` or their subdomains."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return any(host == h or host.endswith("." + h) for h in hosts)


Opener = Callable[[urllib.request.Request, float], bytes]


def _default_open(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data: bytes = response.read()
        return data


class PoliteFetcher:
    """Fetch publisher pages one at a time, never outside the allowlisted hosts."""

    def __init__(
        self,
        hosts: tuple[str, ...],
        *,
        min_interval: float = 1.0,
        timeout: float = 20.0,
        user_agent: str = USER_AGENT,
        opener: Opener | None = None,
        check_robots: bool = True,
    ) -> None:
        self.hosts = hosts
        self.min_interval = min_interval
        self.timeout = timeout
        self.user_agent = user_agent
        self._open = opener or _default_open
        self._check_robots = check_robots
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last = 0.0
        self.requests = 0

    def _wait(self) -> None:
        delay = self._last + self.min_interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()

    def _raw(self, url: str) -> bytes:
        self._wait()
        self.requests += 1
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            return self._open(request, self.timeout)
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, OSError):  # DNS failure, refused, unreachable
                raise OfflineError(f"{urlsplit(url).hostname}: {exc.reason}") from exc
            raise
        except (socket.gaierror, ConnectionError) as exc:
            raise OfflineError(f"{urlsplit(url).hostname}: {exc}") from exc

    def _robots_ok(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
            try:
                body = self._raw(origin + "/robots.txt").decode("utf-8", "replace")
                if parser is not None:
                    parser.parse(body.splitlines())
            except OfflineError:
                raise
            except Exception:  # no robots.txt (404, 403): treat as no rules
                parser = None
            self._robots[origin] = parser
        rules = self._robots[origin]
        return rules is None or rules.can_fetch(self.user_agent, url)

    def get(self, url: str) -> bytes:
        """Return the body of an allowlisted, robots-permitted URL."""
        if not host_allowed(url, self.hosts):
            raise BlockedError(f"host not allowlisted: {urlsplit(url).hostname}")
        if self._check_robots and not self._robots_ok(url):
            raise BlockedError(f"robots.txt disallows {url}")
        return self._raw(url)
