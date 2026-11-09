
from flask import Flask, request, jsonify, render_template
import sqlite3
import hashlib
import re
import os
from pathlib import Path
from difflib import SequenceMatcher

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "dataguard.db"

# PostgreSQL on Render, SQLite locally
DATABASE_URL = os.environ.get("DATABASE_URL")


# ==========================================
# DATABASE CONNECTION
# ==========================================

def get_db():

    if DATABASE_URL:
        import psycopg2
        from psycopg2.extras import DictCursor

        url = DATABASE_URL.replace(
            "postgres://", "postgresql://", 1
        )

        conn = psycopg2.connect(
            url,
            cursor_factory=DictCursor,
            sslmode="require"
        )

        return conn

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    return conn


def execute_query(conn, query, params=()):

    cursor = conn.cursor()

    if DATABASE_URL:
        query = query.replace("?", "%s")

    cursor.execute(query, params)

    return cursor


# ==========================================
# DATABASE INITIALIZATION
# ==========================================

def initialize_database():

    conn = get_db()

    try:

        if DATABASE_URL:

            execute_query(conn, """
                CREATE TABLE IF NOT EXISTS records (
                    id SERIAL PRIMARY KEY,
                    title VARCHAR(200) NOT NULL,
                    category VARCHAR(100) NOT NULL,
                    description TEXT NOT NULL,
                    fingerprint VARCHAR(64) UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            execute_query(conn, """
                CREATE TABLE IF NOT EXISTS activity (
                    id SERIAL PRIMARY KEY,
                    event_type VARCHAR(50) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

        else:

            execute_query(conn, """
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    fingerprint TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            execute_query(conn, """
                CREATE TABLE IF NOT EXISTS activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# ==========================================
# NORMALIZE DATA
# ==========================================

def normalize(value):

    value = value.lower().strip()

    value = re.sub(r"\s+", " ", value)

    value = re.sub(r"[^\w\s]", "", value)

    return value


# ==========================================
# GENERATE DATA FINGERPRINT
# ==========================================

def generate_fingerprint(title, category, description):

    content = "|".join([
        normalize(title),
        normalize(category),
        normalize(description)
    ])

    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()


# ==========================================
# DATA VALIDATION
# ==========================================

def validate_data(title, category, description):

    if not title or not category or not description:

        return False, "All fields are required."

    if len(title) < 3 or len(title) > 200:

        return False, "Title must contain 3-200 characters."

    if len(category) > 100:

        return False, "Category must be below 100 characters."

    if len(description) > 5000:

        return False, "Description is too long."

    return True, "Validation successful."


# ==========================================
# SIMILARITY DETECTION
# ==========================================

def similarity(value1, value2):

    return SequenceMatcher(
        None,
        normalize(value1),
        normalize(value2)
    ).ratio()


# ==========================================
# CONVERT DATABASE ROW TO JSON
# ==========================================

def record_dict(record):

    return {
        "id": record["id"],
        "title": record["title"],
        "category": record["category"],
        "description": record["description"],
        "created_at": str(record["created_at"])
    }


# ==========================================
# HOME PAGE
# ==========================================

@app.route("/")
def home():

    return render_template("index.html")


# ==========================================
# DATABASE HEALTH CHECK
# ==========================================

@app.route("/api/health")
def health():

    conn = get_db()

    try:

        execute_query(conn, "SELECT 1")

        return jsonify({
            "status": "healthy",
            "database": (
                "PostgreSQL" if DATABASE_URL else "SQLite"
            )
        })

    finally:
        conn.close()


# ==========================================
# DASHBOARD STATISTICS
# ==========================================

@app.route("/api/stats")
def stats():

    conn = get_db()

    try:

        total = execute_query(
            conn,
            "SELECT COUNT(*) FROM records"
        ).fetchone()[0]

        duplicates = execute_query(
            conn,
            """
            SELECT COUNT(*) FROM activity
            WHERE event_type = ?
            """,
            ("duplicate",)
        ).fetchone()[0]

        reviews = execute_query(
            conn,
            """
            SELECT COUNT(*) FROM activity
            WHERE event_type = ?
            """,
            ("review",)
        ).fetchone()[0]

        return jsonify({

            "total_records": total,

            "unique_records": total,

            "duplicates_prevented": duplicates,

            "pending_reviews": reviews,

            "database_status": "Active"

        })

    finally:
        conn.close()


# ==========================================
# DISPLAY ALL DATABASE RECORDS
# ==========================================

@app.route("/api/records")
def get_records():

    conn = get_db()

    try:

        records = execute_query(
            conn,
            """
            SELECT * FROM records
            ORDER BY id DESC
            """
        ).fetchall()

        return jsonify([
            record_dict(record)
            for record in records
        ])

    finally:
        conn.close()


# ==========================================
# ADD AND VERIFY NEW DATA
# ==========================================

@app.route("/api/records", methods=["POST"])
def add_record():

    data = request.get_json(silent=True) or {}

    title = str(data.get("title", "")).strip()

    category = str(data.get("category", "")).strip()

    description = str(
        data.get("description", "")
    ).strip()

    # STEP 1: VALIDATION

    valid, message = validate_data(
        title,
        category,
        description
    )

    if not valid:

        return jsonify({

            "status": "invalid",

            "message": message

        }), 400

    # STEP 2: GENERATE FINGERPRINT

    fingerprint = generate_fingerprint(
        title,
        category,
        description
    )

    conn = get_db()

    try:

        # STEP 3: EXACT DUPLICATE CHECK

        existing = execute_query(
            conn,
            """
            SELECT * FROM records
            WHERE fingerprint = ?
            """,
            (fingerprint,)
        ).fetchone()

        if existing:

            execute_query(
                conn,
                """
                INSERT INTO activity(event_type)
                VALUES(?)
                """,
                ("duplicate",)
            )

            conn.commit()

            return jsonify({

                "status": "duplicate",

                "classification": "Redundant Data",

                "message": "This record already exists."

            }), 409

        # STEP 4: SIMILARITY CHECKING

        records = execute_query(
            conn,
            "SELECT * FROM records"
        ).fetchall()

        for record in records:

            title_score = similarity(
                title,
                record["title"]
            )

            category_score = similarity(
                category,
                record["category"]
            )

            description_score = similarity(
                description,
                record["description"]
            )

            if (
                title_score >= 0.80
                and category_score >= 0.90
                and description_score >= 0.90
            ):

                execute_query(
                    conn,
                    """
                    INSERT INTO activity(event_type)
                    VALUES(?)
                    """,
                    ("review",)
                )

                conn.commit()

                return jsonify({

                    "status": "review",

                    "classification": "Possible Duplicate",

                    "message": (
                        "A similar record already exists. "
                        "Manual review is required."
                    ),

                    "similarity": {

                        "title": round(
                            title_score * 100, 2
                        ),

                        "category": round(
                            category_score * 100, 2
                        ),

                        "description": round(
                            description_score * 100, 2
                        )

                    },

                    "existing_record": record_dict(record)

                }), 200

        # STEP 5: SAVE UNIQUE VERIFIED DATA

        try:

            if DATABASE_URL:

                cursor = execute_query(
                    conn,
                    """
                    INSERT INTO records
                    (title, category, description, fingerprint)
                    VALUES (?, ?, ?, ?)
                    RETURNING id
                    """,
                    (
                        title,
                        category,
                        description,
                        fingerprint
                    )
                )

                new_id = cursor.fetchone()["id"]

            else:

                cursor = execute_query(
                    conn,
                    """
                    INSERT INTO records
                    (title, category, description, fingerprint)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        title,
                        category,
                        description,
                        fingerprint
                    )
                )

                new_id = cursor.lastrowid

            saved = execute_query(
                conn,
                """
                SELECT * FROM records
                WHERE id = ?
                """,
                (new_id,)
            ).fetchone()

            conn.commit()

        except Exception:

            conn.rollback()

            raise

        return jsonify({

            "status": "success",

            "classification": "Unique Verified Data",

            "message": "Record successfully added!",

            "record": record_dict(saved)

        }), 201

    finally:

        conn.close()


# ==========================================
# APPLICATION START
# ==========================================

initialize_database()


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
