from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Integer, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker, with_loader_criteria

from app.config import get_settings


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class SoftDeleteMixin:
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class Base(SoftDeleteMixin, DeclarativeBase):
    pass


@event.listens_for(Session, "do_orm_execute")
def _filter_soft_deleted_rows(execute_state) -> None:
    if not execute_state.is_select:
        return
    if execute_state.execution_options.get("include_deleted"):
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            SoftDeleteMixin,
            lambda cls: cls.is_deleted == 0,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _convert_deletes_to_soft_deletes(session, _flush_context, _instances) -> None:
    for instance in list(session.deleted):
        if isinstance(instance, SoftDeleteMixin):
            instance.is_deleted = 1
            session.add(instance)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
