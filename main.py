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
    
    # Initialize Core Services with Template (candidates.json) initially
    try:
        data_handler = DataHandler("candidates.json", log_file=votes_log, token_log_file=tokens_log) 
        printer_service = PrinterService(data_handler)
        
        # Perform an initial cut to clear the printer roll on startup
        if not printer_service.is_printer_connected():
            raise Exception("No USB thermal printer detected! Cannot safely run election.")

        try:
            if data_handler.is_new_genesis:
                printer_service.print_startup_ticket(data_handler.last_hash, log_dir)
                print("Genesis startup ticket printed.")
            else:
                printer_service.printer.text("\n\n\n\n\n\n") # Feed past blade
                printer_service.printer.cut()
                print("Printer connected and initialized with a startup cut.")
        except Exception as e:
            raise Exception(f"Startup cut failed, printer may be jammed: {e}")
                
    except Exception as e:
        print(f"Critical Startup Error: {e}")
        # Show graphic error and abort boot
        messagebox.showerror("System Security Error", str(e))
        return

    app = VotingApp(root, data_handler, printer_service, bm, rfid_service)
    root.mainloop()

if __name__ == "__main__":
    main()
