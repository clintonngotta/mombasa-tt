from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request


class StandardPagination(PageNumberPagination):
    """Default page-number pagination for list endpoints (REQ-032)."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def search_term(request: Request) -> str:
    return request.query_params.get("search", "").strip()
