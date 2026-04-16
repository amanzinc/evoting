import tkinter as tk
from tkinter import messagebox
from gui_app import VotingApp
from ballot_manager import BallotManager
import os
import sys
import logging
import datetime
import shutil
import time

from rfid_service import RFIDService

PROVISIONED_FILENAME = ".provisioned"


def _normalize_logs_path(path):
    """Resolve common misconfiguration where LOGS/LOGS is used instead of LOGS."""
    if not path:
        return path
    normalized = os.path.realpath(os.path.abspath(path))
    if os.path.basename(normalized).upper() == "LOGS":
        parent = os.path.dirname(normalized)
        if os.path.basename(parent).upper() == "LOGS":
            return parent
    return normalized


def _is_writable_log_dir(path):
    """Return True only if directory exists and we can create/remove a file in it."""
    if not path or not os.path.isdir(path):
        return False
    probe_path = os.path.join(path, f".evoting_write_probe_{os.getpid()}")
    try:
        with open(probe_path, "w", encoding="utf-8") as f:
            f.write("probe")
        os.remove(probe_path)
        return True
    except Exception:
        try:
            if os.path.exists(probe_path):
                os.remove(probe_path)
        except Exception:
            pass
        return False


def _find_log_dir(wait_seconds=0.0, poll_interval=0.5):
    """Find the writable log directory. Returns (log_dir, error_msg)."""
    deadline = time.time() + max(0.0, float(wait_seconds or 0.0))
    last_non_writable = []

    while True:
        candidates = [
            _normalize_logs_path(os.environ.get("EVOTING_LOG_DIR", "").strip()),
            _normalize_logs_path("/media/evoting/LOGS"),
            _normalize_logs_path("/media/evoting/LOGS1"),
            _normalize_logs_path("/logs"),
        ]

        last_non_writable = []
        seen = set()
        for cand in candidates:
            if not cand or cand in seen:
                continue
            seen.add(cand)
            if _is_writable_log_dir(cand):
                return cand, None
            if os.path.isdir(cand):
                last_non_writable.append(cand)

        if time.time() >= deadline:
            break
        time.sleep(max(0.1, float(poll_interval or 0.5)))

    if last_non_writable:
        return None, (
            "Log partition found but not writable for current user. "
            f"Checked: {', '.join(last_non_writable)}"
        )

    return None, (
        "Log partition not found! The system cannot start without a writable "
        "log partition. Please ensure the storage is mounted at /media/evoting/LOGS "
        "(or /media/evoting/LOGS1)."
    )


def _is_provisioned(log_dir):
    """Return True if this device has already completed first-boot provisioning."""
    if not log_dir:
        return False

    canonical_log_dir = _normalize_logs_path(log_dir)
    canonical_flag = os.path.join(canonical_log_dir, PROVISIONED_FILENAME)
    if os.path.exists(canonical_flag):
        return True

    # Self-heal: older/misconfigured deployments may have written the flag under LOGS/LOGS/.provisioned.
    nested_flag = os.path.join(canonical_log_dir, "LOGS", PROVISIONED_FILENAME)
    if os.path.exists(nested_flag):
        try:
            shutil.copy2(nested_flag, canonical_flag)
            print(f"[main] Migrated misplaced provision flag from {nested_flag} to {canonical_flag}")
            return True
        except Exception as exc:
            print(f"[main] Found misplaced provision flag but could not migrate it: {exc}")
            return True

    return False


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
    # Give mount services a short grace period during cold boot.
    log_dir_early, _ = _find_log_dir(wait_seconds=8)
    _setup_logging(log_dir_early)

    root = tk.Tk()

    log_dir, log_err = _find_log_dir(wait_seconds=2)

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
