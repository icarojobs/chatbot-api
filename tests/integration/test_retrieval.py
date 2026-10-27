from chatbot_api.db.models import Chunk, ChunkEmbedding, Document, DocumentStatus
from chatbot_api.db.session import SessionFactory
from chatbot_api.rag.retrieval import ChunkRetriever

MODEL = "model-a"


async def seed(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        ready = Document(
            filename="pronto.pdf", content_hash="a" * 64, page_count=3, status=DocumentStatus.READY
        )
        processing = Document(
            filename="pendente.pdf",
            content_hash="b" * 64,
            page_count=1,
            status=DocumentStatus.PROCESSING,
        )
        vectors = {"perto": [1.0, 0.0], "medio": [0.7, 0.7], "longe": [0.0, 1.0]}
        for index, (name, vector) in enumerate(vectors.items()):
            chunk = Chunk(chunk_index=index, page_start=index + 1, page_end=index + 1, content=name)
            ready.chunks.append(chunk)
            session.add(ready)
            await session.flush()
            session.add(ChunkEmbedding(chunk_id=chunk.id, embedding_model=MODEL, embedding=vector))
            session.add(
                ChunkEmbedding(
                    chunk_id=chunk.id, embedding_model="model-b", embedding=[1.0, 0.0, 0.0]
                )
            )
        hidden = Chunk(chunk_index=0, page_start=1, page_end=1, content="nao pronto")
        processing.chunks.append(hidden)
        session.add(processing)
        await session.flush()
        session.add(ChunkEmbedding(chunk_id=hidden.id, embedding_model=MODEL, embedding=[1.0, 0.0]))
        await session.commit()


async def test_returns_most_similar_ready_chunks_for_the_model(
    session_factory: SessionFactory,
) -> None:
    await seed(session_factory)

    results = await ChunkRetriever(session_factory).search([1.0, 0.0], MODEL, top_k=2)

    assert [result.content for result in results] == ["perto", "medio"]
    assert results[0].score == 1.0
    assert round(results[1].score, 4) == 0.7071
    assert results[0].filename == "pronto.pdf"
    assert (results[1].page_start, results[1].page_end) == (2, 2)
