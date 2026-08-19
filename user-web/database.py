"""SQLite database setup and migrations for the health diet app."""

import os
import secrets
import sqlite3
import string
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = APP_ROOT.parents[1]
DEFAULT_DATA_DIR = WORKSPACE_ROOT / ".workspace" / "data" / "user-web"
DB_PATH = os.environ.get(
    "HEALTH_DB_PATH",
    str(DEFAULT_DATA_DIR / "health.db"),
)


def get_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_missing_columns(conn, table, columns):
    existing = _columns(conn, table)
    for name, definition in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _new_bind_code(conn, column):
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        if column == "share_code":
            exists = conn.execute(
                "SELECT 1 FROM users WHERE share_code=? OR supervisor_code=? OR supervisee_code=?",
                (code, code, code),
            ).fetchone()
        else:
            exists = conn.execute(f"SELECT 1 FROM users WHERE {column}=?", (code,)).fetchone()
        if exists is None:
            return code


def _migrate_legacy_schema(conn):
    """Bring databases created by earlier prototypes up to the current schema."""
    _add_missing_columns(conn, "users", [
        ("email", "TEXT"),
        ("avatar_url", "TEXT DEFAULT ''"),
        ("height", "REAL"),
        ("weight", "REAL"),
        ("age", "INTEGER"),
        ("gender", "TEXT"),
        ("health_goal", "TEXT DEFAULT 'weight_management'"),
        ("supervisor_code", "TEXT"),
        ("supervisee_code", "TEXT"),
        ("share_code", "TEXT"),
        ("bound_to", "INTEGER REFERENCES users(id)"),
        # SQLite cannot add CURRENT_TIMESTAMP as a default to a populated table.
        ("created_at", "TIMESTAMP"),
        ("active", "INTEGER NOT NULL DEFAULT 1"),
        ("last_active_at", "TIMESTAMP"),
        ("medical_history", "TEXT NOT NULL DEFAULT ''"),
        ("allergies", "TEXT NOT NULL DEFAULT ''"),
        ("diet_preferences", "TEXT NOT NULL DEFAULT ''"),
        ("dietary_restrictions", "TEXT NOT NULL DEFAULT ''"),
        ("chronic_conditions", "TEXT NOT NULL DEFAULT ''"),
        ("risk_level", "TEXT NOT NULL DEFAULT 'low'"),
        ("health_notes", "TEXT NOT NULL DEFAULT ''"),
        ("daily_calorie_target", "REAL"),
    ])
    _add_missing_columns(conn, "verify_codes", [("email", "TEXT")])
    _add_missing_columns(conn, "food_library", [
        ("sodium_mg", "REAL DEFAULT 0"),
        ("potassium_mg", "REAL DEFAULT 0"),
        ("calcium_mg", "REAL DEFAULT 0"),
        ("magnesium_mg", "REAL DEFAULT 0"),
        ("iron_mg", "REAL DEFAULT 0"),
        ("unit", "TEXT NOT NULL DEFAULT 'g'"),
        ("protein_g", "REAL NOT NULL DEFAULT 0"),
        ("fat_g", "REAL NOT NULL DEFAULT 0"),
        ("carbs_g", "REAL NOT NULL DEFAULT 0"),
        ("fiber_g", "REAL NOT NULL DEFAULT 0"),
        ("substitutes", "TEXT NOT NULL DEFAULT ''"),
        ("active", "INTEGER NOT NULL DEFAULT 1"),
    ])
    _add_missing_columns(conn, "diet_records", [
        ("image_url", "TEXT DEFAULT ''"),
        ("source_type", "TEXT DEFAULT 'manual'"),
        ("recognition_suggestions", "TEXT DEFAULT ''"),
        ("original_food_name", "TEXT"),
        ("original_weight_grams", "REAL"),
        ("corrected_at", "TIMESTAMP"),
        ("protein_g", "REAL NOT NULL DEFAULT 0"),
        ("fat_g", "REAL NOT NULL DEFAULT 0"),
        ("carbs_g", "REAL NOT NULL DEFAULT 0"),
        ("fiber_g", "REAL NOT NULL DEFAULT 0"),
        ("meal_type", "TEXT NOT NULL DEFAULT ''"),
        ("description", "TEXT NOT NULL DEFAULT ''"),
    ])

    user_columns = _columns(conn, "users")
    if "bind_code" in user_columns:
        conn.execute(
            "UPDATE users SET supervisor_code=bind_code "
            "WHERE supervisor_code IS NULL AND bind_code IS NOT NULL"
        )

    rows = conn.execute(
        "SELECT id, supervisor_code, supervisee_code, share_code FROM users"
    ).fetchall()
    for row in rows:
        supervisor_code = row["supervisor_code"] or _new_bind_code(conn, "supervisor_code")
        supervisee_code = row["supervisee_code"] or _new_bind_code(conn, "supervisee_code")
        share_code = row["share_code"] or _new_bind_code(conn, "share_code")
        conn.execute(
            "UPDATE users SET supervisor_code=?, supervisee_code=?, share_code=?, "
            "health_goal=COALESCE(health_goal, 'weight_management'), "
            "created_at=COALESCE(created_at, CURRENT_TIMESTAMP) WHERE id=?",
            (supervisor_code, supervisee_code, share_code, row["id"]),
        )

    # Preserve old one-way relationships as active two-way sharing links.
    legacy_links = conn.execute(
        "SELECT id, bound_to FROM users WHERE bound_to IS NOT NULL"
    ).fetchall()
    for row in legacy_links:
        user_a_id, user_b_id = sorted((row["id"], row["bound_to"]))
        conn.execute(
            "INSERT OR IGNORE INTO user_connections "
            "(user_a_id,user_b_id,requested_by,status,a_share_diet,b_share_diet,"
            "a_share_goal,b_share_goal,a_share_profile,b_share_profile,accepted_at) "
            "VALUES (?,?,?,'active',1,1,1,1,1,1,CURRENT_TIMESTAMP)",
            (user_a_id, user_b_id, row["bound_to"]),
        )


