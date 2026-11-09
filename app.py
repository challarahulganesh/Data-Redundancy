
from flask import Flask, request, jsonify, render_template
import sqlite3
import hashlib
import re
from pathlib import Path
from difflib import SequenceMatcher

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "dataguard.db"


# =====================================
# DATABASE CONNECTION
# =====================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# =====================================
# DATABASE INITIALIZATION
# =====================================

def initialize_database():

    with get_db() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                fingerprint TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


# =====================================
# DATA NORMALIZATION
# =====================================

def normalize(value):

    value = value.lower().strip()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"[^\w\s]", "", value)

    return value


# =====================================
# GENERATE UNIQUE FINGERPRINT
# =====================================

def generate_fingerprint(title, category, description):

    content = "|".join([
        normalize(title),
        normalize(category),
        normalize(description)
    ])

    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()


# =====================================
# DATA VALIDATION
# =====================================

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


# =====================================
# SIMILARITY DETECTION
# =====================================

def similarity(value1, value2):

    value1 = normalize(value1)
    value2 = normalize(value2)

    return SequenceMatcher(
        None,
        value1,
        value2
    ).ratio()


# =====================================
# CONVERT DATABASE ROW TO JSON
# =====================================

def record_dict(record):

    return {
        "id": record["id"],
        "title": record["title"],
        "category": record["category"],
        "description": record["description"],
        "created_at": record["created_at"]
    }


# =====================================
# HOME PAGE
# =====================================

@app.route("/")
def home():

    return render_template("index.html")


# =====================================
# DASHBOARD STATISTICS
# =====================================

@app.route("/api/stats")
def stats():

    with get_db() as conn:

        total = conn.execute(
            "SELECT COUNT(*) FROM records"
        ).fetchone()[0]

        duplicates = conn.execute("""
            SELECT COUNT(*) FROM activity
            WHERE event_type = 'duplicate'
        """).fetchone()[0]

        reviews = conn.execute("""
            SELECT COUNT(*) FROM activity
            WHERE event_type = 'review'
        """).fetchone()[0]

    return jsonify({
        "total_records": total,
        "unique_records": total,
        "duplicates_prevented": duplicates,
        "pending_reviews": reviews,
        "database_status": "Active"
    })


# =====================================
# DISPLAY ALL RECORDS
# =====================================

@app.route("/api/records")
def get_records():

    with get_db() as conn:

        records = conn.execute("""
            SELECT * FROM records
            ORDER BY id DESC
        """).fetchall()

    return jsonify([
        record_dict(record)
        for record in records
    ])


# =====================================
# ADD AND VERIFY NEW DATA
# =====================================

@app.route("/api/records", methods=["POST"])
def add_record():

    data = request.get_json(silent=True) or {}

    title = str(data.get("title", "")).strip()
    category = str(data.get("category", "")).strip()
    description = str(data.get("description", "")).strip()

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

    # STEP 2: EXACT DUPLICATE CHECK

    fingerprint = generate_fingerprint(
        title,
        category,
        description
    )

    with get_db() as conn:

        existing = conn.execute("""
            SELECT * FROM records
            WHERE fingerprint = ?
        """, (fingerprint,)).fetchone()

        if existing:

            conn.execute("""
                INSERT INTO activity(event_type)
                VALUES(?)
            """, ("duplicate",))

            return jsonify({
                "status": "duplicate",
                "classification": "Redundant Data",
                "message": "This record already exists."
            }), 409

        # STEP 3: SIMILARITY CHECKING

        records = conn.execute("""
            SELECT * FROM records
        """).fetchall()

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

            # More tolerant title matching
            # Category and description must also match closely

            if (
                title_score >= 0.80
                and category_score >= 0.90
                and description_score >= 0.90
            ):

                conn.execute("""
                    INSERT INTO activity(event_type)
                    VALUES(?)
                """, ("review",))

                return jsonify({
                    "status": "review",
                    "classification": "Possible Duplicate",
                    "message": (
                        "A similar record already exists. "
                        "Manual review is required."
                    ),
                    "similarity": {
                        "title": round(title_score * 100, 2),
                        "category": round(category_score * 100, 2),
                        "description": round(
                            description_score * 100, 2
                        )
                    },
                    "existing_record": record_dict(record)
                }), 200

        # STEP 4: SAVE UNIQUE VERIFIED DATA

        try:

            cursor = conn.execute("""
                INSERT INTO records
                (title, category, description, fingerprint)
                VALUES (?, ?, ?, ?)
            """, (
                title,
                category,
                description,
                fingerprint
            ))

            new_id = cursor.lastrowid

            saved = conn.execute("""
                SELECT * FROM records
                WHERE id = ?
            """, (new_id,)).fetchone()

        except sqlite3.IntegrityError:

            return jsonify({
                "status": "duplicate",
                "message": "Duplicate record detected."
            }), 409

    return jsonify({
        "status": "success",
        "classification": "Unique Verified Data",
        "message": "Record successfully added!",
        "record": record_dict(saved)
    }), 201


# =====================================
# START APPLICATION
# =====================================

if __name__ == "__main__":

    initialize_database()

    app.run(debug=True)
