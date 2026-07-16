"""Unit tests for chunker.py — RecursiveCharacterTextSplitter wrapper."""
import pytest

from app.services.chunker import chunk_text


class TestChunker:
    def test_empty_text(self):
        assert chunk_text("") == []

    def test_short_text_single_chunk(self):
        chunks = chunk_text("短文本", chunk_size=500, chunk_overlap=50)
        assert len(chunks) == 1
        assert chunks[0] == "短文本"

    def test_long_text_multiple_chunks(self):
        text = "测试文本。" * 500  # ~2500 chars
        chunks = chunk_text(text, chunk_size=500, chunk_overlap=50)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c) <= 500 + 100  # allow some slack

    def test_chunk_overlap_produces_multiple(self):
        parts = []
        for idx in range(20):
            parts.append(("段落%d。" % idx) * 3)
        text = "\n\n".join(parts)
        chunks = chunk_text(text, chunk_size=200, chunk_overlap=30)
        assert len(chunks) > 1
