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
    
    # Core Services
    bm = BallotManager()
    rfid_service = RFIDService()
    
    # Initialize Core Services with Template (candidates.json) initially
    try:
        data_handler = DataHandler("candidates.json") 
        printer_service = PrinterService(data_handler)
    except Exception as e:
        print(f"Critical Startup Error: {e}")
        return

    app = VotingApp(root, data_handler, printer_service, bm, rfid_service)
    root.mainloop()

if __name__ == "__main__":
    main()
