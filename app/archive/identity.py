"""Batch attribution.

Two deliveries of the same inspection may differ only in column order, in how
the UTC offset is spelled, or in row numbers: the conclusions are the same.
Conversely, files whose accepted rows agree but whose isolated rows differ are
*not* the same inspection and must not share a batch.

The batch identity therefore derives from the normalized acceptance and
isolation conclusions alone.  Line numbers are provenance, never identity.
Each received document is registered separately under the digest of its own
bytes, so verification can always point back at the original that arrived.
"""

from datetime import datetime, timezone

from app.manifest import canonical, digest

#: Keys that only describe where a record sat in one particular received file.
PROVENANCE_KEYS = frozenset({'line', 'kept_line', 'sources', 'anchor_lines'})


def _utc(value):
    """Canonical UTC spelling of an ISO timestamp, or the original value."""
    if not isinstance(value, str):
        return value
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    if moment.utcoffset() is None:
        return value
    return moment.astimezone(timezone.utc).isoformat()


def strip_provenance(value):
    """Copy nested data, dropping every received-file line reference."""
    if isinstance(value, dict):
        return {key: strip_provenance(item) for key, item in value.items() if key not in PROVENANCE_KEYS}
    if isinstance(value, (list, tuple)):
        return [strip_provenance(item) for item in value]
    return value


def normalize(value):
    """Scrub provenance and collapse equivalent timestamp spellings."""
    if isinstance(value, dict):
        cleaned = {key: normalize(item) for key, item in value.items() if key not in PROVENANCE_KEYS}
        if 'at' in cleaned:
            cleaned['at'] = _utc(cleaned['at'])
        return cleaned
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    return value


def event_key(event):
    """A capture event scrubbed of the line it happened to occupy."""
    return strip_provenance(event)


def reject_key(reject):
    """The conclusion of an isolation, independent of column and row order."""
    if reject.get('fields') is not None:
        payload = reject['fields']
    else:
        raw = reject.get('raw')
        if isinstance(raw, dict):
            payload = strip_provenance(raw)
        elif isinstance(raw, (list, tuple)):
            payload = sorted(str(value) for value in raw)
        else:
            payload = raw
    return {'reason': reject['reason'], 'payload': normalize(payload)}


def attribution(captured):
    """The line-free acceptance and isolation conclusions of a capture stage."""
    accepted = sorted((event_key(event) for event in captured['events']), key=canonical)
    isolated = sorted((reject_key(reject) for reject in captured['rejects']), key=canonical)
    return {'accepted': accepted, 'isolated': isolated}


def attribution_sha256(captured):
    return digest(canonical(attribution(captured)))


def _lines_by(records, key):
    table = {}
    for record in records:
        table.setdefault(canonical(key(record)), []).append(record['line'])
    return table


def crosswalk(snapshot, delivery):
    """Map the snapshot's line numbers onto one received document's lines.

    ``snapshot`` is the archived capture stage (the first delivery of the
    batch); ``delivery`` is any document attributed to the same batch.  The
    result lets an operator keep the evidence conclusions while citing the row
    where the record actually sits in the original in hand.
    """
    snapshot_events = _lines_by(snapshot['events'], event_key)
    delivery_events = _lines_by(delivery['events'], event_key)
    mapping = {}
    for key, lines in snapshot_events.items():
        mapping.update(zip(lines, delivery_events.get(key, ())))
    snapshot_rejects = _lines_by(snapshot['rejects'], reject_key)
    delivery_rejects = _lines_by(delivery['rejects'], reject_key)
    for key, lines in snapshot_rejects.items():
        mapping.update(zip(lines, delivery_rejects.get(key, ())))

    # Duplicate rows collapse into the accepted event they repeat; pair those
    # collapsed rows by the identity of that event.
    snapshot_key = {line: key for key, lines in snapshot_events.items() for line in lines}
    delivery_key = {line: key for key, lines in delivery_events.items() for line in lines}
    snapshot_repeats, delivery_repeats = {}, {}
    for repeat in snapshot['repeated']:
        key = snapshot_key.get(repeat['kept_line'])
        if key is not None:
            snapshot_repeats.setdefault(key, []).append(repeat['line'])
    for repeat in delivery['repeated']:
        key = delivery_key.get(repeat['kept_line'])
        if key is not None:
            delivery_repeats.setdefault(key, []).append(repeat['line'])
    for key, lines in snapshot_repeats.items():
        mapping.update(zip(sorted(lines), sorted(delivery_repeats.get(key, ()))))
    return {str(line): target for line, target in sorted(mapping.items())}
