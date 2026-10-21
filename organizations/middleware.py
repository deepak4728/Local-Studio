from django.utils.cache import patch_cache_control


class PrivateWorkspaceCacheMiddleware:
    """Avoid retaining workspace pages and responses in shared/browser caches."""

    private_prefixes = ("/org/", "/dashboard/", "/api/", "/_chat/", "/chat/", "/staff/", "/restaurant/staff/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(self.private_prefixes) or (
            request.path == "/" and getattr(request.user, "is_authenticated", False)
        ):
            patch_cache_control(response, private=True, no_store=True, no_cache=True, must_revalidate=True)
            response["Expires"] = "0"
        return response
