"""Diagnostica por qué un post enviado a aprobación no le llega al cliente.

Uso en Railway (Shell del servicio web):

    python manage.py diagnose_client_circuit --workspace "Brisas"

Revisa, para el workspace indicado:
  - modo de aprobación (debe ser 'required_internal_and_client'),
  - quiénes son los miembros CLIENT y su email,
  - los últimos posts y el estado de cada PlatformPost,
  - cuántos están en 'pending_client' (lo que el portal muestra).
"""

from django.core.management.base import BaseCommand

from apps.composer.models import Post
from apps.members.models import WorkspaceMembership
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Diagnostica el circuito de aprobación del cliente para un workspace."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True, help="Nombre (o parte) del workspace.")
        parser.add_argument("--limit", type=int, default=10, help="Cuántos posts recientes revisar.")

    def handle(self, *args, **opts):
        name = opts["workspace"]
        matches = list(Workspace.objects.filter(name__icontains=name))
        if not matches:
            self.stderr.write(f"No se encontró ningún workspace que contenga '{name}'.")
            return
        if len(matches) > 1:
            self.stdout.write("Varios workspaces coinciden:")
            for ws in matches:
                self.stdout.write(f"  - {ws.name} ({ws.id})")
            self.stdout.write("Afiná el nombre.")
            return

        ws = matches[0]
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== Workspace: {ws.name} ({ws.id}) ==="))

        # 1) Modo de aprobación
        mode = ws.approval_workflow_mode
        ok_mode = mode == "required_internal_and_client"
        marker = self.style.SUCCESS("OK") if ok_mode else self.style.ERROR("PROBLEMA")
        self.stdout.write(f"Modo de aprobación: {mode}  [{marker}]")
        if not ok_mode:
            self.stdout.write(
                self.style.WARNING(
                    "  → Para que el post llegue al cliente, el modo debe ser "
                    "'Requerida (Interno + Cliente)'. Cambialo en la configuración del workspace."
                )
            )

        # 2) Miembros CLIENT
        clients = list(
            WorkspaceMembership.objects.filter(
                workspace=ws, workspace_role=WorkspaceMembership.WorkspaceRole.CLIENT
            ).select_related("user")
        )
        if clients:
            self.stdout.write(f"\nClientes del workspace ({len(clients)}):")
            for m in clients:
                self.stdout.write(f"  - {m.user.email}")
        else:
            self.stdout.write(
                self.style.ERROR(
                    "\nNo hay ningún miembro con rol CLIENT en este workspace.  [PROBLEMA]\n"
                    "  → El cliente tiene que estar invitado a ESTE workspace con rol Cliente."
                )
            )

        # 3) Todos los miembros (para ver si el "cliente" quedó con otro rol)
        all_members = WorkspaceMembership.objects.filter(workspace=ws).select_related("user")
        self.stdout.write("\nTodos los miembros del workspace:")
        for m in all_members:
            self.stdout.write(f"  - {m.user.email}: rol={m.workspace_role}")

        # 4) Posts recientes y estado de sus PlatformPosts
        posts = Post.objects.filter(workspace=ws).order_by("-created_at")[: opts["limit"]]
        self.stdout.write(f"\nÚltimos {len(posts)} posts:")
        pending_client_total = 0
        for p in posts:
            rows = list(p.platform_posts.values_list("social_account__platform", "status"))
            n_pc = sum(1 for _, s in rows if s == "pending_client")
            pending_client_total += n_pc
            estados = ", ".join(f"{plat}:{st}" for plat, st in rows) or "(sin platform posts)"
            snippet = (p.caption or "")[:40]
            flag = " ← EN PORTAL" if n_pc else ""
            # Media adjunta al post (lo que el portal del cliente debería mostrar)
            media = list(p.media_attachments.select_related("media_asset").all())
            if media:
                media_desc = "; ".join(
                    f"{pm.media_asset.media_type}(file={'sí' if pm.media_asset.file else 'NO'},"
                    f"thumb={'sí' if pm.media_asset.thumbnail else 'no'})"
                    for pm in media
                )
            else:
                media_desc = "SIN MEDIA adjunta al Post"
            self.stdout.write(f'  - "{snippet}" → {estados}{flag}')
            self.stdout.write(f"      media: {media_desc}")

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\nResumen: {pending_client_total} publicación(es) en 'pending_client' "
                f"(eso es lo que el portal del cliente muestra)."
            )
        )
        if pending_client_total == 0:
            self.stdout.write(
                self.style.WARNING(
                    "  → Si esperabas ver algo en el portal y acá hay 0, el post no llegó a "
                    "'pending_client'. Revisá: (a) que usaste 'Enviar a aprobación' y no 'Programar', "
                    "(b) que el post de Instagram tenía imagen/video (sin media, el envío falla con 400), "
                    "(c) el modo del workspace de arriba."
                )
            )
