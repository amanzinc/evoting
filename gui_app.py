import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue
import datetime
import time

class VotingApp:
    def __init__(self, root, data_handler, printer_service, ballot_manager, rfid_service):
        self.root = root
        self.data_handler = data_handler
        self.printer_service = printer_service
        self.ballot_manager = ballot_manager
        self.rfid_service = rfid_service
        self.active_token = None
        
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

        self.main_container = tk.Frame(self.root, bg="#ffffff")
        self.main_container.pack(fill=tk.BOTH, expand=True)
        
        # Initialize RFID
        self.rfid_service.load_key()
        self.rfid_service.connect()

        try:
            self.data_handler.load_candidates()
        except Exception as e:
            messagebox.showerror("Initialization Error", str(e))

        # Start with RFID Screen
        self.show_rfid_screen()

    def clear_container(self):
        for widget in self.main_container.winfo_children():
            widget.destroy()

    def show_rfid_screen(self):
        self.clear_container()
        self.active_token = None
        
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
            if os.path.exists("tokens.log"):
                os.remove("tokens.log")
                messagebox.showinfo("Dev Tool", "Token Log Cleared!\nAll cards can be used again.")
            else:
                messagebox.showinfo("Dev Tool", "Token Log is already empty.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to reset log: {e}")

    def skip_rfid_check(self):
        self.stop_scanning = True
        # Simulate Multi-Election Token
        payload = '{"token_id": "DEV_SKIP_' + str(int(time.time())) + '", "eid_vector": "E1;E3;E6"}'
        self.on_card_scanned(payload)

    def on_card_scanned(self, token_payload):
        # 1. Parse Token ID & EID Vector
        import json
        token_id = token_payload
        eid_vector_str = ""
        self.current_voter_id = token_id
        self.current_booth = 1
        
        try:
            data = json.loads(token_payload)
            if 'token_id' in data:
                token_id = data['token_id']
            if 'eid_vector' in data:
                eid_vector_str = data['eid_vector']
            if 'entry_number' in data:
                self.current_voter_id = data['entry_number']
            if 'booth' in data:
                self.current_booth = data['booth']
        except:
            pass
            
        # 2. Check Verification
        if self.data_handler.is_token_used(token_id):
            print(f"❌ Token {token_id} already used!")
            self.show_rfid_error("Token Already Used\nVoter has already cast a vote.")
            return

        self.active_token = token_payload
        
        # 3. Setup Election Queue
        if eid_vector_str:
            # Parse "E1;E3;E6" -> ["E1", "E3", "E6"]
            # Clean up whitespace and empty strings
            self.election_queue = [e.strip() for e in eid_vector_str.split(';') if e.strip()]
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
            e_type = self.data_handler.election_type.lower()
            if "preferential" in e_type or "ranked" in e_type:
                self.start_preferential_voting()
            else:
                self.start_normal_voting()
        else:
            # Abort session and return to home screen
            self.election_queue = []
            self.active_token = None
            self.current_election_id = None
            self.show_rfid_screen()

    def finish_voter_session(self):
        """Called when all eligible elections are completed."""
        # 1. BATCH PRINTING IF ENABLED
        if self.merge_receipts and hasattr(self, 'receipt_buffer') and self.receipt_buffer:
            self.show_printing_modal(text="Printing Consolidated Receipt...")
            try:
                # 1. Print
                self.printer_service.print_session_receipts(self.receipt_buffer)
                
                # 2. Log Votes (Only if Print Succeeded)
                all_records = []
                for entry in self.receipt_buffer:
                    if 'vote_record' in entry:
                         all_records.append(entry['vote_record'])
                
                if all_records:
                    for r in all_records:
                        self.data_handler.save_json(r)
                
            except Exception as e:
                messagebox.showerror("Print Error", f"Failed to print session receipt: {e}")
                self.close_printing_modal()
                return # Stop here so we can retry or investigate

            finally:
                self.close_printing_modal()
                self.receipt_buffer = []


        # 2. LOG SESSION TOKEN
        if self.active_token:
            self.data_handler.log_token(self.active_token)
            
        messagebox.showinfo("Session Complete", "Thank you for voting in all elections!")
        
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
        self.max_ranks = max(1, len(self.data_handler.candidates_base) - 1)
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
        
        tk.Label(header, text=e_name, font=('Helvetica', 16, 'bold'), bg=header_bg).pack()
        tk.Label(header, text=f"Election ID: {e_id} | Ballot ID: {self.data_handler.ballot_id}", font=('Helvetica', 10), bg=header_bg, fg="#555").pack()
        tk.Label(header, text=mode_text, font=('Helvetica', 20, 'bold'), bg=header_bg, fg="#333").pack(pady=2)
        
        content = tk.Frame(self.main_container, bg="#ffffff", pady=5, padx=20)
        content.pack(expand=True, fill=tk.BOTH)
        
        self.current_selection_var = tk.IntVar(value=-1)
        if self.current_rank in self.selections:
             self.current_selection_var.set(self.selections[self.current_rank])

        # In both modes, we render all options.
        # For preferential, we will disable the previously selected ones instead of hiding them.
        all_opts = self.data_handler.candidates_base
        available_candidates = all_opts

        total_options = len(available_candidates)
        rows_per_col = (total_options + 1) // 2
        
        if total_options > 8:
            btn_font = ('Helvetica', 12); btn_pady = 2; frame_pady = 2
        elif total_options > 6:
            btn_font = ('Helvetica', 14); btn_pady = 4; frame_pady = 4
        else:
            btn_font = ('Helvetica', 16); btn_pady = 8; frame_pady = 6

        for idx, cand in enumerate(available_candidates):
            is_nota = (cand['name'] == "NAFS")
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
                
                # Disable the button if selected previously AND it is not NAFS/NOTA
                if selected_rank is not None and cand['name'] != "NAFS":
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
            tk.Label(f, text=cand['name'], font=('Helvetica', 22), bg="#e8f5e9").pack(pady=5)
        else:
            for rank in range(1, self.max_ranks + 1):
                cid = self.selections.get(rank)
                cand = self.data_handler.get_candidate_by_id(cid)
                row = tk.Frame(content, bg="white", pady=5)
                row.pack(fill=tk.X)
                if cand:
                    tk.Label(row, text=f"{rank}.", font=('Helvetica', 20, 'bold'), fg="#666", width=4, bg="white").pack(side=tk.LEFT)
                    t = cand['name'] if cand['id'] == 0 else f"{cand['id']}. {cand['name']}"
                    tk.Label(row, text=t, font=('Helvetica', 20), bg="white").pack(side=tk.LEFT, padx=10)
                    if cand.get('candidate_number'):
                        tk.Label(row, text=f"({cand['candidate_number']})", font=('Helvetica', 16, 'italic'), fg="#666", bg="white").pack(side=tk.LEFT, padx=10)
                else:
                     tk.Label(row, text=f"{rank}.  [No Selection]", font=('Helvetica', 20), fg="#aaa", bg="white").pack(side=tk.LEFT, padx=10)

        footer = tk.Frame(self.main_container, bg="#f0f0f0", pady=15)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        
        edit_cmd = self.show_selection_screen if self.voting_mode == 'normal' else self.restart_editing
        tk.Button(footer, text="Edit", font=('Helvetica', 16), command=edit_cmd, padx=20, pady=10).pack(side=tk.LEFT, padx=30)
        tk.Button(footer, text="CONFIRM & CAST VOTE", font=('Helvetica', 16, 'bold'), bg="#4CAF50", fg="white", command=self.cast_vote, padx=20, pady=10).pack(side=tk.RIGHT, padx=30)

    def restart_editing(self):
        self.current_rank = 1
        self.show_selection_screen()

    def cast_vote(self):
        # Prepare Receipt Data Snapshot
        e_name = getattr(self.data_handler, 'election_name', 'General Election')
        ballot_id = self.data_handler.ballot_id
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
            cand = self.data_handler.get_candidate_by_id(cid)
            cand_commitment = cand.get('commitment', '') if cand else ""
            qr_data = f"{sel_str}:{cand_commitment}"
        else:
            ranks = sorted(self.selections.keys())
            vals = []
            for r in ranks:
                c = self.selections[r]
                vals.append(get_cand_display(c))
            sel_str = ", ".join(vals)
            
            qr_parts = []
            for r in ranks:
                cand = self.data_handler.get_candidate_by_id(self.selections[r])
                c_disp = get_cand_display(self.selections[r])
                c_comm = cand.get('commitment', '') if cand else ""
                qr_parts.append(f"{c_disp}:{c_comm}")
            qr_data = "_".join(qr_parts)

        # Pre-generate log JSON while context is valid
        vote_record = self.data_handler.generate_vote_json(
            {'selections': self.selections, 'timestamp': timestamp}, 
            self.voting_mode,
            getattr(self, 'current_voter_id', 'UNKNOWN'),
            getattr(self, 'current_booth', 1)
        )

        # Generate Voter Receipt QR string for batched printing (Raw Commitments ONLY)
        voter_qr_data = getattr(self.data_handler, 'raw_commitments', '')

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
                            getattr(self, 'current_booth', 1)
                        )
                    
                    # Mark ballot as used for this election (ALWAYS MARK USED TO PREVENT REUSE)
                    # Wait, if print fails at the end, we might have an issue. 
                    # But for now, we must mark it used so it's not given again during the session?
                    # No, the buffer holds it. 
                    # Actually, if we mark it used now, and the final print fails, we can't rollback easily.
                    # But preventing reuse is critical.
                    # Let's Mark USed now. The risk is a wasted ballot on print fail. Acceptable.
                    self.ballot_manager.mark_as_used(self.data_handler.ballot_file_id, self.current_election_id)
                    
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
