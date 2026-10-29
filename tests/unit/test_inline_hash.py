import pytest

from chatbot_api.api.routes.pages import inline_hash


def test_inline_hash_requires_the_block() -> None:
    with pytest.raises(ValueError, match="<script>"):
        inline_hash("<html><style>p{}</style></html>", "script")


def test_inline_hash_covers_only_the_block_content() -> None:
    assert inline_hash("<style>a</style>", "style") == inline_hash("x<style>a</style>y", "style")
