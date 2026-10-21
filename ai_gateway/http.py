import json
import logging
from urllib.error import HTTPError
from rest_framework import status
from rest_framework.response import Response
from .providers import CloudProviderNotConfigured, UnsupportedCloudProvider, InvalidCloudProviderResponse


logger = logging.getLogger(__name__)

def _upstream_error_response(error, provider="Ollama"):
    if isinstance(error, HTTPError):
        upstream_detail = ""
        try:
            error_body = error.read().decode("utf-8")
            error_data = json.loads(error_body)
            upstream_detail = error_data.get("error", "") if isinstance(error_data, dict) else ""
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        logger.warning("%s returned HTTP %s for an API request.", provider, error.code)
        status_field = "ollama_status" if provider == "Ollama" else "provider_status"
        response_data = {
            "detail": f"{provider} returned an error.",
            status_field: error.code,
        }
        if upstream_detail:
            response_data["upstream_detail"] = upstream_detail[:500]
        return Response(response_data, status=status.HTTP_502_BAD_GATEWAY)

    logger.warning("Unable to reach %s: %s", provider, error)
    detail = (
        f"{provider} did not respond before the timeout."
        if isinstance(error, TimeoutError)
        else f"Unable to connect to {provider}."
    )
    return Response(
        {"detail": detail},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _model_provider_error_response(error):
    if isinstance(error, CloudProviderNotConfigured):
        return Response({"detail": str(error)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if isinstance(error, UnsupportedCloudProvider):
        return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
    if isinstance(error, InvalidCloudProviderResponse):
        return Response({"detail": str(error)}, status=status.HTTP_502_BAD_GATEWAY)
    return Response(
        {"detail": "The selected model provider is not supported."},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _invalid_ollama_response():
    logger.error("Ollama returned an invalid JSON response.")
    return Response(
        {"detail": "Ollama returned an invalid response."},
        status=status.HTTP_502_BAD_GATEWAY,
    )
