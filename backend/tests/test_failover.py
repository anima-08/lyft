import pytest

from app.failover import parse_failure_header, simulated_status


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_parse_supported_single_key_failures(status):
    assert parse_failure_header(f"key_1={status}", ["key_1", "key_2"], True) == {"key_1": status}


def test_parse_multiple_and_wildcard_failures():
    failures = parse_failure_header("key_1=429,key_2=500", ["key_1", "key_2"], True)
    assert simulated_status(failures, "key_1") == 429
    assert simulated_status(failures, "key_2") == 500
    assert simulated_status({"*": 503}, "key_2") == 503


def test_header_is_ignored_when_simulation_is_disabled():
    assert parse_failure_header("*=429", ["key_1", "key_2"], False) == {}


@pytest.mark.parametrize(
    "header",
    ["key_1", "key_1=401", "key_3=429", "=429", "key_1=429,", "key_1=429=500"],
)
def test_malformed_headers_are_rejected(header):
    with pytest.raises(ValueError):
        parse_failure_header(header, ["key_1", "key_2"], True)
