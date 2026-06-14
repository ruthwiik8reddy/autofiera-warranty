# Deploying X-PPF on PythonAnywhere

A single-studio-friendly, data-safe deploy. Your SQLite database and uploaded
photos live on PythonAnywhere's persistent filesystem, so they survive restarts.
HTTPS is included on your `*.pythonanywhere.com` address (needed for the PWA
install and the camera roll-scanner).

## 1. Create the account
Sign up for a free "Beginner" account at https://www.pythonanywhere.com

## 2. Get the code onto PythonAnywhere
Open a **Bash console** (Consoles tab) and clone your repo:

    git clone https://github.com/ruthwiik8reddy/autofiera-warranty.git
    cd autofiera-warranty

(If you'd rather not use git, upload the zip via the Files tab and unzip it.)

## 3. Create a virtualenv + install deps

    mkvirtualenv --python=/usr/bin/python3.10 xppf
    pip install -r requirements.txt

(The app only needs Flask + Werkzeug. Any Python 3.10+ on PythonAnywhere is fine.)

Generate a secret key now and copy it for the next step:

    python -c "import secrets; print(secrets.token_hex(32))"

## 4. Create the web app
- Go to the **Web** tab -> **Add a new web app** -> **Manual configuration**
  (NOT the "Flask" wizard) -> pick **Python 3.10**.
- **Virtualenv** (Web tab): enter `xppf` (or the full path
  `/home/YOURUSERNAME/.virtualenvs/xppf`).
- **Working directory** / **Source code**: `/home/YOURUSERNAME/autofiera-warranty`

## 5. Point the WSGI file at the app
- On the Web tab, click the **WSGI configuration file** link.
- Delete its contents and paste the contents of `wsgi_pythonanywhere.py`
  from this project.
- Replace `YOURUSERNAME`, paste your `SECRET_KEY`, and (recommended) uncomment
  and set `XPPF_ADMIN_EMAIL` + `XPPF_ADMIN_PASSWORD` so your admin login is
  strong from the very first launch. Save.

## 6. Serve static files efficiently (the video frames)
On the Web tab, under **Static files**, add a mapping:

    URL:        /static/
    Directory:  /home/YOURUSERNAME/autofiera-warranty/static/

This lets PythonAnywhere serve the ~12 MB of scrub frames/videos directly,
keeping the app fast.

## 7. Reload + visit
Click the green **Reload** button, then open
`https://YOURUSERNAME.pythonanywhere.com`.

Log in with the admin credentials you set (or the defaults
`admin@xppf.com` / `xppf-admin` if you didn't set the env vars — change these
immediately by setting the env vars and redeploying with a fresh database).

## Updating later
After pushing changes to GitHub:

    workon xppf
    cd ~/autofiera-warranty
    git pull
    pip install -r requirements.txt   # only if deps changed

Then click **Reload** on the Web tab.

## Notes
- **Persistence:** `xppf.db` and `static/uploads/` are on the persistent disk; do
  not delete them. `.gitignore` already keeps them out of git, so `git pull`
  will not overwrite your live data.
- **Custom domain** (e.g. app.xppf.com) requires a paid PythonAnywhere plan.
- **Outgrowing it:** when you have many studios / heavy concurrent use, migrate
  to managed Postgres (Neon/Supabase) + object storage (Cloudflare R2/S3) on
  Render/Fly/Railway. The app's data layer is isolated in `db.py`, so it's a
  swap, not a rewrite.
