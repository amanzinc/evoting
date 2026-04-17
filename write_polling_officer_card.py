"""
Write a polling-officer trigger phrase to an RFID card.

Usage:
  python write_polling_officer_card.py

Card payload written:
  YOU WILL NEVER WALK ALONE
"""

from rfid_service import RFIDService

PHRASE = "YOU WILL NEVER WALK ALONE"


def main():
    svc = RFIDService()
    if not svc.connect():
        raise SystemExit("RFID reader not connected.")

    print("Place RFID card on reader...")
    uid_hex = svc.write_plaintext_card_payload(PHRASE, wait_seconds=30)
    print(f"Card written successfully. UID={uid_hex}")
    print(f"Payload: {PHRASE}")


if __name__ == "__main__":
    main()
