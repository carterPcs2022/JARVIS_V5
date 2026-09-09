"""core/tools/browser.py — bounded, SSRF-resistant web page fetch."""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

TIMEOUT = 15
MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 2_000_000
BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}


def _host_is_public(host: str) -> bool:
    host = (host or "").strip().lower().rstrip(".")
    if not host or host in BLOCKED_HOSTS or host.endswith(".localhost"):
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except OSError:
        return False
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast, ip.is_unspecified, ip.is_reserved)):
            return False
    return True


def _validate_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except Exception:
        return "invalid_url"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "only_http_https_urls_allowed"
    if parsed.username or parsed.password:
        return "userinfo_in_url_not_allowed"
    if not _host_is_public(parsed.hostname):
        return "destination_not_public"
    return None


def fetch(url: str, max_chars: int = 4000) -> str:
    """Fetch public web content while rejecting private-network targets.

    Redirects are validated one at a time so a public URL cannot redirect the
    agent into localhost, RFC1918, link-local, or other reserved addresses.
    """
    if not isinstance(url, str) or len(url) > 4096:
        return "[Browser error: invalid_url]"
    error = _validate_url(url)
    if error:
        return f"[Browser error: {error}]"
    max_chars = max(1, min(int(max_chars), 100_000))
    current = url
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                r = client.get(current, headers={"User-Agent": "JARVIS/5.0"})
                if 300 <= r.status_code < 400 and r.headers.get("location"):
                    current = urljoin(current, r.headers["location"])
                    error = _validate_url(current)
                    if error:
                        return f"[Browser error: {error}]"
                    continue
                if r.status_code >= 400:
                    return f"[Browser error: HTTP {r.status_code}]"
                if len(r.content) > MAX_RESPONSE_BYTES:
                    return "[Browser error: response_too_large]"
                text = r.text
                text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.S | re.I)
                text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.S | re.I)
                text = re.sub(r"<[^>]+>", " ", text)
                return re.sub(r"\s+", " ", text).strip()[:max_chars]
        return "[Browser error: too_many_redirects]"
    except Exception as e:
        return f"[Browser error: {type(e).__name__}]"


def screenshot_url(url: str) -> str:
    """Placeholder — wire to playwright/selenium if needed."""
    error = _validate_url(url)
    if error:
        return f"[Screenshot error: {error}]"
    return f"[Screenshot not yet implemented for {url}]"
