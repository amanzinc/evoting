import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue
import datetime
import time
import os

class VotingApp:
    def __init__(self, root, data_handler, printer_service, ballot_manager, rfid_service, db_path, votes_log, tokens_log, log_dir):
        self.root = root
        self.data_handler = data_handler
        self.printer_service = printer_service
        self.ballot_manager = ballot_manager
        self.rfid_service = rfid_service
        
        # Store paths for deferred initialization
        self.db_path = db_path
        self.votes_log = votes_log
        self.tokens_log = tokens_log
        self.log_dir = log_dir
        
        self.active_token = None
        self.challenge_counts_by_election = {}
        self.max_challenges_per_election = 1
        
        self.root.title("Ballot Marking Device")
        self.root.attributes('-fullscreen', True)
        self.root.bind("<Escape>", self.exit_app)

        # Style configuration
        self.style = ttk.Style()
        self.style.configure('TLabel', font=('Helvetica', 14))
        self.style.configure('Header.TLabel', font=('Helvetica', 20, 'bold'))

        # State
        self.voting_mode = None 
        self.pv_mode_2 = False
        self.max_ranks = 3
        self.current_rank = 1
        self.selections = {}
        self.merge_receipts = True # Temporary flag for merged printing
        self.receipt_buffer = [] # Store print data for batching 
        self.print_enabled = True

        self.main_container = tk.Frame(self.root, bg="#ffffff")
        self.main_container.pack(fill=tk.BOTH, expand=True)
        
        # Start with USB Polling Screen
        self.show_usb_waiting_screen()

    def show_usb_waiting_screen(self):
        self.clear_container()
        frame = tk.Frame(self.main_container, bg="#E8F5E9")
        frame.pack(expand=True, fill=tk.BOTH)
        
        tk.Label(frame, text="System Initialization", font=('Helvetica', 32, 'bold'), bg="#E8F5E9", fg="#2E7D32").pack(pady=(150, 20))
        tk.Label(frame, text="Please insert the Election Data USB Drive to start.", font=('Helvetica', 24), bg="#E8F5E9", fg="#333").pack(pady=20)
        tk.Label(frame, text="(Waiting for USB with 'ballot' folder)", font=('Helvetica', 14), bg="#E8F5E9", fg="#666").pack(pady=5)

        self.check_usb_loop()

    def check_usb_loop(self):
        # Try to find the USB drive with 'ballot' folder
        usb_path = self.ballot_manager._find_usb_drive(None)
        ballot_path = os.path.join(usb_path, "ballot") if usb_path else None

        if ballot_path and os.path.exists(ballot_path):
            # Found USB with encrypted ballot folder - trigger import
            self.ballot_manager.usb_mount_point = usb_path
            self.import_encrypted_ballots(usb_path)
        else:
            self.root.after(2000, self.check_usb_loop)

    def import_encrypted_ballots(self, usb_path):
        """Import encrypted ballots from USB and prepare for voting."""
        self.clear_container()
        frame = tk.Frame(self.main_container, bg="#E8F5E9")
        frame.pack(expand=True, fill=tk.BOTH)
        
        tk.Label(frame, text="Importing Ballots", font=('Helvetica', 32, 'bold'), bg="#E8F5E9", fg="#2E7D32").pack(pady=(150, 20))
        status_label = tk.Label(frame, text="Decrypting and importing ballots...", font=('Helvetica', 18), bg="#E8F5E9", fg="#333")
        status_label.pack(pady=20)
        
        def run_import():
            try:
                from usb_ballot_import import USBBallotImporter
                
                ballot_path = os.path.join(usb_path, "ballot")
                
                # Create importer (demo_mode=False requires RPi hardware)
                importer = USBBallotImporter(
                    private_key_path="private.pem",
                    local_storage_dir="ballot",
                    demo_mode=False
                )
                
                # Run import
                status_label.config(text="Decrypting AES key...")
                self.root.update()
                
                summary = importer.import_usb_ballots(
                    usb_ballot_path=ballot_path,
                    elections_base_dir="elections"
                )
                
                if summary["status"] == "success":
                    status_label.config(
                        text=f"✓ Successfully imported {summary['total_ballots']} ballots\nProceeding to initialization...",
                        fg="#2E7D32"
                    )
                    self.root.after(2000, self.initialize_core_services)
                else:
                    error_msg = "\\n".join(summary["errors"])
                    status_label.config(
                        text=f"✗ Import failed:\\n{error_msg}",
                        fg="#C62828"
                    )
                    status_label.config(wraplength=600)
                    # Retry after error
                    self.root.after(5000, self.show_usb_waiting_screen)
                    
            except Exception as e:
                status_label.config(
                    text=f"✗ Error: {str(e)}",
                    fg="#C62828",
                    wraplength=600
                )
                # Retry after error
                self.root.after(5000, self.show_usb_waiting_screen)
        
        # Run import in background thread to prevent UI freeze
        import_thread = threading.Thread(target=run_import, daemon=True)
        import_thread.start()

    def end_election(self):
        """Triggers secure export process without automatic shutdown."""
        if messagebox.askyesno("Confirm End Election", "Are you sure you want to officially end the election?\nThis will export data to USB.", icon='warning'):
            try:
                # Find the USB drive explicitly in case it was unplugged
                usb_path = self.ballot_manager._find_usb_drive(None)
                if not usb_path:
                    messagebox.showerror("Export Failed", "USB Drive not found! Please insert the admin USB drive to export logs.")
                    return
                
                from export_service import ExportService
                exporter = ExportService("private.pem")
                export_path = exporter.export_election_data(self.log_dir, usb_path)
                
                # Fetch final hash and force printing of final receipt before shutdown.
                if self.print_enabled and hasattr(self, 'data_handler') and hasattr(self, 'printer_service'):
                    final_hash = self.data_handler.last_hash or "UNKNOWN_HASH"
                    self.printer_service.print_end_election_ticket(final_hash, export_path)
                elif self.print_enabled:
                    raise Exception("Core services unavailable for end-of-election receipt printing.")
                
                messagebox.showinfo("Export Successful", f"Election successfully ended.\nEncrypted logs safely exported to:\n{export_path}\n\nAutomatic shutdown is temporarily disabled.")
            except Exception as e:
                messagebox.showerror("Export Error", f"A critical error occurred during export:\n{str(e)}")

    def initialize_core_services(self):
        try:
            from data_handler import DataHandler
            from printer_service import PrinterService
            
            # Use only local elections directory (imported from USB)
            elections_base = "elections"
            
            if not os.path.exists(elections_base):
                raise Exception(f"Elections directory not found at {elections_base}. Import may have failed.")
            
            # Prefer new folder naming (election_id_*) over legacy E* folders.
            election_dirs = [
                entry.name for entry in os.scandir(elections_base)
                if entry.is_dir()
            ] if os.path.exists(elections_base) else []

            preferred = sorted([eid for eid in election_dirs if eid.startswith("election_id_")])
            fallback = sorted(election_dirs)
            first_election = preferred[0] if preferred else (fallback[0] if fallback else None)

            if not first_election:
                raise Exception("No elections found in local elections directory")
                
            candidate_path = os.path.join(elections_base, first_election, "candidates.json")

            print(f"Initializing DataHandler with candidate map: {candidate_path}")
            self.data_handler = DataHandler(candidate_path, log_file=self.votes_log, token_log_file=self.tokens_log) 
            self.printer_service = PrinterService(self.data_handler)
            
            # Perform an initial cut to clear the printer roll on startup
            if not self.printer_service.is_printer_connected():
                messagebox.showerror("Printer Error", "No USB thermal printer detected! Cannot safely run election. Please connect printer and restart system.")
                return

            try:
                # In DataHandler, we will set a flag if genesis was generated
                if not self.print_enabled:
                    print("Printing disabled: skipping startup ticket/cut.")
                elif hasattr(self.data_handler, 'is_new_genesis') and self.data_handler.is_new_genesis:
                    self.printer_service.print_startup_ticket(self.data_handler.last_hash, self.log_dir)
                    print("Genesis startup ticket printed.")
                else:
                    self.printer_service.printer.text("\n\n\n\n\n\n") # Feed past blade
                    self.printer_service.printer.cut()
                    print("Printer connected and initialized with a startup cut.")
            except Exception as e:
                messagebox.showerror("Printer Error", f"Startup print failed, printer may be jammed: {e}")
                return
                    
            # Initialize RFID
            self.rfid_service.load_key()
            self.rfid_service.connect()
            
            # Try to load base candidates mapping
            try:
                self.data_handler.load_candidates()
            except Exception as e:
                print(f"Base candidate load failed (normal if generic): {e}")

            # Proceed to RFID Screen
            self.show_rfid_screen()

        except Exception as e:
            messagebox.showerror("System Security Error", f"Failed to initialize election data from USB: {e}")
            # Keep polling in case they inserted the wrong USB
            self.root.after(3000, self.show_usb_waiting_screen)

    def clear_container(self):
        for widget in self.main_container.winfo_children():
            widget.destroy()

    def toggle_printing(self):
        """Toggle printing to avoid paper usage during testing."""
        self.print_enabled = not self.print_enabled
        if hasattr(self, 'print_toggle_btn') and self.print_toggle_btn.winfo_exists():
            self.print_toggle_btn.config(
                text=f"Printing: {'ON' if self.print_enabled else 'OFF'}",
                bg="#2E7D32" if self.print_enabled else "#C62828"
            )
        print(f"Printing toggled to: {'ON' if self.print_enabled else 'OFF'}")

    def show_rfid_screen(self):
        self.clear_container()
        self.active_token = None
        self.challenge_counts_by_election = {}
        
        # Background
        frame = tk.Frame(self.main_container, bg="black") # Dark bg for image
        frame.pack(expand=True, fill=tk.BOTH)
        
        try:
            from PIL import Image, ImageTk
            
            # Load Image using absolute path
            import os
            base_dir = os.path.dirname(os.path.abspath(__file__))
            img_path = os.path.join(base_dir, "scan_card_bg.png")
            
            pil_image = Image.open(img_path)
            
            # Resize logic (Aspect Ratio)
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            
            # Use a slightly smaller area to leave room for buttons if needed
            target_w = screen_w
            target_h = screen_h
            
            # Resize
            pil_image = pil_image.resize((target_w, target_h), Image.Resampling.LANCZOS)
            
            self.rfid_bg_image = ImageTk.PhotoImage(pil_image) # Keep reference
            
            # Image Label
            img_label = tk.Label(frame, image=self.rfid_bg_image, bg="black")
            img_label.place(x=0, y=0, relwidth=1, relheight=1)
            
        except Exception as e:
            print(f"Image Load Error: {e}")
            tk.Label(frame, text="Please Scan Card", font=('Helvetica', 32), fg="white", bg="black").pack(expand=True)

        # Overlay Status Label (Bottom Center)
        self.rfid_status_label = tk.Label(frame, text="Waiting for Card...", font=('Helvetica', 16, 'italic'), bg="#333", fg="#fff", padx=20, pady=5)
        self.rfid_status_label.place(relx=0.5, rely=0.9, anchor=tk.CENTER)
        
        # Dev Skip Button (Top Right, discreet)
        tk.Button(frame, text="[DEV] Skip", font=('Helvetica', 10), command=self.skip_rfid_check, bg="#444", fg="white").place(relx=0.95, rely=0.05, anchor=tk.NE)
        
        # Dev Reset Log Button (Top Left, discreet)
        tk.Button(frame, text="[DEV] Reset Log", font=('Helvetica', 10), command=self.reset_token_log, bg="#ffcccb", fg="black").place(relx=0.05, rely=0.05, anchor=tk.NW)

        # Print toggle for testing (no paper mode).
        self.print_toggle_btn = tk.Button(
            frame,
            text=f"Printing: {'ON' if self.print_enabled else 'OFF'}",
            font=('Helvetica', 12, 'bold'),
            command=self.toggle_printing,
            bg="#2E7D32" if self.print_enabled else "#C62828",
            fg="white",
            padx=10,
            pady=5
        )
        self.print_toggle_btn.place(relx=0.5, rely=0.05, anchor=tk.N)
        
        # Admin Button to End Election (Bottom Right)
        tk.Button(frame, text="End Election & Export", font=('Helvetica', 12, 'bold'), 
                  command=self.end_election, bg="#ff4c4c", fg="white", 
                  padx=10, pady=5).place(relx=0.95, rely=0.95, anchor=tk.SE)
        
        # Start Scanning Thread
        self.stop_scanning = False
        self.scan_queue = queue.Queue()
        self.scan_thread = threading.Thread(target=self.rfid_scan_loop)
        self.scan_thread.daemon = True
        self.scan_thread.start()
        
        self.check_scan_queue()

    def rfid_scan_loop(self):
        while not self.stop_scanning:
            # Blocking read (or semi-active loop)
            result = self.rfid_service.read_card() 
            if result:
                # uid, token
                self.scan_queue.put(result)
                break
            time.sleep(0.5) 

    def check_scan_queue(self):
        try:
            result = self.scan_queue.get_nowait()
            if result:
                 uid, token = result
                 self.on_card_scanned(token)
                 return
        except queue.Empty:
            pass
            
        if not self.active_token: 
             self.root.after(500, self.check_scan_queue)

    def reset_token_log(self):
        try:
            import os
            token_log = getattr(self.data_handler, 'token_log_file', "tokens.log")
            if os.path.exists(token_log):
                os.remove(token_log)
                messagebox.showinfo("Dev Tool", "Token Log Cleared!\nAll cards can be used again.")
            else:
                messagebox.showinfo("Dev Tool", "Token Log is already empty.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to reset log: {e}")

    def skip_rfid_check(self):
        self.stop_scanning = True
        # Simulate a dev token that grants access to election_id_1 and election_id_2.
        payload = '{"token_id": "DEV_SKIP_' + str(int(time.time())) + '", "eid_vector": "election_id_1;election_id_2"}'
        self.on_card_scanned(payload)

    def _normalize_election_id(self, election_id):
        """Map token election IDs to local election folder names."""
        if not election_id:
            return election_id

        eid = str(election_id).strip()
        local_root = "elections"

        # Exact folder name already available.
        if os.path.isdir(os.path.join(local_root, eid)):
            return eid

        # Legacy E<number> -> election_id_<number>
        if eid.upper().startswith("E") and eid[1:].isdigit():
            mapped = f"election_id_{int(eid[1:])}"
            if os.path.isdir(os.path.join(local_root, mapped)):
                return mapped

        # Keep original as fallback to preserve existing behavior/error messaging.
        return eid

    def on_card_scanned(self, token_payload):
        # 0. Check Printer Status First
        if hasattr(self.printer_service, 'is_printer_connected') and not self.printer_service.is_printer_connected():
            print("❌ Printer not connected. Rejecting voter session.")
            self.show_rfid_error("Printer Error\nPlease check printer connection.")
            return

        # 1. Parse Token ID & EID Vector
        import json
        token_id = token_payload
        eid_vector_str = ""
        self.current_voter_id = token_id
        self.current_token_id = token_id
        self.current_booth = 1
        
        try:
            data = json.loads(token_payload)
            if isinstance(data, dict):
                if 'token_id' in data:
                    token_id = data['token_id']
                    self.current_token_id = token_id

                if 'eid_vector' in data:
                    if isinstance(data['eid_vector'], list):
                        eid_vector_str = ";".join(str(x) for x in data['eid_vector'])
                    else:
                        eid_vector_str = str(data['eid_vector'])

                if 'voter_id' in data:
                    self.current_voter_id = data['voter_id']
                elif 'entry_number' in data:
                    self.current_voter_id = data['entry_number']

                if 'booth' in data:
                    self.current_booth = data['booth']

            elif isinstance(data, list):
                # Array payload support: [token_id, voter_id, eid_vector, booth]
                if len(data) > 0 and data[0] is not None:
                    token_id = data[0]
                    self.current_token_id = token_id
                if len(data) > 1 and data[1] is not None:
                    self.current_voter_id = data[1]
                if len(data) > 2 and data[2] is not None:
                    if isinstance(data[2], list):
                        eid_vector_str = ";".join(str(x) for x in data[2])
                    else:
                        eid_vector_str = str(data[2])
                if len(data) > 3 and data[3] is not None:
                    self.current_booth = data[3]

            # Normalize IDs to string for consistent logging.
            token_id = str(token_id)
            self.current_token_id = str(self.current_token_id)
            self.current_voter_id = str(self.current_voter_id)
        except:
            pass
            
        # 2. Check Verification
        if self.data_handler.is_token_used(token_id):
            print(f"❌ Token {token_id} already used!")
            self.show_rfid_error("Token Already Used\nVoter has already cast a vote.")
            return

        self.active_token = token_payload
        # Fresh voter session => reset per-election challenge counters.
        self.challenge_counts_by_election = {}
        
        # 3. Setup Election Queue
        if eid_vector_str:
            # Parse "E1;E3;E6" -> ["E1", "E3", "E6"]
            # Clean up whitespace and empty strings
            parsed_ids = [e.strip() for e in eid_vector_str.split(';') if e.strip()]
            self.election_queue = [self._normalize_election_id(eid) for eid in parsed_ids]
        else:
            # Fallback if no vector provided (e.g. legacy card or dev skip)
            # We can define a default or assume single legacy mode
            self.election_queue = [] 

        if not self.election_queue:
            # STRICT MODE: If token has no elections, Access Denied.
            print("❌ No elections found in token vector.")
            self.show_rfid_error("Access Denied\nNo valid elections found for this voter.")
            return

        self.start_next_election()

    def start_next_election(self):
        if not self.election_queue:
            # Queue Done -> Finish Session
            self.finish_voter_session()
            return

        # Pop next election
        self.current_election_id = self.election_queue.pop(0)
        print(f"Starting Election Context: {self.current_election_id}")
        
        # Start Session for this election
        success = self.start_session(self.current_election_id)
        
        if success:
            # Switch modes automatically based on parsed ballot JSON!
            is_pair_layout = bool(getattr(self.data_handler, 'pref_combo_map', {}))
            is_preferential = hasattr(self.data_handler, 'is_preferential_election') and self.data_handler.is_preferential_election()

            if is_preferential or is_pair_layout:
                self.start_preferential_voting()
            else:
                self.start_normal_voting()
        else:
            # Abort session and return to home screen
            self.election_queue = []
            self.active_token = None
            self.current_election_id = None
            self.show_rfid_screen()

    def finish_voter_session(self, aborted=False):
        """Called when all eligible elections are completed."""
        # 1. BATCH PRINTING IF ENABLED
        if not aborted and self.merge_receipts and hasattr(self, 'receipt_buffer') and self.receipt_buffer and self.print_enabled:
            self.show_printing_modal(text="Printing Consolidated Receipt...")
            
            self.batch_print_queue = queue.Queue()
            
            def batch_printer_worker(receipts):
                try:
                    self.printer_service.print_session_receipts(receipts)
                    self.batch_print_queue.put(True)
                except Exception as e:
                    self.batch_print_queue.put(e)

            self.batch_print_thread = threading.Thread(target=batch_printer_worker, args=(self.receipt_buffer,))
            self.batch_print_thread.daemon = True
            self.batch_print_thread.start()
            
            self.batch_print_start_time = datetime.datetime.now()
            self.check_batch_print_status(aborted)
            return

        # If printing is disabled, persist buffered votes without printing.
        if not aborted and self.merge_receipts and hasattr(self, 'receipt_buffer') and self.receipt_buffer and not self.print_enabled:
            all_records = [entry.get('vote_record') for entry in self.receipt_buffer if entry.get('vote_record')]
            for r in all_records:
                self.data_handler.save_json(r)
            self.receipt_buffer = []

        self._finalize_session(aborted)

    def check_batch_print_status(self, aborted=False):
        try:
            result = self.batch_print_queue.get_nowait()
            self.close_printing_modal()
            if result is True:
                # 2. Log Votes (Only if Print Succeeded)
                all_records = []
                for entry in self.receipt_buffer:
                    if 'vote_record' in entry:
                         all_records.append(entry['vote_record'])
                
                if all_records:
                    for r in all_records:
                        self.data_handler.save_json(r)
                self.receipt_buffer = []
                self._finalize_session(aborted)
            else:
                print(f"Batch print error: {result}")
                retry = messagebox.askretrycancel("Printer Error", f"Failed to print session receipt: {result}\n\nRetry?")
                if retry:
                    self.finish_voter_session(aborted)
                else:
                    self.receipt_buffer = []
                    # Pass True so we don't log votes if the receipt failed to print!
                    self._finalize_session(True)
            return
        except queue.Empty:
            pass

        elapsed = (datetime.datetime.now() - self.batch_print_start_time).total_seconds()
        if elapsed > 60:
            self.close_printing_modal()
            retry = messagebox.askretrycancel("Printer Timeout", "Printer is taking too long.\n\nRetry?")
            if retry:
                self.finish_voter_session(aborted)
            else:
                self.receipt_buffer = []
                self._finalize_session(True)
            return

        self.root.after(500, self.check_batch_print_status, aborted)

    def _finalize_session(self, aborted=False):
        # 2. LOG SESSION TOKEN
        if not aborted and self.active_token:
            self.data_handler.log_token(self.active_token)
            
        if not aborted:
            messagebox.showinfo("Session Complete", "Thank you for voting in all elections!")
        else:
            messagebox.showinfo("Session Aborted", "Your session has been cancelled.")
            
        self.active_token = None
        self.current_election_id = None
        self.show_rfid_screen()

    def show_rfid_error(self, message):
        self.clear_container()
        frame = tk.Frame(self.main_container, bg="#FFEBEE") # Reddish bg
        frame.pack(expand=True, fill=tk.BOTH)
        
        tk.Label(frame, text="❌ Access Denied", font=('Helvetica', 32, 'bold'), bg="#FFEBEE", fg="#D32F2F").pack(pady=(150, 20))
        tk.Label(frame, text=message, font=('Helvetica', 24), bg="#FFEBEE", fg="#555").pack(pady=20)
        
        # Auto-retry after 3 seconds
        tk.Label(frame, text="(Resetting in 3 seconds...)", font=('Helvetica', 16), bg="#FFEBEE", fg="#777").pack(pady=40)
        self.root.after(3000, self.show_rfid_screen)

    def start_session(self, election_id=None):
        """Fetches a fresh ballot for the new session."""
        try:
            new_id, new_file = self.ballot_manager.get_unused_ballot(election_id)
            print(f"Starting Session for {election_id} with Ballot ID: {new_id}")
            self.data_handler.set_ballot_file(new_file)
            return True
        except Exception as e:
            print(f"Failed to load new ballot: {e}")
            messagebox.showerror("Ballot Error", f"Could not load new ballot for {election_id}: {e}")
            return False

    # --- Voting Modes ---

    def start_normal_voting(self):
        # self.start_session() # Already started in start_next_election
        self.voting_mode = 'normal'
        self.selections = {}
        self.current_rank = 1
        self.show_selection_screen()

    def start_preferential_voting(self):
        # self.start_session()
        self.voting_mode = 'preferential'
        self.selections = {}
        self.current_rank = 1
        self.max_ranks = max(1, getattr(self.data_handler, 'max_preferences', len(self.data_handler.candidates_base) - 1))
        self.show_selection_screen()

    def show_selection_screen(self):
        self.clear_container()
        
        header_bg = "#E3F2FD" if self.voting_mode == 'normal' else "#F3E5F5"
        header = tk.Frame(self.main_container, bg=header_bg, pady=5)
        header.pack(fill=tk.X)
        
        mode_text = "Single Choice Vote" if self.voting_mode == 'normal' else f"Select Preference #{self.current_rank}"
        
        # Dynamic Header
        e_name = getattr(self.data_handler, 'election_name', 'General Election')
        e_id = getattr(self.data_handler, 'election_id', 'E01')
        short_ballot_id = self.data_handler.get_short_ballot_id()
        
        tk.Label(header, text=e_name, font=('Helvetica', 16, 'bold'), bg=header_bg).pack()
        tk.Label(header, text=f"Election ID: {e_id} | Ballot ID: {short_ballot_id}", font=('Helvetica', 10), bg=header_bg, fg="#555").pack()
        tk.Label(header, text=mode_text, font=('Helvetica', 20, 'bold'), bg=header_bg, fg="#333").pack(pady=2)
        
        content = tk.Frame(self.main_container, bg="#ffffff", pady=5, padx=20)
        content.pack(expand=True, fill=tk.BOTH)
        
        self.current_selection_var = tk.IntVar(value=-1)
        if self.current_rank in self.selections:
             self.current_selection_var.set(self.selections[self.current_rank])

        # In preferential pair-layout ballots, each rank screen may have a different
        # unique candidate set (rank-1 options vs rank-2 options).
        if self.voting_mode == 'preferential' and hasattr(self.data_handler, 'get_candidates_for_rank'):
            available_candidates = self.data_handler.get_candidates_for_rank(self.current_rank)
        else:
            available_candidates = self.data_handler.candidates_base

        total_options = len(available_candidates)
        rows_per_col = (total_options + 1) // 2
        
        if total_options > 8:
            btn_font = ('Helvetica', 12); btn_pady = 2; frame_pady = 2
        elif total_options > 6:
            btn_font = ('Helvetica', 14); btn_pady = 4; frame_pady = 4
        else:
            btn_font = ('Helvetica', 16); btn_pady = 8; frame_pady = 6

        for idx, cand in enumerate(available_candidates):
            is_nota = hasattr(self.data_handler, '_is_nota_name') and self.data_handler._is_nota_name(cand.get('name'))
            cand_text = f"{cand['id']}. {cand['name']}"
            if cand.get('candidate_number'):
                cand_text += f"\n{cand['candidate_number']}"
            
            fg_color = "black"
            if is_nota: fg_color = "#D32F2F"

            row = idx % rows_per_col
            col = idx // rows_per_col
            
            frame = tk.Frame(content, bg="white")
            frame.grid(row=row, column=col, padx=10, pady=frame_pady, sticky="nsew")
            content.grid_columnconfigure(col, weight=1)
            content.grid_rowconfigure(row, weight=1)

            state_val = tk.NORMAL
            bg_color = "white"
            
            # Preferential Mode: Gray out candidates already selected in previous ranks
            if self.voting_mode == 'preferential':
                selected_rank = None
                for rank, cid in self.selections.items():
                    if rank < self.current_rank and cid == cand['id']:
                        selected_rank = rank
                        break
                
                # Disable the button if selected previously AND it is not NOTA/NAFS.
                if selected_rank is not None and not is_nota:
                    state_val = tk.DISABLED
                    bg_color = "#e0e0e0"
                    fg_color = "#888888"
                    cand_text += f"\n(Rank {selected_rank})"

            tk.Radiobutton(
                frame, text=cand_text, variable=self.current_selection_var, value=cand['id'],
                indicatoron=0, font=btn_font, bg=bg_color, fg=fg_color,
                selectcolor='#e8f5e9', activebackground='#f5f5f5',
                padx=10, pady=btn_pady, bd=2, relief=tk.RAISED,
                justify=tk.CENTER, state=state_val
            ).pack(fill=tk.BOTH, expand=True)

        footer = tk.Frame(self.main_container, bg="#f0f0f0")
        footer.pack(fill=tk.X, side=tk.BOTTOM, pady=10)

        if self.voting_mode == 'normal':
             tk.Button(footer, text="Review Vote", font=('Helvetica', 16, 'bold'), bg="#4CAF50", fg="white", command=self.go_next, padx=15, pady=8).pack(side=tk.RIGHT, padx=30)
             tk.Button(footer, text="Cancel", font=('Helvetica', 16), command=self.abort_session, padx=15, pady=8, fg="red").pack(side=tk.LEFT, padx=30)
        else:
            if self.current_rank > 1:
                tk.Button(footer, text="< Previous", font=('Helvetica', 16), command=self.go_previous, padx=15, pady=8).pack(side=tk.LEFT, padx=30)
            else:
                 tk.Button(footer, text="Cancel", font=('Helvetica', 16), command=self.abort_session, padx=15, pady=8, fg="red").pack(side=tk.LEFT, padx=30)

            next_text = "Next >" if self.current_rank < self.max_ranks else "Finish"
            tk.Button(footer, text=next_text, font=('Helvetica', 16, 'bold'), bg="#2196F3", fg="white", command=self.go_next, padx=15, pady=8).pack(side=tk.RIGHT, padx=30)

    def abort_session(self):
        """Cancels the voter's session entirely without casting the current vote and clears queue."""
        self.election_queue = []
        self.receipt_buffer = [] # Clear unprinted receipts from this session
        self.finish_voter_session(aborted=True)

    def go_next(self):
        selection = self.current_selection_var.get()
        if selection == -1:
            messagebox.showwarning("No Selection", "Please make a selection to proceed.")
            return

        if selection != 0:
            ranks_to_clear = [r for r, cid in self.selections.items() if r > self.current_rank and cid == selection]
            for r in ranks_to_clear:
                del self.selections[r]

        self.selections[self.current_rank] = selection
        
        if self.voting_mode == 'normal':
            self.show_confirmation_screen()
        else:
            if self.current_rank < self.max_ranks:
                self.current_rank += 1
                self.show_selection_screen()
            else:
                self.show_confirmation_screen()

    def go_previous(self):
        if self.current_rank > 1:
            self.current_rank -= 1
            self.show_selection_screen()

    def show_confirmation_screen(self):
        self.clear_container()
        header = tk.Frame(self.main_container, bg="#f0f0f0", pady=10)
        header.pack(fill=tk.X)
        tk.Label(header, text="Confirm Your Vote", font=('Helvetica', 24, 'bold'), bg="#f0f0f0").pack()

        content = tk.Frame(self.main_container, bg="#ffffff", pady=10)
        content.pack(expand=True)

        if self.voting_mode == 'normal':
            cid = self.selections.get(1)
            cand = self.data_handler.get_candidate_by_id(cid)
            tk.Label(content, text="You have selected:", font=('Helvetica', 16), bg="white").pack(pady=5)
            f = tk.Frame(content, bg="#e8f5e9", bd=2, relief=tk.SOLID, padx=30, pady=15)
            f.pack(pady=10)
            
            # Show Serial ID (The number displayed on the ballot)
            serial_num = str(cand['id'])
            tk.Label(f, text=f"Choice: {serial_num}", font=('Helvetica', 28, 'bold'), bg="#e8f5e9", fg="#333").pack()
            name_row = tk.Frame(f, bg="#e8f5e9")
            name_row.pack(pady=5)
            tk.Label(name_row, text=cand['name'], font=('Helvetica', 22), bg="#e8f5e9").pack(side=tk.LEFT)
            if cand.get('candidate_number'):
                tk.Label(
                    name_row,
                    text=f"({cand['candidate_number']})",
                    font=('Helvetica', 14, 'italic'),
                    fg="#666",
                    bg="#e8f5e9"
                ).pack(side=tk.LEFT, padx=(8, 0))
        else:
            for rank in range(1, self.max_ranks + 1):
                cid = self.selections.get(rank)
                cand = self.data_handler.get_candidate_by_id(cid)
                row = tk.Frame(content, bg="white", pady=5)
                row.pack(fill=tk.X)
                row.grid_columnconfigure(0, weight=0)
                row.grid_columnconfigure(1, weight=1)
                row.grid_columnconfigure(2, weight=0)
                if cand:
                    tk.Label(
                        row,
                        text=f"Preference {rank})",
                        font=('Helvetica', 18, 'bold'),
                        fg="#666",
                        bg="white",
                        anchor='w'
                    ).grid(row=0, column=0, sticky='w', padx=(10, 12))
                    candidate_number = cand.get('candidate_number')
                    candidate_col = tk.Frame(row, bg="white")
                    candidate_col.grid(row=0, column=1, sticky='w')
                    tk.Label(
                        candidate_col,
                        text=cand['name'],
                        font=('Helvetica', 20),
                        bg="white",
                        anchor='w'
                    ).pack(side=tk.LEFT)
                    if candidate_number:
                        tk.Label(
                            candidate_col,
                            text=f"({candidate_number})",
                            font=('Helvetica', 14, 'italic'),
                            fg="#666",
                            bg="white"
                        ).pack(side=tk.LEFT, padx=(6, 0))
                    tk.Label(
                        row,
                        text=f"Choice Number {cand['id']}",
                        font=('Helvetica', 16, 'italic'),
                        fg="#666",
                        bg="white",
                        anchor='w'
                    ).grid(row=0, column=2, sticky='w', padx=(18, 10))
                else:
                     tk.Label(
                         row,
                         text=f"Preference {rank})",
                         font=('Helvetica', 18, 'bold'),
                         fg="#666",
                         bg="white",
                         anchor='w'
                     ).grid(row=0, column=0, sticky='w', padx=(10, 12))
                     tk.Label(
                         row,
                         text="[No Selection]",
                         font=('Helvetica', 20),
                         fg="#aaa",
                         bg="white",
                         anchor='w'
                     ).grid(row=0, column=1, sticky='w')

        footer = tk.Frame(self.main_container, bg="#f0f0f0", pady=15)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        
        edit_cmd = self.show_selection_screen if self.voting_mode == 'normal' else self.restart_editing
        tk.Button(footer, text="Edit", font=('Helvetica', 16), command=edit_cmd, padx=20, pady=10).pack(side=tk.LEFT, padx=30)
        tk.Button(footer, text="CAST VOTE", font=('Helvetica', 16, 'bold'), bg="#4CAF50", fg="white", command=self.cast_vote, padx=20, pady=10).pack(side=tk.RIGHT, padx=30)
        current_challenges = self.challenge_counts_by_election.get(self.current_election_id, 0)
        if current_challenges < self.max_challenges_per_election:
            tk.Button(footer, text="CHALLENGE", font=('Helvetica', 16, 'bold'), bg="#FF9800", fg="white", command=self.challenge_vote, padx=20, pady=10).pack(side=tk.RIGHT, padx=10)
        else:
            tk.Button(footer, text="CHALLENGE USED", font=('Helvetica', 16, 'bold'), bg="#BDBDBD", fg="#444", state=tk.DISABLED, padx=20, pady=10).pack(side=tk.RIGHT, padx=10)

    def restart_editing(self):
        self.current_rank = 1
        self.show_selection_screen()

    def cast_vote(self):
        # Prepare Receipt Data Snapshot
        e_name = getattr(self.data_handler, 'election_name', 'General Election')
        ballot_id = self.data_handler.get_short_ballot_id()
        timestamp = datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")

        # Helper to find candidate display string (Captured now!)
        def get_cand_display(cid):
            cand = self.data_handler.get_candidate_by_id(cid)
            if cand:
                # User wants ONLY Serial ID on receipt (No Name)
                return str(cand['id'])
            return str(cid)

        # Prepare strings
        if self.voting_mode == 'normal':
            cid = self.selections.get(1)
            sel_str = get_cand_display(cid)
            qr_data = self.data_handler.build_receipt_qr_payload(self.selections, self.voting_mode)
        else:
            ranks = sorted(self.selections.keys())
            vals = []
            for r in ranks:
                c = self.selections[r]
                vals.append(get_cand_display(c))
            sel_str = ", ".join(vals)
            qr_data = self.data_handler.build_receipt_qr_payload(self.selections, self.voting_mode)

        # Pre-generate log JSON while context is valid
        vote_record = self.data_handler.generate_vote_json(
            {'selections': self.selections, 'timestamp': timestamp},
            self.voting_mode,
            getattr(self, 'current_voter_id', 'UNKNOWN'),
            getattr(self, 'current_booth', 1),
            getattr(self, 'current_token_id', 'UNKNOWN')
        )

        # Voter receipt QR should contain only selected commitment.
        voter_qr_data = qr_data

        receipt_entry = {
            'election_id': getattr(self.data_handler, 'election_id', '???'),
            'election_name': e_name,
            'ballot_id': ballot_id,
            'timestamp': timestamp,
            'choice_str': sel_str,
            'qr_choice_data': qr_data,
            'voter_qr_data': voter_qr_data,
            'election_hash': self.data_handler.election_hash,
            # Data for deferred logging
            'vote_record': vote_record,
            'internal_ballot_id': ballot_id
        }

        # MERGE LOGIC
        if self.merge_receipts:
            self.receipt_buffer.append(receipt_entry)

            # Show "Saving..." briefly
            self.show_printing_modal(text="Recording Vote...")

            # Simulate Success (Skip Printer Thread)
            self.print_queue = queue.Queue()
            self.print_queue.put(True)
            self.print_start_time = datetime.datetime.now()
            self.check_print_status()

        else:
            # NORMAL PRINTING
            if not self.print_enabled:
                self.data_handler.save_json(vote_record)
                self.finish_voter_session(False)
                return

            self.show_printing_modal()
            self.print_queue = queue.Queue()

            def printer_worker(mode, sel):
                try:
                    self.printer_service.print_vote(mode, sel, is_final=True)
                    self.print_queue.put(True)
                except Exception as e:
                    self.print_queue.put(e)

            self.print_thread = threading.Thread(target=printer_worker, args=(self.voting_mode, self.selections))
            self.print_thread.daemon = True
            self.print_thread.start()

            self.print_start_time = datetime.datetime.now()
            self.check_print_status()

    def challenge_vote(self):
        """Voter challenges the ballot: print a challenge receipt (no VVPAT, no vote recorded).

        The ballot is marked CHALLENGED so it cannot be cast or reused.
        The voter sees a receipt showing their ballot ID and selection so they
        can independently verify the cryptographic commitments.
        """
        current_challenges = self.challenge_counts_by_election.get(self.current_election_id, 0)
        if current_challenges >= self.max_challenges_per_election:
            messagebox.showwarning(
                "Challenge Limit Reached",
                "You have already used your one allowed challenge in this election.\n"
                "Please cast your vote."
            )
            return

        if not messagebox.askyesno(
            "Challenge Ballot",
            "Challenging this ballot will:\n\n"
            "\u2022 Print a receipt with your Ballot ID and selection\n"
            "\u2022 NOT count your vote\n"
            "\u2022 Invalidate this ballot (it cannot be used again)\n\n"
            "Do you want to challenge?",
            icon='question'
        ):
            return

        ballot_id = self.data_handler.ballot_id
        timestamp = datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")

        def get_cand_display(cid):
            cand = self.data_handler.get_candidate_by_id(cid)
            return str(cand['id']) if cand else str(cid)

        if self.voting_mode == 'normal':
            cid = self.selections.get(1)
            sel_str = get_cand_display(cid)
        else:
            ranks = sorted(self.selections.keys())
            sel_str = ", ".join(get_cand_display(self.selections[r]) for r in ranks)

        selected_commitment = self.data_handler.build_receipt_qr_payload(self.selections, self.voting_mode)
        election_id_for_qr = str(getattr(self, 'current_election_id', '') or getattr(self.data_handler, 'election_id', ''))
        short_ballot_id = self.data_handler.get_short_ballot_id(ballot_id)

        import json
        voter_qr_data = json.dumps([
            election_id_for_qr,
            short_ballot_id,
            selected_commitment
        ], separators=(",", ":"))

        self.show_printing_modal(text="Printing Challenge Receipt..." if self.print_enabled else "Processing Challenge...")
        self.print_queue = queue.Queue()

        if not self.print_enabled:
            self.print_queue.put(True)
            self.print_start_time = datetime.datetime.now()
            self._check_challenge_print_status()
            return

        def _worker():
            try:
                self.printer_service.print_challenge_receipt(ballot_id, sel_str, voter_qr_data)
                self.print_queue.put(True)
            except Exception as e:
                self.print_queue.put(e)

        t = threading.Thread(target=_worker)
        t.daemon = True
        t.start()

        self.print_start_time = datetime.datetime.now()
        self._check_challenge_print_status()

    def _check_challenge_print_status(self):
        try:
            result = self.print_queue.get_nowait()
            self.close_printing_modal()
            if result is True:
                self.challenge_counts_by_election[self.current_election_id] = (
                    self.challenge_counts_by_election.get(self.current_election_id, 0) + 1
                )
                try:
                    self.ballot_manager.mark_as_challenged(
                        self.data_handler.ballot_file_id,
                        self.current_election_id
                    )
                except Exception as e:
                    print(f"Error marking ballot as challenged: {e}")
                messagebox.showinfo(
                    "Ballot Challenged",
                    (
                        "Your challenge receipt has been printed.\n"
                        "This ballot has been invalidated and will NOT be counted.\n\n"
                        "You may use your receipt to verify the commitments independently."
                        if self.print_enabled else
                        "Printing is OFF, so no challenge receipt was printed.\n"
                        "This ballot has been invalidated and will NOT be counted."
                    )
                )
                while True:
                    satisfied = messagebox.askyesno(
                        "Challenge Verification",
                        "Are you satisfied after the challenge verification?\n\n"
                        "Yes: You will vote again in this same election using a new ballot.\n"
                        "No: Session will be paused/aborted for Presiding Officer review."
                    )
                    chosen_label = "SATISFIED" if satisfied else "NOT SATISFIED"
                    confirmed = messagebox.askyesno(
                        "Confirm Selection",
                        f"You selected: {chosen_label}.\n\n"
                        "Press Yes to confirm this choice, or No to choose again."
                    )
                    if confirmed:
                        break
                if satisfied:
                    self.restart_current_election_after_challenge()
                else:
                    self.show_temporarily_down_screen()
            else:
                self.close_printing_modal()
                retry = messagebox.askretrycancel("Printer Error", f"Printing Failed: {result}\n\nRetry?")
                if retry:
                    self.challenge_vote()
            return
        except queue.Empty:
            elapsed = (datetime.datetime.now() - self.print_start_time).total_seconds()
            if elapsed > 30:
                self.close_printing_modal()
                messagebox.showerror("Timeout", "Challenge receipt print timed out.")
                return
            self.root.after(200, self._check_challenge_print_status)

    def restart_current_election_after_challenge(self):
        """Load a fresh ballot and restart the same election after a successful challenge."""
        if not self.current_election_id:
            messagebox.showerror("Session Error", "No active election context found.")
            self.finish_voter_session(aborted=True)
            return

        success = self.start_session(self.current_election_id)
        if not success:
            self.finish_voter_session(aborted=True)
            return

        e_type = self.data_handler.election_type.lower()
        if "preferential" in e_type or "ranked" in e_type:
            self.start_preferential_voting()
        else:
            self.start_normal_voting()

    def show_temporarily_down_screen(self):
        """Show temporary outage screen and require polling officer RFID to recover."""
        self.clear_container()
        frame = tk.Frame(self.main_container, bg="#FFF3E0")
        frame.pack(expand=True, fill=tk.BOTH)

        tk.Label(
            frame,
            text="Ballot Marking Device is Temporarily Down",
            font=('Helvetica', 30, 'bold'),
            bg="#FFF3E0",
            fg="#E65100",
            wraplength=820,
            justify='center'
        ).pack(pady=(140, 20))

        tk.Label(
            frame,
            text="Polling Officer RFID required to continue.",
            font=('Helvetica', 22),
            bg="#FFF3E0",
            fg="#333"
        ).pack(pady=10)

        tk.Label(
            frame,
            text="Please place officer card on reader...",
            font=('Helvetica', 16, 'italic'),
            bg="#FFF3E0",
            fg="#555"
        ).pack(pady=20)

        tk.Button(
            frame,
            text="Polling Officer Menu",
            font=('Helvetica', 14, 'bold'),
            bg="#1565C0",
            fg="white",
            padx=18,
            pady=8,
            command=self.show_polling_officer_action_menu
        ).pack(pady=10)

        self.stop_scanning = False
        self.officer_scan_queue = queue.Queue()
        self.officer_scan_thread = threading.Thread(target=self.officer_scan_loop)
        self.officer_scan_thread.daemon = True
        self.officer_scan_thread.start()
        self.check_officer_scan_queue()

    def officer_scan_loop(self):
        while not self.stop_scanning:
            result = self.rfid_service.read_card()
            if result:
                self.officer_scan_queue.put(result)
                break
            time.sleep(0.5)

    def check_officer_scan_queue(self):
        if self.stop_scanning:
            return

        try:
            result = self.officer_scan_queue.get_nowait()
            if result:
                uid, token_payload = result
                self.on_officer_card_scanned(token_payload)
                return
        except queue.Empty:
            pass

        self.root.after(500, self.check_officer_scan_queue)

    def _is_polling_officer_token(self, token_payload):
        """Returns True if token payload indicates polling officer/admin authorization."""
        try:
            import json
            data = json.loads(token_payload)
            role = str(data.get('role', '')).strip().lower()
            token_type = str(data.get('token_type', '')).strip().lower()
            is_admin = bool(data.get('is_admin', False))
            if role in {'polling_officer', 'presiding_officer', 'officer', 'admin'}:
                return True
            if token_type in {'polling_officer', 'presiding_officer', 'admin'}:
                return True
            if is_admin:
                return True
            return False
        except Exception:
            return False

    def on_officer_card_scanned(self, token_payload):
        if not self._is_polling_officer_token(token_payload):
            messagebox.showerror(
                "Authorization Failed",
                "This card is not authorized as Polling Officer.\n"
                "Please scan a valid officer RFID card."
            )
            self.stop_scanning = False
            self.officer_scan_queue = queue.Queue()
            self.officer_scan_thread = threading.Thread(target=self.officer_scan_loop)
            self.officer_scan_thread.daemon = True
            self.officer_scan_thread.start()
            self.check_officer_scan_queue()
            return

        self.stop_scanning = True
        self.show_polling_officer_action_menu()

    def show_polling_officer_action_menu(self):
        self.stop_scanning = True
        continue_election = messagebox.askyesno(
            "Officer Action Required",
            "Polling Officer menu.\n\n"
            "Yes: Continue election for this voter with a fresh ballot.\n"
            "No: Permanently stop election (End Election & Export)."
        )

        if continue_election:
            self.restart_current_election_after_challenge()
        else:
            self.end_election()

    def show_printing_modal(self, text="Printing VVPAT Receipt..."):
        self.printing_overlay = tk.Toplevel(self.root)
        self.printing_overlay.title("Processing")
        w, h = 400, 200
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.printing_overlay.geometry(f"{w}x{h}+{x}+{y}")
        self.printing_overlay.transient(self.root)
        self.printing_overlay.grab_set()
        self.printing_overlay.overrideredirect(True)
        f = tk.Frame(self.printing_overlay, bg="#E3F2FD", bd=2, relief=tk.RAISED)
        f.pack(fill=tk.BOTH, expand=True)
        tk.Label(f, text=text, font=('Helvetica', 16, 'bold'), bg="#E3F2FD").pack(pady=30)
        tk.Label(f, text="Please Wait", font=('Helvetica', 14), bg="#E3F2FD").pack(pady=10)

    def close_printing_modal(self):
        if hasattr(self, 'printing_overlay') and self.printing_overlay:
            self.printing_overlay.destroy()
            self.printing_overlay = None

    def check_print_status(self):
        try:
            result = self.print_queue.get_nowait()
            self.close_printing_modal()
            if result is True:
                # Save vote
                try:
                    # Defer saving if merging
                    if not self.merge_receipts:
                        vote_data = {'selections': self.selections}
                        self.data_handler.save_vote(
                            vote_data, 
                            self.voting_mode,
                            getattr(self, 'current_voter_id', 'UNKNOWN'),
                            getattr(self, 'current_booth', 1),
                            getattr(self, 'current_token_id', 'UNKNOWN')
                        )
                    
                    # Mark ballot as used for this election (ALWAYS MARK USED TO PREVENT REUSE)
                    # Wait, if print fails at the end, we might have an issue. 
                    # But for now, we must mark it used so it's not given again during the session?
                    # No, the buffer holds it. 
                    # Actually, if we mark it used now, and the final print fails, we can't rollback easily.
                    # But preventing reuse is critical.
                    # Let's Mark USed now. The risk is a wasted ballot on print fail. Acceptable.
                    self.ballot_manager.mark_as_used(self.data_handler.ballot_file_id, self.current_election_id)
                    self.data_handler.store_used_ballot_snapshot(
                        election_id=self.current_election_id,
                        ballot_file_id=self.data_handler.ballot_file_id,
                        status="USED"
                    )
                    
                    if not self.merge_receipts:
                        messagebox.showinfo("Vote Cast", "Your vote has been verified and recorded successfully!")
                    
                    # Proceed to Next Election in Queue (or Finish)
                    self.start_next_election()
                    
                except Exception as e:
                    messagebox.showerror("System Error", f"Vote recorded but processing failed: {e}")
            else:
                print(f"Async print error: {result}")
                retry = messagebox.askretrycancel("Printer Error", f"Printing Failed: {result}\n\nRetry?")
                if retry:
                    self.cast_vote()
            return
        except queue.Empty:
            pass

        elapsed = (datetime.datetime.now() - self.print_start_time).total_seconds()
        if elapsed > 20:
            self.close_printing_modal()
            retry = messagebox.askretrycancel("Printer Timeout", "Printer is taking too long.\n\nRetry?")
            if retry:
                self.cast_vote()
            return

        self.root.after(500, self.check_print_status)

    def exit_app(self, event=None):
        self.root.quit()
