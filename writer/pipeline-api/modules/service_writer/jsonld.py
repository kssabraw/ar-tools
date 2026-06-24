"""JSON-LD builder: Service + FAQPage structured data (PRD brief Layer 3).

Deterministic — no LLM. Emits a compact @graph the page can drop into <head>.
"""

from __future__ import annotations

import json
from typing import Any, Optional


def build_jsonld(
    *,
    service: str,
    primary_query: str,
    brand_name: str = "",
    website_analysis: Optional[dict[str, Any]] = None,
    faqs: Optional[list[dict[str, str]]] = None,
) -> str:
    """Return a JSON-LD string with a Service node and (if FAQs) a FAQPage node."""
    graph: list[dict[str, Any]] = []

    service_node: dict[str, Any] = {
        "@type": "Service",
        "name": service or primary_query,
    }
    provider: dict[str, Any] = {}
    if brand_name:
        provider["name"] = brand_name
    wa = website_analysis or {}
    if isinstance(wa, dict):
        contact = wa.get("contact_info") or {}
        if isinstance(contact, dict) and contact.get("phone"):
            provider["telephone"] = contact["phone"]
        areas = wa.get("locations") or []
        if areas:
            service_node["areaServed"] = areas[:20]
    if provider:
        provider["@type"] = "LocalBusiness"
        service_node["provider"] = provider
    graph.append(service_node)

    clean_faqs = [
        f for f in (faqs or [])
        if isinstance(f, dict) and f.get("question") and f.get("answer")
    ]
    if clean_faqs:
        graph.append({
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": f["question"],
                    "acceptedAnswer": {"@type": "Answer", "text": f["answer"]},
                }
                for f in clean_faqs
            ],
        })

    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)
