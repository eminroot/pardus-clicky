"""Understands a request well enough to pick a recipe, without the internet.

Each recipe lists example sentences. The request is compared with all of them
using sentence embeddings (MiniLM on the CPU), or word overlap when the model
is not installed. The best recipes are tried in order; the first whose parser
finds what it needs (an app name, a folder name...) wins. Below the threshold
nothing matches and the online agent (if allowed) takes the request.
"""

import logging
import re
from dataclasses import dataclass

from .world import spaced

log = logging.getLogger(__name__)

GUIDE = re.compile(r"\b(guide me|let me (do|try|click)|i('ll| will) (do|click|try)|by myself|on my own|"
                   r"teach me to|walk me through|myself)\b", re.IGNORECASE)
DO_IT = re.compile(r"\b(do it for me|you do it|for me please)\b", re.IGNORECASE)
FILLER = re.compile(r"\b(please|can you|could you|would you|will you|hey|clicky|i want you to|i'd like you to|for me)\b",
                    re.IGNORECASE)
STOPWORDS = set("a an the to of on in my me i you it is are be can could would please and or for with this that "
                "how do does what where which show tell want need let us".split())


def clean(text):
    return " ".join(FILLER.sub(" ", text).split()).strip(" .!?")


def tokens(text):
    return {w.rstrip("s") for w in spaced(text).split() if w not in STOPWORDS}


@dataclass
class Match:
    recipe: object
    slots: dict
    score: float
    performer: str = None


class Matcher:
    THRESHOLD = 0.45          # cosine similarity, with embeddings (off-topic requests score below 0.35)
    LEXICAL_THRESHOLD = 0.34  # word overlap, without
    KEYWORD_BONUS = 0.05
    # When the best recipe can't use the request, a runner-up is only tried if it
    # was nearly as close. Otherwise "switch to <unknown app>" could end up closing a window.
    FALLBACK_GAP = 0.12

    def __init__(self, recipes, embedder=None):
        self.recipes = recipes
        self.embedder = embedder
        self.index = [(r, ex) for r in recipes for ex in r.examples]
        self.vectors = embedder.encode([clean(ex) for _, ex in self.index]) if embedder else None
        self._lexical = [(r, tokens(ex)) for r, ex in self.index]

    def rank(self, text):
        """[(score, recipe)] best first, one entry per recipe."""
        query = clean(text)
        best = {}
        if self.vectors is not None:
            sims = self.vectors @ self.embedder.encode([query])[0]
            for (recipe, _), sim in zip(self.index, sims):
                best[recipe.id] = max(best.get(recipe.id, -1.0), float(sim))
        else:
            words = tokens(query)
            for recipe, ex_words in self._lexical:
                union = words | ex_words
                score = len(words & ex_words) / len(union) if union else 0.0
                best[recipe.id] = max(best.get(recipe.id, 0.0), score)
        by_id = {r.id: r for r in self.recipes}
        words = spaced(query)
        for rid in best:
            if any(spaced(k) in words for k in by_id[rid].keywords):
                best[rid] += self.KEYWORD_BONUS
        return sorted(((score, by_id[rid]) for rid, score in best.items()), key=lambda p: -p[0])

    def match(self, text, world):
        performer = "user" if GUIDE.search(text) else "assistant" if DO_IT.search(text) else None
        threshold = self.THRESHOLD if self.vectors is not None else self.LEXICAL_THRESHOLD
        ranked = self.rank(text)
        log.info("match %r: %s", text, ", ".join(f"{r.id} {s:.2f}" for s, r in ranked[:4]))
        top = ranked[0][0] if ranked else 0.0
        for score, recipe in ranked[:5]:
            if score < threshold or top - score > self.FALLBACK_GAP:
                break
            try:
                slots = recipe.slots(text, world)
            except Exception:  # noqa: BLE001 - a broken parser must not break matching
                log.exception("parser of %s failed", recipe.id)
                continue
            if slots is not None:
                return Match(recipe, slots, score, performer)
        return None
