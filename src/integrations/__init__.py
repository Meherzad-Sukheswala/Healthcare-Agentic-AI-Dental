"""Integration layer: standards-shaped adapter ports + sandbox/real implementations."""
from .registry import ServiceRegistry, build_registry

__all__ = ["ServiceRegistry", "build_registry"]
