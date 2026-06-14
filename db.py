"""
db.py — SQLite data layer for the X-Paint Protection Film (X-PPF) platform.

Multi-studio model: every non-admin user is a STUDIO with its own name + logo.
A studio registers warranties for end clients and chooses, per warranty, whether
to brand the certificate with its OWN logo or with X-PPF's branding.

Roles
-----
admin   -> X-PPF operator (you). Creates accounts, verifies & approves warranties,
           receives work orders, handles claims, manages the catalog.
studio  -> a detailing studio reselling PPF.

Accounts are created by admin only (no public signup).
"""

import os
import sqlite3
import secrets
import hashlib
import hmac
from datetime import datetime, timedelta

DB_PATH = os.environ.get("XPPF_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "xppf.db")

# Parts grouped for an organised coverage picker. "Full Body" is a master
# toggle in the UI (selects all) — it is not itself a stored part.
CAR_PART_GROUPS = {
    "Front":      ["Full Hood", "Full Front Fender", "Front Bumper", "Headlights"],
    "Sides":      ["Doors", "Mirrors", "Rocker Panels", "A-Pillars", "Full Fender Flares"],
    "Rear":       ["Rear Bumper", "Rear Quarter Panels", "Rear Diffuser", "Trunk/Hatch"],
    "Roof & Top": ["Roof", "Pillars"],
}
CAR_PARTS = [p for group in CAR_PART_GROUPS.values() for p in group]


# --------------------------------------------------------------------------- #
# Connection
# --------------------------------------------------------------------------- #
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# --------------------------------------------------------------------------- #
# Password hashing (pbkdf2:sha256)
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
    role          TEXT NOT NULL DEFAULT 'studio',      -- 'admin' | 'studio'
    studio_name   TEXT,
    studio_logo   TEXT,
    city          TEXT,
    verified      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    category       TEXT NOT NULL,
    tagline        TEXT,
    description    TEXT,
    price          REAL,
    warranty_years INTEGER DEFAULT 8,
    image          TEXT,
    active         INTEGER DEFAULT 1,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    product_id    INTEGER,
    product_name  TEXT,
    quantity      INTEGER DEFAULT 1,
    transport_mode TEXT,
    assigned_roll TEXT,
    vehicle_ymm   TEXT,
    vehicle_color TEXT,
    vin           TEXT,
    notes         TEXT,
    status        TEXT NOT NULL DEFAULT 'received',
    created_at    TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS warranties (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,
    warranty_number  TEXT,
    customer_name    TEXT NOT NULL,
    customer_phone   TEXT,
    customer_email   TEXT,
    customer_address TEXT,
    vin              TEXT NOT NULL,
    plate            TEXT,
    miles            TEXT,
    vehicle_ymm      TEXT,
    vehicle_color    TEXT,
    product_id       INTEGER,
    product_name     TEXT,
    warranty_years   INTEGER DEFAULT 8,
    roll_id          TEXT,
    brand_choice     TEXT NOT NULL DEFAULT 'xppf',     -- 'studio' | 'xppf'
    status           TEXT NOT NULL DEFAULT 'pending',
    admin_note       TEXT,
    created_at       TEXT NOT NULL,
    approved_at      TEXT,
    expiry_date      TEXT,
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
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    warranty_id   INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    affected_part TEXT,
    description   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'submitted',
    admin_note    TEXT,
    created_at    TEXT NOT NULL,
    resolved_at   TEXT,
    FOREIGN KEY (warranty_id) REFERENCES warranties(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS claim_images (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id  INTEGER NOT NULL,
    filename  TEXT NOT NULL,
    FOREIGN KEY (claim_id) REFERENCES claims(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS inventory (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id      INTEGER NOT NULL,                 -- studio (or admin) that owns the roll
    roll_id       TEXT NOT NULL,                    -- scanned / entered roll code
    product_name  TEXT,
    warranty_years INTEGER,                         -- term this roll is rated for
    length_m      REAL,                             -- metres of film on the roll (optional)
    status        TEXT NOT NULL DEFAULT 'in_stock', -- in_stock | assigned | depleted
    warranty_id   INTEGER,                          -- warranty it was assigned to
    order_id      INTEGER,                          -- work order it was assigned to
    customer_name TEXT,                             -- end client / studio it was assigned to
    note          TEXT,
    created_at    TEXT NOT NULL,
    assigned_at   TEXT,
    UNIQUE(owner_id, roll_id),
    FOREIGN KEY (owner_id) REFERENCES users(id),
    FOREIGN KEY (warranty_id) REFERENCES warranties(id)
);
"""


def _migrate(conn):
    """Add columns to older tables if missing (safe, idempotent)."""
    def cols(table):
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    user_cols = cols("users")
    for col in ("studio_name", "studio_logo", "city"):
        if col not in user_cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
    if "verified" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN verified INTEGER NOT NULL DEFAULT 0")
    if "brand_choice" not in cols("warranties"):
        conn.execute("ALTER TABLE warranties ADD COLUMN brand_choice TEXT NOT NULL DEFAULT 'xppf'")
    if "image" not in cols("products"):
        conn.execute("ALTER TABLE products ADD COLUMN image TEXT")
    order_cols = cols("orders")
    if "quantity" not in order_cols:
        conn.execute("ALTER TABLE orders ADD COLUMN quantity INTEGER DEFAULT 1")
    if "transport_mode" not in order_cols:
        conn.execute("ALTER TABLE orders ADD COLUMN transport_mode TEXT")
    if "assigned_roll" not in order_cols:
        conn.execute("ALTER TABLE orders ADD COLUMN assigned_roll TEXT")
    inv_cols = cols("inventory") if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='inventory'").fetchone() else set()
    if inv_cols:
        if "warranty_years" not in inv_cols:
            conn.execute("ALTER TABLE inventory ADD COLUMN warranty_years INTEGER")
        if "order_id" not in inv_cols:
            conn.execute("ALTER TABLE inventory ADD COLUMN order_id INTEGER")
    conn.commit()


def init_db():
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _migrate(conn)
        _seed(conn)
    finally:
        conn.close()


def _seed(conn):
    now = datetime.utcnow().isoformat()

    if conn.execute("SELECT COUNT(*) c FROM users WHERE role='admin'").fetchone()["c"] == 0:
        admin_email = (os.environ.get("XPPF_ADMIN_EMAIL") or "admin@xppf.com").strip().lower()
        admin_pw = os.environ.get("XPPF_ADMIN_PASSWORD") or "xppf-admin"
        conn.execute(
            "INSERT INTO users (name, email, phone, password_hash, role, studio_name, created_at) "
            "VALUES (?, ?, ?, ?, 'admin', ?, ?)",
            ("X-PPF Admin", admin_email, "+1 000 000 0000",
             hash_password(admin_pw), "X-Paint Protection Film", now),
        )

    if conn.execute("SELECT COUNT(*) c FROM users WHERE role='studio'").fetchone()["c"] == 0:
        conn.execute(
            "INSERT INTO users (name, email, phone, password_hash, role, studio_name, city, verified, created_at) "
            "VALUES (?, ?, ?, ?, 'studio', ?, ?, 1, ?)",
            ("Vivek Reddy", "studio@example.com", "+1 555 000 0000",
             hash_password("studio"), "Apex Auto Studio", "Hyderabad", now),
        )

    if conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"] == 0:
        products = [
            ("X-PPF Lite", "PPF", "5-Year Paint Protection Film",
             "Self-healing TPU film with a hydrophobic top coat. Everyday protection against rock "
             "chips, swirls and stains, backed by a 5-year warranty.", 95000, 5, "img/cat-5yr.jpg"),
            ("X-PPF Plus", "PPF", "7-Year Paint Protection Film",
             "Thicker self-healing film with enhanced gloss and stain resistance — a 7-year "
             "warranty for daily-driven and weekend cars alike.", 175000, 7, "img/cat-7yr.jpg"),
            ("X-PPF Pro", "PPF", "10-Year Premium PPF",
             "Flagship aliphatic-TPU film — maximum clarity, gloss and durability for full-body "
             "coverage, backed by a 10-year warranty.", 280000, 10, "img/cat-10yr.jpg"),
            ("X-PPF Ceramic", "Ceramic Coating", "9H Ceramic Coating",
             "Multi-layer 9H ceramic coating for deep gloss and effortless maintenance. "
             "5-year warranty.", 35000, 5, "img/cat-ceramic.jpg"),
        ]
        for p in products:
            conn.execute(
                "INSERT INTO products (name, category, tagline, description, price, "
                "warranty_years, image, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
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


def list_users():
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM users ORDER BY role, name").fetchall()
    finally:
        conn.close()


def create_user(name, email, phone, password, role="studio", studio_name=None,
                studio_logo=None, city=None, verified=0):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (name, email, phone, password_hash, role, studio_name, "
            "studio_logo, city, verified, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, email.strip().lower(), phone, hash_password(password), role,
             studio_name, studio_logo, city, 1 if verified else 0,
             datetime.utcnow().isoformat()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def set_user_verified(user_id, verified):
    conn = get_conn()
    try:
        conn.execute("UPDATE users SET verified = ? WHERE id = ?", (1 if verified else 0, user_id))
        conn.commit()
    finally:
        conn.close()


def update_studio_profile(user_id, studio_name, studio_logo=None, city=None):
    conn = get_conn()
    try:
        if studio_logo:
            conn.execute("UPDATE users SET studio_name=?, city=?, studio_logo=? WHERE id=?",
                         (studio_name, city, studio_logo, user_id))
        else:
            conn.execute("UPDATE users SET studio_name=?, city=? WHERE id=?",
                         (studio_name, city, user_id))
        conn.commit()
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


def create_product(name, category, tagline, description, price, warranty_years, image=None):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO products (name, category, tagline, description, price, "
            "warranty_years, image, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (name, category, tagline, description, price, warranty_years, image,
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
# Orders
# --------------------------------------------------------------------------- #
def create_order(user_id, product_id, product_name, quantity, transport_mode, notes=""):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO orders (user_id, product_id, product_name, quantity, transport_mode, "
            "notes, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'received', ?)",
            (user_id, product_id, product_name, quantity, transport_mode, notes,
             datetime.utcnow().isoformat()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_orders(user_id=None):
    conn = get_conn()
    try:
        base = ("SELECT o.*, u.name AS customer_name, u.email AS customer_email, "
                "u.phone AS customer_phone, u.studio_name AS studio_name, u.city AS studio_city, "
                "u.verified AS studio_verified, p.warranty_years AS product_warranty_years "
                "FROM orders o JOIN users u ON u.id = o.user_id "
                "LEFT JOIN products p ON p.id = o.product_id ")
        if user_id:
            return conn.execute(base + "WHERE o.user_id = ? ORDER BY o.created_at DESC",
                                (user_id,)).fetchall()
        return conn.execute(base + "ORDER BY o.created_at DESC").fetchall()
    finally:
        conn.close()


def get_order(order_id):
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT o.*, u.studio_name AS studio_name, u.name AS customer_name, "
            "u.verified AS studio_verified, p.warranty_years AS product_warranty_years "
            "FROM orders o JOIN users u ON u.id = o.user_id "
            "LEFT JOIN products p ON p.id = o.product_id WHERE o.id = ?", (order_id,)).fetchone()
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
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO warranties
               (user_id, customer_name, customer_phone, customer_email, customer_address,
                vin, plate, miles, vehicle_ymm, vehicle_color, product_id, product_name,
                warranty_years, roll_id, brand_choice, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (
                data["user_id"], data["customer_name"], data.get("customer_phone"),
                data.get("customer_email"), data.get("customer_address"), data["vin"],
                data.get("plate"), data.get("miles"), data.get("vehicle_ymm"),
                data.get("vehicle_color"), data.get("product_id"), data.get("product_name"),
                data.get("warranty_years", 8), data.get("roll_id"),
                data.get("brand_choice", "xppf"), datetime.utcnow().isoformat(),
            ),
        )
        warranty_id = cur.lastrowid
        for part in parts:
            conn.execute(
                "INSERT INTO warranty_coverage (warranty_id, part_name, product_name) VALUES (?, ?, ?)",
                (warranty_id, part, data.get("product_name")),
            )
        for fn in image_filenames:
            conn.execute("INSERT INTO warranty_images (warranty_id, filename) VALUES (?, ?)",
                         (warranty_id, fn))
        conn.commit()
        return warranty_id
    finally:
        conn.close()


def list_warranties(user_id=None, status=None):
    conn = get_conn()
    try:
        q = ("SELECT w.*, u.name AS registered_by, u.studio_name AS studio_name, "
             "u.studio_logo AS studio_logo FROM warranties w "
             "JOIN users u ON u.id = w.user_id WHERE 1=1")
        params = []
        if user_id:
            q += " AND w.user_id = ?"; params.append(user_id)
        if status:
            q += " AND w.status = ?"; params.append(status)
        q += " ORDER BY w.created_at DESC"
        return conn.execute(q, params).fetchall()
    finally:
        conn.close()


def get_warranty(warranty_id):
    conn = get_conn()
    try:
        w = conn.execute(
            "SELECT w.*, u.studio_name AS studio_name, u.studio_logo AS studio_logo "
            "FROM warranties w JOIN users u ON u.id = w.user_id WHERE w.id = ?",
            (warranty_id,),
        ).fetchone()
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
    conn = get_conn()
    try:
        w = conn.execute("SELECT * FROM warranties WHERE id = ?", (warranty_id,)).fetchone()
        if not w:
            return False
        years = w["warranty_years"] or 8
        approved_at = datetime.utcnow()
        expiry = approved_at + timedelta(days=int(365.25 * years))
        expiry_str = expiry.strftime("%m/%d/%Y")
        warranty_number = f"XP-{90000 + warranty_id}"
        conn.execute(
            "UPDATE warranties SET status='approved', admin_note=?, approved_at=?, "
            "expiry_date=?, warranty_number=? WHERE id=?",
            (admin_note, approved_at.isoformat(), expiry_str, warranty_number, warranty_id),
        )
        conn.execute("UPDATE warranty_coverage SET expiry_date=? WHERE warranty_id=?",
                     (expiry_str, warranty_id))
        conn.commit()
        return True
    finally:
        conn.close()


def reject_warranty(warranty_id, admin_note=""):
    conn = get_conn()
    try:
        conn.execute("UPDATE warranties SET status='rejected', admin_note=? WHERE id=?",
                     (admin_note, warranty_id))
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
             "u.name AS claimant_name, u.email AS claimant_email, u.studio_name AS studio_name "
             "FROM claims c JOIN warranties w ON w.id = c.warranty_id "
             "JOIN users u ON u.id = c.user_id WHERE 1=1")
        params = []
        if user_id:
            q += " AND c.user_id = ?"; params.append(user_id)
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
        conn.execute("UPDATE claims SET status=?, admin_note=?, resolved_at=? WHERE id=?",
                     (status, admin_note, resolved, claim_id))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Inventory (film rolls)
# --------------------------------------------------------------------------- #
def add_roll(owner_id, roll_id, product_name=None, warranty_years=None, length_m=None, note=None):
    """Add a roll to an owner's inventory. Returns (id, error_message)."""
    roll_id = (roll_id or "").strip()
    if not roll_id:
        return None, "Roll ID is required."
    conn = get_conn()
    try:
        if conn.execute("SELECT 1 FROM inventory WHERE owner_id=? AND roll_id=?",
                        (owner_id, roll_id)).fetchone():
            return None, f"Roll {roll_id} is already in your inventory."
        cur = conn.execute(
            "INSERT INTO inventory (owner_id, roll_id, product_name, warranty_years, length_m, "
            "status, note, created_at) VALUES (?, ?, ?, ?, ?, 'in_stock', ?, ?)",
            (owner_id, roll_id, product_name, warranty_years, length_m, note,
             datetime.utcnow().isoformat()),
        )
        conn.commit()
        return cur.lastrowid, None
    finally:
        conn.close()


def available_rolls(owner_id, warranty_years=None):
    """In-stock rolls for an owner, optionally filtered to a warranty term."""
    conn = get_conn()
    try:
        q = "SELECT * FROM inventory WHERE owner_id=? AND status='in_stock'"
        p = [owner_id]
        if warranty_years is not None:
            q += " AND warranty_years=?"; p.append(warranty_years)
        q += " ORDER BY roll_id"
        return conn.execute(q, p).fetchall()
    finally:
        conn.close()


def assign_roll_to_order(roll_pk, order_id, studio_name):
    conn = get_conn()
    try:
        roll = conn.execute("SELECT * FROM inventory WHERE id=? AND status='in_stock'",
                            (roll_pk,)).fetchone()
        if not roll:
            return False
        conn.execute(
            "UPDATE inventory SET status='assigned', order_id=?, customer_name=?, assigned_at=? WHERE id=?",
            (order_id, studio_name, datetime.utcnow().isoformat(), roll_pk))
        conn.execute("UPDATE orders SET assigned_roll=? WHERE id=?", (roll["roll_id"], order_id))
        conn.commit()
        return True
    finally:
        conn.close()


def auto_assign_orders(owner_id):
    """
    Auto-assignment agent: for every open work order placed by a *verified* studio
    that has no roll yet, pick an in-stock roll matching the ordered warranty term
    and assign it. Returns a list of (order_id, studio, roll_id) tuples assigned.
    """
    conn = get_conn()
    assigned = []
    try:
        orders = conn.execute(
            "SELECT o.id, o.user_id, u.studio_name, u.name, u.verified, p.warranty_years AS yrs "
            "FROM orders o JOIN users u ON u.id=o.user_id "
            "LEFT JOIN products p ON p.id=o.product_id "
            "WHERE o.status NOT IN ('completed','cancelled') "
            "AND (o.assigned_roll IS NULL OR o.assigned_roll='') "
            "ORDER BY o.created_at").fetchall()
        for o in orders:
            if not o["verified"]:
                continue
            roll = conn.execute(
                "SELECT * FROM inventory WHERE owner_id=? AND status='in_stock' AND "
                "(warranty_years=? OR ? IS NULL) ORDER BY warranty_years IS NULL, roll_id LIMIT 1",
                (owner_id, o["yrs"], o["yrs"])).fetchone()
            if not roll:
                continue
            conn.execute(
                "UPDATE inventory SET status='assigned', order_id=?, customer_name=?, assigned_at=? WHERE id=?",
                (o["id"], o["studio_name"] or o["name"], datetime.utcnow().isoformat(), roll["id"]))
            conn.execute("UPDATE orders SET assigned_roll=? WHERE id=?", (roll["roll_id"], o["id"]))
            assigned.append((o["id"], o["studio_name"] or o["name"], roll["roll_id"]))
        conn.commit()
        return assigned
    finally:
        conn.close()


def get_roll(owner_id, roll_id):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM inventory WHERE owner_id=? AND roll_id=?",
                            (owner_id, (roll_id or "").strip())).fetchone()
    finally:
        conn.close()


def list_inventory(owner_id=None, status=None):
    """owner_id=None returns the full ledger across all owners (admin view)."""
    conn = get_conn()
    try:
        q = ("SELECT i.*, u.name AS owner_name, u.studio_name AS owner_studio "
             "FROM inventory i JOIN users u ON u.id = i.owner_id WHERE 1=1")
        params = []
        if owner_id:
            q += " AND i.owner_id = ?"; params.append(owner_id)
        if status:
            q += " AND i.status = ?"; params.append(status)
        q += " ORDER BY CASE i.status WHEN 'in_stock' THEN 0 WHEN 'assigned' THEN 1 ELSE 2 END, i.created_at DESC"
        return conn.execute(q, params).fetchall()
    finally:
        conn.close()


def inventory_counts(owner_id=None):
    conn = get_conn()
    try:
        def one(extra, p):
            return conn.execute("SELECT COUNT(*) c FROM inventory WHERE 1=1 " + extra, p).fetchone()["c"]
        scope, p = ("", [])
        if owner_id:
            scope, p = (" AND owner_id=?", [owner_id])
        return {
            "total":    one(scope, p),
            "in_stock": one(scope + " AND status='in_stock'", p),
            "assigned": one(scope + " AND status='assigned'", p),
        }
    finally:
        conn.close()


def assign_roll(roll_pk, warranty_id, customer_name):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE inventory SET status='assigned', warranty_id=?, customer_name=?, assigned_at=? "
            "WHERE id=?",
            (warranty_id, customer_name, datetime.utcnow().isoformat(), roll_pk),
        )
        conn.commit()
    finally:
        conn.close()


def release_roll_for_warranty(warranty_id):
    """Return any roll assigned to this warranty back to stock (e.g. on rejection)."""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE inventory SET status='in_stock', warranty_id=NULL, customer_name=NULL, "
            "assigned_at=NULL WHERE warranty_id=?", (warranty_id,))
        conn.commit()
    finally:
        conn.close()


def auto_verify_roll(warranty_id):
    """
    Cross-check the roll number entered on a warranty against the registering
    studio's inventory. If it matches an in-stock roll, assign (deduct) it and
    report it as verified. Returns one of: 'verified' | 'reused' | 'unknown' | 'none'.
    """
    conn = get_conn()
    try:
        w = conn.execute("SELECT user_id, roll_id, customer_name FROM warranties WHERE id=?",
                         (warranty_id,)).fetchone()
        if not w or not (w["roll_id"] or "").strip():
            return "none"
        roll = conn.execute("SELECT * FROM inventory WHERE owner_id=? AND roll_id=?",
                            (w["user_id"], w["roll_id"].strip())).fetchone()
        if not roll:
            return "unknown"
        if roll["status"] != "in_stock":
            return "reused"
        conn.execute(
            "UPDATE inventory SET status='assigned', warranty_id=?, customer_name=?, assigned_at=? "
            "WHERE id=?",
            (warranty_id, w["customer_name"], datetime.utcnow().isoformat(), roll["id"]),
        )
        conn.commit()
        return "verified"
    finally:
        conn.close()


def admin_counts():
    conn = get_conn()
    try:
        def one(q):
            return conn.execute(q).fetchone()["c"]
        return {
            "pending_warranties": one("SELECT COUNT(*) c FROM warranties WHERE status='pending'"),
            "approved_warranties": one("SELECT COUNT(*) c FROM warranties WHERE status='approved'"),
            "open_orders": one("SELECT COUNT(*) c FROM orders WHERE status NOT IN ('completed','cancelled')"),
            "total_orders": one("SELECT COUNT(*) c FROM orders"),
            "open_claims": one("SELECT COUNT(*) c FROM claims WHERE status NOT IN ('resolved','rejected')"),
            "studios": one("SELECT COUNT(*) c FROM users WHERE role='studio'"),
            "rolls_in_stock": one("SELECT COUNT(*) c FROM inventory WHERE status='in_stock'"),
            "rolls_assigned": one("SELECT COUNT(*) c FROM inventory WHERE status='assigned'"),
        }
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Initialized database at {DB_PATH}")
