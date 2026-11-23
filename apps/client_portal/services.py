"""Client Portal business logic.

Handles magic link generation, verification, and portal session creation.
"""

import logging

from django.conf import settings
from django.contrib.auth import login
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from apps.common.mail import send_or_raise, transactional
from apps.members.models import WorkspaceMembership

from .models import MagicLinkToken

logger = logging.getLogger(__name__)


def generate_magic_link(workspace, client_user, created_by):
    """Generate a magic link for a client user and send it via email.

    Args:
        workspace: The Workspace the client belongs to.
        client_user: The User with client role.
        created_by: The User (manager) who initiated the generation.

    Returns:
        The created MagicLinkToken.

    Raises:
        ValueError: If the user is not a client of this workspace, or the email
            could not be sent — in which case no new token is left behind and
            any existing link keeps working.
    """
    # Validate client has client role in workspace
    membership = WorkspaceMembership.objects.filter(
        user=client_user,
        workspace=workspace,
        workspace_role=WorkspaceMembership.WorkspaceRole.CLIENT,
    ).first()

    if not membership:
        raise ValueError("User does not have client role in this workspace.")

    # The previously issued tokens are NOT invalidated yet. They used to be
    # revoked here, before the new link was sent, which meant a send that did
    # not happen — a refused address, the outbound budget, a broken mail
    # server — left the client with no way in at all while the manager was told
    # the link had gone out. The old links are revoked further down, once the
    # replacement is known to have left.
    superseded = list(
        MagicLinkToken.objects.filter(
            user=client_user,
            workspace=workspace,
            is_consumed=False,
            expires_at__gt=timezone.now(),
        ).values_list("pk", flat=True)
    )

    # Create new token
    token = MagicLinkToken.objects.create(
        user=client_user,
        workspace=workspace,
    )

    # Build magic link URL
    app_url = getattr(settings, "APP_URL", "http://localhost:8000").rstrip("/")
    magic_url = f"{app_url}/portal/{token.token}/"

    # Send email
    context = {
        "client_user": client_user,
        "workspace": workspace,
        "magic_url": magic_url,
        "created_by": created_by,
        "app_url": app_url,
    }

    subject = f"{workspace.name}: publicaciones listas para tu revisión"
    text_content = render_to_string("client_portal/email/magic_link.txt", context)
    html_content = render_to_string("client_portal/email/magic_link.html", context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@localhost"),
        to=[client_user.email],
        # A login link a manager just asked us to send: the recipient is waiting
        # for it, so the per-recipient notification cap must not eat it.
        headers=transactional(),
    )
    msg.attach_alternative(html_content, "text/html")

    try:
        send_or_raise(msg)
    except Exception as exc:
        logger.exception("Failed to send magic link email to %s", client_user.email)
        # Roll the new token back so we do not leave a link nobody was told
        # about, and leave the client's existing one working.
        MagicLinkToken.objects.filter(pk=token.pk).delete()
        raise ValueError("We could not send that link right now. Please try again shortly.") from exc

    # The replacement is on its way, so the old links can go.
    if superseded:
        MagicLinkToken.objects.filter(pk__in=superseded).update(expires_at=timezone.now())

    return token


def peek_magic_link(token_string):
    """Validate a magic link token *without* consuming it.

    Used to render the confirmation page on GET so that email link scanners
    that prefetch the URL cannot burn the one-time token. Returns the
    MagicLinkToken when it is valid and unused, otherwise None.
    """
    try:
        token = MagicLinkToken.objects.select_related("user", "workspace").get(token=token_string)
    except MagicLinkToken.DoesNotExist:
        return None

    if token.is_expired or token.is_consumed:
        return None

    return token


def consume_magic_link(token_string):
    """Validate and atomically consume a magic link token (single-use).

    Returns:
        (user, workspace, is_valid) tuple.
        If missing/expired/already consumed: (None, None, False).
    """
    try:
        token = MagicLinkToken.objects.select_related("user", "workspace").get(token=token_string)
    except MagicLinkToken.DoesNotExist:
        return None, None, False

    if token.is_expired:
        return None, None, False

    # Atomic single-use: only the request that flips is_consumed False->True wins.
    consumed = MagicLinkToken.objects.filter(pk=token.pk, is_consumed=False).update(
        is_consumed=True,
        last_used_at=timezone.now(),
    )
    if not consumed:
        return None, None, False

    return token.user, token.workspace, True


