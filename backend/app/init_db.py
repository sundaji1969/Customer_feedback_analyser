"""Run once to create the database tables:  python -m app.init_db  (from the backend folder)."""
from sqlalchemy import inspect

from .database import engine, init_db

if __name__ == "__main__":
    init_db()
    print("Tables in database:", inspect(engine).get_table_names())
