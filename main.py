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
        # Check if the /logs partition exists (typical for our RPi setup)
        if os.path.isdir("/logs"):
            log_dir = "/logs"
        else:
            # Fallback to current directory for local testing
            log_dir = "."

    db_path = os.path.join(log_dir, "evoting_ballots.db")
    votes_log = os.path.join(log_dir, "votes.json")
    tokens_log = os.path.join(log_dir, "tokens.log")
    
    print(f"System logging routed to: {log_dir}")

    # Core Services
    bm = BallotManager(db_path=db_path)
    rfid_service = RFIDService()
    
    # Initialize Core Services with Template (candidates.json) initially
    try:
        data_handler = DataHandler("candidates.json", log_file=votes_log, token_log_file=tokens_log) 
        printer_service = PrinterService(data_handler)
        
        # Perform an initial cut to clear the printer roll on startup
        if printer_service.printer:
            try:
                printer_service.printer.text("\n\n\n\n\n\n") # Feed past blade
                printer_service.printer.cut()
                print("Printer connected and initialized with a startup cut.")
            except Exception as e:
                print(f"Startup cut failed: {e}")
                
    except Exception as e:
        print(f"Critical Startup Error: {e}")
        return

    app = VotingApp(root, data_handler, printer_service, bm, rfid_service)
    root.mainloop()

if __name__ == "__main__":
    main()
