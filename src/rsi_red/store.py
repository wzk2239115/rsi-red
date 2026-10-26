"""Single-controller SQLite metadata with transactional journals and immutable blobs."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import uuid

from .errors import ResearchError


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "research.sqlite", check_same_thread=False, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL);
        """)
        self.db.commit()

    @contextmanager
    def transaction(self):
        with self.lock:
            outer = not self.db.in_transaction
            if outer:
                self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                if outer:
                    self.db.rollback()
                raise
            else:
                if outer:
                    self.db.commit()

    def create(self, kind, value):
        item = dict(value, id=f"{kind}_{uuid.uuid4().hex}")
        self.save(kind, item)
        return item

    def save(self, kind, item):
        self.db.execute("INSERT INTO entities VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                        (item["id"], kind, encoded(item)))

    def get(self, item_id, kind=None):
        row = self.db.execute("SELECT kind,body FROM entities WHERE id=?", (item_id,)).fetchone()
        if row is None or (kind and row[0] != kind):
            raise ResearchError("NOT_FOUND", "Entity not found")
        return json.loads(row[1])

    def list(self, kind):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT body FROM entities WHERE kind=? ORDER BY rowid", (kind,))]

    def event(self, event_type, entity, actor, now):
        value = {"type": event_type, "entity_id": entity["id"],
                 "campaign_id": entity.get("campaign_id", entity["id"] if event_type.startswith("campaign.") else None),
                 "author": actor, "time": now}
        self.db.execute("INSERT INTO events(body) VALUES(?)", (encoded(value),))

    def events(self, campaign, after=None, limit=100):
        try:
            cursor = int(after) if after else 0
        except (TypeError, ValueError):
            raise ResearchError("INVALID_ARGUMENT", "Invalid event cursor") from None
        result = []
        for seq, body in self.db.execute("SELECT seq,body FROM events WHERE seq>? ORDER BY seq", (cursor,)):
            row = json.loads(body)
            if row["campaign_id"] == campaign:
                result.append(dict(row, id=str(seq)))
                if len(result) >= limit:
                    break
        return result

    def blob(self, content):
        key = hashlib.sha256(content).hexdigest()
        folder = self.root / "blobs"
        folder.mkdir(exist_ok=True)
        path = folder / key
        if not path.exists():
            temporary = folder / (key + "." + uuid.uuid4().hex)
            with temporary.open("wb") as stream:
                stream.write(content)
                stream.flush()
                __import__("os").fsync(stream.fileno())
            temporary.replace(path)
        return key

    def read_blob(self, key):
        path = self.root / "blobs" / key
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != key:
            raise ResearchError("CHECKSUM_MISMATCH", "Stored content is corrupted")
        return content

    def __del__(self):
        # Python 3.13 warns on unclosed SQLite connections; own their lifetime explicitly.
        if hasattr(self, "db"):
            self.db.close()

    def close(self):
        with self.lock:
            self.db.close()
