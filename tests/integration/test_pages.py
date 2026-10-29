import base64
import hashlib
import re
from http import HTTPStatus

from httpx import AsyncClient


def csp_hash(html: str, tag: str) -> str:
    block = re.search(rf"<{tag}>(.*?)</{tag}>", html, re.DOTALL)
    assert block is not None
    digest = hashlib.sha256(block.group(1).encode()).digest()
    return f"'sha256-{base64.b64encode(digest).decode()}'"


async def test_upload_page_is_served_without_token(client: AsyncClient) -> None:
    response = await client.get("/upload")

    assert response.status_code == HTTPStatus.OK
    assert response.headers["content-type"].startswith("text/html")
    assert "Upload de documentos" in response.text
    assert "/v1/documents" in response.text


async def test_upload_page_allows_only_its_own_inline_code(client: AsyncClient) -> None:
    response = await client.get("/upload")
    policy = response.headers["content-security-policy"]

    assert f"script-src {csp_hash(response.text, 'script')};" in policy
    assert f"style-src {csp_hash(response.text, 'style')};" in policy
    assert "connect-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "unsafe-inline" not in policy
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


async def test_docs_link_to_the_upload_page(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert "/upload" in response.json()["paths"]
    assert "[/upload](/upload)" in response.json()["info"]["description"]
