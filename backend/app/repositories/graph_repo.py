from __future__ import annotations

import re
from typing import Iterable, List, Optional

from langchain_core.documents import Document
from neo4j import GraphDatabase

from backend.app.core.config import settings


def _safe_label(label: str, fallback: str = "Entity") -> str:
    if not label:
        return fallback
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", label)
    return cleaned or fallback


def _safe_rel_type(rel_type: str, fallback: str = "RELATED_TO") -> str:
    if not rel_type:
        return fallback
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", rel_type).upper()
    return cleaned or fallback


def _node_key(node_type: str, properties: dict, node_id: Optional[str]) -> str:
    if node_id:
        return str(node_id)
    for key in ("id", "name", "title"):
        value = properties.get(key)
        if value:
            return f"{node_type}:{value}"
    return f"{node_type}:{hash(str(properties))}"


class GraphRepository:
    def __init__(self) -> None:
        self._driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
        )

    def close(self) -> None:
        self._driver.close()

    def search(self, keywords: List[str], limit: int = 5) -> List[Document]:
        if not keywords:
            return []

        try:
            query = (
                "MATCH (n) "
                "WHERE any(k IN $keywords WHERE toLower(coalesce(n.name, n.title, n.id, '')) CONTAINS toLower(k)) "
                "OPTIONAL MATCH (n)-[r]-(m) "
                "RETURN n, r, m "
                "LIMIT $limit"
            )
            with self._driver.session() as session:
                records = session.run(query, keywords=keywords, limit=limit)
                docs: List[Document] = []
                for record in records:
                    n = record.get("n")
                    r = record.get("r")
                    m = record.get("m")

                    # Convert Neo4j node props to plain Python dicts with str values
                    n_props = {k: str(v) for k, v in dict(n).items()} if n else {}
                    m_props = {k: str(v) for k, v in dict(m).items()} if m else {}
                    n_label = list(n.labels)[0] if n and n.labels else "Entity"
                    m_label = list(m.labels)[0] if m and m.labels else "Entity"
                    rel_type = r.type if r else "RELATED_TO"

                    n_name = (
                        n_props.get("name") or n_props.get("title") or n_props.get("id")
                    )
                    m_name = (
                        m_props.get("name") or m_props.get("title") or m_props.get("id")
                    )
                    content = f"{n_label}({n_name}) -[{rel_type}]-> {m_label}({m_name})"

                    docs.append(
                        Document(
                            page_content=content,
                            metadata={
                                "source": "neo4j",
                                "keywords": ",".join(keywords),
                                "node_id": n_props.get("id") or n_name or "",
                                "neighbor_id": m_props.get("id") or m_name or "",
                                "rel_type": rel_type,
                            },
                        )
                    )
                return docs
        except Exception as exc:
            print(f"[Neo4j] Failed to search graph: {exc}")
            return []

    def add_graph_documents(self, graph_docs: Iterable) -> None:
        try:
            with self._driver.session() as session:
                for graph_doc in graph_docs:
                    for node in graph_doc.nodes:
                        node_type = _safe_label(getattr(node, "type", "Entity"))
                        properties = getattr(node, "properties", {}) or {}
                        node_id = _node_key(
                            node_type, properties, getattr(node, "id", None)
                        )
                        query = (
                            f"MERGE (n:{node_type} {{id: $id}}) SET n += $properties"
                        )
                        session.run(query, id=node_id, properties=properties)

                    for rel in graph_doc.relationships:
                        source = rel.source
                        target = rel.target
                        rel_type = _safe_rel_type(getattr(rel, "type", "RELATED_TO"))

                        source_type = _safe_label(getattr(source, "type", "Entity"))
                        target_type = _safe_label(getattr(target, "type", "Entity"))

                        source_props = getattr(source, "properties", {}) or {}
                        target_props = getattr(target, "properties", {}) or {}

                        source_id = _node_key(
                            source_type,
                            source_props,
                            getattr(source, "id", None),
                        )
                        target_id = _node_key(
                            target_type,
                            target_props,
                            getattr(target, "id", None),
                        )
                        rel_props = getattr(rel, "properties", {}) or {}

                        query = (
                            f"MERGE (a:{source_type} {{id: $source_id}}) "
                            f"MERGE (b:{target_type} {{id: $target_id}}) "
                            f"MERGE (a)-[r:{rel_type}]->(b) "
                            "SET r += $properties"
                        )
                        session.run(
                            query,
                            source_id=source_id,
                            target_id=target_id,
                            properties=rel_props,
                        )
            print("[Neo4j] Graph documents inserted successfully.")
        except Exception as exc:
            print(f"[Neo4j] Failed to add graph documents: {exc}")
