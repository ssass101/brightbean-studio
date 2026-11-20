"""Repeating a publication on chosen weekdays (a "series").

The user picks weekdays and a duration next to the date and time. The first
publication is the post itself; every other date becomes a copy of it, scheduled
directly. Copies do not go through approval again: the client approves the
original once, and that approval covers the whole series, for any format (post,
carousel, reel or story).

The configuration lives on ``Post.series_config`` until the post is actually
scheduled; ``materialize_series`` then creates the copies and stamps every post
of the series with the same ``series_id``.
"""

import copy
import logging
import uuid
import zoneinfo
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone

from apps.composer.models import PlatformPost, Post, PostMedia
from apps.composer.services import post_media_types, publish_blocker, sync_post_scheduled_at

logger = logging.getLogger(__name__)

MAX_COPIES = 100
UNITS = ("weeks", "months")
# Statuses of a source child that mean "this is going out", so its copies do too.
_COMMITTED = frozenset({"scheduled", "publishing", "published"})


def parse_series_config(data):
    """Read the composer's repeat fields (a QueryDict-like) into a config dict.

    Returns ``None`` when repetition is off or the fields are unusable.
    """
    if not data.get("repeat_enabled"):
        return None
    getlist = data.getlist if hasattr(data, "getlist") else lambda k: data.get(k, [])
    weekdays = sorted({int(d) for d in getlist("repeat_weekdays") if str(d).isdigit() and 0 <= int(d) <= 6})
    try:
        count = int(data.get("repeat_count", "") or 0)
    except (TypeError, ValueError):
        count = 0
    unit = data.get("repeat_unit", "weeks")
    if not weekdays or count < 1 or unit not in UNITS:
        return None
    return {"weekdays": weekdays, "count": min(count, 52), "unit": unit}


def series_dates(first_dt, config, tz):
    """Datetimes of the copies (the first publication, ``first_dt``, is not included).

    Days run from ``first_dt``'s date for ``count`` weeks or months, at the same
    local wall-clock time as ``first_dt``.
    """
    local_first = first_dt.astimezone(tz)
    start = local_first.date()
    if config["unit"] == "months":
        end = start + relativedelta(months=config["count"])
    else:
        end = start + timedelta(weeks=config["count"])
    out = []
    day = start + timedelta(days=1)
    while day < end and len(out) < MAX_COPIES:
        if day.weekday() in config["weekdays"]:
            out.append(datetime.combine(day, local_first.time()).replace(tzinfo=tz))
        day += timedelta(days=1)
    return out


def _tz(post):
    return zoneinfo.ZoneInfo(post.workspace.effective_timezone or "UTC")


def is_scheduled(post):
    return post.scheduled_at is not None and post.platform_posts.filter(status="scheduled").exists()


@transaction.atomic
def materialize_series(post):
    """Create the scheduled copies for ``post``'s series. Returns how many were made.

    Does nothing unless the post has a repeat config, is already scheduled in the
    future, and has not generated its series yet, so calling it more than once
    (save, approval, manual schedule) is safe.
    """
    post = Post.objects.select_for_update().get(pk=post.pk)
    config = post.series_config
    if not config or post.series_id or not is_scheduled(post):
        return 0
    if post.scheduled_at <= timezone.now():
        return 0

    tz = _tz(post)
    dates = [d for d in series_dates(post.scheduled_at, config, tz) if d > timezone.now()]
    series_id = uuid.uuid4()
    post.series_id = series_id
    post.save(update_fields=["series_id", "updated_at"])
    if not dates:
        return 0

    source_pps = list(post.platform_posts.select_related("social_account"))
    source_media = list(post.media_attachments.all())
    media_types = post_media_types(post)
    made = 0
    for when in dates:
        new_post = Post.objects.create(
            workspace=post.workspace,
            author=post.author,
            title=post.title,
            caption=post.caption,
            first_comment=post.first_comment,
            internal_notes=post.internal_notes,
            tags=post.tags,
            category=post.category,
            scheduled_at=when,
            series_id=series_id,
            series_config=config,
        )
        new_pps = []
        for pp in source_pps:
            blocked = publish_blocker(pp.social_account, media_types=media_types, platform_extra=pp.platform_extra)
            if blocked:
                logger.warning("Series copy of post %s on %s left as a draft: %s", post.id, when, blocked)
            pp_when = when
            if pp.scheduled_at and post.scheduled_at:
                pp_when = when + (pp.scheduled_at - post.scheduled_at)
            new_pps.append(
                PlatformPost(
                    post=new_post,
                    social_account=pp.social_account,
                    platform_specific_caption=pp.platform_specific_caption,
                    platform_specific_first_comment=pp.platform_specific_first_comment,
                    platform_specific_media=pp.platform_specific_media,
                    platform_extra=copy.deepcopy(pp.platform_extra) if pp.platform_extra else {},
                    scheduled_at=pp_when,
                    status="scheduled" if pp.status in _COMMITTED and not blocked else "draft",
                )
            )
        PlatformPost.objects.bulk_create(new_pps)
        sync_post_scheduled_at(new_post)
        if source_media:
            PostMedia.objects.bulk_create(
                [
                    PostMedia(
                        post=new_post,
                        media_asset=pm.media_asset,
                        position=pm.position,
                        alt_text=pm.alt_text,
                        platform_overrides=pm.platform_overrides,
                    )
                    for pm in source_media
                ]
            )
        made += 1
    return made


def future_copies(post):
    """Queryset of the not-yet-published copies in ``post``'s series (excluding ``post``)."""
    if not post.series_id:
        return Post.objects.none()
    return (
        Post.objects.filter(workspace=post.workspace, series_id=post.series_id, scheduled_at__gt=timezone.now())
        .exclude(pk=post.pk)
        .exclude(platform_posts__status__in=[PlatformPost.Status.PUBLISHING, PlatformPost.Status.PUBLISHED])
        .distinct()
    )


def cancel_series(post):
    """Delete the future copies of ``post``'s series. Returns how many were removed."""
    ids = list(future_copies(post).values_list("pk", flat=True))
    deleted, _ = Post.objects.filter(pk__in=ids).delete()
    return len(ids) if deleted else 0
