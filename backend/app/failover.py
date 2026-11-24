ALLOWED_FAILURE_STATUSES = frozenset({429, 500, 502, 503})


def parse_failure_header(header: str | None, key_ids: list[str], enabled: bool) -> dict[str, int]:
    if not enabled or not header:
        return {}

    valid_keys = set(key_ids)
    failures: dict[str, int] = {}
    for raw_pair in header.split(","):
        pair = raw_pair.strip()
        if pair.count("=") != 1:
            raise ValueError("X-Simulate-Failure must use comma-separated key_id=status pairs")
        key_id, raw_status = (part.strip() for part in pair.split("=", 1))
        if key_id != "*" and key_id not in valid_keys:
            raise ValueError(f"unknown key_id: {key_id}")
        if not raw_status.isdigit() or int(raw_status) not in ALLOWED_FAILURE_STATUSES:
            raise ValueError("simulated status must be 429, 500, 502, or 503")
        failures[key_id] = int(raw_status)
    return failures


def simulated_status(failures: dict[str, int], key_id: str) -> int | None:
    return failures.get(key_id, failures.get("*"))
