"""
app.py — Autofiera Warranty & Orders platform.

Run:
    pip install -r requirements.txt
    python app.py
    # open http://127.0.0.1:5055

Seeded logins (change after first login):
    admin     -> admin@autofiera.com / autofiera
    customer  -> vivek@example.com   / customer

Features
--------
  Public      : landing, login, signup
  Customer    : browse + order products, register warranties, view certificates,
                file warranty claims, track own orders/warranties/claims
  Admin (you) : dashboard, verify & approve/reject warranty registrations,
                receive & manage work orders, manage claims, manage products
"""

import os
import uuid
from functools import wraps
from datetime import datetime

from flask import (
    Flask, request, session, redirect, url_for, render_template,
    flash, abort, send_from_directory,
)
from werkzeug.utils import secure_filename

import db

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif", "heic"}
MAX_CONTENT_MB = 25

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_MB * 1024 * 1024
app.config["UPLOAD_DIR"] = UPLOAD_DIR

os.makedirs(UPLOAD_DIR, exist_ok=True)


# --------------------------------------------------------------------------- #
# Context + helpers
# --------------------------------------------------------------------------- #
@app.context_processor
def inject_globals():
    return {
        "current_user": _current_user(),
        "current_role": session.get("role"),
        "year": datetime.utcnow().year,
        "brand": {
            "name": "Autofiera Detailing Studio",
            "tagline": "Premium Paint Protection",
            "address": "Hyderabad, Telangana, India",
            "email": "warranty@autofiera.com",
            "phone": "+91 00000 00000",
        },
    }


