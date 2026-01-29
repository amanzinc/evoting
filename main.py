import tkinter as tk
from tkinter import messagebox
from data_handler import DataHandler
from printer_service import PrinterService
from gui_app import VotingApp
from ballot_manager import BallotManager
import os

def main():
    root = tk.Tk()
    
    # Ballot Management
    bm = BallotManager()
    
    # Auto-generate if missing (Dev convenience)
    if not os.path.exists("ballots") or not os.listdir("ballots"):
        print("No ballots found. Generating new pool...")
        bm.generate_ballots(50)

    try:
        # Get ONE unused ballot for this session
        ballot_id, ballot_file = bm.get_unused_ballot()
        print(f"Session initialized with Ballot ID: {ballot_id}")
        
        # Mark as used IMMEDIATELY to prevent reuse if app crashes?
        # Or mark after vote? 
        # Standard: Mark when issued.
        bm.mark_as_used(ballot_id)
        
    except Exception as e:
        print(f"Ballot Error: {e}")
        root.withdraw()
        messagebox.showerror("Fatal Error", f"Cannot initialize ballot: {e}")
        return

    # Initialize Core Services with SPECIFIC Ballot File
    try:
        data_handler = DataHandler(ballot_file) 
        printer_service = PrinterService(data_handler)
    except Exception as e:
        print(f"Critical Startup Error: {e}")
        return

    app = VotingApp(root, data_handler, printer_service)
    root.mainloop()

if __name__ == "__main__":
    main()
