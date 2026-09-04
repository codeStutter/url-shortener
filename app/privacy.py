import hashlib


def hash_ip(ip: str) -> str:
    """One-way hash of a client IP, for click analytics that need to reason
    about distinct visitors without ever persisting a raw IP address.

    Deliberately unsalted and unrotated: this is a prototype-scope privacy
    default ("never store a raw IP"), not a strong anonymization guarantee —
    the same IP always hashes to the same value, so it remains a stable
    per-visitor fingerprint within this dataset. A production system with
    real privacy requirements would rotate a per-day salt (trading exact
    unique-visitor counting for reduced long-term linkability) or drop IP
    capture entirely. See docs/scenarios/03-ambiguous-analytics-requirements.md.
    """
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]
