"""Write 5 sample voter RFID cards for testing AES-based card reads.

Each card carries a JSON payload for election E1.

Usage:
  python write_test_voter_cards.py
  python write_test_voter_cards.py --count 3
  python write_test_voter_cards.py --election E2 --booth 2
"""

import argparse
import json
import time
import uuid

from rfid_service import RFIDService

CARDS = [
    {"voter_id": "VOTER_TEST_001", "name": "Alice"},
    {"voter_id": "VOTER_TEST_002", "name": "Bob"},
    {"voter_id": "VOTER_TEST_003", "name": "Charlie"},
    {"voter_id": "VOTER_TEST_004", "name": "Diana"},
    {"voter_id": "VOTER_TEST_005", "name": "Eve"},
]


def make_token_id(voter_id: str) -> str:
    short = uuid.uuid4().hex[:8].upper()
    return f"TEST_{voter_id}_{short}"


def write_cards(election: str, booth: int, count: int, wait: int):
    svc = RFIDService()
    if not svc.connect():
        raise SystemExit("RFID reader not connected.")

    cards = CARDS[:count]
    print(f"\nWriting {len(cards)} test voter card(s) for election '{election}', booth {booth}.\n")

    written = []
    for i, card in enumerate(cards, start=1):
        token_id = make_token_id(card["voter_id"])
        payload = {
            "token_id": token_id,
            "voter_id": card["voter_id"],
            "eid_vector": election,
            "booth": booth,
        }
        payload_json = json.dumps(payload)

        print(f"[{i}/{len(cards)}] {card['name']} ({card['voter_id']})")
        print(f"         token_id  : {token_id}")
        print(f"         payload   : {payload_json}")
        print(f"  Place card on reader (waiting up to {wait}s)...")

        try:
            uid_hex = svc.write_card_payload(payload_json, wait_seconds=wait)
            print(f"  ✅ Written. UID = {uid_hex}\n")
            written.append({"uid": uid_hex, **payload})
        except RuntimeError as e:
            print(f"  ❌ Failed: {e}\n")

        if i < len(cards):
            input("  Remove card and press Enter for next card...")
            print()

    print("── Summary ──────────────────────────────────")
    for w in written:
        print(f"  UID {w['uid']}  token={w['token_id']}  voter={w['voter_id']}")
    print(f"  {len(written)}/{len(cards)} cards written successfully.")


def main():
    parser = argparse.ArgumentParser(description="Write test voter RFID cards")
    parser.add_argument("--election", default="E1", help="Election ID (default: E1)")
    parser.add_argument("--booth", type=int, default=1, help="Booth number (default: 1)")
    parser.add_argument("--count", type=int, default=5, choices=range(1, 6),
                        metavar="N", help="Number of cards to write, 1-5 (default: 5)")
    parser.add_argument("--wait", type=int, default=30,
                        help="Seconds to wait for each card placement (default: 30)")
    args = parser.parse_args()

    write_cards(args.election, args.booth, args.count, args.wait)


if __name__ == "__main__":
    main()
