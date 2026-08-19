import os
import sqlite3


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))
DEFAULT_DATA_ROOT = os.path.join(WORKSPACE_ROOT, ".workspace", "data")
ADMIN_DB_PATH = os.environ.get(
    "ADMIN_DB_PATH",
    os.path.join(DEFAULT_DATA_ROOT, "supervisor-web", "admin.db"),
)
USER_DB_PATH = os.environ.get(
    "USER_APP_DB_PATH",
    os.path.join(DEFAULT_DATA_ROOT, "user-web", "health.db"),
)


def connect(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def admin_db():
    return connect(ADMIN_DB_PATH)


def user_db():
    if not os.path.isfile(USER_DB_PATH):
        raise FileNotFoundError(f"找不到用户端数据库：{USER_DB_PATH}")
    return connect(USER_DB_PATH)


def _columns(connection, table):
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def _add_missing_columns(connection, table, columns):
    existing = _columns(connection, table)
    for name, definition in columns:
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_user_db():
    """Add management features without removing or rewriting existing data."""
    connection = user_db()
    try:
        _add_missing_columns(connection, "users", [
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
        _add_missing_columns(connection, "food_library", [
            ("unit", "TEXT NOT NULL DEFAULT 'g'"),
            ("protein_g", "REAL NOT NULL DEFAULT 0"),
            ("fat_g", "REAL NOT NULL DEFAULT 0"),
            ("carbs_g", "REAL NOT NULL DEFAULT 0"),
            ("fiber_g", "REAL NOT NULL DEFAULT 0"),
            ("substitutes", "TEXT NOT NULL DEFAULT ''"),
            ("active", "INTEGER NOT NULL DEFAULT 1"),
            ("sodium_mg", "REAL NOT NULL DEFAULT 0"),
            ("potassium_mg", "REAL NOT NULL DEFAULT 0"),
            ("calcium_mg", "REAL NOT NULL DEFAULT 0"),
            ("magnesium_mg", "REAL NOT NULL DEFAULT 0"),
            ("iron_mg", "REAL NOT NULL DEFAULT 0"),
        ])
        _add_missing_columns(connection, "diet_records", [
            ("protein_g", "REAL NOT NULL DEFAULT 0"),
            ("fat_g", "REAL NOT NULL DEFAULT 0"),
            ("carbs_g", "REAL NOT NULL DEFAULT 0"),
            ("fiber_g", "REAL NOT NULL DEFAULT 0"),
            ("meal_type", "TEXT NOT NULL DEFAULT ''"),
            ("description", "TEXT NOT NULL DEFAULT ''"),
            ("image_url", "TEXT NOT NULL DEFAULT ''"),
            ("source_type", "TEXT NOT NULL DEFAULT 'manual'"),
            ("recognition_suggestions", "TEXT NOT NULL DEFAULT ''"),
            ("original_food_name", "TEXT"),
            ("original_weight_grams", "REAL"),
            ("corrected_at", "TIMESTAMP"),
        ])
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                instructions TEXT NOT NULL DEFAULT '',
                servings INTEGER NOT NULL DEFAULT 1,
                calories_per_serving REAL NOT NULL DEFAULT 0,
                protein_g REAL NOT NULL DEFAULT 0,
                fat_g REAL NOT NULL DEFAULT 0,
                carbs_g REAL NOT NULL DEFAULT 0,
                fiber_g REAL NOT NULL DEFAULT 0,
                suitable_for TEXT NOT NULL DEFAULT '',
                avoid_for TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS recipe_ingredients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                food_id INTEGER REFERENCES food_library(id) ON DELETE SET NULL,
                ingredient_name TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL DEFAULT 'g',
                notes TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS feedback_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                category TEXT NOT NULL DEFAULT 'feedback',
                subject TEXT NOT NULL,
                content TEXT NOT NULL,
                contact TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                priority TEXT NOT NULL DEFAULT 'normal',
                admin_reply TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_users_active ON users(active, last_active_at);
            CREATE INDEX IF NOT EXISTS idx_diet_intake ON diet_records(intake_time, user_id);
            CREATE INDEX IF NOT EXISTS idx_recipes_active ON recipes(active, category);
            CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_recipe ON recipe_ingredients(recipe_id);
            CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback_tickets(status, created_at);
        """)
        connection.execute("UPDATE users SET active=1 WHERE active IS NULL")
        connection.execute("""
            UPDATE diet_records
            SET protein_g=COALESCE((SELECT protein_g * diet_records.weight_grams / 100.0 FROM food_library WHERE name=diet_records.food_name),0),
                fat_g=COALESCE((SELECT fat_g * diet_records.weight_grams / 100.0 FROM food_library WHERE name=diet_records.food_name),0),
                carbs_g=COALESCE((SELECT carbs_g * diet_records.weight_grams / 100.0 FROM food_library WHERE name=diet_records.food_name),0),
                fiber_g=COALESCE((SELECT fiber_g * diet_records.weight_grams / 100.0 FROM food_library WHERE name=diet_records.food_name),0)
            WHERE protein_g=0 AND fat_g=0 AND carbs_g=0 AND fiber_g=0
        """)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_admin_db():
    connection = admin_db()
    try:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'super_admin',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS admin_invitations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code_hash TEXT NOT NULL UNIQUE,
                invitee_name TEXT NOT NULL DEFAULT '',
                invitee_contact TEXT NOT NULL DEFAULT '',
                created_by INTEGER NOT NULL REFERENCES admins(id),
                expires_at TIMESTAMP NOT NULL,
                used_at TIMESTAMP,
                used_by INTEGER REFERENCES admins(id),
                revoked_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER REFERENCES admins(id),
                admin_name TEXT NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT,
                detail TEXT,
                ip_address TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_login_username_time ON login_attempts(username, created_at);
            CREATE INDEX IF NOT EXISTS idx_admin_invite_expiry ON admin_invitations(expires_at,used_at,revoked_at);
        """)
        _add_missing_columns(connection, "admins", [
            ("approval_status", "TEXT NOT NULL DEFAULT 'approved'"),
            ("approved_by", "INTEGER REFERENCES admins(id)"),
            ("approved_at", "TIMESTAMP"),
            ("email", "TEXT"),
        ])
        connection.execute("UPDATE admins SET approval_status='approved' WHERE approval_status IS NULL OR approval_status='' ")
        connection.execute("UPDATE admins SET approved_at=COALESCE(approved_at,created_at) WHERE approval_status='approved'")
        connection.execute("""
            UPDATE admins
            SET approval_status='approved',active=1,
                approved_by=COALESCE(approved_by,(SELECT created_by FROM admin_invitations WHERE used_by=admins.id LIMIT 1)),
                approved_at=COALESCE(approved_at,CURRENT_TIMESTAMP)
            WHERE approval_status='pending'
              AND EXISTS (SELECT 1 FROM admin_invitations WHERE used_by=admins.id)
        """)
        connection.commit()
    finally:
        connection.close()
