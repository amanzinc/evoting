import tkinter as tk
from tkinter import ttk, messagebox

class VotingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Ballot Marking Device")
        self.root.attributes('-fullscreen', True)
        self.root.bind("<Escape>", self.exit_app)

        # Style configuration
        self.style = ttk.Style()
        self.style.configure('TLabel', font=('Helvetica', 16))
        self.style.configure('Header.TLabel', font=('Helvetica', 24, 'bold'))
        self.style.configure('SubHeader.TLabel', font=('Helvetica', 20))
        self.style.configure('Nav.TButton', font=('Helvetica', 20, 'bold'), padding=20)
        self.style.configure('Confirm.TButton', font=('Helvetica', 24, 'bold'), background='#4CAF50', foreground='white', padding=20)
        self.style.configure('Mode.TButton', font=('Helvetica', 24, 'bold'), padding=30)

        # Data
        self.candidates_base = [
            {"id": 1, "name": "Narendra Modi", "party": "Bharatiya Janata Party (BJP)"},
            {"id": 2, "name": "Rahul Gandhi", "party": "Indian National Congress (INC)"},
            {"id": 3, "name": "Arvind Kejriwal", "party": "Aam Aadmi Party (AAP)"},
            {"id": 4, "name": "Mamata Banerjee", "party": "Trinamool Congress (TMC)"},
            {"id": 5, "name": "M.K. Stalin", "party": "Dravida Munnetra Kazhagam (DMK)"},
        ]
        self.nota_candidate = {"id": 0, "name": "None of the Above (NOTA)", "party": "NOTA"}
        
        # State
        self.voting_mode = None # 'normal' or 'preferential'
        self.max_ranks = 3  # Maximum number of preferences to select
        self.current_rank = 1
        self.selections = {} # Dictionary to store {rank: candidate_id}
        
        self.main_container = tk.Frame(self.root, bg="#ffffff")
        self.main_container.pack(fill=tk.BOTH, expand=True)

        self.show_mode_selection_screen()

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
        header = tk.Frame(self.main_container, bg="#f0f0f0", pady=30)
        header.pack(fill=tk.X)
        tk.Label(header, text="Dev Mode: Select Voting Type", font=('Helvetica', 32, 'bold'), bg="#f0f0f0").pack()

        content = tk.Frame(self.main_container, bg="white")
        content.pack(expand=True)
        
        btn_frame = tk.Frame(content, bg="white")
        btn_frame.pack(pady=50)

        tk.Button(btn_frame, text="Normal Voting\n(Single Choice)", font=('Helvetica', 24, 'bold'), command=self.start_normal_voting, padx=40, pady=30, bg="#2196F3", fg="white").pack(pady=20, fill=tk.X)
        tk.Button(btn_frame, text="Preferential Voting\n(Ranked)", font=('Helvetica', 24, 'bold'), command=self.start_preferential_voting, padx=40, pady=30, bg="#9C27B0", fg="white").pack(pady=20, fill=tk.X)
        
        tk.Button(btn_frame, text="Exit App", font=('Helvetica', 16), command=self.exit_app).pack(pady=20)

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
        header = tk.Frame(self.main_container, bg=header_bg, pady=10)
        header.pack(fill=tk.X)
        
        mode_text = "Single Choice Vote" if self.voting_mode == 'normal' else f"Select Preference #{self.current_rank}"
        tk.Label(header, text="General Election 2026", font=('Helvetica', 14), bg=header_bg).pack()
        tk.Label(header, text=mode_text, font=('Helvetica', 24, 'bold'), bg=header_bg, fg="#333").pack(pady=5)
        
        # Content Frame (No Scroll)
        content = tk.Frame(self.main_container, bg="#ffffff", pady=10, padx=50)
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
        
        rows_per_col = (len(available_candidates) + 1) // 2
        
        for idx, cand in enumerate(available_candidates):
            cand_text = f"{cand['name']}"
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
            frame.grid(row=row, column=col, padx=20, pady=10, sticky="nsew")
            content.grid_columnconfigure(col, weight=1)
            content.grid_rowconfigure(row, weight=1)

            rb = tk.Radiobutton(
                frame, 
                text=cand_text, 
                variable=self.current_selection_var, 
                value=cand['id'],
                indicatoron=0, 
                font=('Helvetica', 18),
                bg='white',
                fg=fg_color,
                selectcolor='#e8f5e9', 
                activebackground='#f5f5f5',
                padx=10,
                pady=10,
                bd=2,
                relief=tk.RAISED,
                justify=tk.CENTER,
                width=20 # Fixed width for uniformity
            )
            rb.pack(fill=tk.BOTH, expand=True)

        # Footer
        footer = tk.Frame(self.main_container, bg="#f0f0f0")
        footer.pack(fill=tk.X, side=tk.BOTTOM, pady=20)

        # BUTTONS
        if self.voting_mode == 'normal':
             confirm_btn = tk.Button(footer, text="Review Vote", font=('Helvetica', 20, 'bold'), bg="#4CAF50", fg="white", command=self.go_next, padx=20, pady=10)
             confirm_btn.pack(side=tk.RIGHT, padx=50)
             tk.Button(footer, text="< Back", font=('Helvetica', 20), command=self.show_mode_selection_screen, padx=20, pady=10).pack(side=tk.LEFT, padx=50)
        else:
            if self.current_rank > 1:
                tk.Button(footer, text="< Previous", font=('Helvetica', 20), command=self.go_previous, padx=20, pady=10).pack(side=tk.LEFT, padx=50)
            else:
                 tk.Button(footer, text="Cancel", font=('Helvetica', 20), command=self.show_mode_selection_screen, padx=20, pady=10, fg="red").pack(side=tk.LEFT, padx=50)

            next_text = "Next >" if self.current_rank < self.max_ranks else "Finish"
            tk.Button(footer, text=next_text, font=('Helvetica', 20, 'bold'), bg="#2196F3", fg="white", command=self.go_next, padx=20, pady=10).pack(side=tk.RIGHT, padx=50)

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
        
        header = tk.Frame(self.main_container, bg="#f0f0f0", pady=20)
        header.pack(fill=tk.X)
        tk.Label(header, text="Confirm Your Vote", font=('Helvetica', 28, 'bold'), bg="#f0f0f0").pack()

        content = tk.Frame(self.main_container, bg="#ffffff", pady=40)
        content.pack(expand=True)

        # Display Logic
        if self.voting_mode == 'normal':
            cid = self.selections.get(1)
            cand = self.get_candidate_by_id(cid)
            tk.Label(content, text="You have selected:", font=('Helvetica', 20), bg="white").pack(pady=10)
            
            f = tk.Frame(content, bg="#e8f5e9", bd=2, relief=tk.SOLID, padx=40, pady=20)
            f.pack(pady=20)
            tk.Label(f, text=cand['name'], font=('Helvetica', 32, 'bold'), bg="#e8f5e9").pack()
            tk.Label(f, text=cand['party'], font=('Helvetica', 24), bg="#e8f5e9").pack()

        else:
            # Preferential list
            for rank in range(1, self.max_ranks + 1):
                cid = self.selections.get(rank)
                cand = self.get_candidate_by_id(cid)
                
                row = tk.Frame(content, bg="white", pady=10)
                row.pack(fill=tk.X)
                
                if cand:
                    tk.Label(row, text=f"{rank}.", font=('Helvetica', 24, 'bold'), fg="#666", width=5, bg="white").pack(side=tk.LEFT)
                    tk.Label(row, text=f"{cand['name']}", font=('Helvetica', 24), bg="white").pack(side=tk.LEFT, padx=10)
                    if cand['party']:
                        tk.Label(row, text=f"({cand['party']})", font=('Helvetica', 18, 'italic'), fg="#666", bg="white").pack(side=tk.LEFT, padx=10)
                else:
                     tk.Label(row, text=f"{rank}.  [No Selection]", font=('Helvetica', 24), fg="#aaa", bg="white").pack(side=tk.LEFT, padx=10)


        # Footer
        footer = tk.Frame(self.main_container, bg="#f0f0f0", pady=30)
        footer.pack(fill=tk.X, side=tk.BOTTOM)

        edit_cmd = self.show_selection_screen if self.voting_mode == 'normal' else self.restart_editing
        
        edit_btn = tk.Button(footer, text="Edit", font=('Helvetica', 20), command=edit_cmd, padx=30, pady=15)
        edit_btn.pack(side=tk.LEFT, padx=50)

        confirm_btn = tk.Button(footer, text="CONFIRM & CAST VOTE", font=('Helvetica', 20, 'bold'), bg="#4CAF50", fg="white", command=self.cast_vote, padx=30, pady=15)
        confirm_btn.pack(side=tk.RIGHT, padx=50)

    def restart_editing(self):
        self.current_rank = 1
        self.show_selection_screen()

    def cast_vote(self):
        messagebox.showinfo("Vote Cast", "Your vote has been recorded successfully!\n\nPrinting VVPAT and Receipt...")
        self.show_mode_selection_screen()

    def exit_app(self, event=None):
        self.root.quit()

if __name__ == "__main__":
    root = tk.Tk()
    app = VotingApp(root)
    root.mainloop()
