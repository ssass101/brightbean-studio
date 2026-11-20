from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("composer", "0023_platformpost_youtube_video_checked_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="series_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="post",
            name="series_config",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
