import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from models import Base

_TURSO_URL = os.getenv("TURSO_DATABASE_URL")
_TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

if _TURSO_URL and _TURSO_TOKEN:
    # Turso 雲端生產環境（Streamlit Cloud 使用）
    import turso_serverless

    class _TursoConn:
        """Wrap turso_serverless connection to stub out SQLite-only methods."""
        def __init__(self, conn):
            self._conn = conn

        def create_function(self, *args, **kwargs):
            pass  # turso_serverless 不支援，忽略即可

        def __getattr__(self, name):
            return getattr(self._conn, name)

    def _creator():
        return _TursoConn(turso_serverless.connect(_TURSO_URL, auth_token=_TURSO_TOKEN))

    engine = create_engine(
        "sqlite://",       # 用 SQLite 語法生成 SQL
        creator=_creator,  # 實際連線由 turso_serverless 提供
        poolclass=StaticPool,
    )
else:
    # 本地開發環境 - SQLite
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    engine = create_engine(
        f"sqlite:///{os.path.join(_BASE_DIR, 'ca_scheduler.db')}",
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
