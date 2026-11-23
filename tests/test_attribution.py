import csv
import io
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.archive.save import origins, recent, replay
from app.capture.dialect import FIELDS
from app.inputs import sample
from app.manifest import digest


def _spell(moment, offset):
    """Re-spell one instant with the given UTC offset, keeping the instant."""
    sign = -1 if offset.startswith('-') else 1
    hours, minutes = (int(part) for part in offset.lstrip('+-').split(':'))
    return moment.astimezone(timezone(sign * timedelta(hours=hours, minutes=minutes))).isoformat()


def rewrite(raw, order=FIELDS, offset='+00:00', extra_header=False, extra_rows=(), shift=None):
    """Re-emit a telegram with different column order / offset spelling.

    ``offset`` only changes how the instant is written; pass ``shift`` to move
    the event in time, producing a genuinely different inspection.
    """
    text = raw.decode('utf-8-sig')
    reader = csv.reader(io.StringIO(text, newline=''), strict=True)
    header = tuple(next(reader))
    body = io.StringIO()
    writer = csv.writer(body, lineterminator='\n')
    writer.writerow(order)
    if extra_header:
        writer.writerow(order)
    for row in reader:
        if tuple(row) == header:
            writer.writerow(order)
            continue
        if len(row) != len(header):
            writer.writerow(row)
            continue
        values = dict(zip(header, row))
        try:
            moment = datetime.fromisoformat(values['at'])
        except ValueError:
            pass
        else:
            moment = moment.astimezone(timezone.utc) + (shift or timedelta())
            values['at'] = _spell(moment, offset)
        writer.writerow([values[key] for key in order])
    for row in extra_rows:
        writer.writerow(row)
    return body.getvalue().encode('utf-8')


def test_reordered_columns_keep_batch(archive_app):
    archive = archive_app.track_archive
    first = replay(archive, sample('clean'))
    order = ('grade', 'ref', 'odo_mm', 'at', 'kind', 'run', 'event_id')
    second = replay(archive, rewrite(sample('clean'), order=order))
    assert second['run_id'] == first['run_id']
    assert second['reused'] is True


def test_offset_spelling_keeps_batch(archive_app):
    archive = archive_app.track_archive
    first = replay(archive, sample('clean'))
    second = replay(archive, rewrite(sample('clean'), offset='-05:00'))
    assert (second['run_id'], second['reused']) == (first['run_id'], True)


def test_moved_instant_is_a_different_batch(archive_app):
    archive = archive_app.track_archive
    first = replay(archive, sample('clean'))
    other = replay(archive, rewrite(sample('clean'), shift=timedelta(hours=1)))
    assert other['run_id'] != first['run_id']
    assert other['reused'] is False


def test_resend_registers_second_original(archive_app):
    archive = archive_app.track_archive
    first = replay(archive, sample('clean'))
    resent = rewrite(sample('clean'), extra_header=True)
    second = replay(archive, resent)
    listed = origins(archive, first['run_id'])['origins']
    assert second['run_id'] == first['run_id']
    assert [item['input_sha256'] for item in listed] == [digest(sample('clean')), digest(resent)]
    assert len({item['input_sha256'] for item in listed}) == 2


def test_crosswalk_points_at_received_line(archive_app):
    archive = archive_app.track_archive
    first = replay(archive, sample('clean'))
    resent = rewrite(sample('clean'), extra_header=True)
    replay(archive, resent)
    listed = origins(archive, first['run_id'])['origins']
    shifted = next(item for item in listed if item['input_sha256'] == digest(resent))
    # The repeated header pushes every data row down by one.
    assert shifted['crosswalk']['2'] == 3
    assert shifted['crosswalk']['13'] == 14


def test_different_isolation_is_a_different_batch(archive_app):
    archive = archive_app.track_archive
    base = replay(archive, sample('clean'))
    # Same accepted rows, but an extra unparseable telegram is now isolated.
    noisy = rewrite(sample('clean'), extra_rows=[('bad', 'R7', 'defect', '2026-11-22T00:00:30Z',
                                                  'oops', '擦伤', '2')])
    other = replay(archive, noisy)
    assert other['run_id'] != base['run_id']
    assert other['reused'] is False


def test_rerun_is_not_a_new_archive(archive_app):
    archive = archive_app.track_archive
    raw = sample('clean')
    replay(archive, raw)
    replay(archive, raw)
    listed = origins(archive, replay(archive, raw)['run_id'])['origins']
    assert len(listed) == 1


def test_failure_can_be_retried(archive_app):
    archive = archive_app.track_archive
    with archive.transaction() as db:
        db.execute("CREATE TRIGGER fail_origin BEFORE INSERT ON origins BEGIN SELECT RAISE(ABORT, 'fault'); END")
    with pytest.raises(sqlite3.IntegrityError):
        replay(archive, sample('clean'))
    assert recent(archive) == {'runs': []}
    with archive.transaction() as db:
        db.execute('DROP TRIGGER fail_origin')
    result = replay(archive, sample('clean'))
    assert result['reused'] is False
    assert [item['input_sha256'] for item in origins(archive, result['run_id'])['origins']] == [digest(sample('clean'))]


def test_issued_sheet_still_verifies_after_resend(client):
    run_id = client.post('/api/runs', json={'sample': 'clean'}).json['run_id']
    seal = client.post(f'/api/runs/{run_id}/issue').json['seal']
    resent = rewrite(sample('clean'), offset='+00:00').decode('utf-8')
    joined = client.post('/api/runs', json={'csv': resent}).json
    assert (joined['run_id'], joined['reused']) == (run_id, True)
    checked = client.get(f'/api/runs/{run_id}/export').json
    assert checked['verified'] is True
    assert checked['seal'] == seal
    assert len(checked['evidence']['originals']) == 1


def test_issue_after_resend_cites_every_original(client):
    first = client.post('/api/runs', json={'sample': 'clean'}).json
    resent = rewrite(sample('clean'), extra_header=True)
    client.post('/api/runs', json={'csv': resent.decode('utf-8')})
    client.post(f"/api/runs/{first['run_id']}/issue")
    evidence = client.get(f"/api/runs/{first['run_id']}/export").json
    assert evidence['verified'] is True
    originals = evidence['evidence']['originals']
    assert len(originals) == 2
    shifted = next(item for item in originals if item['input_sha256'] == digest(resent))
    assert shifted['crosswalk']['2'] == 3


def test_original_download_returns_received_bytes(client):
    first = client.post('/api/runs', json={'sample': 'clean'}).json
    resent = rewrite(sample('clean'), extra_header=True)
    client.post('/api/runs', json={'csv': resent.decode('utf-8')})
    listed = client.get(f"/api/runs/{first['run_id']}/origins").json['origins']
    target = next(item for item in listed if item['input_sha256'] == digest(resent))
    response = client.get(f"/api/runs/{first['run_id']}/origins/{target['input_sha256']}")
    assert response.status_code == 200
    assert response.data == resent
    assert response.headers['Content-Disposition'].startswith('attachment;')


def test_unknown_original_is_reported(client):
    run_id = client.post('/api/runs', json={'sample': 'clean'}).json['run_id']
    response = client.get(f'/api/runs/{run_id}/origins/deadbeef')
    assert (response.status_code, response.json['error']) == (404, 'ORIGIN_MISSING')


def test_issue_page_lists_originals(client):
    run_id = client.post('/api/runs', json={'sample': 'clean'}).json['run_id']
    page = client.get(f'/work/issue?run={run_id}').get_data(as_text=True)
    assert '登记原件' in page
    assert '/api/runs/' + run_id + '/origins/' in page
    assert '快照行' in page
