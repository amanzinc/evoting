import tkinter as tk
from tkinter import messagebox
from gui_app import VotingApp
from ballot_manager import BallotManager
import os

from rfid_service import RFIDService

PROVISIONED_FILENAME = ".provisioned"


def _find_log_dir():
    """Find the writable log directory. Returns (log_dir, error_msg)."""
    log_dir = os.environ.get("EVOTING_LOG_DIR", "").strip()
    if log_dir and os.path.isdir(log_dir):
        return log_dir, None
    if os.path.isdir("/media/evoting/LOGS"):
        return "/media/evoting/LOGS", None
    if os.path.isdir("/logs"):
        return "/logs", None
    return None, (
        "Log partition not found! The system cannot start without a writable "
        "log partition. Please ensure the storage is mounted at /media/evoting/LOGS."
    )


def _is_provisioned(log_dir):
    """Return True if this device has already completed first-boot provisioning."""
    if not log_dir:
        return False
    return os.path.exists(os.path.join(log_dir, PROVISIONED_FILENAME))


def main():
    root = tk.Tk()

    log_dir, log_err = _find_log_dir()

    # ── First-boot provisioning ─────────────────────────────────────────────
    # If the .provisioned flag is absent (or log partition not yet mounted),
    # launch the provisioning wizard instead of the voting app.
    if not _is_provisioned(log_dir):
        from first_boot_provision import ProvisionApp
        print("[main] .provisioned flag not found — launching provisioning wizard.")
        ProvisionApp(root, log_dir)   # log_dir may be None; wizard handles it
        root.mainloop()
        return

    # ── Normal voting-app startup ────────────────────────────────────────────
    if not log_dir:
        messagebox.showerror("Fatal Error", log_err)
        root.destroy()
        return

    db_path    = os.path.join(log_dir, "evoting_ballots.db")
    votes_log  = os.path.join(log_dir, "votes.json")
    tokens_log = os.path.join(log_dir, "tokens.log")

    print(f"[main] System logging routed to: {log_dir}")

    # Core Services
    bm           = BallotManager(db_path=db_path)
    rfid_service = RFIDService()

    # DataHandler and PrinterService are initialised AFTER USB ballot import.
    VotingApp(root, None, None, bm, rfid_service, db_path, votes_log, tokens_log, log_dir)
    root.mainloop()


if __name__ == "__main__":
    main()
