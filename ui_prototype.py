import tkinter as tk
from tkinter import ttk, messagebox
import csv
import datetime
import uuid
import os
import threading
import queue

try:
    from escpos.printer import File
except ImportError:
    print("Warning: python-escpos not installed. Printing will fail silently or log errors.")
    File = None # Handle optional dependency for dev machines

# Image processing for side-by-side QRs
import qrcode
from PIL import Image, ImageDraw, ImageFont

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
                    # Logic Change: Only filter out candidates selected in PREVIOUS ranks.
                    # Future ranks (rank > self.current_rank) should NOT block selection (swapping).
                    if rank < self.current_rank and cid == cand['id']:
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

        # Conflict Resolution:
        # If this candidate was selected in a FUTURE rank, we must clear that future rank
        # because a candidate cannot be selected twice (except NOTA).
        if selection != 0:
            ranks_to_clear = []
            for rank, cid in self.selections.items():
                 if rank > self.current_rank and cid == selection:
                     ranks_to_clear.append(rank)
            
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

    def print_receipt_async(self, mode, selections, result_queue):
        """
        Background thread worker for printing.
        Puts result (True/False/Error) into result_queue.
        """
        try:
            # We reuse the logic from print_receipt but adapted for being in a thread
            # NOTE: Tkinter GUI updates must NOT happen here. They must be scheduled or done by main thread.
            # We will use self.printer directly.
            
            # --- CONNECTION CHECK (Thread Safe-ish if we just read) ---
            if not self.printer:
                 # Try to reconnect
                if File and os.path.exists("/dev/usb/lp0"):
                    try:
                        self.printer = File("/dev/usb/lp0")
                    except:
                        pass
            
            if not self.printer:
                result_queue.put(Exception("Printer not connected"))
                return

            p = self.printer
            if not os.path.exists("/dev/usb/lp0"):
                 result_queue.put(Exception("Device file not found"))
                 return

            # --- GENERATION ---
             # Standard 58mm printer width alignment
            TOP_BAR = "_" * 32
            BOTTOM_BAR = "_" * 32
            
            ballot_id = uuid.uuid4().hex[:8].upper()
            
            if mode == 'normal':
                qr_choice_data = str(selections.get(1))
            else:
                ranks = sorted(selections.keys())
                qr_choice_data = "_".join([str(selections[r]) for r in ranks])
            
            # QR Image Gen
            try:
                qr_c = qrcode.make(qr_choice_data)
                qr_b = qrcode.make(ballot_id)
                qr_size = 140
                qr_c = qr_c.resize((qr_size, qr_size))
                qr_b = qr_b.resize((qr_size, qr_size))
                
                total_width = 384
                title_height = 45 
                height = qr_size + title_height
                
                img = Image.new('RGB', (total_width, height), 'white')
                draw = ImageDraw.Draw(img)
                
                font_size = 30
                font = None
                font_candidates = [
                    "arial.ttf", 
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 
                    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf", 
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
                ]
                for fpath in font_candidates:
                    try:
                        font = ImageFont.truetype(fpath, font_size)
                        break
                    except IOError:
                        continue
                if font is None:
                    font = ImageFont.load_default()

                x_c = 30
                x_b = 214
                draw.text((x_c + 20, 0), "Choice", font=font, fill="black")
                draw.text((x_b + 5, 0), "Ballot ID", font=font, fill="black")
                img.paste(qr_c, (x_c, title_height))
                img.paste(qr_b, (x_b, title_height))
                
                # Unique temp file for thread safety
                temp_img = f"temp_qr_{uuid.uuid4().hex}.png"
                img.save(temp_img)
                
                p.set(align='center')
                p.image(temp_img)
                p.text("\n")
                if os.path.exists(temp_img):
                    os.remove(temp_img)
            except Exception as e:
                print(f"QR Error: {e}")
                p.text(f"Choice: {qr_choice_data} | Ballot: {ballot_id}\n")

            # Text
            p.set(align='center', font='a', width=1, height=1, bold=True)
            p.text(TOP_BAR + "\n")
            p.text("STUDENT GENERAL\n")
            p.text("ELECTION 2026\n")
            p.set(align='center', bold=False)
            p.text("\n") 

            station_id = "PS-105-DELHI"
            timestamp = datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")
            p.set(align='left')
            p.text(f"Station: {station_id}\n") 
            p.text(f"Session: {timestamp}\n")
            p.text(f"Ballot : {ballot_id}\n")

            if mode == 'normal':
                cid = selections.get(1)
                sel_str = "NOTA" if cid == 0 else str(cid)
            else:
                vals = []
                for r in sorted(selections.keys()):
                    cid = selections[r]
                    vals.append("NOTA" if cid == 0 else str(cid))
                sel_str = ", ".join(vals)
            
            p.text("\n")
            p.set(align='left', bold=True)
            p.text(f"Choice : {sel_str}\n")
            p.set(align='left', bold=False)
            
            p.text(BOTTOM_BAR + "\n")
            p.set(align='center', bold=True)
            p.text("VERIFIED VOTE\n")
            p.set(align='center', bold=False)
            p.text(BOTTOM_BAR + "\n")
            
            p.text("\n") 
            p.cut()
            
            result_queue.put(True) # Success

        except Exception as e:
            result_queue.put(e)

    def cast_vote(self):
        # UI Feedback: Show Printing Modal
        self.show_printing_modal()

        # Start Async Print
        self.print_queue = queue.Queue()
        
        self.print_thread = threading.Thread(
            target=self.print_receipt_async, 
            args=(self.voting_mode, self.selections, self.print_queue)
        )
        self.print_thread.daemon = True # Kill if app closes
        self.print_thread.start()

        # Start Timeout Checker
        self.print_start_time = datetime.datetime.now()
        self.check_print_status()

    def show_printing_modal(self):
        # Simple overlay for "Printing..."
        self.printing_overlay = tk.Toplevel(self.root)
        self.printing_overlay.title("Printing VVPAT")
        # Center it
        w, h = 400, 200
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.printing_overlay.geometry(f"{w}x{h}+{x}+{y}")
        self.printing_overlay.transient(self.root)
        self.printing_overlay.grab_set() # Modal
        self.printing_overlay.overrideredirect(True) # No close buttons
        
        f = tk.Frame(self.printing_overlay, bg="#E3F2FD", bd=2, relief=tk.RAISED)
        f.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(f, text="Printing VVPAT Receipt...", font=('Helvetica', 16, 'bold'), bg="#E3F2FD").pack(pady=30)
        tk.Label(f, text="Please Wait", font=('Helvetica', 14), bg="#E3F2FD").pack(pady=10)

    def close_printing_modal(self):
        if hasattr(self, 'printing_overlay') and self.printing_overlay:
            self.printing_overlay.destroy()
            self.printing_overlay = None

    def check_print_status(self):
        # Check Queue
        try:
            # Non-blocking get
            result = self.print_queue.get_nowait()
            
            # Thread finished
            self.close_printing_modal()
            
            if result is True:
                self.save_vote()
                messagebox.showinfo("Vote Cast", "Your vote has been verified and recorded successfully!")
                self.show_mode_selection_screen()
            else:
                # Error Case
                print(f"Async print error: {result}")
                self.printer = None # Force reconnection on next try
                retry = messagebox.askretrycancel("Printer Error", f"Printing Failed: {result}\n\nRetry?")
                if retry:
                    self.cast_vote() # Restart process
                else:
                    # Cancelled
                    pass # Stay on confirmation screen?
            return

        except queue.Empty:
            # Still running
            pass

        # Check Timeout (20 seconds)
        elapsed = (datetime.datetime.now() - self.print_start_time).total_seconds()
        if elapsed > 20:
            self.close_printing_modal()
            # If thread is stuck, we can't easily kill it in Python. 
            # We just abandon it and warn the user.
            retry = messagebox.askretrycancel("Printer Timeout", "Printer is taking too long (Paper/Jam?).\n\nRetry?")
            if retry:
                self.cast_vote()
            else:
                pass # Return to confirm screen
            return

        # Schedule next check
        self.root.after(500, self.check_print_status)

    def save_vote(self):
        # Only called AFTER successful print
        timestamp = datetime.datetime.now().isoformat()
        log_file = "votes.log"
        
        try:
            with open(log_file, "a", newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if self.voting_mode == 'normal':
                    cid = self.selections.get(1)
                    cand = self.get_candidate_by_id(cid)
                    writer.writerow([timestamp, self.voting_mode, 1, cid, cand['name']])
                else:
                    for rank, cid in self.selections.items():
                        cand = self.get_candidate_by_id(cid)
                        writer.writerow([timestamp, self.voting_mode, rank, cid, cand['name']])
            print("Vote saved to log.")
        except Exception as e:
            print(f"Error saving vote: {e}") 
            messagebox.showerror("System Error", "Vote printed but failed to save to disk!")

    def exit_app(self, event=None):
        self.root.quit()

if __name__ == "__main__":
    root = tk.Tk()
    app = VotingApp(root)
    root.mainloop()