def init_db():
    conn = get_db()
    try:
        # Tables are created first. Migrations then add columns missing from old
        # databases before indexes reference those columns.
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('supervisor', 'supervisee')),
                nickname TEXT NOT NULL,
                avatar_url TEXT DEFAULT '',
                height REAL,
                weight REAL,
                age INTEGER,
                gender TEXT CHECK(gender IN ('male', 'female')),
                health_goal TEXT DEFAULT 'weight_management'
                    CHECK(health_goal IN ('weight_management', 'blood_sugar', 'blood_pressure')),
                supervisor_code TEXT UNIQUE NOT NULL,
                supervisee_code TEXT UNIQUE NOT NULL,
                share_code TEXT UNIQUE,
                bound_to INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS verify_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT,
                email TEXT,
                code TEXT NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS food_library (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                calories_per_100g REAL NOT NULL,
                category TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS diet_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                food_name TEXT NOT NULL,
                weight_grams REAL NOT NULL CHECK(weight_grams > 0 AND weight_grams <= 5000),
                calories REAL NOT NULL CHECK(calories >= 0),
                intake_time TIMESTAMP NOT NULL,
                image_url TEXT DEFAULT '',
                source_type TEXT DEFAULT 'manual',
                recognition_suggestions TEXT DEFAULT '',
                original_food_name TEXT,
                original_weight_grams REAL,
                corrected_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_a_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                user_b_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                requested_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'active')),
                a_remark_for_b TEXT NOT NULL DEFAULT '',
                b_remark_for_a TEXT NOT NULL DEFAULT '',
                a_share_diet INTEGER NOT NULL DEFAULT 1 CHECK(a_share_diet IN (0,1)),
                b_share_diet INTEGER NOT NULL DEFAULT 1 CHECK(b_share_diet IN (0,1)),
                a_share_goal INTEGER NOT NULL DEFAULT 0 CHECK(a_share_goal IN (0,1)),
                b_share_goal INTEGER NOT NULL DEFAULT 0 CHECK(b_share_goal IN (0,1)),
                a_share_profile INTEGER NOT NULL DEFAULT 0 CHECK(a_share_profile IN (0,1)),
                b_share_profile INTEGER NOT NULL DEFAULT 0 CHECK(b_share_profile IN (0,1)),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                accepted_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CHECK(user_a_id < user_b_id),
                UNIQUE(user_a_id, user_b_id)
            );
        """)

        _migrate_legacy_schema(conn)
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_diet_user ON diet_records(user_id);
            CREATE INDEX IF NOT EXISTS idx_diet_time ON diet_records(intake_time);
            CREATE INDEX IF NOT EXISTS idx_verify_phone ON verify_codes(phone);
            CREATE INDEX IF NOT EXISTS idx_verify_email ON verify_codes(email);
            CREATE INDEX IF NOT EXISTS idx_verify_created ON verify_codes(created_at);
            CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);
            CREATE INDEX IF NOT EXISTS idx_users_bound ON users(bound_to);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_supervisor_code ON users(supervisor_code);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_supervisee_code ON users(supervisee_code);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_share_code ON users(share_code);
            CREATE INDEX IF NOT EXISTS idx_connections_a ON user_connections(user_a_id, status);
            CREATE INDEX IF NOT EXISTS idx_connections_b ON user_connections(user_b_id, status);
            CREATE INDEX IF NOT EXISTS idx_connections_requested ON user_connections(requested_by, status);
        """)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
