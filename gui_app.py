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

    def skip_rfid_check(self):
        self.stop_scanning = True
        self.on_card_scanned('{"token_id": "SKIPPED_DEV_MODE"}')

    def on_card_scanned(self, token_payload):
        # 1. Parse Token ID
        import json
        token_id = token_payload
        try:
            data = json.loads(token_payload)
            if 'token_id' in data:
                token_id = data['token_id']
        except:
            pass
            
        # 2. Check Verification
        if self.data_handler.is_token_used(token_id):
            print(f"❌ Token {token_id} already used!")
            # Show Error Overlay then restart scan
            self.show_rfid_error("Token Already Used\nVoter has already cast a vote.")
            return

        self.active_token = token_payload
        # Proceed to Normal Flow
        self.show_mode_selection_screen()

    def show_rfid_error(self, message):
        self.clear_container()
        frame = tk.Frame(self.main_container, bg="#FFEBEE") # Reddish bg
        frame.pack(expand=True, fill=tk.BOTH)
        
        tk.Label(frame, text="❌ Access Denied", font=('Helvetica', 32, 'bold'), bg="#FFEBEE", fg="#D32F2F").pack(pady=(150, 20))
        tk.Label(frame, text=message, font=('Helvetica', 24), bg="#FFEBEE", fg="#555").pack(pady=20)
        
        # Auto-retry after 3 seconds
        tk.Label(frame, text="(Resetting in 3 seconds...)", font=('Helvetica', 16), bg="#FFEBEE", fg="#777").pack(pady=40)
        self.root.after(3000, self.show_rfid_screen)

    def start_session(self):
        """Fetches a fresh ballot for the new session."""
        try:
            new_id, new_file = self.ballot_manager.get_unused_ballot()
            print(f"Starting Session with Ballot ID: {new_id}")
            self.data_handler.set_ballot_file(new_file)
        except Exception as e:
            print(f"Failed to load new ballot: {e}")
            messagebox.showerror("Ballot Error", f"Could not load new ballot: {e}")

    def show_mode_selection_screen(self):
        self.clear_container()
        header = tk.Frame(self.main_container, bg="#f0f0f0", pady=15)
        header.pack(fill=tk.X)
        tk.Label(header, text="Select Voting Type", font=('Helvetica', 24, 'bold'), bg="#f0f0f0").pack()
        
        tk.Label(header, text="System Ready", font=('Helvetica', 12, 'bold'), bg="#f0f0f0", fg="#555").pack()

        content = tk.Frame(self.main_container, bg="white")
        content.pack(expand=True)
        
        btn_frame = tk.Frame(content, bg="white")
        btn_frame.pack(pady=20)

        tk.Button(btn_frame, text="Normal Voting\n(Single Choice)", font=('Helvetica', 20, 'bold'), command=self.start_normal_voting, padx=30, pady=20, bg="#2196F3", fg="white").pack(pady=10, fill=tk.X)
        tk.Button(btn_frame, text="Preferential Voting\n(Ranked)", font=('Helvetica', 20, 'bold'), command=self.start_preferential_voting, padx=30, pady=20, bg="#9C27B0", fg="white").pack(pady=10, fill=tk.X)
        tk.Button(btn_frame, text="Preferential Voting 2\n(Greyed Out)", font=('Helvetica', 20, 'bold'), command=self.start_preferential_voting_2, padx=30, pady=20, bg="#673AB7", fg="white").pack(pady=10, fill=tk.X)
        
        # Disabled Exit for smoother kiosk feel or keep for Dev
        tk.Button(btn_frame, text="Exit App", font=('Helvetica', 14), command=self.exit_app).pack(pady=10)

    def start_normal_voting(self):
        self.start_session()
        self.voting_mode = 'normal'
        self.pv_mode_2 = False
        self.selections = {}
        self.current_rank = 1
        self.show_selection_screen()

    def start_preferential_voting(self):
        self.start_session()
        self.voting_mode = 'preferential'
        self.pv_mode_2 = False
        self.selections = {}
        self.current_rank = 1
        self.max_ranks = max(1, len(self.data_handler.candidates_base) - 1)
        self.show_selection_screen()

    def start_preferential_voting_2(self):
        self.start_session()
        self.voting_mode = 'preferential'
        self.pv_mode_2 = True
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
        tk.Label(header, text="General Election 2026", font=('Helvetica', 12), bg=header_bg).pack()
        tk.Label(header, text=f"Ballot ID: {self.data_handler.ballot_id}", font=('Helvetica', 10, 'bold'), bg=header_bg, fg="#555").pack()
        tk.Label(header, text=mode_text, font=('Helvetica', 20, 'bold'), bg=header_bg, fg="#333").pack(pady=2)
        
        content = tk.Frame(self.main_container, bg="#ffffff", pady=5, padx=20)
        content.pack(expand=True, fill=tk.BOTH)
        
        self.current_selection_var = tk.IntVar(value=-1)
        if self.current_rank in self.selections:
             self.current_selection_var.set(self.selections[self.current_rank])

        available_candidates = []
        all_opts = self.data_handler.candidates_base

        if self.voting_mode == 'normal':
            available_candidates = all_opts
        else:
            for cand in all_opts:
                is_selected_elsewhere = False
                for rank, cid in self.selections.items():
                    if rank < self.current_rank and cid == cand['id']:
                        is_selected_elsewhere = True
                
                if self.pv_mode_2:
                    available_candidates.append(cand)
                elif not is_selected_elsewhere:
                    available_candidates.append(cand)

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
            if self.pv_mode_2:
                selected_rank = None
                for rank, cid in self.selections.items():
                    if rank < self.current_rank and cid == cand['id']:
                        selected_rank = rank
                        break
                
                if selected_rank is not None and cand['name'] != "NAFS":
                    state_val = tk.DISABLED
                    fg_color = "grey"
                    cand_text += f" (Pref {selected_rank})"

            tk.Radiobutton(
                frame, text=cand_text, variable=self.current_selection_var, value=cand['id'],
                indicatoron=0, font=btn_font, bg='white', fg=fg_color,
                selectcolor='#e8f5e9', activebackground='#f5f5f5',
                padx=10, pady=btn_pady, bd=2, relief=tk.RAISED,
                justify=tk.CENTER, state=state_val
            ).pack(fill=tk.BOTH, expand=True)

        footer = tk.Frame(self.main_container, bg="#f0f0f0")
        footer.pack(fill=tk.X, side=tk.BOTTOM, pady=10)

        if self.voting_mode == 'normal':
             tk.Button(footer, text="Review Vote", font=('Helvetica', 16, 'bold'), bg="#4CAF50", fg="white", command=self.go_next, padx=15, pady=8).pack(side=tk.RIGHT, padx=30)
             tk.Button(footer, text="< Back", font=('Helvetica', 16), command=self.show_mode_selection_screen, padx=15, pady=8).pack(side=tk.LEFT, padx=30)
        else:
            if self.current_rank > 1:
                tk.Button(footer, text="< Previous", font=('Helvetica', 16), command=self.go_previous, padx=15, pady=8).pack(side=tk.LEFT, padx=30)
            else:
                 tk.Button(footer, text="Cancel", font=('Helvetica', 16), command=self.show_mode_selection_screen, padx=15, pady=8, fg="red").pack(side=tk.LEFT, padx=30)

            next_text = "Next >" if self.current_rank < self.max_ranks else "Finish"
            tk.Button(footer, text=next_text, font=('Helvetica', 16, 'bold'), bg="#2196F3", fg="white", command=self.go_next, padx=15, pady=8).pack(side=tk.RIGHT, padx=30)

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
            if cand.get('candidate_number'):
                c_num = cand.get('candidate_number', str(cand['id']))
                tk.Label(f, text=f"Candidate No: {c_num}", font=('Helvetica', 28, 'bold'), bg="#e8f5e9", fg="#333").pack()
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
        self.show_printing_modal()
        self.print_queue = queue.Queue()
        
        def printer_worker(mode, sel):
            try:
                self.printer_service.print_vote(mode, sel)
                self.print_queue.put(True)
            except Exception as e:
                self.print_queue.put(e)

        self.print_thread = threading.Thread(target=printer_worker, args=(self.voting_mode, self.selections))
        self.print_thread.daemon = True
        self.print_thread.start()

        self.print_start_time = datetime.datetime.now()
        self.check_print_status()

    def show_printing_modal(self):
        self.printing_overlay = tk.Toplevel(self.root)
        self.printing_overlay.title("Printing VVPAT")
        w, h = 400, 200
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.printing_overlay.geometry(f"{w}x{h}+{x}+{y}")
        self.printing_overlay.transient(self.root)
        self.printing_overlay.grab_set()
        self.printing_overlay.overrideredirect(True)
        f = tk.Frame(self.printing_overlay, bg="#E3F2FD", bd=2, relief=tk.RAISED)
        f.pack(fill=tk.BOTH, expand=True)
        tk.Label(f, text="Printing VVPAT Receipt...", font=('Helvetica', 16, 'bold'), bg="#E3F2FD").pack(pady=30)
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
                    vote_data = {'selections': self.selections}
                    self.data_handler.save_vote(vote_data, self.voting_mode)
                    self.ballot_manager.mark_as_used(self.data_handler.ballot_id) 
                    
                    # LOG TOKEN (New)
                    if self.active_token:
                        self.data_handler.log_token(self.active_token)
                    
                    messagebox.showinfo("Vote Cast", "Your vote has been verified and recorded successfully!")
                    
                    # Instead of showing mode selection, we go back to Card Scan screen (Full Loop)
                    self.active_token = None
                    self.show_rfid_screen()
                    
                except Exception as e:
                    messagebox.showerror("System Error", f"Vote printed but failed to save: {e}")
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
