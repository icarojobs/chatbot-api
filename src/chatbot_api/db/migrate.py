from pathlib import Path

from alembic import command
from alembic.config import Config

from chatbot_api.core.config import get_settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
HEAD_REVISION = "head"


def build_alembic_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["database_url"] = database_url
    return config


def upgrade(database_url: str) -> None:
    command.upgrade(build_alembic_config(database_url), HEAD_REVISION)


def main() -> None:
    upgrade(get_settings().database_url.get_secret_value())


if __name__ == "__main__":  # pragma: no cover
    main()
