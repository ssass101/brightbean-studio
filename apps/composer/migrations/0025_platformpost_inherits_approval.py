"""Add ``PlatformPost.inherits_approval``.

Set by :func:`apps.composer.services.clone_post` when the source PlatformPost
had already cleared the approval gate (status in approved/scheduled/publishing/
published/failed). The gate in ``_require_approval_gate_passes`` lets a draft
whose children all carry the flag go straight to ``scheduled``, so republishing
an already-approved piece as Historia from the same account doesn't trigger a
new approval round.

``db_default=False`` closes the release-phase window the previous release's
code (which has no awareness of the column) would otherwise crash on when the
composer autosave INSERTs a PlatformPost without the field.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("composer", "0024_post_series"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformpost",
            name="inherits_approval",
            field=models.BooleanField(default=False, db_default=False),
        ),
    ]
