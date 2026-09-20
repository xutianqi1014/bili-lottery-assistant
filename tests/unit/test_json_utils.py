import pytest

from backend.domain.json_utils import load_json_ints


@pytest.mark.parametrize("value,expected", [
    ("broken", []), ("null", []), ('{"id": 1}', []), ("7", []), ("[]", []),
    ('[3, "3", 3.0, true, false, null, {}, [], -2, 3]', [3, True, False, -2, 3]),
])
def test_integer_json_reader_preserves_persisted_value_semantics(value, expected):
    result = load_json_ints(value)
    assert result == expected
    assert [type(item) for item in result] == [type(item) for item in expected]
