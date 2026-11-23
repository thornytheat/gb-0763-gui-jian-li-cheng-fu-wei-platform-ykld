"""Evidence issuance.

A batch can accrue several received originals over time (the same telegram
re-sent with a different column order or UTC-offset spelling).  Issuing pins the
set of originals that existed at issuance; later deliveries join the batch
without changing the sealed sheet, and the saved sheet keeps verifying against
its pinned originals.
"""

import json

from app.archive.save import origins, retrieve
from app.errors import TrackError
from app.manifest import canonical
from .packet import fingerprint, packet


def _received(archive, run_id):
    return origins(archive, run_id)['origins']


def _pin(listed):
    return canonical(sorted(item['input_sha256'] for item in listed))


def _document(archive, run_id, pin):
    keep = set(json.loads(pin))
    listed = [item for item in _received(archive, run_id) if item['input_sha256'] in keep]
    return packet(retrieve(archive, run_id), listed)


def issue(archive, run_id):
    pin = _pin(_received(archive, run_id))
    seal = fingerprint(_document(archive, run_id, pin))
    with archive.transaction() as db:
        created = db.execute('INSERT OR IGNORE INTO issues (run_id, seal, originals) VALUES (?, ?, ?)',
                             (run_id, seal, pin)).rowcount
        committed = db.execute('SELECT seal FROM issues WHERE run_id=?', (run_id,)).fetchone()[0]
    return {'run_id': run_id, 'seal': committed, 'reused': not bool(created), 'issued': True}


def verified(archive, run_id):
    with archive.transaction() as db:
        saved = db.execute('SELECT seal, originals FROM issues WHERE run_id=?', (run_id,)).fetchone()
    if saved is None:
        raise TrackError('NOT_ISSUED', 409)
    document = _document(archive, run_id, saved[1])
    return {'seal': saved[0], 'verified': saved[0] == fingerprint(document), 'evidence': document}
