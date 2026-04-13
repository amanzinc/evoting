import tkinter as tk
from tkinter import messagebox
from gui_app import VotingApp
from ballot_manager import BallotManager
import os
import sys
import logging
import datetime

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


def _setup_logging(log_dir):
    """Route all stdout, stderr, and Python logging to a timestamped log file.

    Two destinations:
      1. The original console (so journalctl / terminal still show output).
      2. A persistent log file on the LOGS partition (survives reboots).

    File naming: app_YYYYMMDD_HHMMSS.log
    Kept in:      <log_dir>/applogs/  (created if needed)
    """
    class _Tee:
        """Write to both the original stream and a file simultaneously."""
        def __init__(self, stream, file_obj):
            self._stream = stream
            self._file   = file_obj

        def write(self, data):
            try:
                self._stream.write(data)
                self._stream.flush()
            except Exception:
                pass
            try:
                self._file.write(data)
                self._file.flush()
            except Exception:
                pass

        def flush(self):
            try:
                self._stream.flush()
            except Exception:
                pass
            try:
                self._file.flush()
            except Exception:
                pass

        def fileno(self):
            return self._stream.fileno()

    # Choose log directory
    if log_dir and os.path.isdir(log_dir):
        app_log_dir = os.path.join(log_dir, "applogs")
    else:
        # Fallback: project directory
        app_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

    os.makedirs(app_log_dir, exist_ok=True)

    timestamp   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path    = os.path.join(app_log_dir, f"app_{timestamp}.log")

    log_file = open(log_path, "a", encoding="utf-8", buffering=1)

    # Write session header to file
    log_file.write(f"{'='*60}\n")
    log_file.write(f"EVoting BMD Session Started: {datetime.datetime.now().isoformat()}\n")
    log_file.write(f"Log file: {log_path}\n")
    log_file.write(f"{'='*60}\n")

    # Tee stdout and stderr
    sys.stdout = _Tee(sys.stdout, log_file)
    sys.stderr = _Tee(sys.stderr, log_file)

    # Python logging module -> same file
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.__stdout__),
            logging.FileHandler(log_path, encoding="utf-8"),
        ]
    )

    print(f"[main] Logging to: {log_path}")
    return log_path


def main():
    # ── Logging: must be first so every subsequent print is captured ──────────
    # Discover log dir early (before provisioning check) so logs persist.
    log_dir_early, _ = _find_log_dir()
    _setup_logging(log_dir_early)

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
