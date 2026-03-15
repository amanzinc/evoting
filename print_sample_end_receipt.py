import argparse
import datetime
import secrets
import sys

from printer_service import PrinterService


class _DummyDataHandler:
    """Placeholder used because PrinterService expects a data handler instance."""



def build_sample_hash() -> str:
    # Keep a realistic 64-char hex hash for ticket layout testing.
    return secrets.token_hex(32)



def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print a sample end-of-election receipt on the configured thermal printer."
    )
    parser.add_argument(
        "--final-hash",
        default=build_sample_hash(),
        help="64-char final hash to print (default: random sample hash)",
    )
    parser.add_argument(
        "--export-path",
        default=f"SAMPLE_EXPORT_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Export directory label/path shown on the ticket",
    )
    args = parser.parse_args()

    service = PrinterService(_DummyDataHandler())

    print("Attempting to print sample end-of-election receipt...")
    print(f"Final hash : {args.final_hash}")
    print(f"Export path: {args.export_path}")

    try:
        service.print_end_election_ticket(args.final_hash, args.export_path)
        print("Sample receipt printed successfully.")
        return 0
    except Exception as exc:
        print(f"Print failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
