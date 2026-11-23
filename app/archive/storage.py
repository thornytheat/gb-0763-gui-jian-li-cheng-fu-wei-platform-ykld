from contextlib import contextmanager
from pathlib import Path
import sqlite3


class TrackArchive:
    def __init__(self, filename):
        self.file = Path(filename)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload BLOB NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS issues (run_id TEXT PRIMARY KEY REFERENCES runs(id), seal TEXT NOT NULL)')
            columns = {row[1] for row in db.execute('PRAGMA table_info(issues)')}
            if 'originals' not in columns:
                db.execute("ALTER TABLE issues ADD COLUMN originals TEXT NOT NULL DEFAULT '[]'")
            db.execute('CREATE TABLE IF NOT EXISTS origins '
                       '(run_id TEXT NOT NULL REFERENCES runs(id), input_sha256 TEXT NOT NULL, '
                       'received_at TEXT NOT NULL, raw BLOB NOT NULL, PRIMARY KEY (run_id, input_sha256))')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.file, timeout=15)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()
