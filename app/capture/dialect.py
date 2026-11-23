import csv
import io

from app.errors import TrackError

FIELDS = ('event_id', 'run', 'kind', 'at', 'odo_mm', 'ref', 'grade')
MISSING = frozenset({'-', 'N/A', 'NULL', '未知'})


def decode(raw):
    for codec in ('utf-8-sig', 'gb18030'):
        try:
            return raw.decode(codec)
        except UnicodeError:
            continue
    raise TrackError('BAD_CSV')


def records(raw):
    text = decode(raw)
    if not text:
        raise TrackError('EMPTY_FILE')
    if not text.strip():
        raise TrackError('BLANK_FILE')
    reader = csv.reader(io.StringIO(text, newline=''), strict=True)
    try:
        header = tuple(next(reader))
        if sorted(header) != sorted(FIELDS):
            raise TrackError('BAD_HEADER')
        start = reader.line_num + 1
        for row in reader:
            yield start, row, header
            start = reader.line_num + 1
    except csv.Error as exc:
        raise TrackError('BAD_CSV') from exc
