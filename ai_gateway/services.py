import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen
from .models import AIConfiguration
from .ollama import open_ollama_response
from .providers import open_cloud_response


"""Single server-side entry point for local and optional cloud AI providers."""


def open_model_response(profile, payload, *, local_adapter=None):
    """Route an inference request through the provider selected by the business."""
    if profile.effective_provider == AIConfiguration.PROVIDER_LOCAL:
        adapter = local_adapter or open_ollama_response
        return adapter("/api/chat", payload)
    if profile.effective_provider == AIConfiguration.PROVIDER_CLOUD:
        return open_cloud_response(profile, payload)
    raise ValueError("The selected model provider is not supported.")


def generate_json(profile, prompt, system_prompt, *, max_tokens=2000):
    payload = {
        "model": profile.default_model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "options": {"num_predict": max_tokens},
    }
    with open_model_response(profile, payload) as response:
        result = json.load(response)
    content = result.get("message", {}).get("content", "")
    return json.loads(content)


def classify_remote(data_points, fields):
    """Call an optional System 1 endpoint; return None when unconfigured/unavailable."""
    endpoint = os.environ.get("JEV_API_URL") or os.environ.get("SCALEDOWN_API_URL")
    if not endpoint:
        return None
    key = os.environ.get("JEV_API_KEY") or os.environ.get("SCALEDOWN_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["x-api-key"] = key
    request = Request(
        endpoint,
        data=json.dumps({"data_points": data_points, "dataPoints": data_points, "fields": fields}).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=4) as response:
            result = json.load(response)
        classifications = result.get("classifications", result.get("results"))
        if isinstance(classifications, list):
            return classifications
    except (OSError, ValueError, URLError, TimeoutError, json.JSONDecodeError):
        return None
    return None


def configuration_for_request(request, *, manage=False):
    from organizations.models import Organization, OrganizationMembership
    from organizations.permissions import require_membership
    from django.shortcuts import get_object_or_404
    from django.core.exceptions import PermissionDenied
    slug = request.headers.get("X-Organization") or getattr(request, "query_params", request.GET).get("org", "") or getattr(request, "data", {}).get("organization_slug", "") or request.session.get("active_organization_slug", "")
    if slug:
        organization = get_object_or_404(Organization, slug=slug)
        require_membership(request.user, organization, manage=manage)
        return AIConfiguration.for_organization(organization)
    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False) and hasattr(user, "_meta"):
        memberships = OrganizationMembership.objects.filter(user=user).select_related("organization")
        if memberships.count() == 1:
            membership = memberships.first()
            require_membership(user, membership.organization, manage=manage)
            return AIConfiguration.for_organization(membership.organization)
        raise PermissionDenied("Select an organization with the X-Organization header.")
    return AIConfiguration.get_or_create_default()
