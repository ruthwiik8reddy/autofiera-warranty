# Autofiera — Warranty & Orders Platform

A self-contained Flask app for selling PPF, registering warranties, approving them,
receiving work orders, and handling warranty claims. Styled in the Autofiera
dark-gold design language; the warranty certificate mirrors the XPEL layout in your
own branding and prints to PDF.

## Run

```bash
pip install -r requirements.txt
python app.py
# open http://127.0.0.1:5055
```

The database (`autofiera.db`, SQLite) and tables are created automatically on first run.

### Seeded logins — change these after first login
| Role     | Email                 | Password   |
|----------|-----------------------|------------|
| Admin    | admin@autofiera.com   | autofiera  |
| Customer | vivek@example.com     | customer   |

The admin password lives in `db._seed()`. Change it, or just sign in and create
your own admin row, then delete the seed.

## What's included

**Customer / installer side**
- **Products** — browse PPF & coating packages and place an order.
- **Register Warranty** — customer + vehicle details, VIN, product, **film roll ID**,
  a **part checklist** (Hood, Doors, Roof, Bumpers, Mirrors, etc.), and **photo upload**.
  Submits as `pending`.
- **My Warranties / Orders / Claims** + a dashboard.
- **Warranty Certificate** — XPEL-style certificate, printable to PDF (only after approval).
- **File a Claim** — pick the affected part, describe the issue, upload photos.

**Admin side (you only — `/admin`, gated by `admin_required`)**
- **Dashboard** — KPIs + pending-verification queue.
- **Warranties** — review roll ID + photos, then **Verify & Approve** (issues a
  warranty number `AF-9xxxx` and computes the expiry from the product's warranty term)
  or **Reject** with a note.
- **Work Orders** — every order customers place, with status updates
  (received → scheduled → in progress → completed / cancelled).
- **Claims** — view claim photos, change status, leave a note for the customer.
- **Catalog** — add products and show/hide them.

## Structure

```
app.py        Flask routes, auth decorators, file uploads
db.py         SQLite schema, queries, password hashing, seed data
templates/    Jinja2 templates (extend base.html)
static/css/   tokens.css (design tokens) + app.css (UI)
static/uploads/   uploaded photos (created at runtime)
```

## Security notes before going live
- Set a real `SECRET_KEY` env var; turn off `debug=True`.
- Change the seeded admin credentials.
- The `/uploads/<file>` route is `login_required`; tighten to owner/admin if you
  store sensitive images, and move uploads out of `static/` or behind signed URLs.
- Add CSRF protection (Flask-WTF) to the state-changing forms.
- This uses SQLite for zero-setup. To match your main stack, the queries are plain
  parameterized SQL and port cleanly to `psycopg2` / Postgres — swap `db.get_conn()`
  and the `?` placeholders for `%s`.
```
