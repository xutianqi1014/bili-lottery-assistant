import argparse
from pathlib import Path

import yaml  # type: ignore[import-untyped]


def contract_files(root: Path) -> list[Path]:
    return sorted(
        [
            root / "backend" / "source_adapters" / "lottery_toolman" / "interface_contracts.yaml",
            root / "backend" / "activity_engine" / "interface_contracts.yaml",
        ]
    )


def load_contracts(root: Path) -> list[dict]:
    rows: list[dict] = []
    for path in contract_files(root):
        if not path.exists():
            continue
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if not isinstance(value, list):
            raise ValueError(f"CONTRACT_FILE_NOT_LIST:{path}")
        rows.extend(value)
    return rows


def audit(root: Path, require_evidence: bool) -> list[str]:
    errors: list[str] = []
    contracts = load_contracts(root)
    ids: set[str] = set()
    allowed_status = {
        "SOURCE_FOUND",
        "READ_ANON_PASSED",
        "READ_AUTH_PASSED",
        "WRITE_TEST_PASSED",
        "PRODUCTION_APPROVED",
        "REJECTED",
        "STALE",
    }
    for row in contracts:
        raw_contract_id = row.get("contract_id")
        contract_id = str(raw_contract_id) if raw_contract_id is not None else ""
        if not contract_id or contract_id in ids:
            errors.append(f"duplicate_or_missing_contract_id:{contract_id}")
        ids.add(contract_id)
        for field in ("owner", "capability", "request", "response", "status"):
            if field not in row:
                errors.append(f"missing_field:{contract_id}:{field}")
        if row.get("status") not in allowed_status:
            errors.append(f"invalid_status:{contract_id}:{row.get('status')}")
        passed_statuses = {
            "READ_ANON_PASSED",
            "READ_AUTH_PASSED",
            "WRITE_TEST_PASSED",
        }
        if require_evidence and row.get("status") in passed_statuses:
            if not row.get("discovered_from"):
                errors.append(f"missing_evidence:{contract_id}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-evidence", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    errors = audit(root, args.require_evidence)
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print(f"OK: {len(load_contracts(root))} web contracts audited")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
