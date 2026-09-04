import pytest

from app.shortener import decode_base62, encode_base62


@pytest.mark.parametrize("number", [0, 1, 9, 10, 61, 62, 63, 12345, 999_999_999])
def test_encode_decode_round_trip(number: int) -> None:
    code = encode_base62(number)
    assert decode_base62(code) == number


def test_encoding_is_deterministic() -> None:
    assert encode_base62(12345) == encode_base62(12345)


def test_sequential_ids_produce_unique_codes() -> None:
    codes = {encode_base62(i) for i in range(1, 5000)}
    assert len(codes) == 4999


def test_negative_number_rejected() -> None:
    with pytest.raises(ValueError):
        encode_base62(-1)


def test_zero_encodes_to_single_char() -> None:
    assert encode_base62(0) == "0"
