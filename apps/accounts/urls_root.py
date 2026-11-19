from django.urls import path
from django.views.generic import TemplateView

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # Public legal pages (required by TikTok / Meta / LinkedIn app review).
    path("privacy/", TemplateView.as_view(template_name="legal/privacy.html"), name="legal_privacy"),
    path("terms/", TemplateView.as_view(template_name="legal/terms.html"), name="legal_terms"),
]
