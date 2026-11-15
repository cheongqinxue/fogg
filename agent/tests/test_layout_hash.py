"""Layout canonical hashing (parity with the browser client)."""

from __future__ import annotations

import json

import pytest

from layout.hashing import layout_document_hash
from layout.models import LayoutDocument


class TestLayoutHash:
    @pytest.mark.unit
    def test_default_singapore_hash_stable(self) -> None:
        document = LayoutDocument.default_singapore().to_storage_dict()
        digest = layout_document_hash(document)
        assert len(digest) == 64
        assert digest == layout_document_hash(json.loads(json.dumps(document)))

    @pytest.mark.unit
    def test_viewport_change_changes_hash(self) -> None:
        doc = LayoutDocument.default_singapore().to_storage_dict()
        other = json.loads(json.dumps(doc))
        other["map"]["viewport"]["zoom"] = 12.0
        assert layout_document_hash(doc) != layout_document_hash(other)
