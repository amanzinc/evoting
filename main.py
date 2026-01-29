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

    # Initialize Core Services with Template (candidates.json) initially
    try:
        data_handler = DataHandler("candidates.json") 
        printer_service = PrinterService(data_handler)
    except Exception as e:
        print(f"Critical Startup Error: {e}")
        return

    app = VotingApp(root, data_handler, printer_service, bm)
    root.mainloop()

if __name__ == "__main__":
    main()
