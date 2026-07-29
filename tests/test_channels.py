import pytest

from app.channels import normalize_chat_ref


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("@mychannel", "@mychannel"),
        ("mychannel", None),  # bare word without @ or numeric id is rejected
        ("https://t.me/mychannel", "@mychannel"),
        ("http://t.me/mychannel", "@mychannel"),
        ("t.me/mychannel", "@mychannel"),
        ("-1001234567890", "-1001234567890"),
        ("1001234567890", "1001234567890"),
        ("", None),
        ("   ", None),
        ("@", None),
        ("@my channel", None),  # space is not a valid username character
    ],
)
def test_normalize_chat_ref(raw: str, expected: str | None) -> None:
    assert normalize_chat_ref(raw) == expected