def _current_user():
    uid = session.get("user_id")
    return db.get_user(uid) if uid else None


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to continue.", "info")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        if session.get("role") != "admin":
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def _allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def _save_uploads(file_field):
    """Save all files for a multipart field; return list of stored filenames."""
    saved = []
    for f in request.files.getlist(file_field):
        if f and f.filename and _allowed(f.filename):
            ext = f.filename.rsplit(".", 1)[1].lower()
            fn = f"{uuid.uuid4().hex}.{ext}"
            f.save(os.path.join(app.config["UPLOAD_DIR"], secure_filename(fn)))
            saved.append(fn)
    return saved


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html", products=db.list_products())


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = db.get_user_by_email(request.form.get("email", ""))
        if user and db.verify_password(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session.permanent = True
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["name"] = user["name"]
            dest = request.args.get("next")
            if user["role"] == "admin":
                return redirect(dest or url_for("admin_dashboard"))
            return redirect(dest or url_for("customer_dashboard"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        if not (name and email and password):
            flash("Name, email and password are required.", "error")
        elif db.get_user_by_email(email):
            flash("An account with that email already exists.", "error")
        else:
            uid = db.create_user(name, email, phone, password, role="customer")
            session.clear()
            session["user_id"] = uid
            session["role"] = "customer"
            session["name"] = name
            flash("Welcome to Autofiera.", "success")
            return redirect(url_for("customer_dashboard"))
    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# --------------------------------------------------------------------------- #
# Products + ordering (customer)
# --------------------------------------------------------------------------- #
@app.route("/products")
def products():
    return render_template("products.html", products=db.list_products())


@app.route("/order/<int:product_id>", methods=["GET", "POST"])
@login_required
def order(product_id):
    product = db.get_product(product_id)
    if not product:
        abort(404)
    if request.method == "POST":
        db.create_order(
            user_id=session["user_id"],
            product_id=product["id"],
            product_name=product["name"],
            vehicle_ymm=request.form.get("vehicle_ymm", "").strip(),
            vehicle_color=request.form.get("vehicle_color", "").strip(),
            vin=request.form.get("vin", "").strip(),
            notes=request.form.get("notes", "").strip(),
        )
        flash("Order placed — Autofiera will reach out to schedule your install.", "success")
        return redirect(url_for("my_orders"))
    return render_template("order.html", product=product)


@app.route("/my/orders")
@login_required
def my_orders():
    return render_template("my_orders.html", orders=db.list_orders(user_id=session["user_id"]))


# --------------------------------------------------------------------------- #
# Warranty registration (customer / installer)
# --------------------------------------------------------------------------- #
@app.route("/warranty/register", methods=["GET", "POST"])
@login_required
def warranty_register():
    if request.method == "POST":
        parts = request.form.getlist("parts")
        if not parts:
            flash("Select at least one part covered by the PPF.", "error")
            return render_template("warranty_register.html",
                                   parts=db.CAR_PARTS, products=db.list_products(),
                                   form=request.form)
        if not request.form.get("vin"):
            flash("VIN is required.", "error")
            return render_template("warranty_register.html",
                                   parts=db.CAR_PARTS, products=db.list_products(),
                                   form=request.form)

        product = None
        pid = request.form.get("product_id")
        if pid:
            product = db.get_product(int(pid))

        images = _save_uploads("photos")
        data = {
            "user_id": session["user_id"],
            "customer_name": request.form.get("customer_name", "").strip(),
            "customer_phone": request.form.get("customer_phone", "").strip(),
            "customer_email": request.form.get("customer_email", "").strip(),
            "customer_address": request.form.get("customer_address", "").strip(),
            "vin": request.form.get("vin", "").strip().upper(),
            "plate": request.form.get("plate", "").strip(),
            "miles": request.form.get("miles", "").strip(),
            "vehicle_ymm": request.form.get("vehicle_ymm", "").strip(),
            "vehicle_color": request.form.get("vehicle_color", "").strip(),
            "product_id": product["id"] if product else None,
            "product_name": product["name"] if product else request.form.get("product_name", "").strip(),
            "warranty_years": product["warranty_years"] if product else 8,
            "roll_id": request.form.get("roll_id", "").strip(),
        }
        wid = db.create_warranty(data, parts, images)
        flash("Warranty submitted for verification. You'll be notified once Autofiera approves it.", "success")
        return redirect(url_for("warranty_view", warranty_id=wid))

    return render_template("warranty_register.html",
                           parts=db.CAR_PARTS, products=db.list_products(), form={})


@app.route("/my/warranties")
@login_required
def my_warranties():
    return render_template("my_warranties.html",
                           warranties=db.list_warranties(user_id=session["user_id"]))


@app.route("/warranty/<int:warranty_id>")
@login_required
def warranty_view(warranty_id):
    w, coverage, images = db.get_warranty(warranty_id)
    if not w:
        abort(404)
    # access control: owner or admin
    if session.get("role") != "admin" and w["user_id"] != session["user_id"]:
        abort(403)
    return render_template("warranty_certificate.html", w=w, coverage=coverage, images=images)


# --------------------------------------------------------------------------- #
# Warranty claims (customer)
# --------------------------------------------------------------------------- #
@app.route("/claim/<int:warranty_id>", methods=["GET", "POST"])
@login_required
def claim(warranty_id):
    w, coverage, _ = db.get_warranty(warranty_id)
    if not w:
        abort(404)
    if session.get("role") != "admin" and w["user_id"] != session["user_id"]:
        abort(403)
    if w["status"] != "approved":
        flash("Claims can only be filed against an approved warranty.", "error")
        return redirect(url_for("warranty_view", warranty_id=warranty_id))

    if request.method == "POST":
        desc = request.form.get("description", "").strip()
        if not desc:
            flash("Please describe the issue you're claiming for.", "error")
        else:
            images = _save_uploads("photos")
            db.create_claim(
                warranty_id=warranty_id,
                user_id=session["user_id"],
                affected_part=request.form.get("affected_part", "").strip(),
                description=desc,
                image_filenames=images,
            )
            flash("Claim submitted. Autofiera will review it shortly.", "success")
            return redirect(url_for("my_claims"))

    return render_template("warranty_claim.html", w=w, coverage=coverage)


@app.route("/my/claims")
@login_required
def my_claims():
    claims = db.list_claims(user_id=session["user_id"])
    images = {c["id"]: db.get_claim_images(c["id"]) for c in claims}
    return render_template("my_claims.html", claims=claims, images=images)


# --------------------------------------------------------------------------- #
# Customer dashboard
# --------------------------------------------------------------------------- #
@app.route("/dashboard")
@login_required
def customer_dashboard():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))
    uid = session["user_id"]
    return render_template(
        "customer_dashboard.html",
        warranties=db.list_warranties(user_id=uid),
        orders=db.list_orders(user_id=uid),
        claims=db.list_claims(user_id=uid),
    )


# --------------------------------------------------------------------------- #
# Admin
# --------------------------------------------------------------------------- #
@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template(
        "admin_dashboard.html",
        counts=db.admin_counts(),
        pending=db.list_warranties(status="pending"),
        recent_orders=db.list_orders()[:6],
    )


@app.route("/admin/warranties")
@admin_required
def admin_warranties():
    status = request.args.get("status")  # None = all
    return render_template(
        "admin_warranties.html",
        warranties=db.list_warranties(status=status),
        active_status=status,
    )


@app.route("/admin/warranty/<int:warranty_id>/approve", methods=["POST"])
@admin_required
def admin_approve(warranty_id):
    db.approve_warranty(warranty_id, admin_note=request.form.get("admin_note", "").strip())
    flash(f"Warranty #{warranty_id} approved and certificate issued.", "success")
    return redirect(request.referrer or url_for("admin_warranties"))


@app.route("/admin/warranty/<int:warranty_id>/reject", methods=["POST"])
@admin_required
def admin_reject(warranty_id):
    db.reject_warranty(warranty_id, admin_note=request.form.get("admin_note", "").strip())
    flash(f"Warranty #{warranty_id} rejected.", "info")
    return redirect(request.referrer or url_for("admin_warranties"))


@app.route("/admin/orders")
@admin_required
def admin_orders():
    return render_template("admin_orders.html", orders=db.list_orders())


@app.route("/admin/order/<int:order_id>/status", methods=["POST"])
@admin_required
def admin_order_status(order_id):
    db.update_order_status(order_id, request.form.get("status", "received"))
    flash("Work order updated.", "success")
    return redirect(url_for("admin_orders"))


@app.route("/admin/claims")
@admin_required
def admin_claims():
    claims = db.list_claims()
    images = {c["id"]: db.get_claim_images(c["id"]) for c in claims}
    return render_template("admin_claims.html", claims=claims, images=images)


@app.route("/admin/claim/<int:claim_id>/status", methods=["POST"])
@admin_required
def admin_claim_status(claim_id):
    db.update_claim_status(claim_id, request.form.get("status", "under_review"),
                           admin_note=request.form.get("admin_note", "").strip())
    flash("Claim updated.", "success")
    return redirect(url_for("admin_claims"))


@app.route("/admin/products", methods=["GET", "POST"])
@admin_required
def admin_products():
    if request.method == "POST":
        db.create_product(
            name=request.form.get("name", "").strip(),
            category=request.form.get("category", "PPF").strip(),
            tagline=request.form.get("tagline", "").strip(),
            description=request.form.get("description", "").strip(),
            price=float(request.form.get("price") or 0),
            warranty_years=int(request.form.get("warranty_years") or 8),
        )
        flash("Product added.", "success")
        return redirect(url_for("admin_products"))
    return render_template("admin_products.html", products=db.list_products(active_only=False))


@app.route("/admin/product/<int:product_id>/toggle", methods=["POST"])
@admin_required
def admin_product_toggle(product_id):
    p = db.get_product(product_id)
    if p:
        db.set_product_active(product_id, not p["active"])
    return redirect(url_for("admin_products"))


# --------------------------------------------------------------------------- #
# Uploaded file serving (explicit route so it's easy to lock down later)
# --------------------------------------------------------------------------- #
@app.route("/uploads/<path:filename>")
@login_required
def uploads(filename):
    return send_from_directory(app.config["UPLOAD_DIR"], filename)


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, msg="You don't have access to that page."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, msg="Page not found."), 404


if __name__ == "__main__":
    db.init_db()
    app.run(host="127.0.0.1", port=5055, debug=True)
