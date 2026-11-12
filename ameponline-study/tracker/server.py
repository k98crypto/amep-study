import base64
import hashlib
import json
import re
import secrets
import sqlite3
import time
from datetime import date, datetime, timezone
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit


DB_PATH = "/data/progress.sqlite3"
WEB_ROOT = Path("/app")
SESSION_COOKIE = "AMEPSID"
SESSION_SECONDS = 60 * 60 * 24 * 30
PASSWORD_ROUNDS = 310_000
MAX_ACCOUNTS = 5
ALLOWED_HOSTS = {"lwa.spiritwave.dpdns.org", "study.spiritwave.dpdns.org"}
STATUSES = {"未开始", "学习中", "已完成"}
CACHEABLE_ASSETS = {"/auth.css", "/auth.js", "/style.css", "/app.js"}


def connect_db():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    return db


def create_records_table(db):
    db.execute(
        """CREATE TABLE records (
            id INTEGER PRIMARY KEY,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            course TEXT NOT NULL,
            activity TEXT NOT NULL,
            status TEXT NOT NULL,
            progress INTEGER NOT NULL,
            last_studied TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'manual',
            updated_at TEXT NOT NULL,
            UNIQUE(account_id, course, activity)
        )"""
    )


def initialize_db():
    Path("/data").mkdir(parents=True, exist_ok=True)
    with connect_db() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                recovery_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        db.execute(
            "INSERT OR IGNORE INTO accounts (id, username, password_hash, recovery_hash, created_at) "
            "VALUES (0, '__legacy__', '', '', '')"
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            )"""
        )

        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='records'").fetchone()
        if not table:
            create_records_table(db)
        else:
            columns = {row[1] for row in db.execute("PRAGMA table_info(records)")}
            if "account_id" not in columns:
                db.execute("ALTER TABLE records RENAME TO records_legacy")
                create_records_table(db)
                db.execute(
                    """INSERT INTO records (id, account_id, course, activity, status, progress,
                       last_studied, notes, source, updated_at)
                       SELECT id, 0, course, activity, status, progress, last_studied,
                              notes, source, updated_at FROM records_legacy"""
                )
                db.execute("DROP TABLE records_legacy")
        db.execute("CREATE INDEX IF NOT EXISTS records_account_idx ON records(account_id, last_studied)")


def hash_secret(secret, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, PASSWORD_ROUNDS)
    return f"{base64.urlsafe_b64encode(salt).decode()}:{base64.urlsafe_b64encode(digest).decode()}"


def verify_secret(secret, stored):
    try:
        salt_text, digest_text = stored.split(":", 1)
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, PASSWORD_ROUNDS)
    return secrets.compare_digest(actual, expected)


def clean_text(value, limit):
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    return " ".join("".join(ch for ch in value if ch >= " " or ch in "\n\t").split())[:limit]


def normalize_record(item, source="manual"):
    if not isinstance(item, dict):
        raise ValueError("Each record must be an object")
    course = clean_text(item.get("course"), 180)
    activity = clean_text(item.get("activity"), 180) or "课程进度"
    if not course:
        raise ValueError("Course name is required")

    raw_status = clean_text(item.get("status"), 40).lower()
    if raw_status in {"completed", "complete", "done", "finished", "已完成", "完成"}:
        status = "已完成"
    elif raw_status in {"in progress", "started", "学习中", "进行中"}:
        status = "学习中"
    else:
        status = "未开始"
    if raw_status in STATUSES:
        status = raw_status

    try:
        progress = max(0, min(100, int(float(item.get("progress", 100 if status == "已完成" else 0)))))
    except (TypeError, ValueError, OverflowError):
        progress = 100 if status == "已完成" else 0
    if status == "已完成":
        progress = 100
    if progress == 100:
        status = "已完成"
    elif progress > 0 and status == "未开始":
        status = "学习中"

    studied = clean_text(item.get("lastStudied"), 10)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", studied):
        studied = date.today().isoformat()
    try:
        date.fromisoformat(studied)
    except ValueError:
        studied = date.today().isoformat()

    return {
        "course": course,
        "activity": activity,
        "status": status,
        "progress": progress,
        "lastStudied": studied,
        "notes": clean_text(item.get("notes"), 1000),
        "source": source,
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def read_records(account_id):
    with connect_db() as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT id, course, activity, status, progress, last_studied, notes, source, updated_at "
            "FROM records WHERE account_id=? "
            "ORDER BY last_studied DESC, course COLLATE NOCASE, activity COLLATE NOCASE",
            (account_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "course": row["course"],
            "activity": row["activity"],
            "status": row["status"],
            "progress": row["progress"],
            "lastStudied": row["last_studied"],
            "notes": row["notes"],
            "source": row["source"],
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]


def save_records(account_id, records):
    with connect_db() as db:
        db.executemany(
            """INSERT INTO records (account_id, course, activity, status, progress, last_studied, notes, source, updated_at)
               VALUES (:account_id, :course, :activity, :status, :progress, :lastStudied, :notes, :source, :updatedAt)
               ON CONFLICT(account_id, course, activity) DO UPDATE SET
                 status=excluded.status,
                 progress=excluded.progress,
                 last_studied=excluded.last_studied,
                 notes=excluded.notes,
                 source=excluded.source,
                 updated_at=excluded.updated_at""",
            [{**record, "account_id": account_id} for record in records],
        )


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self):
        path = urlsplit(self.path).path
        cache_control = "public, max-age=300" if self.command in {"GET", "HEAD"} and path in CACHEABLE_ASSETS else "no-store"
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def log_message(self, _format, *args):
        return

    def is_local_loopback_host(self):
        host = self.headers.get("Host", "").split(":", 1)[0].lower()
        return host in {"localhost", "127.0.0.1"}

    def session_cookie_attributes(self, max_age):
        attributes = f"Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"
        if not self.is_local_loopback_host():
            attributes += "; Domain=spiritwave.dpdns.org; Secure"
        return attributes

    def send_json(self, payload, status=200, cookie=None, clear_cookie=False):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}={cookie}; {self.session_cookie_attributes(SESSION_SECONDS)}",
            )
        if clear_cookie:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}=; {self.session_cookie_attributes(0)}",
            )
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size < 1 or size > 2_000_000:
            raise ValueError("Request body must be between 1 byte and 2 MB")
        return json.loads(self.rfile.read(size))

    def check_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlsplit(origin)
        request_host = self.headers.get("Host", "").lower()
        if self.is_local_loopback_host():
            return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"} and parsed.netloc.lower() == request_host
        return parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS

    def current_session(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie[SESSION_COOKIE].value
        except (KeyError, ValueError):
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with connect_db() as db:
            row = db.execute(
                """SELECT accounts.id, accounts.username FROM sessions
                   JOIN accounts ON accounts.id=sessions.account_id
                   WHERE sessions.token_hash=? AND sessions.expires_at>?""",
                (token_hash, int(time.time())),
            ).fetchone()
        return {"id": row[0], "username": row[1]} if row else None

    def new_session(self, account_id):
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with connect_db() as db:
            db.execute(
                "INSERT INTO sessions (token_hash, account_id, expires_at) VALUES (?, ?, ?)",
                (token_hash, account_id, int(time.time()) + SESSION_SECONDS),
            )
        return token

    def require_user(self):
        user = self.current_session()
        if not user:
            self.send_json({"error": "Please sign in"}, 401)
            return None
        return user

    def send_login_redirect(self):
        host = self.headers.get("X-Forwarded-Host", "").split(":", 1)[0].lower()
        uri = self.headers.get("X-Forwarded-Uri", "/")
        if host not in ALLOWED_HOSTS:
            host, uri = "study.spiritwave.dpdns.org", "/"
        next_url = f"https://{host}{uri}"
        location = "https://study.spiritwave.dpdns.org/login?next=" + quote(next_url, safe="")
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/auth/check":
            if self.current_session():
                self.send_response(204)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
            else:
                self.send_login_redirect()
            return
        if path == "/api/auth/me":
            user = self.current_session()
            self.send_json({"authenticated": bool(user), "username": user["username"] if user else None})
            return
        if path in {"/login", "/register", "/forgot"}:
            self.path = "/auth.html"
            super().do_GET()
            return
        if path == "/api/records":
            user = self.require_user()
            if user:
                self.send_json({"records": read_records(user["id"])})
            return
        if path == "/api/export":
            user = self.require_user()
            if user:
                self.send_json(
                    {
                        "format": "amep-study-progress-v1",
                        "exportedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "records": read_records(user["id"]),
                    }
                )
            return
        if path == "/api/health":
            self.send_json({"ok": True})
            return
        self.path = "/index.html" if path == "/" else path
        super().do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path
        if not self.check_origin():
            self.send_json({"error": "Request origin is not allowed"}, 403)
            return
        try:
            payload = self.read_json()
            if path == "/api/auth/register":
                username = clean_text(payload.get("username"), 32).lower()
                password = payload.get("password", "")
                if not re.fullmatch(r"[a-z0-9._-]{3,32}", username):
                    raise ValueError("账号需为 3-32 位字母、数字、点、下划线或短横线")
                if not isinstance(password, str) or len(password) < 10 or len(password) > 128:
                    raise ValueError("密码长度需为 10-128 位")
                recovery_code = secrets.token_urlsafe(18)
                try:
                    with connect_db() as db:
                        count = db.execute("SELECT COUNT(*) FROM accounts WHERE id<>0").fetchone()[0]
                        if count >= MAX_ACCOUNTS:
                            raise ValueError("目前不再接受新账号")
                        cursor = db.execute(
                            "INSERT INTO accounts (username, password_hash, recovery_hash, created_at) VALUES (?, ?, ?, ?)",
                            (username, hash_secret(password), hash_secret(recovery_code), datetime.now(timezone.utc).isoformat(timespec="seconds")),
                        )
                        account_id = cursor.lastrowid
                        db.execute("UPDATE records SET account_id=? WHERE account_id=0", (account_id,))
                        db.execute("DELETE FROM accounts WHERE id=0")
                except sqlite3.IntegrityError:
                    raise ValueError("这个账号名称已被使用")
                cookie = self.new_session(account_id)
                self.send_json({"username": username, "recoveryCode": recovery_code}, 201, cookie=cookie)
                return

            if path == "/api/auth/login":
                username = clean_text(payload.get("username"), 32).lower()
                password = payload.get("password", "")
                with connect_db() as db:
                    row = db.execute(
                        "SELECT id, password_hash FROM accounts WHERE username=? AND id<>0",
                        (username,),
                    ).fetchone()
                if not row or not isinstance(password, str) or not verify_secret(password, row[1]):
                    self.send_json({"error": "账号或密码不正确"}, 401)
                    return
                cookie = self.new_session(row[0])
                self.send_json({"username": username}, cookie=cookie)
                return

            if path == "/api/auth/reset":
                username = clean_text(payload.get("username"), 32).lower()
                recovery_code = payload.get("recoveryCode", "")
                password = payload.get("password", "")
                if not isinstance(password, str) or len(password) < 10 or len(password) > 128:
                    raise ValueError("新密码长度需为 10-128 位")
                with connect_db() as db:
                    row = db.execute(
                        "SELECT id, recovery_hash FROM accounts WHERE username=? AND id<>0",
                        (username,),
                    ).fetchone()
                if not row or not isinstance(recovery_code, str) or not verify_secret(recovery_code, row[1]):
                    self.send_json({"error": "账号或恢复码不正确"}, 401)
                    return
                new_recovery_code = secrets.token_urlsafe(18)
                with connect_db() as db:
                    db.execute(
                        "UPDATE accounts SET password_hash=?, recovery_hash=? WHERE id=?",
                        (hash_secret(password), hash_secret(new_recovery_code), row[0]),
                    )
                    db.execute("DELETE FROM sessions WHERE account_id=?", (row[0],))
                self.send_json({"recoveryCode": new_recovery_code})
                return

            if path == "/api/auth/logout":
                cookie = SimpleCookie()
                try:
                    cookie.load(self.headers.get("Cookie", ""))
                    token = cookie[SESSION_COOKIE].value
                    token_hash = hashlib.sha256(token.encode()).hexdigest()
                    with connect_db() as db:
                        db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
                except (KeyError, ValueError):
                    pass
                self.send_json({"ok": True}, clear_cookie=True)
                return

            if path == "/api/records":
                user = self.require_user()
                if not user:
                    return
                record = normalize_record(payload)
                save_records(user["id"], [record])
                self.send_json({"record": record}, 201)
                return

            if path == "/api/import":
                user = self.require_user()
                if not user:
                    return
                incoming = payload.get("records") if isinstance(payload, dict) else None
                if not isinstance(incoming, list) or not incoming or len(incoming) > 1000:
                    raise ValueError("Import must contain between 1 and 1000 records")
                records = [normalize_record(item, "AMEPOnline browser import") for item in incoming]
                save_records(user["id"], records)
                self.send_json({"imported": len(records)})
                return
            self.send_json({"error": "Not found"}, 404)
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)
        except Exception:
            self.send_json({"error": "The request could not be saved"}, 500)

    def do_PUT(self):
        if not self.check_origin():
            self.send_json({"error": "Request origin is not allowed"}, 403)
            return
        user = self.require_user()
        if not user:
            return
        match = re.fullmatch(r"/api/records/(\d+)", urlsplit(self.path).path)
        if not match:
            self.send_json({"error": "Not found"}, 404)
            return
        try:
            record = normalize_record(self.read_json())
            with connect_db() as db:
                cursor = db.execute(
                    """UPDATE records SET course=:course, activity=:activity, status=:status,
                       progress=:progress, last_studied=:lastStudied, notes=:notes,
                       source=:source, updated_at=:updatedAt WHERE id=:id AND account_id=:account_id""",
                    {**record, "id": int(match.group(1)), "account_id": user["id"]},
                )
            if cursor.rowcount == 0:
                self.send_json({"error": "Record not found"}, 404)
                return
            self.send_json({"record": record})
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)
        except Exception:
            self.send_json({"error": "The request could not be saved"}, 500)

    def do_DELETE(self):
        if not self.check_origin():
            self.send_json({"error": "Request origin is not allowed"}, 403)
            return
        user = self.require_user()
        if not user:
            return
        match = re.fullmatch(r"/api/records/(\d+)", urlsplit(self.path).path)
        if not match:
            self.send_json({"error": "Not found"}, 404)
            return
        with connect_db() as db:
            cursor = db.execute(
                "DELETE FROM records WHERE id=? AND account_id=?",
                (int(match.group(1)), user["id"]),
            )
        self.send_json({"deleted": cursor.rowcount == 1})


if __name__ == "__main__":
    initialize_db()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
