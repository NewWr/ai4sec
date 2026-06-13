from __future__ import annotations

import ipaddress
from functools import lru_cache

from fastapi import Request
from slowapi import Limiter

from app.config import get_settings


def _parse_ip(raw: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    if value.startswith("[") and "]" in value:
        value = value[1:value.index("]")]
    elif value.count(":") == 1 and "." in value:
        value = value.rsplit(":", 1)[0]
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


@lru_cache(maxsize=16)
def _trusted_proxy_networks(raw: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _first_forwarded_for(headers: dict[str, str] | Request) -> str:
    raw = headers.get("x-forwarded-for", "") if hasattr(headers, "get") else ""
    if not raw:
        return ""
    return raw.split(",", 1)[0].strip()


def rate_limit_key(request: Request) -> str:
    remote = _parse_ip(getattr(request.client, "host", "") if request.client else "")
    if remote is None:
        return "unknown"

    settings = get_settings()
    trusted = any(remote in network for network in _trusted_proxy_networks(settings.trusted_proxy_cidrs))
    if trusted:
        forwarded = _parse_ip(_first_forwarded_for(request.headers))
        if forwarded is not None:
            return str(forwarded)
    return str(remote)

# Shared rate limiter instance — imported by main.py and all routers.
# Kept in a separate module to avoid circular imports between main ↔ routers.
limiter = Limiter(key_func=rate_limit_key, default_limits=["60/minute"])
