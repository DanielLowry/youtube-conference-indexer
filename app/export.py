from io import StringIO
import csv
from typing import Iterable


def generate_markdown_export(videos: Iterable) -> str:
    """Produce a simple Markdown list of videos with metadata."""
    lines = ["# Video Export", ""]
    for v in videos:
        tags = ", ".join(t.name for t in v.tags) if v.tags else ""
        status = v.state.status if v.state else ""
        lines.append(f"- **{v.title}** ({v.channel_title}, {v.published_at.date()})")
        lines.append(f"  - Duration: {v.duration_seconds // 60} min")
        lines.append(f"  - Status: {status}")
        if tags:
            lines.append(f"  - Tags: {tags}")
        lines.append(f"  - Link: https://www.youtube.com/watch?v={v.external_id}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def generate_csv_export(videos: Iterable) -> str:
    """Generate CSV content for videos."""
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["title", "channel", "published_at", "duration_seconds", "status", "tags", "video_id"]
    )
    for v in videos:
        tags = ", ".join(t.name for t in v.tags) if v.tags else ""
        status = v.state.status if v.state else ""
        writer.writerow(
            [
                v.title,
                v.channel_title,
                v.published_at.isoformat(),
                v.duration_seconds,
                status,
                tags,
                v.external_id,
            ]
        )
    return buffer.getvalue()
