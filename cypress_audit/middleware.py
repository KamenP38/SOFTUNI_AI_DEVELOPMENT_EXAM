class AuditIdentityMiddleware:
    """Identify the isolated server without adding a product test endpoint."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-Cypress-Audit"] = "isolated-synthetic-database"
        return response
