from collections import OrderedDict, defaultdict

from .intervals import intersect, length, subtract, union


def _explain(chain, lo, hi, gaps):
    """Attribute a missing stretch to the break/gap records that touch it."""
    reasons, sources = [], []
    for gap in gaps:
        if gap['chain'] != chain:
            continue
        start, end = sorted((gap['start_mm'], gap['end_mm']))
        if start < hi and lo < end:
            if gap['reason'] not in reasons:
                reasons.append(gap['reason'])
            for source in gap['sources']:
                if source not in sources:
                    sources.append(source)
    return reasons or ['NO_COVERAGE'], sources


def balance(plan, segments, gaps):
    """Reconcile planned track against mapped spans per chain.

    Coverage is the intersection of the union of planned intervals with the
    union of spans restored from two anchors.  Overlap is the raw clipped
    length (before de-duplication) minus that intersection, so a repeated
    survey shows up as extra mapped length without inflating coverage.
    """
    planned = OrderedDict()
    for item in plan:
        planned.setdefault(item['chain'], []).append((item['start_mm'], item['end_mm']))
    spans = defaultdict(list)
    for segment in segments:
        left = segment['left']
        spans[left['chain']].append((left['station_mm'], segment['right']['station_mm']))
    gaps_by_chain = defaultdict(list)
    for gap in gaps:
        gaps_by_chain[gap['chain']].append(gap)

    tracks, missing_parts = [], []
    planned_total = mapped_total = missing_total = overlap_total = 0
    for chain, parts in planned.items():
        plan_union = union(parts)
        chain_spans = union(spans.get(chain, []))
        mapped = intersect(plan_union, chain_spans)
        holes = subtract(plan_union, mapped)
        clipped_raw = sum(length(intersect(plan_union, union([span]))) for span in spans.get(chain, []))
        planned_mm, mapped_mm = length(plan_union), length(mapped)
        tracks.append({'chain': chain, 'start_mm': plan_union[0][0], 'end_mm': plan_union[-1][1],
                       'planned_mm': planned_mm, 'mapped_mm': mapped_mm, 'mapped_parts': mapped})
        for lo, hi in holes:
            reasons, sources = _explain(chain, lo, hi, gaps_by_chain.get(chain, []))
            missing_parts.append({'chain': chain, 'start_mm': lo, 'end_mm': hi,
                                  'reasons': reasons, 'sources': sources})
        planned_total += planned_mm
        mapped_total += mapped_mm
        missing_total += planned_mm - mapped_mm
        overlap_total += max(0, clipped_raw - mapped_mm)
    return {'planned_mm': planned_total, 'mapped_mm': mapped_total, 'missing_mm': missing_total,
            'overlap_mm': overlap_total, 'tracks': tracks, 'missing_parts': missing_parts}
