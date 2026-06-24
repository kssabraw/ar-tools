"""Service Page Brief Generator module.

Generates a structured, commercial-intent brief for a single service page,
running its own research pipeline (SERP shape → competitor teardown → entity
coverage → question mining → AIO presence) and a reconciliation synthesis that
lets the client's differentiator reshape the competitor-derived skeleton.
"""

from .router import router

__all__ = ["router"]
