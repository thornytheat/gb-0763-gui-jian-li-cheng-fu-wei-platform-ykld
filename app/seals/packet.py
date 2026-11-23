from app.config import REVISION
from app.manifest import canonical, digest


def packet(snapshot, originals):
    """The evidence sheet, pinned to the exact originals that had arrived.

    ``originals`` lists every received document of the batch together with a
    crosswalk from the archived snapshot's line numbers to that document's own
    rows.  The snapshot stays the single source of conclusions; the crosswalk
    only answers "which line of the file I received is this?".
    """
    manifest, stages = snapshot['manifest'], snapshot['stages']
    return {'document': '轨检证据单', 'revision': REVISION, 'manifest': manifest,
            'source_events': stages['capture']['events'], 'isolated': stages['capture']['rejects'],
            'duplicate_events': stages['capture']['repeated'], 'originals': originals,
            'anchor_review': stages['anchors'], 'chainage': stages['chainage'],
            'defects': stages['defects'], 'coverage': stages['coverage']}


def fingerprint(document):
    return digest(canonical(document))
