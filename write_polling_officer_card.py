"""Write polling-officer phrase or phrase+command payload to an RFID card.

Usage:
  python write_polling_officer_card.py
  python write_polling_officer_card.py --command END_ELECTION_EXPORT
  python write_polling_officer_card.py --set-window "2026-04-18 16:00" "2026-04-18 18:00"
  python write_polling_officer_card.py --extend-end-minutes 30

Card payload format:
  YOU WILL NEVER WALK ALONE
  YOU WILL NEVER WALK ALONE\nEND_ELECTION_EXPORT
"""

import argparse

from rfid_service import RFIDService

PHRASE = "YOU WILL NEVER WALK ALONE"


def main():
    parser = argparse.ArgumentParser(description="Write polling-officer RFID payload")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--command",
        type=str,
        default="",
        help="Optional command, e.g. END_ELECTION_EXPORT",
    )
    mode.add_argument(
        "--set-window",
        nargs=2,
        metavar=("START", "END"),
        help="Write SET_WINDOW command with START and END datetimes",
    )
    mode.add_argument(
        "--extend-end-minutes",
        type=int,
        metavar="MINUTES",
        help="Write EXTEND_END_MINUTES command",
    )
    args = parser.parse_args()

    command_text = ""
    if args.set_window:
        start_text, end_text = args.set_window
        command_text = f"SET_WINDOW|{start_text.strip()}|{end_text.strip()}"
    elif args.extend_end_minutes is not None:
        if args.extend_end_minutes <= 0:
            raise SystemExit("--extend-end-minutes must be greater than 0")
        command_text = f"EXTEND_END_MINUTES|{args.extend_end_minutes}"
    elif args.command.strip():
        command_text = args.command.strip()

    payload = PHRASE if not command_text else f"{PHRASE}\n{command_text}"

    svc = RFIDService()
    if not svc.connect():
        raise SystemExit("RFID reader not connected.")

    print("Place RFID card on reader...")
    uid_hex = svc.write_card_payload(payload, wait_seconds=30)
    print(f"Card written successfully. UID={uid_hex}")
    print("Payload written (before encryption):")
    print(payload)


if __name__ == "__main__":
    main()
