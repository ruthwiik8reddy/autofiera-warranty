# X-Paint Protection Film (X-PPF) — Warranty Platform

A multi-studio Flask app for issuing and managing PPF / ceramic-coating warranties.
Each studio registers warranties for end clients and can issue each certificate
under **its own brand** or under **X-PPF**.

## Run locally
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5055
```

## Seeded logins (change after first login)
| Role   | Email               | Password    |
|--------|---------------------|-------------|
| Admin  | admin@xppf.com      | xppf-admin  |
| Studio | studio@example.com  | studio      |

There is **no public signup** — the admin creates every account at `/admin/users`
and assigns its role (admin or studio).

## Roles
- **admin** — X-PPF operator: creates accounts, verifies & approves warranties,
  manages work orders, claims and the product catalog.
- **studio** — a detailing studio: sets its name + logo, registers warranties,
  chooses per-warranty branding (own studio vs X-PPF), orders product, files claims.

## Co-branding
On each registration the studio picks **My studio** (its logo + "Authorised X-PPF
installer" on the certificate) or **X-PPF** (X-PPF mark + wording). Studio branding
requires a studio name + logo set on the Studio page first.

## Stack
Flask · SQLite (`xppf.db`) · pbkdf2:sha256 auth · vanilla JS (IntersectionObserver
scroll reveals, coverage picker). Apple-clean light UI. Queries port cleanly to
Postgres (swap `?` → `%s`).

## Before production
- Set a real `SECRET_KEY` env var and disable debug.
- Change the seeded admin password (`db._seed`).
- Add CSRF protection (Flask-WTF) and owner-scope the `/uploads/<file>` route.
