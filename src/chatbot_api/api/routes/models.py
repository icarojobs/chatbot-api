from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from chatbot_api.core.security import require_access_token
from chatbot_api.providers.profile import ProviderProfile

MODEL_OWNER = "chatbot-api"
MODEL_CREATED_AT = 0

router = APIRouter(prefix="/v1", tags=["Modelos"], dependencies=[Depends(require_access_token)])


class ModelCard(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = MODEL_CREATED_AT
    owned_by: str = MODEL_OWNER


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelCard]


def get_provider_profile(request: Request) -> ProviderProfile:
    profile: ProviderProfile = request.app.state.provider_profile
    return profile


Profile = Annotated[ProviderProfile, Depends(get_provider_profile)]


@router.get("/models", summary="Lista os modelos de chat disponíveis")
async def list_models(profile: Profile) -> ModelList:
    return ModelList(data=[ModelCard(id=model) for model in profile.chat_models])


@router.get("/models/{model_id:path}", summary="Detalha um modelo de chat disponível")
async def retrieve_model(model_id: str, profile: Profile) -> ModelCard:
    return ModelCard(id=profile.resolve_chat_model(model_id))
