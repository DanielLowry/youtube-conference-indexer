from pydantic import BaseModel
import datetime
from typing import List, Optional


class VideoStateBase(BaseModel):
    status: str = "queued"
    notes: Optional[str] = None
    score: Optional[int] = None


class VideoStateCreate(VideoStateBase):
    pass


class VideoState(VideoStateBase):
    id: int
    video_id: int

    class Config:
        from_attributes = True


class TagBase(BaseModel):
    name: str


class TagCreate(TagBase):
    pass


class Tag(TagBase):
    id: int

    class Config:
        from_attributes = True


class VideoBase(BaseModel):
    external_id: str
    title: str
    description: Optional[str] = None
    published_at: datetime.datetime
    duration_seconds: int
    channel_title: str


class VideoCreate(VideoBase):
    pass


class Video(VideoBase):
    id: int
    playlist_id: int
    tags: List[Tag] = []
    state: Optional[VideoState] = None

    class Config:
        from_attributes = True


class PlaylistBase(BaseModel):
    external_id: str
    title: str
    description: str | None = None
    pinned: bool = False


class PlaylistCreate(PlaylistBase):
    pass


class Playlist(PlaylistBase):
    id: int
    source_id: int
    last_synced_at: datetime.datetime | None = None
    videos: List[Video] = []

    class Config:
        from_attributes = True


class SourceBase(BaseModel):
    type: str
    external_id: str
    name: str


class SourceCreate(SourceBase):
    pass


class Source(SourceBase):
    id: int
    created_at: datetime.datetime
    playlists: list[Playlist] = []

    class Config:
        from_attributes = True
