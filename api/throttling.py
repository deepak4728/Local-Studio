from rest_framework.throttling import SimpleRateThrottle


class _ClientThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        ident = request.META.get("REMOTE_ADDR", "")
        owner = request.headers.get("X-Chat-Owner", "")
        return self.cache_format % {"scope": self.scope, "ident": f"{ident}:{owner}"}


class ChatRateThrottle(_ClientThrottle):
    scope = "chat"


class OrderCreateThrottle(_ClientThrottle):
    scope = "orders"

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)
