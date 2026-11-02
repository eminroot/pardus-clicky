"""Which recipe would a sentence run? For tuning recipes and examples.
Run in the VM with the venv python (no app or display needed):

    ~/.local/share/pardus-clicky/venv/bin/python scripts/dev/match.py "turn on dark mode" ["another sentence" ...]
    ~/.local/share/pardus-clicky/venv/bin/python scripts/dev/match.py --lexical "..."   (without the embedder)
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from pardus_clicky import local_ai, recipes  # noqa: E402
from pardus_clicky.recipes.matcher import Matcher  # noqa: E402
from pardus_clicky.recipes.world import World  # noqa: E402

args = sys.argv[1:]
lexical = "--lexical" in args
sentences = [a for a in args if a != "--lexical"]
started = time.monotonic()
matcher = Matcher(recipes.load_all(), None if lexical else local_ai.Embedder())
world = World()
print(f"{len(matcher.recipes)} recipes, {len(matcher.index)} examples, ready in {time.monotonic() - started:.2f}s")
for sentence in sentences:
    started = time.monotonic()
    ranked = matcher.rank(sentence)
    match = matcher.match(sentence, world)
    took = time.monotonic() - started
    top = ", ".join(f"{r.id} {s:.2f}" for s, r in ranked[:3])
    if match:
        slots = {k: getattr(v, "id", v) for k, v in match.slots.items()}
        print(f"{sentence!r}\n    -> {match.recipe.id} {slots} performer={match.performer}  [{top}] {took * 1000:.0f}ms")
    else:
        print(f"{sentence!r}\n    -> (online agent)  [{top}] {took * 1000:.0f}ms")
