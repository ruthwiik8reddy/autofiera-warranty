"""
db.py — SQLite data layer for the Autofiera Warranty & Orders platform.

Single-file, zero-setup persistence. Uses parameterized queries everywhere
(never f-strings) per Autofiera Flask conventions. Row factory returns dict-like
sqlite3.Row objects.

Tables
------
users               login + role (admin / customer)
products            PPF / coating products customers can order
orders              work orders (a customer requests an install)
warranties          warranty registrations (pending -> approved/rejected)
warranty_coverage   one row per car part covered by a warranty
warranty_images     photos uploaded at registration time
claims              warranty claims filed against an approved warranty
claim_images        photos uploaded with a claim
"""

import os
import sqlite3
import secrets
import hashlib
import hmac
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autofiera.db")

# Car parts that can be covered by PPF — mirrors the XPEL coverage list,
# plus a few common extras. Used to render the registration checklist.
CAR_PARTS = [
    "Full Hood",
    "Full Front Fender",
    "Front Bumper",
    "Full Fender Flares",
    "Doors",
    "Mirrors",
    "Roof",
    "Rocker Panels",
    "Rear Quarter Panels",
    "Rear Bumper",
    "Rear Diffuser",
    "Trunk/Hatch",
    "Headlights",
    "A-Pillars",
    "Full Body",
]


# --------------------------------------------------------------------------- #
# Connection helpers
# --------------------------------------------------------------------------- #
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# --------------------------------------------------------------------------- #
# Password hashing (pbkdf2:sha256 — Autofiera standard)
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
    return f"pbkdf2:sha256:{salt}:{hashed.hex()}"


