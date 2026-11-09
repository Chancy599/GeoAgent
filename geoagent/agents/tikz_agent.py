"""Compatibility imports for the agent now named CodeAgent."""
from .code_agent import CodeAgent as TikZAgent, _complete_document, _geometry_digest

__all__ = ["TikZAgent", "_complete_document", "_geometry_digest"]
