from __future__ import annotations

import logging
from typing import Iterable, List

from langchain_core.documents import Document
from langchain_experimental.graph_transformers import LLMGraphTransformer

from backend.app.core.model_factory import get_chat_model

logger = logging.getLogger(__name__)


class GraphExtractor:
    def __init__(self) -> None:
        self._llm = get_chat_model()
        self._transformer = LLMGraphTransformer(
            llm=self._llm,
            allowed_nodes=["Paper", "Author", "Concept"],
            allowed_relationships=None,
            node_properties=False,
        )

    def extract(self, docs: Iterable[Document]) -> List:
        try:
            return self._transformer.convert_to_graph_documents(list(docs))
        except Exception as exc:
            logger.warning("[GraphExtractor] Failed to extract graph documents: %s", exc)
            return []
