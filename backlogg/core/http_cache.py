"""HTTP caching — Cache-Control + ETag/If-None-Match in one middleware.

Feature 40. A single :class:`CacheHeadersMiddleware` attaches the right
``Cache-Control`` to idempotent GET reads and gives detail reads an ``ETag`` so
a client can revalidate with ``If-None-Match`` and get a ``304 Not Modified``
without re-transferring the body.

Routes are classified by their *route template* (``/movies/{slug}``), resolved
from the Starlette scope after routing, so the policy lives in one place instead
of being sprinkled across every router (no duplicated logic, DRY call sites).

Sharing rules (the important part):

* **Listings** (catalog lists, ``/genres``, ``/trending``) do not depend on the
  caller, so they are ``public`` and safe for shared caches.
* **Detail** reads carry ``viewer_status`` when authenticated (feature 31), so an
  authenticated response is user-specific: it is marked ``private`` and never
  ``public``, and ``Vary: Authorization`` stops a shared cache from serving an
  anonymous body to an authenticated caller (or vice versa). Anonymous detail
  reads are identical for everyone and stay ``public``. Both variants still get
  an ``ETag`` so clients can revalidate (``304``).
* **User-state** reads (``/feed``, ``/users/me``) are ``private, no-store`` —
  never stored in any shared cache.
"""

import hashlib

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backlogg.core.config import settings

# Detail reads: cacheable per item, revalidate with ETag. May be user-specific
# (viewer_status) when authenticated.
DETAIL_TEMPLATES = frozenset({"/movies/{slug}", "/series/{slug}", "/books/{slug}", "/games/{slug}"})

# Catalog listings + the expensive aggregate reads. Never user-specific.
LISTING_TEMPLATES = frozenset({"/movies", "/series", "/books", "/games", "/genres", "/trending"})

# Per-user state: must never land in a shared cache.
PRIVATE_TEMPLATES = frozenset({"/feed", "/users/me"})


def _route_template(request: Request) -> str | None:
    """Return the matched route template, or ``None`` for unmatched URLs.

    Starlette stores the matched route on the shared scope during routing, so it
    is available once ``call_next`` has returned. The template (``/movies/{slug}``)
    is stable regardless of the concrete slug.
    """
    route = request.scope.get("route")
    return getattr(route, "path", None)


def _compute_etag(body: bytes) -> str:
    """Strong ETag: a quoted hex digest of the exact response bytes."""
    return f'"{hashlib.sha256(body).hexdigest()}"'


def _if_none_match(header: str | None, etag: str) -> bool:
    """Return True when *header* (an ``If-None-Match`` value) matches *etag*.

    Supports the wildcard ``*`` and a comma-separated list of validators.
    """
    if not header:
        return False
    candidates = {token.strip() for token in header.split(",")}
    return "*" in candidates or etag in candidates


def _listing_max_age(template: str) -> int:
    """Cache-Control max-age for a listing template.

    ``/trending`` and ``/genres`` advertise the same TTL the in-process cache
    holds them for; other catalog listings use the generic listing max-age.
    """
    if template == "/trending":
        return settings.CACHE_TTL_TRENDING
    if template == "/genres":
        return settings.CACHE_TTL_GENRES
    return settings.CACHE_CONTROL_LISTING_MAX_AGE


class CacheHeadersMiddleware(BaseHTTPMiddleware):
    """Attach Cache-Control to reads and serve ``304`` for detail revalidation.

    Only successful (``200``) GET responses are touched; everything else passes
    through unchanged. Registered as the innermost app middleware so the security
    headers still decorate the rebuilt / ``304`` responses it produces.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if request.method != "GET" or response.status_code != 200:
            return response

        template = _route_template(request)
        if template is None:
            return response

        if template in PRIVATE_TEMPLATES:
            response.headers["Cache-Control"] = "private, no-store"
            return response

        if template in LISTING_TEMPLATES:
            response.headers["Cache-Control"] = f"public, max-age={_listing_max_age(template)}"
            return response

        if template in DETAIL_TEMPLATES:
            return await self._handle_detail(request, response)

        return response

    async def _handle_detail(self, request: Request, response: Response) -> Response:
        # Read the full body so we can hash it into an ETag. Detail responses are
        # small JSON documents, so buffering them is cheap.
        body = b"".join([section async for section in response.body_iterator])
        etag = _compute_etag(body)

        # An authenticated detail read includes viewer_status, so it is
        # user-specific: keep it out of shared caches (private) and let a shared
        # cache key on Authorization just in case.
        authenticated = "authorization" in request.headers
        if authenticated:
            cache_control = "private, no-cache"
        else:
            cache_control = f"public, max-age={settings.CACHE_CONTROL_DETAIL_MAX_AGE}"

        common_headers = {
            "ETag": etag,
            "Cache-Control": cache_control,
            "Vary": "Authorization",
        }

        if _if_none_match(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=common_headers)

        headers = {key: value for key, value in response.headers.items()}
        headers.pop("content-length", None)
        headers.update(common_headers)
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
        )
