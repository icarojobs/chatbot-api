from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from chatbot_api.core.security import require_access_token
from chatbot_api.providers.profile import ModelType, ProviderProfile

MODEL_OWNER = "chatbot-api"
MODEL_CREATED_AT = 0

router = APIRouter(prefix="/v1", tags=["Modelos"], dependencies=[Depends(require_access_token)])


class ModelCard(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = MODEL_CREATED_AT
    owned_by: str = MODEL_OWNER
    type: ModelType = Field(
        description="Finalidade: `chat` gera as respostas (use em `model` no chat); "
        "`embedding` vetoriza perguntas e documentos para a busca (uso interno do RAG)."
    )


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelCard]


def get_provider_profile(request: Request) -> ProviderProfile:
    profile: ProviderProfile = request.app.state.provider_profile
    return profile


Profile = Annotated[ProviderProfile, Depends(get_provider_profile)]


@router.get("/models", summary="Lista os modelos do ambiente (chat e embedding)")
async def list_models(profile: Profile) -> ModelList:
    return ModelList(
        data=[ModelCard(id=model, type=model_type) for model, model_type in profile.models.items()]
    )


@router.get("/models/{model_id:path}", summary="Detalha um modelo do ambiente")
async def retrieve_model(model_id: str, profile: Profile) -> ModelCard:
    return ModelCard(id=model_id, type=profile.model_type(model_id))
