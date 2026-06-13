from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.rate_limit import rate_limit_key


class _Headers(dict[str, str]):
    def get(self, key: str, default: str = "") -> str:
        return super().get(key.lower(), default)


def _request(remote: str, xff: str = ""):
    headers = _Headers({"x-forwarded-for": xff} if xff else {})
    return SimpleNamespace(client=SimpleNamespace(host=remote), headers=headers)


class RateLimitKeyTests(unittest.TestCase):
    def test_trusted_proxy_uses_leftmost_forwarded_for(self) -> None:
        with patch("app.rate_limit.get_settings") as get_settings:
            get_settings.return_value.trusted_proxy_cidrs = "127.0.0.1/32,172.16.0.0/12"
            self.assertEqual(
                rate_limit_key(_request("172.18.0.5", "203.0.113.10, 172.18.0.5")),
                "203.0.113.10",
            )

    def test_untrusted_remote_ignores_forged_forwarded_for(self) -> None:
        with patch("app.rate_limit.get_settings") as get_settings:
            get_settings.return_value.trusted_proxy_cidrs = "127.0.0.1/32,172.16.0.0/12"
            self.assertEqual(
                rate_limit_key(_request("198.51.100.20", "203.0.113.10")),
                "198.51.100.20",
            )

    def test_invalid_forwarded_for_falls_back_to_remote(self) -> None:
        with patch("app.rate_limit.get_settings") as get_settings:
            get_settings.return_value.trusted_proxy_cidrs = "127.0.0.1/32"
            self.assertEqual(rate_limit_key(_request("127.0.0.1", "not-an-ip")), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
