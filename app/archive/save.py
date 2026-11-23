from datetime import datetime, timezone
import json
from time import perf_counter

from app.config import GAP_SECONDS, LATE_SECONDS, MERGE_MM, REVISION
from app.capture.scan import scan
from app.errors import TrackError
from app.manifest import canonical, digest
from app.pipeline import inspect
from app.anchors.register import survey_book
from .identity import attribution_sha256, crosswalk


def retrieve(archive, run_id):
    with archive.transaction() as db:
        record = db.execute('SELECT payload FROM runs WHERE id=?', (run_id,)).fetchone()
    if record is None:
        raise TrackError('RUN_MISSING', 404)
    return json.loads(record[0])


def _summary(evidence):
    return {key: evidence['coverage'][key] for key in ('planned_mm', 'mapped_mm', 'missing_mm', 'overlap_mm')}


def replay(archive, raw):
    """Attribute one received document to a batch and register it.

    The batch key is the normalized acceptance and isolation conclusions, not
    the bytes that carried them: a re-issued telegram whose columns moved, whose
    UTC offset was spelled differently, or whose rows shifted keeps its batch.
    The document itself is registered under its own digest, so several received
    originals can belong to one batch without duplicating the issuance.
    """
    started = perf_counter()
    survey = survey_book()
    evidence = inspect(raw, survey=survey)
    parameters = {'gap_s': GAP_SECONDS, 'late_s': LATE_SECONDS, 'merge_mm': MERGE_MM}
    identity = {'attribution_sha256': attribution_sha256(evidence['capture']),
                'survey_sha256': digest(canonical(survey)),
                'revision': REVISION, 'parameters': parameters}
    run_id = digest(canonical(identity))
    input_sha256 = digest(raw)
    manifest = dict(identity, run_id=run_id, input_sha256=input_sha256,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    elapsed_ms=round((perf_counter() - started) * 1000), summary=_summary(evidence))
    payload = canonical({'manifest': manifest, 'stages': evidence})
    received_at = datetime.now(timezone.utc).isoformat()
    with archive.transaction() as db:
        inserted = db.execute('INSERT OR IGNORE INTO runs VALUES (?, ?)',
                              (run_id, payload)).rowcount
        db.execute('INSERT OR IGNORE INTO origins VALUES (?, ?, ?, ?)',
                   (run_id, input_sha256, received_at, raw))
        previous = db.execute('SELECT payload FROM runs WHERE id=?', (run_id,)).fetchone()[0]
    return dict(json.loads(previous)['manifest'], reused=not bool(inserted), origin_sha256=input_sha256)


def origins(archive, run_id):
    """The received originals of one batch, each with its line crosswalk.

    Evidence conclusions cite the snapshot's line numbers.  The crosswalk maps
    those onto the rows of every original that arrived, so a checker can open
    the document actually received and point at the right line.
    """
    snapshot = retrieve(archive, run_id)
    with archive.transaction() as db:
        rows = db.execute('SELECT input_sha256, received_at, raw FROM origins '
                          'WHERE run_id=? ORDER BY rowid', (run_id,)).fetchall()
    documents = []
    for input_sha256, received_at, raw in rows:
        delivery = scan(bytes(raw))
        documents.append({'input_sha256': input_sha256, 'received_at': received_at,
                          'input_rows': delivery['input_rows'],
                          'crosswalk': crosswalk(snapshot['stages']['capture'], delivery)})
    return {'run_id': run_id, 'origins': documents}


def original(archive, run_id, input_sha256):
    with archive.transaction() as db:
        record = db.execute('SELECT raw FROM origins WHERE run_id=? AND input_sha256=?',
                            (run_id, input_sha256)).fetchone()
    if record is None:
        raise TrackError('ORIGIN_MISSING', 404)
    return bytes(record[0])


def recent(archive):
    with archive.transaction() as db:
        rows = db.execute('SELECT payload FROM runs ORDER BY rowid DESC LIMIT 30').fetchall()
    return {'runs': [json.loads(row[0])['manifest'] for row in rows]}
