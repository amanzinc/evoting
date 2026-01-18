import tkinter as tk
from tkinter import ttk, messagebox
import csv
import datetime
import uuid
import os
try:
    from escpos.printer import File
except ImportError:
    print("Warning: python-escpos not installed. Printing will fail silently or log errors.")
    File = None # Handle optional dependency for dev machines

class VotingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Ballot Marking Device")
        self.root.attributes('-fullscreen', True)
        self.root.bind("<Escape>", self.exit_app)

        # Style configuration
        self.style = ttk.Style()
        self.style.configure('TLabel', font=('Helvetica', 14))
        self.style.configure('Header.TLabel', font=('Helvetica', 20, 'bold'))
        self.style.configure('SubHeader.TLabel', font=('Helvetica', 18))
        self.style.configure('Nav.TButton', font=('Helvetica', 16, 'bold'), padding=10)
        self.style.configure('Confirm.TButton', font=('Helvetica', 20, 'bold'), background='#4CAF50', foreground='white', padding=10)
        self.style.configure('Mode.TButton', font=('Helvetica', 20, 'bold'), padding=15)

        # Data
        # Data
        self.load_candidates()
        self.nota_candidate = {"id": 0, "name": "None of the Above (NOTA)", "party": "NOTA"}
        
        # State
        self.voting_mode = None # 'normal' or 'preferential'
        self.max_ranks = 3  # Maximum number of preferences to select
        self.current_rank = 1
        self.selections = {} # Dictionary to store {rank: candidate_id}
        
        self.main_container = tk.Frame(self.root, bg="#ffffff")
        self.main_container.pack(fill=tk.BOTH, expand=True)

        # Connect to Printer (Singleton)
        self.printer = None
        if File:
            try:
                self.printer = File("/dev/usb/lp0")
                print("Printer connected successfully.")
            except Exception as e:
                print(f"Printer Connection Failed: {e}")

        self.show_mode_selection_screen()

    def load_candidates(self):
        self.candidates_base = []
        filename = "candidates.csv"
        if not os.path.exists(filename):
            messagebox.showerror("Error", "candidates.csv not found!")
            return

        try:
            with open(filename, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Ensure properly typed dictionary
                    self.candidates_base.append({
                        "id": int(row["id"]),
                        "name": row["name"],
                        "party": row["party"]
                    })
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load candidates: {e}")

    def get_all_candidates(self):
        return self.candidates_base + [self.nota_candidate]

    def clear_container(self):
        for widget in self.main_container.winfo_children():
            widget.destroy()

    def get_candidate_by_id(self, cid):
        choices = self.get_all_candidates()
        return next((c for c in choices if c['id'] == cid), None)

    def show_mode_selection_screen(self):
        self.clear_container()
        header = tk.Frame(self.main_container, bg="#f0f0f0", pady=15)
        header.pack(fill=tk.X)
        tk.Label(header, text="Dev Mode: Select Voting Type", font=('Helvetica', 24, 'bold'), bg="#f0f0f0").pack()

        content = tk.Frame(self.main_container, bg="white")
        content.pack(expand=True)
        
        btn_frame = tk.Frame(content, bg="white")
        btn_frame.pack(pady=20)

        tk.Button(btn_frame, text="Normal Voting\n(Single Choice)", font=('Helvetica', 20, 'bold'), command=self.start_normal_voting, padx=30, pady=20, bg="#2196F3", fg="white").pack(pady=10, fill=tk.X)
        tk.Button(btn_frame, text="Preferential Voting\n(Ranked)", font=('Helvetica', 20, 'bold'), command=self.start_preferential_voting, padx=30, pady=20, bg="#9C27B0", fg="white").pack(pady=10, fill=tk.X)
        
        tk.Button(btn_frame, text="Exit App", font=('Helvetica', 14), command=self.exit_app).pack(pady=10)

    def start_normal_voting(self):
        self.voting_mode = 'normal'
        self.selections = {}
        self.current_rank = 1 # Just one rank effectively
        self.show_selection_screen()

    def start_preferential_voting(self):
        self.voting_mode = 'preferential'
        self.selections = {}
        self.current_rank = 1
        self.show_selection_screen()

    def show_selection_screen(self):
        self.clear_container()
        
        # Header
        header_bg = "#E3F2FD" if self.voting_mode == 'normal' else "#F3E5F5"
        header = tk.Frame(self.main_container, bg=header_bg, pady=5)
        header.pack(fill=tk.X)
        
        mode_text = "Single Choice Vote" if self.voting_mode == 'normal' else f"Select Preference #{self.current_rank}"
        tk.Label(header, text="General Election 2026", font=('Helvetica', 12), bg=header_bg).pack()
        tk.Label(header, text=mode_text, font=('Helvetica', 20, 'bold'), bg=header_bg, fg="#333").pack(pady=2)
        
        # Content Frame (No Scroll)
        content = tk.Frame(self.main_container, bg="#ffffff", pady=5, padx=20)
        content.pack(expand=True, fill=tk.BOTH)
        
        self.current_selection_var = tk.IntVar(value=-1) # Default to -1 (no selection)
        
        # Only pre-select if navigating BACK and we have a stored choice
        if self.current_rank in self.selections:
             self.current_selection_var.set(self.selections[self.current_rank])

        # Filter candidates
        available_candidates = []
        all_opts = self.get_all_candidates()

        if self.voting_mode == 'normal':
            available_candidates = all_opts
        else:
            for cand in all_opts:
                is_selected_elsewhere = False
                for rank, cid in self.selections.items():
                    # Standard logic: You can't pick the same PERSON twice.
                    # NOTA logic: User requested NOTA to be available in all options.
                    # We will NOT filter out NOTA (ID 0) even if selected previously.
                    if rank != self.current_rank and cid == cand['id']:
                        if cid != 0: # Allow NOTA to appear again
                            is_selected_elsewhere = True
                
                if not is_selected_elsewhere:
                    available_candidates.append(cand)




        # Layout: Grid or Packed list. 6 items.
        # To fit 6 items on one screen easily, we can use a 2-column grid if height is an issue,
        # or just tight vertical packing. Let's try 2 columns for better touch targets.
        
        total_options = len(available_candidates)
        rows_per_col = (total_options + 1) // 2
        
        # Dynamic Scaling Logic
        # If we have many candidates (e.g. > 8), we need to reduce size to fit
        if total_options > 8:
            btn_font = ('Helvetica', 12)
            btn_pady = 2
            frame_pady = 2
        elif total_options > 6:
            btn_font = ('Helvetica', 14)
            btn_pady = 4
            frame_pady = 4
        else:
            btn_font = ('Helvetica', 16)
            btn_pady = 8
            frame_pady = 6

        for idx, cand in enumerate(available_candidates):
            if cand['id'] == 0:
                cand_text = cand['name'] # Just "None of the Above..."
            else:
                cand_text = f"{cand['id']}. {cand['name']}"
            
            if cand['party']:
                cand_text += f"\n{cand['party']}"
            
            fg_color = "black"
            if cand['id'] == 0: 
                fg_color = "#D32F2F"

            # Frame to hold the button for spacing
            # Use Grid
            row = idx % rows_per_col
            col = idx // rows_per_col
            
            # Using Frame as a wrapper for margins
            frame = tk.Frame(content, bg="white")
            frame.grid(row=row, column=col, padx=10, pady=frame_pady, sticky="nsew")
            content.grid_columnconfigure(col, weight=1)
            content.grid_rowconfigure(row, weight=1)

            rb = tk.Radiobutton(
                frame, 
                text=cand_text, 
                variable=self.current_selection_var, 
                value=cand['id'],
                indicatoron=0, 
                font=btn_font,
                bg='white',
                fg=fg_color,
                selectcolor='#e8f5e9', 
                activebackground='#f5f5f5',
                padx=10,
                pady=btn_pady,
                bd=2,
                relief=tk.RAISED,
                justify=tk.CENTER
                # Removed fixed width to allow dynamic sizing
            )
            rb.pack(fill=tk.BOTH, expand=True)

        # Footer
        footer = tk.Frame(self.main_container, bg="#f0f0f0")
        footer.pack(fill=tk.X, side=tk.BOTTOM, pady=10)

        # BUTTONS
        if self.voting_mode == 'normal':
             confirm_btn = tk.Button(footer, text="Review Vote", font=('Helvetica', 16, 'bold'), bg="#4CAF50", fg="white", command=self.go_next, padx=15, pady=8)
             confirm_btn.pack(side=tk.RIGHT, padx=30)
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
        if selection == -1: # Explicit check for default initialized value logic
            messagebox.showwarning("No Selection", "Please make a selection to proceed.")
            return

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

        # Display Logic
        if self.voting_mode == 'normal':
            cid = self.selections.get(1)
            cand = self.get_candidate_by_id(cid)
            tk.Label(content, text="You have selected:", font=('Helvetica', 16), bg="white").pack(pady=5)
            
            f = tk.Frame(content, bg="#e8f5e9", bd=2, relief=tk.SOLID, padx=30, pady=15)
            f.pack(pady=10)
            
            if cand['id'] != 0:
                tk.Label(f, text=f"Candidate No: {cand['id']}", font=('Helvetica', 28, 'bold'), bg="#e8f5e9", fg="#333").pack()
            
            tk.Label(f, text=cand['name'], font=('Helvetica', 22), bg="#e8f5e9").pack(pady=5)
            tk.Label(f, text=cand['party'], font=('Helvetica', 18), bg="#e8f5e9").pack()

        else:
            # Preferential list
            for rank in range(1, self.max_ranks + 1):
                cid = self.selections.get(rank)
                cand = self.get_candidate_by_id(cid)
                
                row = tk.Frame(content, bg="white", pady=5)
                row.pack(fill=tk.X)
                
                if cand:
                    tk.Label(row, text=f"{rank}.", font=('Helvetica', 20, 'bold'), fg="#666", width=4, bg="white").pack(side=tk.LEFT)
                    
                    if cand['id'] == 0:
                        t = cand['name']
                    else:
                        t = f"{cand['id']}. {cand['name']}"
                        
                    tk.Label(row, text=t, font=('Helvetica', 20), bg="white").pack(side=tk.LEFT, padx=10)
                    if cand['party']:
                        tk.Label(row, text=f"({cand['party']})", font=('Helvetica', 16, 'italic'), fg="#666", bg="white").pack(side=tk.LEFT, padx=10)
                else:
                     tk.Label(row, text=f"{rank}.  [No Selection]", font=('Helvetica', 20), fg="#aaa", bg="white").pack(side=tk.LEFT, padx=10)


        # Footer
        footer = tk.Frame(self.main_container, bg="#f0f0f0", pady=15)
        footer.pack(fill=tk.X, side=tk.BOTTOM)

        edit_cmd = self.show_selection_screen if self.voting_mode == 'normal' else self.restart_editing
        
        edit_btn = tk.Button(footer, text="Edit", font=('Helvetica', 16), command=edit_cmd, padx=20, pady=10)
        edit_btn.pack(side=tk.LEFT, padx=30)

        confirm_btn = tk.Button(footer, text="CONFIRM & CAST VOTE", font=('Helvetica', 16, 'bold'), bg="#4CAF50", fg="white", command=self.cast_vote, padx=20, pady=10)
        confirm_btn.pack(side=tk.RIGHT, padx=30)

    def restart_editing(self):
        self.current_rank = 1
        self.show_selection_screen()

    def print_receipt(self, mode, selections):
        """
        Prints a VVPAT receipt using the attached thermal printer.
        Advanced layout with QR code.
        """
        if not self.printer:
            print("VVPAT Skipped: Printer not connected.")
            return

        try:
            p = self.printer
            
            # 1. Generate QR Data
            # Format: 1_2_3 for pref, 1 for normal
            if mode == 'normal':
                qr_data = str(selections.get(1))
            else:
                # specific order string: 1_2_3 based on rank
                ranks = sorted(selections.keys())
                qr_data = "_".join([str(selections[r]) for r in ranks])
            
            # 2. Print QR Code (Top)
            p.set(align='center')
            try:
                # native=False renders it as an image, usually safer/more consistent
                p.qr(qr_data, native=False, size=6, center=True)
            except Exception as qr_e:
                print(f"QR Print Error: {qr_e}")
                p.text(f"[QR: {qr_data}]\n")

            # 3. Print Header & Box Top
            # Reset font explicitly
            p.set(align='center', font='a', width=1, height=1)
            p.text("\n________________________________\n")
            p.text("|                                |\n")
            p.set(align='center', bold=True)
            p.text("| STUDENT GENERAL ELECTION 2026  |\n")
            p.set(align='center', bold=False)
            p.text("|--------------------------------|\n")

            # 4. Meta Data
            # Station ID: PS-105-DELHI (Hardcoded)
            # Session: DD-MM-YYYY HH:MM:SS
            # Ballot ID: Random Hex
            
            station_id = "PS-105-DELHI"
            timestamp = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            ballot_id = uuid.uuid4().hex[:8].upper()

            p.set(align='left')
            p.text(f"| Station ID: {station_id:<19}|\n")
            p.text(f"| Session: {timestamp:<21}|\n")
            p.text(f"| Ballot ID: {ballot_id:<20}|\n")
            p.text("|--------------------------------|\n")

            # 5. Selection (Sl No)
            p.set(align='left', bold=True)
            
            # Format selection string "Sl No: 1, 5, 9"
            if mode == 'normal':
                cid = selections.get(1)
                # Handle NOTA specially in string
                if cid == 0:
                    sel_str = "NOTA"
                else:
                    sel_str = str(cid)
            else:
                # For preferential, show list like 1, 5, 2
                # If NOTA is selected in rank, show NOTA
                vals = []
                for r in sorted(selections.keys()):
                    cid = selections[r]
                    if cid == 0:
                        vals.append("NOTA")
                    else:
                        vals.append(str(cid))
                sel_str = ", ".join(vals)
            
            p.text(f"| Sl No: {sel_str:<24}|\n")
            p.set(align='left', bold=False)
            p.text("|                                |\n")
            p.text("|                                |\n") # Padding
            
            # 6. Footer
            p.text("|--------------------------------|\n")
            p.set(align='center', bold=True)
            p.text("|         VERIFIED VOTE          |\n")
            p.set(align='center', bold=False)
            p.text("|      NOT FOR OFFICIAL USE      |\n")
            p.text("|                                |\n")
            p.text("|________________________________|\n")
            
            p.text("\n\n\n") # Feed
            p.cut()
            
            print("VVPAT Receipt printed successfully.")

        except Exception as e:
            # Log error but do not stop the voting process
            print(f"VVPAT Print Error: {e}")

    def cast_vote(self):
        # Log the vote
        timestamp = datetime.datetime.now().isoformat()
        log_file = "votes.log"
        
        try:
            # Prepare rows to write
            # Log format: Timestamp, Mode, Rank, CandidateID, CandidateName
            # For preferential, we might have multiple lines or one line per rank. 
            # Let's do one line per rank selection for clarity, sharing the same timestamp.
            
            with open(log_file, "a", newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                # Write header if new file (optional, but good practice if we check generic logic, 
                # but appending blind is faster. keeping it simple.)
                
                if self.voting_mode == 'normal':
                    cid = self.selections.get(1)
                    cand = self.get_candidate_by_id(cid)
                    writer.writerow([timestamp, self.voting_mode, 1, cid, cand['name']])
                else:
                    for rank, cid in self.selections.items():
                        cand = self.get_candidate_by_id(cid)
                        writer.writerow([timestamp, self.voting_mode, rank, cid, cand['name']])
                        
        except Exception as e:
            print(f"Error saving vote: {e}") # Fallback logging to console

        # Print VVPAT
        self.print_receipt(self.voting_mode, self.selections)

        messagebox.showinfo("Vote Cast", "Your vote has been recorded successfully!\n\nPrinting VVPAT and Receipt...")
        self.show_mode_selection_screen()

    def exit_app(self, event=None):
        self.root.quit()

if __name__ == "__main__":
    root = tk.Tk()
    app = VotingApp(root)
    root.mainloop()
