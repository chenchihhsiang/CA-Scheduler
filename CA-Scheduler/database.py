import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from models import Base

# 支持 Turso（生產）和本地 SQLite（開發）
_DATABASE_URL = os.getenv("DATABASE_URL")

if _DATABASE_URL:
    # Turso 生產環境
    if _DATABASE_URL.startswith("libsql://"):
        # Turso 遠程資料庫
        engine = create_engine(_DATABASE_URL, echo=False)
    else:
        # 其他 SQL 方言
        engine = create_engine(_DATABASE_URL, echo=False)
else:
    # 本地開發環境 - SQLite
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    _LOCAL_DB = f"sqlite:///{os.path.join(_BASE_DIR, 'ca_scheduler.db')}"
    engine = create_engine(
        _LOCAL_DB,
        connect_args={"check_same_thread": False},
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables if they do not exist yet, then apply migrations."""
    Base.metadata.create_all(bind=engine)
    _migrate()


def _migrate() -> None:
    """Incremental schema migrations for existing databases."""
    insp = inspect(engine)
    if "employees" in insp.get_table_names():
        existing_cols = {c["name"] for c in insp.get_columns("employees")}
        with engine.begin() as conn:
            if "availability" not in existing_cols:
                conn.execute(
                    text("ALTER TABLE employees ADD COLUMN availability TEXT DEFAULT '{}'")
                )
            if "target_hours" not in existing_cols:
                conn.execute(
                    text("ALTER TABLE employees ADD COLUMN target_hours REAL DEFAULT 40.0")
                )


def get_db():
    """Return a new database session. Caller is responsible for closing it."""
    return SessionLocal()
