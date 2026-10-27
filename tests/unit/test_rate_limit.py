import pytest
from starlette.types import Scope

from chatbot_api.core.rate_limit import UNKNOWN_CLIENT, client_key

DIRECT_CLIENT = "10.0.0.1"


def http_scope(forwarded_for: str | None = None) -> Scope:
    headers = [(b"x-forwarded-for", forwarded_for.encode())] if forwarded_for else []
    return {"type": "http", "client": (DIRECT_CLIENT, 1234), "headers": headers}


def test_uses_direct_client_without_trusted_proxies() -> None:
    assert client_key(http_scope("6.6.6.6")) == DIRECT_CLIENT


def test_falls_back_when_client_is_unknown() -> None:
    assert client_key({"type": "http"}) == UNKNOWN_CLIENT


@pytest.mark.parametrize(
    ("forwarded_for", "hops", "expected"),
    [
        ("6.6.6.6, 203.0.113.7", 1, "203.0.113.7"),
        ("6.6.6.6, 203.0.113.7, 35.0.0.1", 2, "203.0.113.7"),
        ("203.0.113.7", 2, DIRECT_CLIENT),
        ("6.6.6.6, ", 1, DIRECT_CLIENT),
        (None, 1, DIRECT_CLIENT),
    ],
)
def test_uses_hop_appended_by_trusted_proxy(
    forwarded_for: str | None, hops: int, expected: str
) -> None:
    assert client_key(http_scope(forwarded_for), hops) == expected
