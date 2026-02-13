"""Tests for the knowledge graph module."""

import os
import tempfile
import pytest

from buddy.knowledge.graph import (
    KnowledgeGraph, Node, Edge, NodeType, EdgeType, make_id,
)
from buddy.knowledge.retriever import GraphRetriever, ContextBundle
from buddy.knowledge.updater import GraphUpdater
from buddy.core.state_detector import UserState


@pytest.fixture
def graph():
    """Create a temporary graph database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    g = KnowledgeGraph(db_path=path)
    yield g
    g.close()
    os.unlink(path)


@pytest.fixture
def populated_graph(graph):
    """Graph with a sample document, chunks, concepts, and edges."""
    doc_id = "doc-1"

    # Document node
    graph.add_node(Node(id=doc_id, type=NodeType.DOCUMENT, label="Test Doc", doc_id=doc_id))

    # Page chunks
    for page in [1, 2, 3]:
        graph.add_node(Node(
            id=f"chunk-{page}", type=NodeType.PAGE_CHUNK,
            label=f"Page {page}", data={"page": page, "text_preview": f"Content of page {page}"},
            doc_id=doc_id,
        ))

    # Concepts
    graph.add_node(Node(
        id="c-ml", type=NodeType.CONCEPT, label="Machine Learning",
        data={"definition": "Algorithms that learn from data"}, doc_id=doc_id, confidence=0.9,
    ))
    graph.add_node(Node(
        id="c-nn", type=NodeType.CONCEPT, label="Neural Networks",
        data={"definition": "Layered computational models"}, doc_id=doc_id, confidence=0.8,
    ))
    graph.add_node(Node(
        id="c-grad", type=NodeType.CONCEPT, label="Gradient Descent",
        data={"definition": "Optimization algorithm"}, doc_id=doc_id, confidence=0.85,
    ))

    # Claim
    graph.add_node(Node(
        id="cl-1", type=NodeType.CLAIM, label="NNs outperform traditional ML",
        data={"statement": "Neural networks outperform traditional ML on complex tasks"},
        doc_id=doc_id, confidence=0.7,
    ))

    # Mentions edges (chunk → concept)
    graph.add_edge(Edge(id="e1", source_id="chunk-1", target_id="c-ml", rel_type=EdgeType.MENTIONS))
    graph.add_edge(Edge(id="e2", source_id="chunk-2", target_id="c-nn", rel_type=EdgeType.MENTIONS))
    graph.add_edge(Edge(id="e3", source_id="chunk-2", target_id="c-grad", rel_type=EdgeType.MENTIONS))
    graph.add_edge(Edge(id="e4", source_id="chunk-2", target_id="cl-1", rel_type=EdgeType.MENTIONS))

    # Dependency: Neural Networks depends on Machine Learning
    graph.add_edge(Edge(id="e5", source_id="c-nn", target_id="c-ml", rel_type=EdgeType.DEPENDS_ON))

    # Dependency: Gradient Descent depends on Machine Learning
    graph.add_edge(Edge(id="e6", source_id="c-grad", target_id="c-ml", rel_type=EdgeType.DEPENDS_ON))

    # Claim supports Neural Networks
    graph.add_edge(Edge(id="e7", source_id="cl-1", target_id="c-nn", rel_type=EdgeType.SUPPORTS))

    return graph, doc_id


class TestGraphCRUD:
    def test_add_and_get_node(self, graph):
        node = Node(id="n1", type=NodeType.CONCEPT, label="Test Concept", doc_id="d1")
        graph.add_node(node)
        retrieved = graph.get_node("n1")
        assert retrieved is not None
        assert retrieved.label == "Test Concept"
        assert retrieved.type == NodeType.CONCEPT

    def test_find_nodes_by_type(self, graph):
        graph.add_node(Node(id="n1", type=NodeType.CONCEPT, label="A", doc_id="d1"))
        graph.add_node(Node(id="n2", type=NodeType.CLAIM, label="B", doc_id="d1"))
        graph.add_node(Node(id="n3", type=NodeType.CONCEPT, label="C", doc_id="d1"))

        concepts = graph.find_nodes(node_type=NodeType.CONCEPT)
        assert len(concepts) == 2

    def test_find_nodes_by_doc(self, graph):
        graph.add_node(Node(id="n1", type=NodeType.CONCEPT, label="A", doc_id="d1"))
        graph.add_node(Node(id="n2", type=NodeType.CONCEPT, label="B", doc_id="d2"))

        d1_nodes = graph.find_nodes(doc_id="d1")
        assert len(d1_nodes) == 1
        assert d1_nodes[0].id == "n1"

    def test_delete_node_removes_edges(self, graph):
        graph.add_node(Node(id="n1", type=NodeType.CONCEPT, label="A", doc_id="d1"))
        graph.add_node(Node(id="n2", type=NodeType.CONCEPT, label="B", doc_id="d1"))
        graph.add_edge(Edge(id="e1", source_id="n1", target_id="n2", rel_type=EdgeType.DEPENDS_ON))

        graph.delete_node("n1")
        assert graph.get_node("n1") is None
        assert graph.get_edges_from("n1") == []

    def test_update_confidence(self, graph):
        graph.add_node(Node(id="n1", type=NodeType.CONCEPT, label="A", doc_id="d1", confidence=0.5))
        graph.update_node_confidence("n1", 0.3)
        node = graph.get_node("n1")
        assert abs(node.confidence - 0.8) < 0.01

    def test_confidence_clamped_to_1(self, graph):
        graph.add_node(Node(id="n1", type=NodeType.CONCEPT, label="A", doc_id="d1", confidence=0.9))
        graph.update_node_confidence("n1", 0.5)
        node = graph.get_node("n1")
        assert node.confidence == 1.0

    def test_add_and_get_edges(self, graph):
        graph.add_node(Node(id="n1", type=NodeType.CONCEPT, label="A", doc_id="d1"))
        graph.add_node(Node(id="n2", type=NodeType.CONCEPT, label="B", doc_id="d1"))
        graph.add_edge(Edge(id="e1", source_id="n1", target_id="n2", rel_type=EdgeType.DEPENDS_ON))

        from_edges = graph.get_edges_from("n1")
        assert len(from_edges) == 1
        assert from_edges[0].target_id == "n2"

        to_edges = graph.get_edges_to("n2")
        assert len(to_edges) == 1

    def test_edge_weight_update(self, graph):
        graph.add_node(Node(id="n1", type=NodeType.CONCEPT, label="A", doc_id="d1"))
        graph.add_node(Node(id="n2", type=NodeType.CONCEPT, label="B", doc_id="d1"))
        graph.add_edge(Edge(id="e1", source_id="n1", target_id="n2", rel_type=EdgeType.MENTIONS, weight=1.0))

        graph.update_edge_weight("e1", 0.5)
        edges = graph.get_edges_from("n1")
        assert abs(edges[0].weight - 1.5) < 0.01


class TestGraphQueries:
    def test_get_concepts_for_page(self, populated_graph):
        graph, doc_id = populated_graph
        # Page 2 has Neural Networks, Gradient Descent, and a claim
        concepts = graph.get_concepts_for_page(doc_id, 2)
        names = {c.label for c in concepts}
        assert "Neural Networks" in names
        assert "Gradient Descent" in names

    def test_get_prerequisites(self, populated_graph):
        graph, doc_id = populated_graph
        # Neural Networks depends on Machine Learning
        prereqs = graph.get_prerequisites("c-nn")
        names = {p.label for p in prereqs}
        assert "Machine Learning" in names

    def test_get_page_chunk(self, populated_graph):
        graph, doc_id = populated_graph
        chunk = graph.get_page_chunk(doc_id, 2)
        assert chunk is not None
        assert chunk.data["page"] == 2

    def test_doc_stats(self, populated_graph):
        graph, doc_id = populated_graph
        stats = graph.get_doc_stats(doc_id)
        assert stats["concepts"] == 3
        assert stats["claims"] == 1
        assert stats["chunks"] == 3
        assert stats["edges"] > 0


class TestRetriever:
    def test_context_bundle_for_page(self, populated_graph):
        graph, doc_id = populated_graph
        retriever = GraphRetriever(graph)

        bundle = retriever.get_context_bundle(doc_id, 2, passage="Some text about neural networks")
        assert len(bundle.concepts) > 0
        assert bundle.passage == "Some text about neural networks"

    def test_context_bundle_includes_prereqs(self, populated_graph):
        graph, doc_id = populated_graph
        retriever = GraphRetriever(graph)

        bundle = retriever.get_context_bundle(doc_id, 2)
        prereq_names = {p["name"] for p in bundle.prerequisites}
        # ML is a prereq of NN which is on page 2
        assert "Machine Learning" in prereq_names

    def test_context_string_format(self, populated_graph):
        graph, doc_id = populated_graph
        retriever = GraphRetriever(graph)

        bundle = retriever.get_context_bundle(doc_id, 2, passage="Test passage")
        context_str = bundle.to_context_string()
        assert "Test passage" in context_str
        assert "Neural Networks" in context_str

    def test_empty_bundle_for_unknown_page(self, populated_graph):
        graph, doc_id = populated_graph
        retriever = GraphRetriever(graph)

        bundle = retriever.get_context_bundle(doc_id, 99)
        assert bundle.is_empty

    def test_concept_summary(self, populated_graph):
        graph, doc_id = populated_graph
        retriever = GraphRetriever(graph)

        summary = retriever.get_concept_summary(doc_id)
        assert len(summary) == 3
        names = {c["name"] for c in summary}
        assert "Machine Learning" in names


class TestUpdater:
    def test_record_stuck(self, populated_graph):
        graph, doc_id = populated_graph
        updater = GraphUpdater(graph)

        updater.record_stuck(doc_id, 2, UserState.STUCK)

        # Should have created a signal node
        signals = graph.find_nodes(node_type=NodeType.SIGNAL, doc_id=doc_id)
        assert len(signals) == 1
        assert "stuck" in signals[0].label.lower()

    def test_record_highlight_boosts_confidence(self, populated_graph):
        graph, doc_id = populated_graph
        updater = GraphUpdater(graph)

        original = graph.get_node("c-nn")
        original_conf = original.confidence

        updater.record_highlight(doc_id, 2, "Neural networks are interesting")

        updated = graph.get_node("c-nn")
        assert updated.confidence > original_conf

    def test_record_question_creates_concept(self, populated_graph):
        graph, doc_id = populated_graph
        updater = GraphUpdater(graph)

        updater.record_question_about(doc_id, "Backpropagation")

        matches = graph.find_nodes(node_type=NodeType.CONCEPT, doc_id=doc_id, label_contains="Backpropagation")
        assert len(matches) == 1
        assert matches[0].confidence == 0.6  # lower confidence for user-created

    def test_mark_understood(self, populated_graph):
        graph, doc_id = populated_graph
        updater = GraphUpdater(graph)

        updater.mark_understood(doc_id, "Neural Networks")

        node = graph.get_node("c-nn")
        assert node.data.get("understood") is True
