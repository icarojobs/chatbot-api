"""CLI: uv run python -m chatbot_api.ingest docs/apostilas [outro.pdf ...]"""

import argparse
import asyncio
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from chatbot_api.core.config import Settings, get_settings
from chatbot_api.core.errors import ApiError
from chatbot_api.core.logging import configure_logging
from chatbot_api.db.session import create_engine, create_session_factory
from chatbot_api.ingestion.loaders import InvalidDocumentError
from chatbot_api.ingestion.pipeline import IngestionService
from chatbot_api.providers.openai_compatible import (
    InvalidEmbeddingsError,
    OpenAICompatibleProvider,
    create_client,
)
from chatbot_api.providers.profile import build_provider_profile

PDF_PATTERN = "*.pdf"
EXIT_OK = 0
EXIT_FAILURE = 1


def expand_paths(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        files.extend(sorted(path.glob(PDF_PATTERN)) if path.is_dir() else [path])
    return files


async def ingest_file(service: IngestionService, path: Path) -> bool:
    try:
        data = await asyncio.to_thread(path.read_bytes)
        result = await service.ingest(path.name, data)
    except (InvalidDocumentError, InvalidEmbeddingsError, ApiError, OSError) as exc:
        print(f"[erro] {path.name}: {exc}")
        return False
    print(
        f"[{result.status}] {result.filename}: {result.chunk_count} trechos "
        f"({result.embedded_chunks} novos embeddings)"
    )
    return True


async def run(paths: Sequence[Path], settings: Settings) -> int:
    profile = build_provider_profile(settings)
    provider = OpenAICompatibleProvider(create_client(profile, settings), profile.embedding_model)
    engine = create_engine(settings.database_url.get_secret_value())
    service = IngestionService(create_session_factory(engine), provider)
    try:
        results = [await ingest_file(service, path) for path in expand_paths(paths)]
    finally:
        await provider.close()
        await engine.dispose()
    return EXIT_OK if all(results) else EXIT_FAILURE


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingere PDFs na base de conhecimento.")
    parser.add_argument("paths", nargs="+", type=Path, help="Arquivos PDF ou diretórios")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    return asyncio.run(run(args.paths, settings))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
