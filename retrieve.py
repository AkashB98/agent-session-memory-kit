"""Retrieval and budgeted injection over memory cards.

Ranking is TF-IDF-style term scoring (term frequency in the card x
inverse document frequency across the active corpus), computed with
the standard library only - no embeddings, no vector store. Ties
break on card_id, so the same query over the same store always
returns the same order.

Token budget: one estimator, used everywhere -
``estimate_tokens(text) = ceil(words * 1.3)`` where words are
whitespace-separated tokens. Injection greedily takes ranked cards
whose rendered line fits the remaining budget (skipping an oversized
card and trying smaller later ones) and NEVER exceeds the budget.
"""

from __future__ import annotations

import math
import re
from typing import Dict, List, Sequence

from cards import active_cards

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "to", "of", "for",
    "on", "in", "at", "with", "after", "before", "and", "or", "it",
    "its", "this", "that", "we", "i", "you", "will",
}


def tokenize(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower())
            if t not in STOPWORDS and len(t) > 1]


def estimate_tokens(text: str) -> int:
    words = len(text.split())
    return math.ceil(words * 1.3) if words else 0


def _card_terms(card: Dict) -> List[str]:
    return tokenize(f"{card['kind']} {card['subject_key']} {card['text']}")


def score_cards(cards: List[Dict], query: str) -> List[Dict]:
    """Ranked scored results over ACTIVE cards with score > 0."""
    actives = active_cards(cards)
    query_terms = tokenize(query)
    if not actives or not query_terms:
        return []
    n = len(actives)
    doc_terms = [_card_terms(c) for c in actives]
    df: Dict[str, int] = {}
    for terms in doc_terms:
        for term in set(terms):
            df[term] = df.get(term, 0) + 1

    def idf(term: str) -> float:
        return math.log((1 + n) / (1 + df.get(term, 0))) + 1.0

    results = []
    for card, terms in zip(actives, doc_terms):
        score = 0.0
        for term in query_terms:
            if term in terms:
                score += terms.count(term) * idf(term)
        if score > 0:
            results.append({
                "card_id": card["card_id"],
                "score": round(score, 6),
                "kind": card["kind"],
                "subject_key": card["subject_key"],
                "text": card["text"],
            })
    results.sort(key=lambda r: (-r["score"], r["card_id"]))
    return results


def retrieve(cards: List[Dict], query: str, k: int = 5) -> List[Dict]:
    return score_cards(cards, query)[:k]


def render_line(result: Dict) -> str:
    return f"- [{result['kind']}] {result['text']}"


def inject(cards: List[Dict], query: str, budget_tokens: int,
           k: int = 10) -> Dict:
    """Top ranked cards under a strict token budget.

    Greedy in rank order: a card whose line does not fit is skipped
    (a smaller lower-ranked card may still fit). ``used_tokens`` is
    the sum of the included lines' estimates and is guaranteed
    ``<= budget_tokens``.
    """
    ranked = retrieve(cards, query, k=k)
    lines: List[str] = []
    ids: List[str] = []
    used = 0
    for result in ranked:
        line = render_line(result)
        cost = estimate_tokens(line)
        if used + cost <= budget_tokens:
            lines.append(line)
            ids.append(result["card_id"])
            used += cost
    return {
        "query": query,
        "budget_tokens": budget_tokens,
        "used_tokens": used,
        "card_ids": ids,
        "text": "\n".join(lines),
    }


def recall_precision_at_k(retrieved_ids: Sequence[str],
                          relevant_ids: Sequence[str], k: int) -> Dict:
    """recall@k = hits / |relevant|; precision@k = hits / k."""
    top = list(retrieved_ids)[:k]
    hits = sum(1 for cid in top if cid in set(relevant_ids))
    recall = hits / len(relevant_ids) if relevant_ids else 0.0
    precision = hits / k if k else 0.0
    return {"k": k, "hits": hits,
            "recall": round(recall, 4), "precision": round(precision, 4)}
