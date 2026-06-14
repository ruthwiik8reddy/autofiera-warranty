"""
PythonAnywhere WSGI config for X-PPF.

HOW TO USE
----------
1. In the PythonAnywhere "Web" tab, open the WSGI configuration file link
   (it looks like /var/www/USERNAME_pythonanywhere_com_wsgi.py).
2. Delete everything in it and paste THIS file's contents.
3. Replace YOURUSERNAME below with your PythonAnywhere username.
4. Paste a long random SECRET_KEY (generate one in a Bash console with:
       python -c "import secrets; print(secrets.token_hex(32))")
5. (Recommended, before the FIRST reload) set a strong admin email + password.
   These are only used the first time the database is created.
6. Save, then click the green "Reload" button on the Web tab.
"""
import os
import sys

# --- path to your project folder on PythonAnywhere ---
PROJECT_HOME = "/home/YOURUSERNAME/autofiera-warranty"
if PROJECT_HOME not in sys.path:
    sys.path.insert(0, PROJECT_HOME)

# --- secrets / config (set these before the first reload) ---
os.environ["SECRET_KEY"] = "PASTE_A_LONG_RANDOM_STRING_HERE"

# Optional but recommended: strong admin login created on first launch only.
# os.environ["XPPF_ADMIN_EMAIL"] = "you@yourdomain.com"
# os.environ["XPPF_ADMIN_PASSWORD"] = "use-a-strong-password"

# Optional: keep the database on an explicit persistent path.
# os.environ["XPPF_DB_PATH"] = PROJECT_HOME + "/xppf.db"

from app import app as application  # noqa: E402
