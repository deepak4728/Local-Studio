import json
from io import BytesIO
from urllib.request import Request, urlopen

from django.conf import settings


class CloudProviderError(ValueError):
    pass


class CloudProviderNotConfigured(CloudProviderError):
    pass


class UnsupportedCloudProvider(CloudProviderError):
    pass


class InvalidCloudProviderResponse(CloudProviderError):
    pass


def validate_cloud_provider(profile):
    provider = profile.cloud_provider.strip().lower()
    if provider not in {"openai", "openai-compatible"}:
        raise UnsupportedCloudProvider(
            "Choose OpenAI or an OpenAI-compatible provider in business settings."
        )
    if not settings.CLOUD_API_KEY:
        raise CloudProviderNotConfigured("Set CLOUD_API_KEY on the server to use the cloud provider.")
    if not settings.CLOUD_API_BASE_URL:
        raise CloudProviderNotConfigured("Set CLOUD_API_BASE_URL on the server to use the cloud provider.")


def open_cloud_response(profile, payload):
    validate_cloud_provider(profile)
    request_payload = {
        "model": payload["model"],
        "messages": payload["messages"],
        "stream": False,
    }
    if payload.get("format") == "json":
        request_payload["response_format"] = {"type": "json_object"}

    request = Request(
        f"{settings.CLOUD_API_BASE_URL.rstrip('/')}/chat/completions",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {settings.CLOUD_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=settings.OLLAMA_TIMEOUT_SECONDS) as upstream:
            response = json.load(upstream)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise InvalidCloudProviderResponse("The cloud provider returned invalid JSON.") from error

    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise InvalidCloudProviderResponse("The cloud provider returned an invalid response.") from error
    if not isinstance(content, str):
        raise InvalidCloudProviderResponse("The cloud provider returned an invalid response.")

    normalized = {"message": {"role": "assistant", "content": content}, "done": True}
    return BytesIO(json.dumps(normalized, ensure_ascii=True).encode("utf-8") + b"\n")