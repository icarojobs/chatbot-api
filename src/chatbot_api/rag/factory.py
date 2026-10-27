from chatbot_api.core.config import Settings
from chatbot_api.db.session import SessionFactory
from chatbot_api.providers.base import ChatModelProvider, EmbeddingProvider
from chatbot_api.rag.graph import RAGNodes, RAGSettings, build_rag_graph
from chatbot_api.rag.retrieval import ChunkRetriever
from chatbot_api.rag.service import RAGService


def build_rag_service(
    embedder: EmbeddingProvider,
    chat: ChatModelProvider,
    session_factory: SessionFactory,
    settings: Settings,
    min_score: float,
) -> RAGService:
    rag_settings = RAGSettings(
        min_score=min_score,
        context_max_chars=settings.rag_context_max_chars,
        max_output_tokens=settings.llm_max_output_tokens,
    )
    nodes = RAGNodes(embedder, chat, ChunkRetriever(session_factory), rag_settings)
    return RAGService(build_rag_graph(nodes))
