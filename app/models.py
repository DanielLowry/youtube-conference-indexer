import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Table,
)
from sqlalchemy.orm import relationship

from .database import Base


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, index=True)  # "channel" or "playlist"
    external_id = Column(String, unique=True, index=True)
    name = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))

    playlists = relationship("Playlist", back_populates="source", cascade="all, delete-orphan")


video_tags = Table('video_tags', Base.metadata,
    Column('video_id', Integer, ForeignKey('videos.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)


class Playlist(Base):
    __tablename__ = "playlists"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"))
    external_id = Column(String, unique=True, index=True)
    title = Column(String)
    description = Column(Text)
    pinned = Column(Boolean, default=False, index=True)
    last_synced_at = Column(DateTime, nullable=True)

    source = relationship("Source", back_populates="playlists")
    videos = relationship("Video", back_populates="playlist", cascade="all, delete-orphan")


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, index=True)
    playlist_id = Column(Integer, ForeignKey("playlists.id"), nullable=True)
    external_id = Column(String, unique=True, index=True)
    title = Column(String)
    description = Column(Text)
    published_at = Column(DateTime)
    duration_seconds = Column(Integer)
    channel_id = Column(String, nullable=True)
    channel_title = Column(String)
    fetched_at = Column(DateTime, nullable=True)

    playlist = relationship("Playlist", back_populates="videos")
    tags = relationship("Tag", secondary=video_tags, back_populates="videos")
    state = relationship("VideoState", back_populates="video", uselist=False, cascade="all, delete-orphan")
    search_run_links = relationship("SearchRunVideo", back_populates="video")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

    videos = relationship("Video", secondary=video_tags, back_populates="tags")


class VideoState(Base):
    __tablename__ = "video_states"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"))
    status = Column(String, default="queued", index=True)  # queued, watching, done, skipped
    notes = Column(Text)
    score = Column(Integer) # e.g., 1-5 rating

    video = relationship("Video", back_populates="state")


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    query = Column(String, index=True, nullable=False)
    channel_id = Column(String, nullable=True)
    published_after = Column(DateTime, nullable=True)
    published_before = Column(DateTime, nullable=True)
    video_duration = Column(String, nullable=True)
    order_by = Column(String, default="relevance", nullable=False)
    region_code = Column(String, nullable=True)
    relevance_language = Column(String, nullable=True)
    safe_search = Column(String, nullable=True)
    max_pages = Column(Integer, default=10, nullable=False)
    stop_after_empty_pages = Column(Integer, default=2, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.UTC),
        onupdate=lambda: datetime.datetime.now(datetime.UTC),
    )

    runs = relationship("SearchRun", back_populates="saved_search", cascade="all, delete-orphan")


class SearchRun(Base):
    __tablename__ = "search_runs"

    id = Column(Integer, primary_key=True, index=True)
    saved_search_id = Column(Integer, ForeignKey("saved_searches.id"), index=True, nullable=False)
    status = Column(String, default="queued", index=True, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    pages_processed = Column(Integer, default=0, nullable=False)
    results_seen = Column(Integer, default=0, nullable=False)
    new_video_ids = Column(Integer, default=0, nullable=False)
    existing_video_ids = Column(Integer, default=0, nullable=False)
    videos_fetched = Column(Integer, default=0, nullable=False)
    next_page_token = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    quota_estimate = Column(Integer, nullable=True)

    saved_search = relationship("SavedSearch", back_populates="runs")
    videos = relationship("SearchRunVideo", back_populates="search_run", cascade="all, delete-orphan")


class SearchRunVideo(Base):
    __tablename__ = "search_run_videos"

    search_run_id = Column(Integer, ForeignKey("search_runs.id"), primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), primary_key=True, index=True)
    rank_in_search = Column(Integer, nullable=True)
    page_number = Column(Integer, nullable=True)
    added_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))

    search_run = relationship("SearchRun", back_populates="videos")
    video = relationship("Video", back_populates="search_run_links")
