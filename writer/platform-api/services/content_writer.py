"""Content-writer provider selection (owner request 2026-09).

One place resolves which LLM provider writes a client's DRAFT prose across all
four content writers (blog + service/location in pipeline-api; Local SEO +
Ecommerce in nlp-api):

    per-run/request override  ??  client default  ??  "openai"

Only a PROVIDER string is resolved here ("anthropic" | "openai"); the concrete
OpenAI model id lives in each generating service's own config
(``content_writer_openai_model`` / ``CONTENT_WRITER_OPENAI_MODEL``), so the Luna
version bumps via env with no code change here. Mirrors how ``entity_provider``
is resolved (the default lives with the generator), but adds a client-level
default column so a client can standardize on one writer.

Pure + import-light so every creation path (runs, Local SEO / Ecommerce jobs,
Fanout, reoptimize) can share it.
"""

from __future__ import annotations

from typing import Optional

CONTENT_WRITER_PROVIDERS = ("anthropic", "openai")
# The agency standardized on OpenAI (gpt-5.6-luna) for draft prose (owner request
# 2026-09-15), so a piece of content with no override and no client-level default
# falls back to OpenAI. Mirrors clients.content_writer_provider's DB default.
DEFAULT_CONTENT_WRITER_PROVIDER = "openai"


def normalize_provider(value: Optional[str]) -> Optional[str]:
    """A known provider string, or None for anything unrecognized/empty. Pure."""
    if value is None:
        return None
    v = str(value).strip().lower()
    return v if v in CONTENT_WRITER_PROVIDERS else None


def resolve_content_writer_provider(
    override: Optional[str], client: Optional[dict]
) -> str:
    """Effective provider for a piece of content: the per-run/request override if
    valid, else the client's ``content_writer_provider`` default, else
    ``DEFAULT_CONTENT_WRITER_PROVIDER`` ("openai"). Never raises; an unknown value
    at any level is ignored (falls through), so a bad column can't route content to
    a nonexistent provider."""
    chosen = normalize_provider(override)
    if chosen:
        return chosen
    if client:
        client_default = normalize_provider(client.get("content_writer_provider"))
        if client_default:
            return client_default
    return DEFAULT_CONTENT_WRITER_PROVIDER
