from slowapi import Limiter
from slowapi.util import get_remote_address

# Single shared limiter instance. In-process/in-memory: per-worker-process
# counters that reset on restart. Documented as a known limitation (see
# docs/TESTING.md) — swapping to a Redis storage backend is the production
# path and is a config change, not a redesign, because slowapi supports it
# out of the box via its `storage_uri` option.
limiter = Limiter(key_func=get_remote_address)