def revoke_magic_link(token_id, workspace):
    """Revoke an active magic link by expiring it immediately."""
    MagicLinkToken.objects.filter(
        id=token_id,
        workspace=workspace,
        expires_at__gt=timezone.now(),
    ).update(expires_at=timezone.now())


def create_portal_session(request, user, workspace):
    """Create a portal session for the client user.

    Logs in the user and sets portal-specific session variables. Si es la primera
    vez que el cliente entra al portal (last_login todavía None), avisamos al
    equipo del workspace (owner + admins) con una notificación — así se enteran
    sin tener que llamar al cliente para preguntar si el magic link funcionó.
    """
    is_first_login = user.last_login is None
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session["is_portal_session"] = True
    request.session["portal_workspace_id"] = str(workspace.id)
    # 30-day session
    request.session.set_expiry(30 * 24 * 60 * 60)

    if is_first_login:
        try:
            _notify_team_of_first_client_login(user, workspace)
        except Exception:
            # Nunca romper el login por un fallo de notificación.
            logger.exception("Could not notify team of first client login for %s", user.email)


def _notify_team_of_first_client_login(client_user, workspace):
    """Avisa a owner + admins del workspace que el cliente entró al portal por primera vez."""
    from apps.members.models import WorkspaceMembership
    from apps.notifications.engine import notify
    from apps.notifications.models import EventType

    recipients = WorkspaceMembership.objects.filter(
        workspace=workspace,
        workspace_role__in=[
            WorkspaceMembership.WorkspaceRole.OWNER,
            WorkspaceMembership.WorkspaceRole.ADMIN,
        ],
    ).select_related("user")

    client_label = client_user.name or client_user.email
    for membership in recipients:
        notify(
            user=membership.user,
            event_type=EventType.CLIENT_PORTAL_FIRST_LOGIN,
            title=f"{client_label} entró al portal",
            body=f"El cliente de {workspace.name} abrió el portal por primera vez. Ya puede aprobar publicaciones.",
            data={
                "workspace_id": str(workspace.id),
                "client_user_id": str(client_user.pk),
            },
        )


REVIEW_LINK_DAYS = 7
REVIEW_MAIL_COOLDOWN_SECONDS = 30 * 60


def send_review_request(workspace, client_user):
    """Email a client a one-click link to the portal approval queue.

    One email per client per half hour: posts sent in a burst share a single
    message, since the portal lists everything pending anyway. The link lasts
    seven days. Returns the token, or None when the cooldown suppressed it.
    Raises if the email cannot be sent (the token is rolled back).
    """
    from datetime import timedelta

    from django.core.cache import cache

    from apps.composer.models import Post

    cooldown_key = f"portal-review-mail:{workspace.id}:{client_user.pk}"
    if cache.get(cooldown_key):
        return None

    pending = (
        Post.objects.for_workspace(workspace.id).filter(platform_posts__status="pending_client").distinct().count()
    )
    token = MagicLinkToken.objects.create(
        user=client_user,
        workspace=workspace,
        expires_at=timezone.now() + timedelta(days=REVIEW_LINK_DAYS),
    )
    app_url = getattr(settings, "APP_URL", "http://localhost:8000").rstrip("/")
    context = {
        "client_user": client_user,
        "workspace": workspace,
        "magic_url": f"{app_url}/portal/{token.token}/",
        "pending_count": pending,
        "link_days": REVIEW_LINK_DAYS,
    }
    msg = EmailMultiAlternatives(
        subject=f"{workspace.name}: tienes publicaciones para aprobar",
        body=render_to_string("client_portal/email/review_request.txt", context),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@localhost"),
        to=[client_user.email],
        headers=transactional(),
    )
    msg.attach_alternative(render_to_string("client_portal/email/review_request.html", context), "text/html")
    try:
        send_or_raise(msg)
    except Exception:
        MagicLinkToken.objects.filter(pk=token.pk).delete()
        raise
    cache.set(cooldown_key, 1, REVIEW_MAIL_COOLDOWN_SECONDS)
    return token
