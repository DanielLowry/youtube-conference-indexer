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
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

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
    playlist_id = Column(Integer, ForeignKey("playlists.id"))
    external_id = Column(String, unique=True, index=True)
    title = Column(String)
    description = Column(Text)
    published_at = Column(DateTime)
    duration_seconds = Column(Integer)
    channel_title = Column(String)

    playlist = relationship("Playlist", back_populates="videos")
    tags = relationship("Tag", secondary=video_tags, back_populates="videos")
    state = relationship("VideoState", back_populates="video", uselist=False, cascade="all, delete-orphan")


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
