"""Function tools the model can call. One call is one visible step on screen.

Schemas use strict mode, so every property is required and optional ones are
nullable. Coordinates are pixels in the latest screenshot.
"""

POINTER_ACTIONS = ("click", "double_click", "right_click", "drag", "point")

_int_or_null = {"type": ["integer", "null"]}

STEP = {
    "type": "function",
    "name": "step",
    "strict": True,
    "description": (
        "Do or show one small, visible step on the desktop. The pointer flies to (x, y), "
        "`say` is spoken and captioned, then the action happens (performer assistant) or "
        "the user is asked to do it (performer user). You get a new screenshot back."
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["say", "label", "action", "performer", "x", "y", "x2", "y2", "text", "keys", "amount"],
        "properties": {
            "say": {"type": "string", "description": "One short spoken sentence about this step, at most about 15 words."},
            "label": {"type": "string", "description": "The target's text exactly as on screen, or 1-3 words naming it. Empty for keys or typing."},
            "action": {
                "type": "string",
                "enum": ["click", "double_click", "right_click", "drag", "scroll", "type", "keys", "point", "wait"],
                "description": (
                    "The real action of this step, also when the user is the one who does it. "
                    "point = only show and explain something that nobody needs to click. "
                    "wait = give a slow window a moment to appear."),
            },
            "performer": {
                "type": "string",
                "enum": ["assistant", "user"],
                "description": (
                    "assistant: you do the action yourself. user: the pointer shows the target and Clicky waits "
                    "until the user has done the action; you then get the new screen."),
            },
            "x": {**_int_or_null, "description": "Target x (drag: start x). Null for keys, type without a field, or wait."},
            "y": {**_int_or_null, "description": "Target y (drag: start y)."},
            "x2": {**_int_or_null, "description": "Drag end x, otherwise null."},
            "y2": {**_int_or_null, "description": "Drag end y, otherwise null."},
            "text": {"type": ["string", "null"], "description": (
                "For action=type: the text, typed into the field that has keyboard focus (x, y only shows where). "
                "Selected text is replaced. Otherwise null.")},
            "keys": {"type": ["string", "null"], "description": (
                "For action=keys: one combo or several in order, separated by commas, "
                "e.g. 'Return', 'Escape', 'ctrl+a, BackSpace'. Otherwise null.")},
            "amount": {**_int_or_null, "description": "For action=scroll: wheel clicks, positive scrolls down. Otherwise null."},
        },
    },
}

DRAW = {
    "type": "function",
    "name": "draw",
    "strict": True,
    "description": (
        "Sketch on top of the screen to explain something: circles, arrows, boxes, lines, "
        "freehand paths and short text notes. Shapes appear one after another while `say` is spoken."
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["say", "clear_first", "shapes"],
        "properties": {
            "say": {"type": "string", "description": "One or two short spoken sentences explaining the drawing."},
            "clear_first": {"type": "boolean", "description": "Remove earlier drawings before drawing these."},
            "shapes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "x", "y", "x2", "y2", "r", "text", "points", "color"],
                    "properties": {
                        "kind": {"type": "string", "enum": ["circle", "arrow", "box", "line", "path", "text"]},
                        "x": {"type": "integer", "description": "circle: centre x. arrow/line: start x. box: left. text: left."},
                        "y": {"type": "integer"},
                        "x2": {**_int_or_null, "description": "arrow/line end x, box right. Null otherwise."},
                        "y2": _int_or_null,
                        "r": {**_int_or_null, "description": "circle radius. Null otherwise."},
                        "text": {"type": ["string", "null"], "description": "text: the note. Optional label for arrows."},
                        "points": {
                            "type": ["array", "null"],
                            "description": "path: list of [x, y] points. Null otherwise.",
                            "items": {"type": "array", "items": {"type": "integer"}},
                        },
                        "color": {"type": "string", "enum": ["coral", "blue", "green", "yellow", "white", "black"]},
                    },
                },
            },
        },
    },
}

ASK_USER = {
    "type": "function",
    "name": "ask_user",
    "strict": True,
    "description": "Ask the user a short question out loud and wait for their spoken answer. Use for confirmations and missing details.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["question"],
        "properties": {"question": {"type": "string"}},
    },
}

FINISH = {
    "type": "function",
    "name": "finish",
    "strict": True,
    "description": "End the task with one short spoken sentence: what was done, or why it could not be done.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["say"],
        "properties": {"say": {"type": "string"}},
    },
}

ALL = [STEP, DRAW, ASK_USER, FINISH]
