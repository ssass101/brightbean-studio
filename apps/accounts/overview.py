"""Resumen de cuentas: cuántas publicaciones programadas tiene cada cuenta por delante.

Alimenta la página de inicio (``/``). Para cada espacio de trabajo al que el
usuario pertenece, lista sus cuentas conectadas con:

- cantidad de publicaciones programadas hacia adelante,
- cuántas caen en los próximos 7 días,
- fecha de la próxima y de la última programada,
- un estado de alerta (``empty`` / ``low`` / ``ok`` / ``disconnected``).

Solo cuentan las publicaciones en estado "programada" con fecha futura. Los
borradores y las pendientes de aprobación no se consideran contenido listo.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from django.db.models.functions import Coalesce
from django.utils import timezone

# Una cuenta pasa a "poco contenido" si su última publicación programada cae
# dentro de estos días (o antes). Ajustar aquí para cambiar la sensibilidad.
LOW_CONTENT_DAYS = 3

_STATUS_ORDER = {"empty": 0, "disconnected": 1, "low": 2, "ok": 3}
_WEEKDAYS_SHORT = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _short_date(dt) -> str:
    """'jue 20 nov', en español e independiente del locale del sistema."""
    from apps.calendar.views import _es_day_month

    local = timezone.localtime(dt)
    return f"{_WEEKDAYS_SHORT[local.weekday()]} {_es_day_month(local)}"


def build_overview(user) -> dict:
    from apps.composer.models import PlatformPost
    from apps.members.models import WorkspaceMembership
    from apps.social_accounts.models import SocialAccount

    memberships = (
        WorkspaceMembership.objects.filter(user=user, workspace__is_archived=False)
        .select_related("workspace")
        .order_by("workspace__name")
    )
    workspaces = [m.workspace for m in memberships]
    workspace_ids = [w.id for w in workspaces]

    now = timezone.now()
    week_limit = now + timedelta(days=7)

    scheduled = (
        PlatformPost.objects.filter(
            social_account__workspace_id__in=workspace_ids,
            status=PlatformPost.Status.SCHEDULED,
        )
        .annotate(effective_at=Coalesce("scheduled_at", "post__scheduled_at"))
        .filter(effective_at__gte=now)
        .values_list("social_account_id", "effective_at")
    )
    times_by_account: dict = defaultdict(list)
    for account_id, effective_at in scheduled:
        times_by_account[account_id].append(effective_at)

    accounts_by_workspace: dict = defaultdict(list)
    accounts = SocialAccount.objects.filter(workspace_id__in=workspace_ids).order_by("platform", "account_name")
    for account in accounts:
        times = sorted(times_by_account.get(account.id, []))
        connected = account.connection_status in (
            SocialAccount.ConnectionStatus.CONNECTED,
            SocialAccount.ConnectionStatus.TOKEN_EXPIRING,
        )
        if not connected:
            status = "disconnected"
        elif not times:
            status = "empty"
        elif times[-1] <= now + timedelta(days=LOW_CONTENT_DAYS):
            status = "low"
        else:
            status = "ok"

        accounts_by_workspace[account.workspace_id].append(
            {
                "account": account,
                "status": status,
                "total": len(times),
                "next_7_days": sum(1 for t in times if t <= week_limit),
                "next_label": _short_date(times[0]) if times else "",
                "last_label": _short_date(times[-1]) if times else "",
                "days_covered": max((timezone.localtime(times[-1]).date() - timezone.localdate()).days, 0)
                if times
                else 0,
            }
        )

    rows = []
    totals = {"empty": 0, "low": 0, "disconnected": 0, "ok": 0, "accounts": 0}
    for workspace in workspaces:
        items = accounts_by_workspace.get(workspace.id, [])
        counts = {key: sum(1 for i in items if i["status"] == key) for key in _STATUS_ORDER}
        for key in _STATUS_ORDER:
            totals[key] += counts[key]
        totals["accounts"] += len(items)
        worst = min((i["status"] for i in items), key=_STATUS_ORDER.get, default="ok")
        rows.append(
            {
                "workspace": workspace,
                "accounts": items,
                "counts": counts,
                "total_scheduled": sum(i["total"] for i in items),
                "worst": worst if items else "none",
            }
        )

    # Primero los clientes con problemas (sin contenido > desconectadas > poco), luego por nombre.
    rows.sort(key=lambda r: (_STATUS_ORDER.get(r["worst"], 4), r["workspace"].name.lower()))
    return {"rows": rows, "totals": totals, "low_days": LOW_CONTENT_DAYS}