def verify_password(stored: str, provided: str) -> bool:
    try:
        _, _algo, salt, hashed = stored.split(":")
        check = hashlib.pbkdf2_hmac("sha256", provided.encode(), salt.encode(), 260000)
        return hmac.compare_digest(hashed, check.hex())
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    phone         TEXT,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'customer',   -- 'admin' | 'customer'
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    category      TEXT NOT NULL,                       -- 'PPF' | 'Ceramic Coating'
    tagline       TEXT,
    description   TEXT,
    price         REAL,
    warranty_years INTEGER DEFAULT 8,
    active        INTEGER DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    product_id    INTEGER,
    product_name  TEXT,
    vehicle_ymm   TEXT,
    vehicle_color TEXT,
    vin           TEXT,
    notes         TEXT,
    status        TEXT NOT NULL DEFAULT 'received',    -- received|scheduled|in_progress|completed|cancelled
    created_at    TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS warranties (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,                  -- who registered it
    warranty_number TEXT,                              -- assigned on approval
    customer_name   TEXT NOT NULL,
    customer_phone  TEXT,
    customer_email  TEXT,
    customer_address TEXT,
    vin             TEXT NOT NULL,
    plate           TEXT,
    miles           TEXT,
    vehicle_ymm     TEXT,
    vehicle_color   TEXT,
    product_id      INTEGER,
    product_name    TEXT,
    warranty_years  INTEGER DEFAULT 8,
    roll_id         TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',   -- pending|approved|rejected
    admin_note      TEXT,
    created_at      TEXT NOT NULL,
    approved_at     TEXT,
    expiry_date     TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS warranty_coverage (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    warranty_id  INTEGER NOT NULL,
    part_name    TEXT NOT NULL,
    product_name TEXT,
    expiry_date  TEXT,
    FOREIGN KEY (warranty_id) REFERENCES warranties(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS warranty_images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    warranty_id INTEGER NOT NULL,
    filename    TEXT NOT NULL,
    FOREIGN KEY (warranty_id) REFERENCES warranties(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS claims (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    warranty_id  INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    affected_part TEXT,
    description  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'submitted',    -- submitted|under_review|approved|rejected|resolved
    admin_note   TEXT,
    created_at   TEXT NOT NULL,
    resolved_at  TEXT,
    FOREIGN KEY (warranty_id) REFERENCES warranties(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS claim_images (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id  INTEGER NOT NULL,
    filename  TEXT NOT NULL,
    FOREIGN KEY (claim_id) REFERENCES claims(id) ON DELETE CASCADE
);
"""


def init_db():
    """Create tables and seed an admin + sample products on first run."""
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _seed(conn)
    finally:
        conn.close()


def _seed(conn):
    now = datetime.utcnow().isoformat()

    # --- seed admin (you) ---
    cur = conn.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'admin'")
    if cur.fetchone()["c"] == 0:
        conn.execute(
            "INSERT INTO users (name, email, phone, password_hash, role, created_at) "
            "VALUES (?, ?, ?, ?, 'admin', ?)",
            (
                "Ruthvik — Autofiera",
                "admin@autofiera.com",
                "+91 00000 00000",
                hash_password("autofiera"),  # CHANGE THIS after first login
                now,
            ),
        )

    # --- seed a sample customer for testing ---
    cur = conn.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'customer'")
    if cur.fetchone()["c"] == 0:
        conn.execute(
            "INSERT INTO users (name, email, phone, password_hash, role, created_at) "
            "VALUES (?, ?, ?, ?, 'customer', ?)",
            (
                "Vivek Reddy",
                "vivek@example.com",
                "+91 90000 00000",
                hash_password("customer"),
                now,
            ),
        )

    # --- seed products ---
    cur = conn.execute("SELECT COUNT(*) AS c FROM products")
    if cur.fetchone()["c"] == 0:
        products = [
            ("Autofiera Protex Lite 8", "PPF",
             "8-Year Paint Protection Film",
             "Self-healing TPU film with hydrophobic top coat. Protects against rock chips, "
             "scratches and stains with an 8-year warranty.", 145000, 8),
            ("Autofiera Protex Pro 10", "PPF",
             "10-Year Premium PPF",
             "Our flagship film — superior gloss, stain resistance and a 10-year warranty for "
             "full-body coverage.", 215000, 10),
            ("Autofiera Shield Matte", "PPF",
             "Matte-Finish PPF",
             "Transforms gloss paint into a satin matte finish while protecting it. 8-year warranty.",
             175000, 8),
            ("Autofiera Ceramic Elite", "Ceramic Coating",
             "9H Ceramic Coating",
             "Multi-layer 9H ceramic coating for deep gloss and easy maintenance. 5-year warranty.",
             65000, 5),
        ]
        for p in products:
            conn.execute(
                "INSERT INTO products (name, category, tagline, description, price, "
                "warranty_years, active, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (*p, now),
            )

    conn.commit()


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def get_user_by_email(email):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    finally:
        conn.close()


def get_user(user_id):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    finally:
        conn.close()


def create_user(name, email, phone, password, role="customer"):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (name, email, phone, password_hash, role, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, email.strip().lower(), phone, hash_password(password), role,
             datetime.utcnow().isoformat()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #
def list_products(active_only=True):
    conn = get_conn()
    try:
        q = "SELECT * FROM products"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY category, price"
        return conn.execute(q).fetchall()
    finally:
        conn.close()


def get_product(product_id):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    finally:
        conn.close()


def create_product(name, category, tagline, description, price, warranty_years):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO products (name, category, tagline, description, price, "
            "warranty_years, active, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (name, category, tagline, description, price, warranty_years,
             datetime.utcnow().isoformat()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def set_product_active(product_id, active):
    conn = get_conn()
    try:
        conn.execute("UPDATE products SET active = ? WHERE id = ?", (1 if active else 0, product_id))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Orders (work orders)
# --------------------------------------------------------------------------- #
def create_order(user_id, product_id, product_name, vehicle_ymm, vehicle_color, vin, notes):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO orders (user_id, product_id, product_name, vehicle_ymm, "
            "vehicle_color, vin, notes, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'received', ?)",
            (user_id, product_id, product_name, vehicle_ymm, vehicle_color, vin, notes,
             datetime.utcnow().isoformat()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_orders(user_id=None):
    conn = get_conn()
    try:
        if user_id:
            return conn.execute(
                "SELECT o.*, u.name AS customer_name, u.email AS customer_email, u.phone AS customer_phone "
                "FROM orders o JOIN users u ON u.id = o.user_id "
                "WHERE o.user_id = ? ORDER BY o.created_at DESC",
                (user_id,),
            ).fetchall()
        return conn.execute(
            "SELECT o.*, u.name AS customer_name, u.email AS customer_email, u.phone AS customer_phone "
            "FROM orders o JOIN users u ON u.id = o.user_id ORDER BY o.created_at DESC"
        ).fetchall()
    finally:
        conn.close()


def update_order_status(order_id, status):
    conn = get_conn()
    try:
        conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Warranties
# --------------------------------------------------------------------------- #
def create_warranty(data, parts, image_filenames):
    """data: dict of warranty fields. parts: list of part names. image_filenames: list."""
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO warranties
               (user_id, customer_name, customer_phone, customer_email, customer_address,
                vin, plate, miles, vehicle_ymm, vehicle_color, product_id, product_name,
                warranty_years, roll_id, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (
                data["user_id"], data["customer_name"], data.get("customer_phone"),
                data.get("customer_email"), data.get("customer_address"), data["vin"],
                data.get("plate"), data.get("miles"), data.get("vehicle_ymm"),
                data.get("vehicle_color"), data.get("product_id"), data.get("product_name"),
                data.get("warranty_years", 8), data.get("roll_id"),
                datetime.utcnow().isoformat(),
            ),
        )
        warranty_id = cur.lastrowid
        for part in parts:
            conn.execute(
                "INSERT INTO warranty_coverage (warranty_id, part_name, product_name) VALUES (?, ?, ?)",
                (warranty_id, part, data.get("product_name")),
            )
        for fn in image_filenames:
            conn.execute(
                "INSERT INTO warranty_images (warranty_id, filename) VALUES (?, ?)",
                (warranty_id, fn),
            )
        conn.commit()
        return warranty_id
    finally:
        conn.close()


def list_warranties(user_id=None, status=None):
    conn = get_conn()
    try:
        q = ("SELECT w.*, u.name AS registered_by FROM warranties w "
             "JOIN users u ON u.id = w.user_id WHERE 1=1")
        params = []
        if user_id:
            q += " AND w.user_id = ?"
            params.append(user_id)
        if status:
            q += " AND w.status = ?"
            params.append(status)
        q += " ORDER BY w.created_at DESC"
        return conn.execute(q, params).fetchall()
    finally:
        conn.close()


def get_warranty(warranty_id):
    conn = get_conn()
    try:
        w = conn.execute("SELECT * FROM warranties WHERE id = ?", (warranty_id,)).fetchone()
        if not w:
            return None, [], []
        coverage = conn.execute(
            "SELECT * FROM warranty_coverage WHERE warranty_id = ? ORDER BY id", (warranty_id,)
        ).fetchall()
        images = conn.execute(
            "SELECT * FROM warranty_images WHERE warranty_id = ?", (warranty_id,)
        ).fetchall()
        return w, coverage, images
    finally:
        conn.close()


def approve_warranty(warranty_id, admin_note=""):
    """Assign a warranty number, compute expiry dates, set status=approved."""
    conn = get_conn()
    try:
        w = conn.execute("SELECT * FROM warranties WHERE id = ?", (warranty_id,)).fetchone()
        if not w:
            return False
        years = w["warranty_years"] or 8
        approved_at = datetime.utcnow()
        # ~365.25 days/year
        expiry = approved_at + timedelta(days=int(365.25 * years))
        expiry_str = expiry.strftime("%m/%d/%Y")
        warranty_number = f"AF-{90000 + warranty_id}"
        conn.execute(
            "UPDATE warranties SET status = 'approved', admin_note = ?, approved_at = ?, "
            "expiry_date = ?, warranty_number = ? WHERE id = ?",
            (admin_note, approved_at.isoformat(), expiry_str, warranty_number, warranty_id),
        )
        conn.execute(
            "UPDATE warranty_coverage SET expiry_date = ? WHERE warranty_id = ?",
            (expiry_str, warranty_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def reject_warranty(warranty_id, admin_note=""):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE warranties SET status = 'rejected', admin_note = ? WHERE id = ?",
            (admin_note, warranty_id),
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Claims
# --------------------------------------------------------------------------- #
def create_claim(warranty_id, user_id, affected_part, description, image_filenames):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO claims (warranty_id, user_id, affected_part, description, status, created_at) "
            "VALUES (?, ?, ?, ?, 'submitted', ?)",
            (warranty_id, user_id, affected_part, description, datetime.utcnow().isoformat()),
        )
        claim_id = cur.lastrowid
        for fn in image_filenames:
            conn.execute("INSERT INTO claim_images (claim_id, filename) VALUES (?, ?)", (claim_id, fn))
        conn.commit()
        return claim_id
    finally:
        conn.close()


def list_claims(user_id=None):
    conn = get_conn()
    try:
        q = ("SELECT c.*, w.warranty_number, w.vin, w.vehicle_ymm, w.customer_name, "
             "u.name AS claimant_name, u.email AS claimant_email "
             "FROM claims c JOIN warranties w ON w.id = c.warranty_id "
             "JOIN users u ON u.id = c.user_id WHERE 1=1")
        params = []
        if user_id:
            q += " AND c.user_id = ?"
            params.append(user_id)
        q += " ORDER BY c.created_at DESC"
        return conn.execute(q, params).fetchall()
    finally:
        conn.close()


def get_claim_images(claim_id):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM claim_images WHERE claim_id = ?", (claim_id,)).fetchall()
    finally:
        conn.close()


def update_claim_status(claim_id, status, admin_note=""):
    conn = get_conn()
    try:
        resolved = datetime.utcnow().isoformat() if status in ("resolved", "approved", "rejected") else None
        conn.execute(
            "UPDATE claims SET status = ?, admin_note = ?, resolved_at = ? WHERE id = ?",
            (status, admin_note, resolved, claim_id),
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Dashboard counts
# --------------------------------------------------------------------------- #
def admin_counts():
    conn = get_conn()
    try:
        def one(q, p=()):
            return conn.execute(q, p).fetchone()["c"]
        return {
            "pending_warranties": one("SELECT COUNT(*) c FROM warranties WHERE status='pending'"),
            "approved_warranties": one("SELECT COUNT(*) c FROM warranties WHERE status='approved'"),
            "open_orders": one("SELECT COUNT(*) c FROM orders WHERE status NOT IN ('completed','cancelled')"),
            "total_orders": one("SELECT COUNT(*) c FROM orders"),
            "open_claims": one("SELECT COUNT(*) c FROM claims WHERE status NOT IN ('resolved','rejected')"),
            "total_claims": one("SELECT COUNT(*) c FROM claims"),
        }
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Initialized database at {DB_PATH}")
