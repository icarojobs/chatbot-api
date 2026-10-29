import base64
import hashlib
import re
from functools import cache
from importlib.resources import files

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

UPLOAD_PAGE = "upload.html"
INLINE_BLOCK = r"<{tag}>(.*?)</{tag}>"
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src {script}; style-src {style}; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}

router = APIRouter(tags=["Páginas"])


def inline_hash(html: str, tag: str) -> str:
    block = re.search(INLINE_BLOCK.format(tag=tag), html, re.DOTALL)
    if block is None:
        raise ValueError(f"<{tag}> não encontrado na página.")
    digest = hashlib.sha256(block.group(1).encode()).digest()
    return f"'sha256-{base64.b64encode(digest).decode()}'"


@cache
def load_page(name: str) -> tuple[str, dict[str, str]]:
    html = (files("chatbot_api") / "static" / name).read_text(encoding="utf-8")
    policy = CONTENT_SECURITY_POLICY.format(
        script=inline_hash(html, "script"), style=inline_hash(html, "style")
    )
    return html, SECURITY_HEADERS | {"Content-Security-Policy": policy}


@router.get(
    "/upload",
    response_class=HTMLResponse,
    summary="Página que divide um PDF em partes e faz o upload automaticamente",
    description="Pede o token admin, calcula o SHA-256, envia as partes pelo "
    "`/v1/documents/uploads` e acompanha o documento até `ready`.",
)
async def upload_page() -> HTMLResponse:
    html, headers = load_page(UPLOAD_PAGE)
    return HTMLResponse(html, headers=headers)
