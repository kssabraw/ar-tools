"""Provider-aware prose generation for the service/location page writer.

The service writer's PROSE calls (title/meta/CTA, section bodies + their
banned-term retry, FAQ answers) route through :func:`prose_json_model` so a
service/location run can write its draft with OpenAI (gpt-5.6-luna) instead of
Claude, exactly like the blog Writer. Selection rides the shared per-request
contextvar in ``modules.writer.prose_llm`` (set once at the top of
``run_service_writer``); the default is Anthropic, so this is a drop-in for
``claude_json_model``.

The Anthropic branch stays on the service transport (``service_brief.llm`` +
its own cost tally); the OpenAI branch reuses the shared ``openai_json`` but
records usage into the service-page cost bucket.
"""

from __future__ import annotations

from typing import Any, Optional

from modules.service_brief.cost import record_usage as _service_record_usage
from modules.service_brief.llm import claude_json_model
from modules.writer.prose_llm import current_prose_provider, openai_json


async def prose_json_model(
    system: str,
    user: str,
    *,
    model: str,
    max_tokens: int = 1500,
    temperature: Optional[float] = 0.4,
) -> Any:
    """Generate one JSON prose response with the request's selected provider.

    ``model`` is the Claude model id used on the Anthropic path (unchanged); the
    OpenAI path uses ``content_writer_openai_model``.
    """
    if current_prose_provider() == "openai":
        return await openai_json(
            system,
            user,
            max_tokens=max_tokens,
            temperature=temperature,
            record_usage=_service_record_usage,
        )
    return await claude_json_model(
        system, user, model=model, max_tokens=max_tokens, temperature=temperature
    )
