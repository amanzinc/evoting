import tkinter as tk
from data_handler import DataHandler
from printer_service import PrinterService
from gui_app import VotingApp

def main():
    root = tk.Tk()
    
    # Initialize Core Services
    try:
        data_handler = DataHandler()
        # printer_service = PrinterService(data_handler) # Dependency injection if needed, but PrinterService needs data for receipts
        printer_service = PrinterService(data_handler)
    except Exception as e:
        print(f"Critical Startup Error: {e}")
        return

    app = VotingApp(root, data_handler, printer_service)
    root.mainloop()

if __name__ == "__main__":
    main()
