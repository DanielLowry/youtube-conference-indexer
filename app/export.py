from io import StringIO
import csv
from typing import Iterable


def generate_markdown_export(videos: Iterable) -> str:
    """Produce a simple Markdown list of videos with metadata."""
    lines = ["# Video Export", ""]
    for v in videos:
        tags = ", ".join(t.name for t in v.tags) if v.tags else ""
        status = v.state.status if v.state else ""
        playlist_title = v.playlist.title if v.playlist else ""
        lines.append(f"- **{v.title}** ({v.channel_title}, {v.published_at.date()})")
        lines.append(f"  - Duration: {v.duration_seconds // 60} min")
        lines.append(f"  - Status: {status}")
        if playlist_title:
            lines.append(f"  - Playlist: {playlist_title}")
        if tags:
            lines.append(f"  - Tags: {tags}")
        lines.append(f"  - Link: https://www.youtube.com/watch?v={v.external_id}")
        if v.description:
            lines.append(f"  - Description: {v.description}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def generate_csv_export(videos: Iterable) -> str:
    """Generate CSV content for videos."""
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "title",
            "channel",
            "published_at",
            "duration_seconds",
            "status",
            "tags",
            "video_id",
            "playlist",
            "playlist_id",
            "description",
        ]
    )
    for v in videos:
        tags = ", ".join(t.name for t in v.tags) if v.tags else ""
        status = v.state.status if v.state else ""
        playlist_title = v.playlist.title if v.playlist else ""
        playlist_external = v.playlist.external_id if v.playlist else ""
        writer.writerow(
            [
                v.title,
                v.channel_title,
                v.published_at.isoformat(),
                v.duration_seconds,
                status,
                tags,
                v.external_id,
                playlist_title,
                playlist_external,
                (v.description or "").replace("\n", " ").strip(),
            ]
        )
    return buffer.getvalue()
