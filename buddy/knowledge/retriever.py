"""Assembles context bundles from the knowledge graph for LLM prompts."""

import logging
from dataclasses import dataclass, field

from .graph import KnowledgeGraph, Node, NodeType, EdgeType

logger = logging.getLogger(__name__)


@dataclass
class ContextBundle:
    """Enriched context for LLM prompts, assembled from the knowledge graph."""
    passage: str = ""
    concepts: list[dict] = field(default_factory=list)       # [{name, definition}]
    prerequisites: list[dict] = field(default_factory=list)   # [{name, definition}]
    claims: list[dict] = field(default_factory=list)          # [{statement}]
    confusion_history: list[dict] = field(default_factory=list)  # [{concept, page, when}]

    def to_context_string(self) -> str:
        """Format the bundle as a string for LLM system prompt injection."""
        parts = []

        if self.passage:
            parts.append(f"Current passage:\n---\n{self.passage}\n---")

        if self.concepts:
            concept_lines = [f"- {c['name']}: {c.get('definition', '')}" for c in self.concepts]
            parts.append("Key concepts on this page:\n" + "\n".join(concept_lines))

        if self.prerequisites:
            prereq_lines = [f"- {p['name']}: {p.get('definition', '')}" for p in self.prerequisites]
            parts.append("Prerequisites (concepts this page builds on):\n" + "\n".join(prereq_lines))

        if self.claims:
            claim_lines = [f"- {c['statement']}" for c in self.claims]
            parts.append("Claims made in this section:\n" + "\n".join(claim_lines))

        if self.confusion_history:
            confused = [f"- Reader struggled with \"{h['concept']}\" (page {h.get('page', '?')})" for h in self.confusion_history]
            parts.append("Reader's past difficulties:\n" + "\n".join(confused))

        return "\n\n".join(parts)

    @property
    def is_empty(self) -> bool:
        return not (self.concepts or self.prerequisites or self.claims or self.confusion_history)


class GraphRetriever:
    """Retrieves context bundles from the knowledge graph for a given page."""

    def __init__(self, graph: KnowledgeGraph):
        self.graph = graph

    def get_context_bundle(self, doc_id: str, page: int, passage: str = "",
                           max_concepts: int = 7, max_prereqs: int = 5) -> ContextBundle:
        """Build a full context bundle for a page."""
        bundle = ContextBundle(passage=passage)

        if not doc_id:
            return bundle

        # 1. Get concepts and claims for this page
        page_nodes = self.graph.get_concepts_for_page(doc_id, page)

        concept_ids = []
        for node in page_nodes:
            if node.type == NodeType.CONCEPT and len(bundle.concepts) < max_concepts:
                bundle.concepts.append({
                    "name": node.label,
                    "definition": node.data.get("definition", ""),
                })
                concept_ids.append(node.id)
            elif node.type == NodeType.CLAIM and len(bundle.claims) < 5:
                bundle.claims.append({
                    "statement": node.data.get("statement", node.label),
                })

        # 2. Get prerequisites for page concepts
        for cid in concept_ids[:5]:  # limit prereq lookups
            prereqs = self.graph.get_prerequisites(cid, depth=2)
            for prereq in prereqs:
                if len(bundle.prerequisites) >= max_prereqs:
                    break
                # Don't duplicate concepts already listed
                if not any(c["name"].lower() == prereq.label.lower() for c in bundle.concepts):
                    if not any(p["name"].lower() == prereq.label.lower() for p in bundle.prerequisites):
                        bundle.prerequisites.append({
                            "name": prereq.label,
                            "definition": prereq.data.get("definition", ""),
                        })

        # 3. Get confusion history for these concepts
        confusion = self.graph.get_confusion_history(doc_id, concept_ids, limit=5)
        for signal in confusion:
            # Find which concept this confusion was about
            edges = self.graph.get_edges_from(signal.id, rel_type=EdgeType.CONFUSED_AT)
            for edge in edges:
                target = self.graph.get_node(edge.target_id)
                if target:
                    bundle.confusion_history.append({
                        "concept": target.label,
                        "page": signal.data.get("page", "?"),
                        "state": signal.data.get("state", "stuck"),
                    })

        logger.debug(
            "Context bundle for page %d: %d concepts, %d prereqs, %d claims, %d confusion entries",
            page, len(bundle.concepts), len(bundle.prerequisites),
            len(bundle.claims), len(bundle.confusion_history),
        )
        return bundle

    def get_concept_summary(self, doc_id: str) -> list[dict]:
        """Get a summary of all concepts in a document (for concept map UI)."""
        concepts = self.graph.find_nodes(node_type=NodeType.CONCEPT, doc_id=doc_id, limit=200)
        result = []
        for c in concepts:
            deps = self.graph.get_edges_from(c.id, rel_type=EdgeType.DEPENDS_ON)
            result.append({
                "id": c.id,
                "name": c.label,
                "definition": c.data.get("definition", ""),
                "confidence": c.confidence,
                "depends_on": [d.target_id for d in deps],
            })
        return result
