"""Regresión: un post NUEVO con imagen enviado a aprobación debe conservar la media.

El composer guarda la media recién subida en la sesión (pending_media_<ws>)
hasta que el post tiene PK. El camino submit_for_approval retornaba antes de
adjuntarla, así que el post llegaba al cliente sin imagen.
"""

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.composer.models import Post
from apps.media_library.models import MediaAsset
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace

User = get_user_model()

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class SubmitForApprovalKeepsMediaTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(
            organization=self.org,
            name="Brisas",
            approval_workflow_mode="required_internal_and_client",
        )
        self.sa = SocialAccount.objects.create(
            workspace=self.ws,
            platform="facebook",
            account_platform_id="fb-1",
            account_name="brisas",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        self.owner = User.objects.create_user(
            email="owner@x.com", password="x", tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.create(user=self.owner, organization=self.org, org_role=OrgMembership.OrgRole.OWNER)
        WorkspaceMembership.objects.create(
            user=self.owner, workspace=self.ws, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER
        )
        # A client so the two-stage flow has someone to notify.
        client_user = User.objects.create_user(email="client@x.com", password="x")
        OrgMembership.objects.create(user=client_user, organization=self.org, org_role=OrgMembership.OrgRole.MEMBER)
        WorkspaceMembership.objects.create(
            user=client_user, workspace=self.ws, workspace_role=WorkspaceMembership.WorkspaceRole.CLIENT
        )
        # An uploaded image, held in the session as pending media (new post).
        self.asset = MediaAsset.objects.create(
            organization=self.org,
            workspace=self.ws,
            uploaded_by=self.owner,
            filename="foto.png",
            media_type=MediaAsset.MediaType.IMAGE,
            file_size=len(PNG),
        )
        self.asset.file.save("foto.png", ContentFile(PNG), save=True)

    def test_new_post_submit_for_approval_keeps_media(self):
        http = Client()
        http.force_login(self.owner)
        # Put the asset in the session exactly as the composer upload does.
        session = http.session
        session[f"pending_media_{self.ws.id}"] = [str(self.asset.id)]
        session.save()

        from unittest.mock import patch

        with patch("apps.client_portal.services.send_review_request"):
            resp = http.post(
                reverse("composer:save_post", kwargs={"workspace_id": self.ws.id}),
                data={
                    "action": "submit_for_approval",
                    "title": "t",
                    "caption": "",  # sin texto, solo imagen (el caso de Sergio)
                    "tags": "",
                    "selected_accounts": str(self.sa.id),
                },
            )

        self.assertIn(resp.status_code, (200, 204, 302), f"status {resp.status_code}: {resp.content[:300]}")
        post = Post.objects.filter(workspace=self.ws).order_by("-created_at").first()
        self.assertIsNotNone(post)
        # La media debe haber quedado adjunta al Post (lo que el portal muestra).
        self.assertEqual(post.media_attachments.count(), 1, "El post quedó SIN MEDIA tras enviar a aprobación")
        # Y debe estar en pending_client.
        statuses = set(post.platform_posts.values_list("status", flat=True))
        self.assertIn("pending_client", statuses)
