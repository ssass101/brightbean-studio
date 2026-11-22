"""Context processor for onboarding checklist popup."""

from apps.onboarding.checklist import get_checklist_items
from apps.onboarding.models import OnboardingChecklist


def onboarding_checklist(request):
    """Inject onboarding checklist data into every template context."""
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return {}

    workspace = getattr(request, "workspace", None)
    if not workspace:
        return {}

    # El checklist se muestra UNA vez por usuario, no una por workspace. En una
    # agencia con 20 workspaces, cerrarlo una vez y que reapareciera en los otros
    # 19 era puro ruido — el usuario ya sabe cómo funciona la herramienta.
    # Si lo cerró alguna vez en algún workspace, queda cerrado para siempre.
    checklist_dismissed = OnboardingChecklist.objects.filter(
        user=request.user, is_dismissed=True
    ).exists()

    if checklist_dismissed:
        return {"checklist_dismissed": True, "checklist_items": []}

    checklist_items = get_checklist_items(workspace)
    completed_count = sum(1 for item in checklist_items if item["completed"])
    total_count = len(checklist_items)

    # Don't show if all items are complete
    if completed_count == total_count:
        return {"checklist_dismissed": True, "checklist_items": []}

    return {
        "checklist_items": checklist_items,
        "checklist_dismissed": False,
        "checklist_completed_count": completed_count,
        "checklist_total_count": total_count,
    }
