"""ORM mappings for the existing snapshot and request ledger schema."""

from sqlalchemy import Float, ForeignKey, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class GameSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)


class Request(Base):
    __tablename__ = "requests"

    session_id: Mapped[str] = mapped_column(Text, ForeignKey("sessions.id"), primary_key=True)
    request_id: Mapped[str] = mapped_column(Text, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created: Mapped[float] = mapped_column(Float, nullable=False)
    result: Mapped[str | None] = mapped_column(Text)
    trace: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int] = mapped_column(Integer, nullable=False, server_default="200")
