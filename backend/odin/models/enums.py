"""Enum types shared by the ORM models."""

import enum


class DocType(enum.Enum):
    source = "source"
    derived = "derived"


class DocState(enum.Enum):
    pending = "pending"
    indexed = "indexed"
    failed = "failed"
    soft_deleted = "soft_deleted"


class JobState(enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
