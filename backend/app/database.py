"""Database connection (SQLAlchemy)."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """Gives each API request its own database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(bind=None):
    """Creates tables if they don't exist yet, and adds columns that newer versions need."""
    from . import models  # noqa: F401  (registers the tables)

    bind = bind or engine
    Base.metadata.create_all(bind=bind)
    add_missing_columns(bind)


def add_missing_columns(bind):
    """create_all() never changes an existing table. When a new version adds a column
    (e.g. reply_rating), add it here so an existing database keeps its data and still works.
    Only nullable columns are added, so old rows simply get NULL."""
    inspector = inspect(bind)
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                col_type = column.type.compile(dialect=bind.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {col_type}'))
                for index in table.indexes:
                    if [c.name for c in index.columns] == [column.name]:
                        index.create(conn)
