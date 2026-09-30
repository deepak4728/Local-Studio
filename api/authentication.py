import hmac
from dataclasses import dataclass

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import APIException, AuthenticationFailed


@dataclass(frozen=True)
class APIKeyPrincipal:
    is_authenticated: bool = True
    is_anonymous: bool = False
    is_staff: bool = False


@dataclass(frozen=True)
class StaffKeyPrincipal(APIKeyPrincipal):
    is_staff: bool = True


class APIKeyNotConfigured(APIException):
    status_code = 503
    default_detail = "API key authentication is not configured."
    default_code = "api_key_not_configured"


class APIKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        configured_key = settings.API_KEY
        if not configured_key:
            raise APIKeyNotConfigured()

        supplied_key = request.headers.get("X-API-Key")
        if supplied_key is None:
            raise AuthenticationFailed("The X-API-Key header is required.")

        if not hmac.compare_digest(
            supplied_key.encode("utf-8"),
            configured_key.encode("utf-8"),
        ):
            raise AuthenticationFailed("The API key is invalid.")

        return APIKeyPrincipal(), None

    def authenticate_header(self, request):
        return "Api-Key"


class StaffKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        configured_key = settings.STAFF_API_KEY
        if not configured_key:
            raise APIKeyNotConfigured()

        supplied_key = request.headers.get("X-Staff-Key")
        if supplied_key is None:
            raise AuthenticationFailed("The X-Staff-Key header is required.")

        if not hmac.compare_digest(
            supplied_key.encode("utf-8"),
            configured_key.encode("utf-8"),
        ):
            raise AuthenticationFailed("The X-Staff-Key is invalid.")

        return StaffKeyPrincipal(), None

    def authenticate_header(self, request):
        return "Staff-Key"


class APIKeyOrStaffKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        if request.headers.get("X-Staff-Key") is not None:
            return StaffKeyAuthentication().authenticate(request)
        return APIKeyAuthentication().authenticate(request)

    def authenticate_header(self, request):
        return "Api-Key"
