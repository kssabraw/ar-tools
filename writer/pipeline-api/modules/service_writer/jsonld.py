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
    page_type: str = "service",
    location: Optional[str] = None,
    services: Optional[list[str]] = None,
) -> str:
    """Return a JSON-LD string with Service node(s) and (if FAQs) a FAQPage node.

    For a location page the graph emits one Service node per covered service,
    each `areaServed` the target location, under a shared LocalBusiness provider.
    """
    graph: list[dict[str, Any]] = []

    wa = website_analysis or {}
    provider: dict[str, Any] = {}
    if brand_name:
        provider["name"] = brand_name
    if isinstance(wa, dict):
        contact = wa.get("contact_info") or {}
        if isinstance(contact, dict) and contact.get("phone"):
            provider["telephone"] = contact["phone"]
    if provider:
        provider["@type"] = "LocalBusiness"

    services = [s.strip() for s in (services or []) if s and s.strip()]
    if page_type == "location" and services:
        # One Service node per covered service, all served in the target area.
        area = location or primary_query
        for svc in services[:25]:
            node: dict[str, Any] = {"@type": "Service", "name": svc}
            if area:
                node["areaServed"] = area
            if provider:
                node["provider"] = provider
            graph.append(node)
    else:
        service_node: dict[str, Any] = {
            "@type": "Service",
            "name": service or primary_query,
        }
        if isinstance(wa, dict):
            areas = wa.get("locations") or []
            if areas:
                service_node["areaServed"] = areas[:20]
        if provider:
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
