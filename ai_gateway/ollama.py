import json
from urllib.request import Request, urlopen
from django.conf import settings


class InvalidOllamaResponse(ValueError):
    pass


def open_ollama_response(path, payload=None):
    body = None
    headers = {"Accept": "application/json, application/x-ndjson"}
    method = "GET"

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"

    request = Request(
        f"{settings.OLLAMA_BASE_URL}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    return urlopen(request, timeout=settings.OLLAMA_TIMEOUT_SECONDS)


def get_ollama_models():
    with open_ollama_response("/api/tags") as response:
        data = json.load(response)

    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise InvalidOllamaResponse("Expected Ollama's model list response.")

    return data["models"]
