from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from canto.models.schemas import Policy


class PolicyDenied(ValueError):
    pass


def evaluate_policy(provider: dict[str, Any], inputs: dict[str, Any], policy: Policy) -> list[str]:
    permissions = provider.get("permissions", {})
    reasons: list[str] = []

    if permissions.get("network_read") and not policy.allow_network:
        raise PolicyDenied("Provider requires network access, but policy.allow_network is false")
    if permissions.get("destructive") and not policy.allow_destructive:
        raise PolicyDenied("Provider is destructive, but policy.allow_destructive is false")
    if permissions.get("filesystem_write") and not policy.allow_filesystem_write:
        raise PolicyDenied("Provider writes artifacts, but policy.allow_filesystem_write is false")

    approval_rules = set(provider.get("approval_required", []))
    if "always" in approval_rules or "scaffold_capability" in approval_rules:
        reasons.append("Provider requires Cantor approval")
    if "max_depth_greater_than_5" in approval_rules and int(inputs.get("max_depth", 0)) > 5:
        reasons.append("Crawl depth greater than 5")
    if "network_access_to_non_approved_domain" in approval_rules:
        source_url = inputs.get("source_url")
        hostname = urlparse(source_url).hostname if isinstance(source_url, str) else None
        approved = {domain.lower() for domain in policy.approved_domains}
        if hostname and hostname.lower() not in approved:
            reasons.append(f"Network access to non-approved domain {hostname}")
    if permissions.get("database_write"):
        reasons.append("Database write access")
    if permissions.get("production_access"):
        reasons.append("Production access")
    if policy.mode == "live" and provider.get("risk_level", 1) >= 2:
        reasons.append("Live execution with elevated risk")
    return sorted(set(reasons))

