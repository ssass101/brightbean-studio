"""Tests de la página de inicio (resumen de publicaciones programadas por cuenta)."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.overview import build_overview
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class OverviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com", password="testpass123", tos_accepted_at=timezone.now()
        )
        self.org = Organization.objects.create(name="Org")
        OrgMembership.objects.create(user=self.user, organization=self.org, org_role=OrgMembership.OrgRole.OWNER)
        self.ws = Workspace.objects.create(organization=self.org, name="Hestia")
        WorkspaceMembership.objects.create(
            user=self.user, workspace=self.ws, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER
        )
        self.client.force_login(self.user)

    def _account(self, name, platform="instagram", status=SocialAccount.ConnectionStatus.CONNECTED):
        return SocialAccount.objects.create(
            workspace=self.ws,
            platform=platform,
            account_platform_id=name,
            account_name=name,
            connection_status=status,
        )

    def _schedule(self, account, days, status=PlatformPost.Status.SCHEDULED, on_platform_post=True):
        when = timezone.now() + timedelta(days=days)
        post = Post.objects.create(workspace=self.ws, author=self.user, caption="x", scheduled_at=None if on_platform_post else when)
        return PlatformPost.objects.create(
            post=post, social_account=account, status=status, scheduled_at=when if on_platform_post else None
        )

    def test_status_per_account(self):
        empty = self._account("vacia")
        low = self._account("poca")
        ok = self._account("bien")
        off = self._account("caida", status=SocialAccount.ConnectionStatus.DISCONNECTED)
        self._schedule(low, 1)
        self._schedule(ok, 2)
        self._schedule(ok, 10)
        # Un borrador y una publicación pasada no cuentan.
        self._schedule(empty, 5, status=PlatformPost.Status.DRAFT)
        self._schedule(empty, -2)

        data = build_overview(self.user)
        items = {i["account"].account_name: i for i in data["rows"][0]["accounts"]}
        self.assertEqual(items["vacia"]["status"], "empty")
        self.assertEqual(items["vacia"]["total"], 0)
        self.assertEqual(items["poca"]["status"], "low")
        self.assertEqual(items["bien"]["status"], "ok")
        self.assertEqual(items["bien"]["total"], 2)
        self.assertEqual(items["bien"]["next_7_days"], 1)
        self.assertEqual(items["caida"]["status"], "disconnected")
        self.assertEqual(data["totals"]["empty"], 1)
        self.assertEqual(data["totals"]["low"], 1)
        self.assertEqual(data["totals"]["disconnected"], 1)
        self.assertEqual(data["totals"]["ok"], 1)
        _ = (empty, off)

    def test_falls_back_to_post_scheduled_at(self):
        acc = self._account("fallback")
        self._schedule(acc, 8, on_platform_post=False)
        data = build_overview(self.user)
        self.assertEqual(data["rows"][0]["accounts"][0]["total"], 1)
        self.assertEqual(data["rows"][0]["accounts"][0]["status"], "ok")

    def test_workspaces_with_problems_come_first(self):
        other = Workspace.objects.create(organization=self.org, name="Aaa cliente al dia")
        WorkspaceMembership.objects.create(
            user=self.user, workspace=other, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER
        )
        good = SocialAccount.objects.create(
            workspace=other, platform="instagram", account_platform_id="g", account_name="g"
        )
        post = Post.objects.create(workspace=other, author=self.user, caption="x")
        PlatformPost.objects.create(
            post=post,
            social_account=good,
            status=PlatformPost.Status.SCHEDULED,
            scheduled_at=timezone.now() + timedelta(days=20),
        )
        self._account("sin contenido")
        names = [r["workspace"].name for r in build_overview(self.user)["rows"]]
        self.assertEqual(names[:2], ["Hestia", "Aaa cliente al dia"])

    def test_home_renders_overview(self):
        self._account("vacia")
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "accounts/overview.html")
        self.assertContains(resp, "Resumen de cuentas")
        self.assertContains(resp, "Sin contenido")
        self.assertContains(resp, "Hestia")

    def test_home_without_workspaces_shows_create_screen(self):
        WorkspaceMembership.objects.all().delete()
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "accounts/dashboard.html")
