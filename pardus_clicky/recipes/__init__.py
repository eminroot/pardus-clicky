"""Offline recipes: the desktop tasks Clicky knows by heart.

A recipe is a short Python function that does one task through the visible
interface (pointer flies, speaks, clicks), finding every button by name
through the shell extension or AT-SPI instead of looking at screenshots. It
works without internet, takes the same steps every time, and is fast.

Register one with @recipe:

    @recipe("dark_mode",
            examples=["turn on dark mode", "make everything dark", ...],
            parse=lambda text, world: {"on": world.on_off(text)})
    def dark_mode(ctx, on=None):
        ...

`examples` teach the matcher what users say; `parse` pulls the details out of
the request (return None when this recipe cannot handle it, so the matcher
tries the next one). See AGENTS.md for how to write one.
"""

from dataclasses import dataclass, field


@dataclass
class Recipe:
    id: str
    examples: list
    run: object
    parse: object = None
    keywords: tuple = field(default_factory=tuple)

    def slots(self, text, world):
        return self.parse(text, world) if self.parse else {}


REGISTRY = []


def recipe(id, examples, parse=None, keywords=()):
    def register(fn):
        REGISTRY.append(Recipe(id, list(examples), fn, parse, tuple(keywords)))
        return fn
    return register


def load_all():
    """Import the recipe modules so they register themselves."""
    from . import appearance, desktop, explain, system, windows  # noqa: F401
    return REGISTRY
