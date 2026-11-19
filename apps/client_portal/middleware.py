"""Confine client-only users to the client portal.

A user whose only role anywhere is "client" (no org owner/admin, no other
workspace role) must never see the rest of the app: after accepting an
invitation or logging in, they land in /portal/ and any other URL sends them
back there.
"""

from django.core.cache import cache
from django.shortcuts import redirect

from apps.members.models import OrgMembership, WorkspaceMembership

ALLOWED_PREFIXES = (
    "/portal/",
    "/accounts/",
    "/members/invite/",
    "/static/",
    "/media/",
    "/health/",
    "/privacy/",
    "/terms/",
)

_CACHE_SECONDS = 60


def client_only_workspace_ids(user):
    """Workspace ids where ``user`` is a client, or [] if they have any other role."""
    key = f"client-only:{user.pk}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    result = []
    is_staff_org = OrgMembership.objects.filter(
        user=user, org_role__in=[OrgMembership.OrgRole.OWNER, OrgMembership.OrgRole.ADMIN]
    ).exists()
    if not is_staff_org:
        memberships = list(
            WorkspaceMembership.objects.filter(user=user, workspace__is_archived=False).values_list(
                "workspace_id", "workspace_role", "custom_role_id"
            )
        )
        if memberships and all(role == "client" and custom is None for _, role, custom in memberships):
            result = [str(ws_id) for ws_id, _, _ in memberships]
    cache.set(key, result, _CACHE_SECONDS)
    return result


class ClientPortalConfinementMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(("/static/", "/media/")):
            return self.get_response(request)

        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            workspace_ids = client_only_workspace_ids(user)
            if workspace_ids:
                session = request.session
                if not session.get("is_portal_session") or session.get("portal_workspace_id") not in workspace_ids:
                    session["is_portal_session"] = True
                    session["portal_workspace_id"] = workspace_ids[0]
                if not request.path.startswith(ALLOWED_PREFIXES):
                    return redirect("client_portal:dashboard")

        return self.get_response(request)
