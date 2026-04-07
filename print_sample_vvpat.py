import argparse
import datetime
import os
import time

from printer_service import PrinterService


class MockDataHandler:
    def __init__(self):
        self.ballot_id = "SAMPLE-001"
        self.candidates = {
            1: {"candidate_number": "1"},
            2: {"candidate_number": "2"},
            3: {"candidate_number": "3"},
        }

    def get_short_ballot_id(self, ballot_id=None):
        bid = ballot_id if ballot_id is not None else self.ballot_id
        return str(bid).split(",", 1)[0]

    def get_candidate_by_id(self, cid):
        return self.candidates.get(cid)

    def build_receipt_qr_payload(self, selections, mode):
        if mode == "normal":
            return f"sample:{self.ballot_id}:choice:{selections.get(1, 'NA')}"
        ordered = [f"{rank}:{selections[rank]}" for rank in sorted(selections.keys())]
        return f"sample:{self.ballot_id}:prefs:" + "|".join(ordered)


def main():
    parser = argparse.ArgumentParser(description="Print a sample VVPAT (optionally without voter receipt)")
    parser.add_argument(
        "--printer-name",
        default="POS-80C",
        help="Windows printer queue name (for example: POS-80C or KPOS_58 Printer)",
    )
    parser.add_argument(
        "--candidate-id",
        type=int,
        default=1,
        help="Candidate id for sample selection",
    )
    parser.add_argument(
        "--vvpat-only",
        action="store_true",
        help="Print only the VVPAT slip and skip voter receipt",
    )
    args = parser.parse_args()

    os.environ["EVOTING_PRINTER_NAME"] = args.printer_name

    service = PrinterService(MockDataHandler())
    if not service.is_printer_connected():
        raise RuntimeError(
            f"Printer not connected. Check queue name: {args.printer_name}"
        )

    if args.vvpat_only:
        ballot_id = service.data_handler.get_short_ballot_id()
        qr_choice_data = service.data_handler.build_receipt_qr_payload(
            {1: args.candidate_id}, "normal"
        )
        sel_str = str(args.candidate_id)
        timestamp = datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")

        p = service.printer
        top_bar = service._bar("_")
        bottom_bar = service._bar("_")

        service._set_reverse_print_mode(True)
        try:
            p.text("\n")
            p.text(bottom_bar + "\n")

            short_b_id = service.data_handler.get_short_ballot_id(ballot_id)
            temp_img = service._generate_vvpat_qr(qr_choice_data, short_b_id)

            p.text("\n")
            p.set(align="left")
            p.image(temp_img)
            p.text("\n")
            if os.path.exists(temp_img):
                os.remove(temp_img)

            p.set(align="left", bold=True)
            p.text(f"Choice : {sel_str}\n")
            p.set(align="left", bold=False)
            p.text("\n")

            p.set(align="left")
            p.text(f"Session: {timestamp}\n")
            p.text("Station: SAMPLE-STATION\n")
            p.text("\n")

            p.set(align="left", font="a", width=1, height=1, bold=True)
            p.text(service._center_line("** VVPAT SLIP **") + "\n")
            p.text(top_bar + "\n")
            p.set(align="left", bold=False)

            p.text("\n\n")
            time.sleep(5)
            p.cut(mode="FULL")
            # Extra post-cut feed helps the detached slip clear the cutter area.
            p.text("\n\n\n\n\n")
        finally:
            service._set_reverse_print_mode(False)

        print("Sample VVPAT-only print job sent successfully.")
    else:
        service.print_vote("normal", {1: args.candidate_id}, is_final=True)
        print("Sample VVPAT + voter receipt print job sent successfully.")


if __name__ == "__main__":
    main()
