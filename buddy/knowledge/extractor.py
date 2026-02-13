"""LLM-powered concept and claim extraction from document chunks."""

import json
import logging
from dataclasses import dataclass

from ..llm.base import LLMProvider
from .graph import KnowledgeGraph, Node, Edge, NodeType, EdgeType, make_id

logger = logging.getLogger(__name__)


# ── Extraction Prompts ───────────────────────────────────────────────────────

EXTRACT_PROMPT = """\
Analyze this passage and extract:

1. **Concepts** — key terms, topics, or ideas (1-4 words each)
2. **Claims** — specific assertions or arguments the author makes (1 sentence each)
3. **Relationships** between them

For each concept, provide:
- name: short label (1-4 words)
- definition: one-sentence explanation in simple language
- prerequisites: other concepts needed to understand this one (from this passage or general knowledge)

For each claim, provide:
- statement: the claim in one sentence
- supports: which concepts this claim supports or relates to

Return ONLY valid JSON in this exact format (no markdown, no extra text):
{
  "concepts": [
    {"name": "...", "definition": "...", "prerequisites": ["..."]}
  ],
  "claims": [
    {"statement": "...", "supports": ["..."]}
  ]
}

If the passage is too short or has no meaningful concepts, return:
{"concepts": [], "claims": []}

Passage:
---
{text}
---"""


RELATE_PROMPT = """\
Given these concepts extracted from a document, identify relationships between them.

Concepts:
{concept_list}

For each pair that has a relationship, specify:
- source: concept name
- target: concept name
- relation: one of "depends_on" (source requires understanding target first), "explains" (source helps clarify target)

Return ONLY valid JSON:
{
  "relationships": [
    {"source": "...", "target": "...", "relation": "depends_on|explains"}
  ]
}

If no relationships exist, return: {"relationships": []}"""


# ── Extractor ────────────────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    concepts_added: int = 0
    claims_added: int = 0
    edges_added: int = 0


