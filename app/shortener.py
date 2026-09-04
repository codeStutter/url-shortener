"""Short-code generation.

We base62-encode the row's auto-increment primary key rather than generating a
random string and retrying on collision. A monotonically increasing id is
already guaranteed unique by the database, so encoding it sidesteps collision
handling entirely and keeps code generation O(1) with no retry loop.
"""

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_BASE = len(_ALPHABET)

# Custom aliases must not collide with our own top-level routes, or a short
# link would shadow (or be shadowed by) part of the API/UI surface.
RESERVED_CODES = {"api", "demo", "static", "docs", "redoc", "openapi.json", ""}


def encode_base62(number: int) -> str:
    if number < 0:
        raise ValueError("cannot encode a negative number")
    if number == 0:
        return _ALPHABET[0]

    digits = []
    while number:
        number, remainder = divmod(number, _BASE)
        digits.append(_ALPHABET[remainder])
    return "".join(reversed(digits))


def decode_base62(code: str) -> int:
    number = 0
    for char in code:
        number = number * _BASE + _ALPHABET.index(char)
    return number
