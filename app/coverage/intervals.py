def union(spans):
    """Merge half-open [lo, hi) spans; zero-length spans are dropped."""
    ordered = sorted((lo, hi) if lo <= hi else (hi, lo) for lo, hi in spans if lo != hi)
    merged = []
    for lo, hi in ordered:
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return merged


def intersect(left, right):
    """Intersection of two already-merged interval lists."""
    result, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        lo = max(left[i][0], right[j][0])
        hi = min(left[i][1], right[j][1])
        if lo < hi:
            result.append([lo, hi])
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return result


def subtract(whole, covered):
    """Half-open parts of a merged list not covered by another merged list."""
    result = []
    for lo, hi in whole:
        cursor = lo
        for c_lo, c_hi in covered:
            if c_hi <= cursor or c_lo >= hi:
                continue
            if c_lo > cursor:
                result.append([cursor, c_lo])
            cursor = max(cursor, c_hi)
            if cursor >= hi:
                break
        if cursor < hi:
            result.append([cursor, hi])
    return result


def length(spans):
    return sum(hi - lo for lo, hi in spans)
