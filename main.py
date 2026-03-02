import tkinter as tk
from tkinter import messagebox
from data_handler import DataHandler
from printer_service import PrinterService
from gui_app import VotingApp
from ballot_manager import BallotManager
import os

from rfid_service import RFIDService

def main():
    root = tk.Tk()
    
    # Determine the log directory for read-only RPi compatibility
    log_dir = os.environ.get("EVOTING_LOG_DIR")
    if not log_dir:
        # Check if the /media/evoting/LOGS partition exists (typical for our RPi setup)
        if os.path.isdir("/media/evoting/LOGS"):
            log_dir = "/media/evoting/LOGS"
        elif os.path.isdir("/logs"):
            log_dir = "/logs"
        else:
            messagebox.showerror("Fatal Error", "Log partition not found! The system cannot start without a writable log partition. Please ensure the USB/SD partition is mounted at /media/evoting/LOGS.")
            return

    db_path = os.path.join(log_dir, "evoting_ballots.db")
    votes_log = os.path.join(log_dir, "votes.json")
    tokens_log = os.path.join(log_dir, "tokens.log")
    
    print(f"System logging routed to: {log_dir}")
    
    # Core Services
    bm = BallotManager(db_path=db_path)
    rfid_service = RFIDService()
    
    # We will initialize DataHandler and PrinterService AFTER the USB is detected.
    # For now, we launch the GUI with placeholders.
    app = VotingApp(root, None, None, bm, rfid_service, db_path, votes_log, tokens_log, log_dir)
    root.mainloop()

if __name__ == "__main__":
    main()
