import argparse
import csv
import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import requests
except ImportError:  # pragma: no cover - handled at runtime
    requests = None

DEFAULT_INVOICE_DIR = "invoices"
DEFAULT_OUTPUT_CSV = os.path.join("output", "processed_invoices.csv")
DEFAULT_LOG_DIR = "logs"
DEFAULT_ENDPOINT = "https://httpbin.org/post"

REQUIRED_FIELDS = ("vendor", "invoice_number", "invoice_date", "amount")
AMOUNT_MATCH_FIELDS = ("po_amount", "expected_amount")

DEFAULT_FIELD_ORDER = (
    "vendor",
    "invoice_number",
    "invoice_date",
    "amount",
    "po_number",
    "po_amount",
    "expected_amount",
    "status",
    "issues",
    "processed_at",
    "api_status",
    "api_error",
    "source_file",
)


def setup_logging(log_dir: str) -> str:
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "invoice_automation.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return log_path


def load_invoices(invoice_dir: str) -> Tuple[List[Dict[str, Any]], int]:
    invoices: List[Dict[str, Any]] = []
    failures = 0

    for fname in sorted(os.listdir(invoice_dir)):
        if not fname.lower().endswith(".json"):
            continue
        path = os.path.join(invoice_dir, fname)
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("invoice JSON must be an object")
            data["source_file"] = fname
            invoices.append(data)
        except Exception as exc:
            failures += 1
            logging.warning("Failed to load %s: %s", fname, exc)

    return invoices, failures


def normalize_value(value: Any) -> str:
    return str(value or "").strip().lower()


def invoice_key(inv: Dict[str, Any]) -> str:
    return f"{normalize_value(inv.get('vendor'))}:{normalize_value(inv.get('invoice_number'))}"


def parse_amount(value: Any) -> Tuple[Optional[Decimal], Optional[str]]:
    try:
        return Decimal(str(value)), None
    except (InvalidOperation, ValueError, TypeError):
        return None, "amount_not_number"


def validate_invoice(inv: Dict[str, Any], seen_keys: Set[str]) -> Tuple[str, List[str]]:
    issues: List[str] = []

    for field in REQUIRED_FIELDS:
        if inv.get(field) in (None, "", []):
            issues.append(f"missing_{field}")

    amount_value: Optional[Decimal] = None
    if inv.get("amount") not in (None, "", []):
        amount_value, amount_issue = parse_amount(inv.get("amount"))
        if amount_issue:
            issues.append(amount_issue)
        elif amount_value <= 0:
            issues.append("invalid_amount")

    invoice_date = inv.get("invoice_date")
    if invoice_date not in (None, "", []):
        try:
            datetime.fromisoformat(str(invoice_date))
        except ValueError:
            issues.append("bad_invoice_date_format")

    if not inv.get("po_number"):
        issues.append("missing_po_number")

    expected_value: Optional[Decimal] = None
    for field in AMOUNT_MATCH_FIELDS:
        if inv.get(field) not in (None, "", []):
            expected_value, expected_issue = parse_amount(inv.get(field))
            if expected_issue:
                issues.append(f"{field}_not_number")
            break

    if amount_value is not None and expected_value is not None:
        if abs(amount_value - expected_value) > Decimal("0.01"):
            issues.append("amount_mismatch")

    if inv.get("vendor") and inv.get("invoice_number"):
        key = invoice_key(inv)
        if key in seen_keys:
            issues.append("duplicate_invoice")
        else:
            seen_keys.add(key)

    status = "NEEDS_REVIEW" if issues else "APPROVED"
    return status, issues


def post_to_api(
    endpoint: Optional[str], payload: Dict[str, Any], timeout: int = 10
) -> Tuple[str, str]:
    if not endpoint:
        return "SKIPPED", ""
    if requests is None:
        return "FAILED", "requests_not_installed"

    try:
        response = requests.post(endpoint, json=payload, timeout=timeout)
        if 200 <= response.status_code < 300:
            return "SUCCESS", ""
        return "FAILED", f"status_{response.status_code}"
    except Exception as exc:
        return "FAILED", str(exc)


def build_fieldnames(rows: List[Dict[str, Any]]) -> List[str]:
    fieldnames: List[str] = []

    for name in DEFAULT_FIELD_ORDER:
        if any(name in row for row in rows):
            fieldnames.append(name)

    extras = sorted({key for row in rows for key in row.keys() if key not in fieldnames})
    return fieldnames + extras


def write_csv(rows: List[Dict[str, Any]], output_csv: str) -> None:
    os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)
    fieldnames = build_fieldnames(rows)

    with open(output_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automated invoice processing demo")
    parser.add_argument("--invoice-dir", default=DEFAULT_INVOICE_DIR)
    parser.add_argument("--output-csv", default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--skip-api", action="store_true", help="Skip API posting")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    log_path = setup_logging(args.log_dir)

    if not os.path.isdir(args.invoice_dir):
        raise SystemExit(
            f"Missing folder '{args.invoice_dir}'. Add .json invoices and try again."
        )

    endpoint = None if args.skip_api else args.endpoint
    invoices, failed_loads = load_invoices(args.invoice_dir)

    if not invoices:
        print("No invoices found. Add .json files to the invoices folder.")
        print(f"Log saved to: {log_path}")
        return

    seen_keys: Set[str] = set()
    processed_rows: List[Dict[str, Any]] = []
    approved = 0
    review = 0
    api_success = 0
    api_failed = 0
    api_skipped = 0

    for inv in invoices:
        status, issues = validate_invoice(inv, seen_keys)

        record = dict(inv)
        record["status"] = status
        record["issues"] = ";".join(issues)
        record["processed_at"] = utc_now_iso()

        api_status, api_error = post_to_api(endpoint, record)
        record["api_status"] = api_status
        if api_error:
            record["api_error"] = api_error

        if api_status == "SUCCESS":
            api_success += 1
        elif api_status == "FAILED":
            api_failed += 1
        else:
            api_skipped += 1

        if status == "APPROVED":
            approved += 1
        else:
            review += 1

        processed_rows.append(record)

    write_csv(processed_rows, args.output_csv)

    print("=== Invoice Automation Summary ===")
    print(f"Total invoices loaded: {len(invoices)}")
    print(f"Failed to load:        {failed_loads}")
    print(f"Approved:              {approved}")
    print(f"Needs review:          {review}")
    print(f"API posts success:     {api_success}")
    print(f"API posts failed:      {api_failed}")
    print(f"API posts skipped:     {api_skipped}")
    print(f"Output saved to:       {args.output_csv}")
    print(f"Log saved to:          {log_path}")

    logging.info("Processed %s invoices", len(invoices))
    logging.info("Approved: %s", approved)
    logging.info("Needs review: %s", review)
    logging.info("API success: %s", api_success)
    logging.info("API failed: %s", api_failed)
    logging.info("API skipped: %s", api_skipped)
    logging.info("Output: %s", args.output_csv)


if __name__ == "__main__":
    main()
