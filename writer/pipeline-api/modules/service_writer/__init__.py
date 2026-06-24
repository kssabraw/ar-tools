"""Service Page Writer module.

Consumes a Service Page Brief and produces a conversion-focused service page,
rendered as Markdown, HTML, and WordPress (Gutenberg) block markup, with
Service + FAQPage JSON-LD.
"""

from .router import router

__all__ = ["router"]
