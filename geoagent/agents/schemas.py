"""Function-calling schemas exposed to the Supervisor and subagents."""
from __future__ import annotations

from ..cv_tools.registry import CV_TOOL_SCHEMAS

SUPERVISOR_TOOLS = CV_TOOL_SCHEMAS + [
    {
        "type": "function",
        "function": {
            "name": "inspect_image",
            "description": (
                "Look at the original figure (optionally one crop) with vision. "
                "Use sparingly: it consumes the visual-call budget. Never use it to "
                "measure coordinates precisely; use CV tools for that."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                        "description": "Optional ROI [x0,y0,x1,y1] normalized (0-1) or pixels >1.",
                    },
                    "question": {"type": "string", "description": "What to check in the image."},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_geometry_agent",
            "description": (
                "Delegate to the Geometry subagent: it runs CV tools itself and "
                "submits consolidated geometric objects/relations/conflicts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string", "description": "Precise task and focus."},
                    "use_image": {
                        "type": "boolean",
                        "description": "Let the subagent see the original image (costs a visual call).",
                    },
                    "roi": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                        "description": "Optional crop for the subagent.",
                    },
                },
                "required": ["instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tikz_agent",
            "description": (
                "Delegate to the TikZ subagent. mode=generate writes a first figure from "
                "the geometry state; mode=repair fixes the latest version using compiler "
                "errors and critic feedback. Compilation/render/validation happen "
                "automatically afterwards."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["generate", "repair"]},
                    "instruction": {"type": "string", "description": "What to change or emphasise."},
                    "use_image": {
                        "type": "boolean",
                        "description": "Allow the generator to view the original image (costs a visual call).",
                    },
                },
                "required": ["mode", "instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_critic",
            "description": (
                "Ask the Critic to compare the latest successful render with the original "
                "figure and list concrete mismatches. Costs one visual call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "Aspect to prioritise, e.g. arc extent, labels."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Stop the run and report the outcome. Call when a compiled figure "
            "(ideally critic-reviewed) exists, or when you are blocked.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "What was produced and its state."},
                    "unresolved": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Known open problems.",
                    },
                    "status": {"type": "string", "enum": ["success", "partial", "blocked"]},
                },
                "required": ["summary"],
            },
        },
    },
]

GEOMETRY_TOOLS = CV_TOOL_SCHEMAS + [
    {
        "type": "function",
        "function": {
            "name": "submit_geometry",
            "description": "Submit the final consolidated geometry as one JSON object (as a string).",
            "parameters": {
                "type": "object",
                "properties": {
                    "json": {"type": "string", "description": "JSON with keys objects, relations, conflicts, unresolved, summary."},
                },
                "required": ["json"],
            },
        },
    }
]

TIKZ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "submit_tikz",
            "description": "Submit a complete, compilable standalone LaTeX/TikZ document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tex": {"type": "string", "description": "Full document source (or bare tikzpicture)."},
                    "notes": {"type": "string", "description": "Short description of decisions made."},
                },
                "required": ["tex"],
            },
        },
    }
]


SUPERVISOR_NAMES = [
    "inspect_image",
    "run_geometry_agent",
    "run_tikz_agent",
    "run_critic",
    "finish",
]