class ConceptExtractor:
    """Extracts concepts, claims, and relationships from text using an LLM."""

    def __init__(self, llm: LLMProvider, graph: KnowledgeGraph):
        self.llm = llm
        self.graph = graph

    async def extract_from_page(self, doc_id: str, page: int, text: str) -> ExtractionResult:
        """Extract concepts and claims from a single page's text."""
        if not text.strip() or len(text.strip()) < 50:
            return ExtractionResult()

        # Create page chunk node
        chunk_id = make_id()
        self.graph.add_node(Node(
            id=chunk_id,
            type=NodeType.PAGE_CHUNK,
            label=f"Page {page}",
            data={"page": page, "text_preview": text[:200]},
            doc_id=doc_id,
        ))

        # Extract concepts and claims via LLM
        result = ExtractionResult()
        try:
            prompt = EXTRACT_PROMPT.format(text=text[:3000])  # cap input length
            resp = await self.llm.generate(prompt)
            parsed = self._parse_json(resp.text)
        except Exception as e:
            logger.error("Extraction failed for page %d: %s", page, e)
            return result

        if not parsed:
            return result

        # Store concepts
        concept_map: dict[str, str] = {}  # name → node_id
        for c in parsed.get("concepts", []):
            name = c.get("name", "").strip()
            if not name:
                continue
            # Check if concept already exists for this doc
            existing = self.graph.find_nodes(
                node_type=NodeType.CONCEPT, doc_id=doc_id, label_contains=name, limit=1
            )
            if existing and existing[0].label.lower() == name.lower():
                concept_id = existing[0].id
            else:
                concept_id = make_id()
                self.graph.add_node(Node(
                    id=concept_id,
                    type=NodeType.CONCEPT,
                    label=name,
                    data={
                        "definition": c.get("definition", ""),
                        "prerequisites": c.get("prerequisites", []),
                    },
                    doc_id=doc_id,
                    confidence=0.8,
                ))
                result.concepts_added += 1

            concept_map[name.lower()] = concept_id

            # Link chunk → concept
            self.graph.add_edge(Edge(
                id=make_id(),
                source_id=chunk_id,
                target_id=concept_id,
                rel_type=EdgeType.MENTIONS,
            ))
            result.edges_added += 1

        # Store claims
        for cl in parsed.get("claims", []):
            statement = cl.get("statement", "").strip()
            if not statement:
                continue
            claim_id = make_id()
            self.graph.add_node(Node(
                id=claim_id,
                type=NodeType.CLAIM,
                label=statement[:80],
                data={"statement": statement},
                doc_id=doc_id,
                confidence=0.8,
            ))
            result.claims_added += 1

            # Link chunk → claim
            self.graph.add_edge(Edge(
                id=make_id(),
                source_id=chunk_id,
                target_id=claim_id,
                rel_type=EdgeType.MENTIONS,
            ))
            result.edges_added += 1

            # Link claim → concepts it supports
            for concept_name in cl.get("supports", []):
                cid = concept_map.get(concept_name.lower())
                if cid:
                    self.graph.add_edge(Edge(
                        id=make_id(),
                        source_id=claim_id,
                        target_id=cid,
                        rel_type=EdgeType.SUPPORTS,
                    ))
                    result.edges_added += 1

        # Create prerequisite edges from concept data
        for c in parsed.get("concepts", []):
            name = c.get("name", "").strip().lower()
            source_id = concept_map.get(name)
            if not source_id:
                continue
            for prereq_name in c.get("prerequisites", []):
                target_id = concept_map.get(prereq_name.lower())
                if target_id and target_id != source_id:
                    self.graph.add_edge(Edge(
                        id=make_id(),
                        source_id=source_id,
                        target_id=target_id,
                        rel_type=EdgeType.DEPENDS_ON,
                    ))
                    result.edges_added += 1

        logger.info(
            "Page %d: extracted %d concepts, %d claims, %d edges",
            page, result.concepts_added, result.claims_added, result.edges_added,
        )
        return result

    async def extract_from_document(self, doc_id: str, pages: list[dict]) -> ExtractionResult:
        """Extract from all pages of a document. Pages: [{"page": int, "text": str}]."""
        total = ExtractionResult()

        # Create document node
        self.graph.add_node(Node(
            id=doc_id,
            type=NodeType.DOCUMENT,
            label=f"Document {doc_id[:8]}",
            doc_id=doc_id,
        ))

        for p in pages:
            result = await self.extract_from_page(doc_id, p["page"], p["text"])
            total.concepts_added += result.concepts_added
            total.claims_added += result.claims_added
            total.edges_added += result.edges_added

        # Cross-page relationship inference
        cross = await self._infer_cross_relationships(doc_id)
        total.edges_added += cross

        stats = self.graph.get_doc_stats(doc_id)
        logger.info(
            "Document %s extraction complete: %d concepts, %d claims, %d total edges",
            doc_id[:8], stats["concepts"], stats["claims"], stats["edges"],
        )
        return total

    async def _infer_cross_relationships(self, doc_id: str) -> int:
        """Use LLM to find depends_on/explains relationships across all concepts in a document."""
        concepts = self.graph.find_nodes(node_type=NodeType.CONCEPT, doc_id=doc_id, limit=50)
        if len(concepts) < 2:
            return 0

        concept_list = "\n".join(
            f"- {c.label}: {c.data.get('definition', 'no definition')}" for c in concepts
        )
        concept_map = {c.label.lower(): c.id for c in concepts}

        try:
            prompt = RELATE_PROMPT.format(concept_list=concept_list)
            resp = await self.llm.generate(prompt)
            parsed = self._parse_json(resp.text)
        except Exception as e:
            logger.error("Cross-relationship inference failed: %s", e)
            return 0

        if not parsed:
            return 0

        edges_added = 0
        for rel in parsed.get("relationships", []):
            source_name = rel.get("source", "").lower()
            target_name = rel.get("target", "").lower()
            rel_type = rel.get("relation", "")

            if rel_type not in (EdgeType.DEPENDS_ON, EdgeType.EXPLAINS):
                continue

            source_id = concept_map.get(source_name)
            target_id = concept_map.get(target_name)

            if source_id and target_id and source_id != target_id:
                self.graph.add_edge(Edge(
                    id=make_id(),
                    source_id=source_id,
                    target_id=target_id,
                    rel_type=rel_type,
                ))
                edges_added += 1

        logger.info("Cross-page inference: added %d relationship edges", edges_added)
        return edges_added

    def _parse_json(self, text: str) -> dict | None:
        """Robustly parse JSON from LLM response (handles markdown fences)."""
        text = text.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last fence lines
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            logger.warning("Failed to parse LLM JSON response: %s...", text[:100])
            return None
