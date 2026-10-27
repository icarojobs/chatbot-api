from http import HTTPStatus

from fastapi import FastAPI
from httpx import AsyncClient

from chatbot_api.providers.openai_compatible import OpenAICompatibleProvider
from tests.conftest import ACCESS_TOKEN, auth_header

DEV_CHAT_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
DEV_EMBEDDING_MODEL = "bge-m3:567m"


async def test_requires_access_token(client: AsyncClient) -> None:
    response = await client.get("/v1/models")

    assert response.status_code == HTTPStatus.UNAUTHORIZED


async def test_lists_configured_models_in_openai_format(client: AsyncClient) -> None:
    response = await client.get("/v1/models", headers=auth_header(ACCESS_TOKEN))

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        "object": "list",
        "data": [
            {
                "id": DEV_CHAT_MODEL,
                "object": "model",
                "created": 0,
                "owned_by": "chatbot-api",
                "type": "chat",
            },
            {
                "id": DEV_EMBEDDING_MODEL,
                "object": "model",
                "created": 0,
                "owned_by": "chatbot-api",
                "type": "embedding",
            },
        ],
    }


async def test_retrieves_model_with_special_characters(client: AsyncClient) -> None:
    response = await client.get(f"/v1/models/{DEV_CHAT_MODEL}", headers=auth_header(ACCESS_TOKEN))

    assert response.status_code == HTTPStatus.OK
    assert response.json()["id"] == DEV_CHAT_MODEL
    assert response.json()["type"] == "chat"


async def test_retrieves_embedding_model_with_its_type(client: AsyncClient) -> None:
    response = await client.get(
        f"/v1/models/{DEV_EMBEDDING_MODEL}", headers=auth_header(ACCESS_TOKEN)
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["type"] == "embedding"


async def test_unknown_model_returns_model_not_found(client: AsyncClient) -> None:
    response = await client.get("/v1/models/azure/gpt-x", headers=auth_header(ACCESS_TOKEN))

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["error"]["code"] == "model_not_found"


async def test_lifespan_creates_and_closes_provider(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        provider = app.state.provider
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.embedding_model == DEV_EMBEDDING_MODEL

    assert provider._client.is_closed()
