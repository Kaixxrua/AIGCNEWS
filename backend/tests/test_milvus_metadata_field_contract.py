from __future__ import annotations

"""Milvus 元数据 JSON 列契约:aigc_docs 的 schema 必须恒定。

历史事故:langchain Milvus 未设 metadata_field 时按每批首文档的元数据键集
推断显式列;主管线与 arxiv PDF 切片(chunk_index/total_chunks)键集不同,
轮流 DataNotMatch → drop_old 重建,整日反复清空向量库(实测单日 20 次)。
metadata_field 固定后 schema 恒为 metadata(JSON)+text+pk+vector。
"""

from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from backend.app.repositories.milvus_repo import _METADATA_FIELD, MilvusRepository


def _repo() -> MilvusRepository:
    return MilvusRepository(embeddings=MagicMock())


def test_add_documents_constructs_milvus_with_json_metadata_field() -> None:
    with patch("backend.app.repositories.milvus_repo.Milvus") as milvus_cls:
        milvus_cls.return_value.add_documents.return_value = None
        assert _repo().add_documents([Document(page_content="t", metadata={"a": 1})])

    assert milvus_cls.call_count == 1
    assert milvus_cls.call_args.kwargs["metadata_field"] == _METADATA_FIELD
    assert milvus_cls.call_args.kwargs["drop_old"] is False


def test_schema_mismatch_rebuild_keeps_json_metadata_field() -> None:
    """旧显式列 collection 上的首写仍 mismatch,重建路径也必须用 JSON 列。"""
    first, second = MagicMock(), MagicMock()
    first.add_documents.side_effect = Exception(
        "DataNotMatchException: data doesn't match with schema"
    )

    with patch(
        "backend.app.repositories.milvus_repo.Milvus",
        side_effect=[first, second],
    ) as milvus_cls:
        assert _repo().add_documents([Document(page_content="t", metadata={"a": 1})])

    assert milvus_cls.call_count == 2
    rebuild_kwargs = milvus_cls.call_args_list[1].kwargs
    assert rebuild_kwargs["drop_old"] is True
    assert rebuild_kwargs["metadata_field"] == _METADATA_FIELD


def test_search_constructs_milvus_with_json_metadata_field() -> None:
    with patch("backend.app.repositories.milvus_repo.Milvus") as milvus_cls:
        milvus_cls.return_value.similarity_search_with_score.return_value = []
        assert _repo().search("query", top_k=3) == []

    assert milvus_cls.call_args.kwargs["metadata_field"] == _METADATA_FIELD


def test_search_by_source_filters_json_metadata_column() -> None:
    collection = MagicMock()
    collection.query.return_value = [
        {"pk": 7, "text": "chunk text", _METADATA_FIELD: {"source": "arxiv", "title": "t"}}
    ]

    with (
        patch("pymilvus.connections") as connections,
        patch("pymilvus.utility") as utility,
        patch("pymilvus.Collection", return_value=collection),
    ):
        connections.connect.return_value = None
        utility.has_collection.return_value = True
        docs = _repo().search_by_source("arxiv", top_k=3)

    query_kwargs = collection.query.call_args.kwargs
    assert query_kwargs["expr"] == f'{_METADATA_FIELD}["source"] == "arxiv"'
    assert _METADATA_FIELD in query_kwargs["output_fields"]

    assert len(docs) == 1
    assert docs[0].page_content == "chunk text"
    assert docs[0].metadata["source"] == "arxiv"
    assert docs[0].metadata["title"] == "t"
    assert docs[0].metadata["id"] == "7"
