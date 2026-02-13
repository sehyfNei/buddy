"""Incremental graph updates from reading signals and user actions."""

import logging

from ..core.state_detector import UserState
from .graph import KnowledgeGraph, Node, Edge, NodeType, EdgeType, make_id

logger = logging.getLogger(__name__)


class GraphUpdater:
    """Updates the knowledge graph based on reading signals and user interactions."""

    def __init__(self, graph: KnowledgeGraph):
        self.graph = graph

    def record_stuck(self, doc_id: str, page: int, state: UserState) -> None:
        """Record a STUCK or TIRED signal and create confused_at edges to page concepts."""
        if state not in (UserState.STUCK, UserState.TIRED):
            return

        # Create signal node
        signal_id = make_id()
        self.graph.add_node(Node(
            id=signal_id,
            type=NodeType.SIGNAL,
            label=f"{state.value} on page {page}",
            data={"page": page, "state": state.value},
            doc_id=doc_id,
        ))

        # Link to page chunk
        chunk = self.graph.get_page_chunk(doc_id, page)
        if chunk:
            self.graph.add_edge(Edge(
                id=make_id(),
                source_id=signal_id,
                target_id=chunk.id,
                rel_type=EdgeType.CONFUSED_AT,
            ))

        # Link to concepts on this page
        concepts = self.graph.get_concepts_for_page(doc_id, page)
        for concept in concepts:
            self.graph.add_edge(Edge(
                id=make_id(),
                source_id=signal_id,
                target_id=concept.id,
                rel_type=EdgeType.CONFUSED_AT,
            ))
            # Lower concept confidence slightly (user finds it hard)
            self.graph.update_node_confidence(concept.id, -0.05)

        logger.info(
            "Recorded %s signal for page %d, linked to %d concepts",
            state.value, page, len(concepts),
        )

    def record_highlight(self, doc_id: str, page: int, text: str) -> None:
        """Record a highlight and boost related concept weights."""
        # Create annotation node
        annotation_id = make_id()
        self.graph.add_node(Node(
            id=annotation_id,
            type=NodeType.ANNOTATION,
            label=text[:80],
            data={"page": page, "text": text},
            doc_id=doc_id,
        ))

        # Link to page chunk
        chunk = self.graph.get_page_chunk(doc_id, page)
        if chunk:
            self.graph.add_edge(Edge(
                id=make_id(),
                source_id=annotation_id,
                target_id=chunk.id,
                rel_type=EdgeType.ANNOTATED,
            ))

        # Boost confidence of concepts on this page (user engaged with them)
        concepts = self.graph.get_concepts_for_page(doc_id, page)
        for concept in concepts:
            self.graph.update_node_confidence(concept.id, 0.1)

        logger.info("Recorded highlight on page %d, boosted %d concepts", page, len(concepts))

    def record_question_about(self, doc_id: str, concept_name: str) -> None:
        """When user asks about a concept, boost its retrieval priority."""
        matches = self.graph.find_nodes(
            node_type=NodeType.CONCEPT, doc_id=doc_id, label_contains=concept_name, limit=1
        )
        if matches:
            # Boost weight — user is actively interested
            self.graph.update_node_confidence(matches[0].id, 0.15)
            logger.info("Boosted concept '%s' — user asked about it", concept_name)
        else:
            # Concept not in graph — create it with lower confidence
            new_id = make_id()
            self.graph.add_node(Node(
                id=new_id,
                type=NodeType.CONCEPT,
                label=concept_name,
                data={"definition": "", "source": "user_question"},
                doc_id=doc_id,
                confidence=0.6,
            ))
            logger.info("Created new concept '%s' from user question", concept_name)

    def record_reread(self, doc_id: str, page: int) -> None:
        """When user re-reads a page, slightly increase edge weights for that page's concepts."""
        concepts = self.graph.get_concepts_for_page(doc_id, page)
        for concept in concepts:
            # Boost mentions edges for this page
            edges = self.graph.get_edges_to(concept.id, rel_type=EdgeType.MENTIONS)
            for edge in edges:
                self.graph.update_edge_weight(edge.id, 0.1)

    def mark_understood(self, doc_id: str, concept_name: str) -> None:
        """Mark a concept as understood — reduces future intervention weight."""
        matches = self.graph.find_nodes(
            node_type=NodeType.CONCEPT, doc_id=doc_id, label_contains=concept_name, limit=1
        )
        if matches:
            node = matches[0]
            node.data["understood"] = True
            self.graph.add_node(node)  # re-save with updated data
            self.graph.update_node_confidence(node.id, 0.2)
            logger.info("Marked concept '%s' as understood", concept_name)
