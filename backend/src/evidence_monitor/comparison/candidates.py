"""Step 1: embed claims and find top-5 candidate newer claims per anchor."""

import json
import logging
from datetime import datetime, UTC

import numpy as np
from sqlalchemy import select

from ..db import session_scope, create_all
from ..models import Claim, ClaimEmbedding, ClaimPair, Paper

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "all-MiniLM-L6-v2"


_encoder = None

def _get_encoder():
    global _encoder
    if _encoder is None:
        from sentence_transformers import SentenceTransformer
        _encoder = SentenceTransformer(EMBEDDING_MODEL)
    return _encoder


def _embed_text(claim: Claim) -> list[float]:
    text = " ".join(filter(None, [claim.claim_text, claim.outcome_measure, claim.population]))
    encoder = _get_encoder()
    return encoder.encode(text, normalize_embeddings=True).tolist()


def build_embeddings(force: bool = False) -> int:
    """Embed all claims that don't have an embedding yet. Returns count created."""
    create_all()
    created = 0
    with session_scope() as session:
        claims = session.execute(select(Claim)).scalars().all()
        for claim in claims:
            existing = session.get(ClaimEmbedding, claim.id)
            if existing and not force:
                continue
            vec = _embed_text(claim)
            if existing:
                existing.embedding_json = json.dumps(vec)
                existing.model = EMBEDDING_MODEL
            else:
                session.add(ClaimEmbedding(
                    claim_id=claim.id,
                    model=EMBEDDING_MODEL,
                    embedding_json=json.dumps(vec),
                ))
            created += 1
    return created


def _cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(np.dot(va, vb) / denom) if denom > 0 else 0.0


def find_candidates(limit: int | None = None, top_k: int = 5) -> int:
    """
    For each anchor claim, find up to top_k newer candidate claims by:
    1. Embedding similarity (all claims with embeddings).
    2. Claims from papers that cite the anchor's paper.
    Store as ClaimPair rows. Returns count of new pairs created.
    """
    create_all()
    new_pairs = 0

    with session_scope() as session:
        # Load all embeddings
        emb_rows = session.execute(select(ClaimEmbedding)).scalars().all()
        emb_map: dict[str, list[float]] = {
            e.claim_id: json.loads(e.embedding_json) for e in emb_rows
        }

        # Load all claims with their paper publication years
        claims = session.execute(
            select(Claim, Paper)
            .join(Paper, Claim.paper_id == Paper.id)
        ).all()

    claim_list = [(c, p) for c, p in claims]
    anchors = claim_list[:limit] if limit else claim_list

    for anchor_claim, anchor_paper in anchors:
        if anchor_claim.id not in emb_map:
            continue

        anchor_vec = emb_map[anchor_claim.id]
        anchor_year = anchor_paper.publication_year or 0

        # Score all other claims that are newer (same-paper guard: skip same paper)
        scored: list[tuple[float, str]] = []
        for cand_claim, cand_paper in claim_list:
            if cand_claim.id == anchor_claim.id:
                continue
            # Same-paper guard: never pair claims from the same paper
            if cand_claim.paper_id == anchor_claim.paper_id:
                continue
            cand_year = cand_paper.publication_year or 0
            if cand_year < anchor_year:
                continue
            if cand_claim.id not in emb_map:
                continue
            # Skip heavily overlapping source sentences (Jaccard >= 0.7)
            a_words = set(anchor_claim.source_sentence.lower().split())
            b_words = set(cand_claim.source_sentence.lower().split())
            if a_words and b_words:
                jaccard = len(a_words & b_words) / len(a_words | b_words)
                if jaccard >= 0.7:
                    continue
            sim = _cosine(anchor_vec, emb_map[cand_claim.id])
            scored.append((sim, cand_claim.id))

        scored.sort(reverse=True)
        top = scored[:top_k]

        with session_scope() as session:
            for sim, cand_id in top:
                existing = session.execute(
                    select(ClaimPair).where(
                        ClaimPair.anchor_claim_id == anchor_claim.id,
                        ClaimPair.new_claim_id == cand_id,
                    )
                ).scalar_one_or_none()
                if existing is None:
                    session.add(ClaimPair(
                        anchor_claim_id=anchor_claim.id,
                        new_claim_id=cand_id,
                        similarity=sim,
                    ))
                    new_pairs += 1

    return new_pairs
