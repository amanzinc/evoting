import tkinter as tk
from tkinter import ttk
import threading
import queue
import datetime
import time
import os
import subprocess
import json
import calendar

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
        self._kiosk_enforcing = False

        # Two-phase commit journal — tracks PENDING/COMMITTED per VVPAT print
        self._pending_journal_id = None
        self._journal_startup_checked = False
        try:
            from vote_journal import VoteJournal
            self._vote_journal = VoteJournal(log_dir) if log_dir else None
        except Exception as _je:
            print(f"[journal] Could not init VoteJournal: {_je}")
            self._vote_journal = None

        # Hidden polling-officer menu trigger: typing "Aman" opens the panel.
        self._admin_key_buffer = ""
        self._admin_overlay = None
        self.polling_officer_phrase = "YOU WILL NEVER WALK ALONE"
        
        self.root.title("Ballot Marking Device")
        self.root.overrideredirect(True)
        self.root.resizable(False, False)
        self.root.attributes('-fullscreen', True)
        self._enforce_kiosk_mode()
        self.root.bind("<Configure>", self._on_root_configure)
        self.root.bind("<Escape>", self.exit_app)
        self.root.bind("<Key>", self._on_key_press)

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
        self.merge_receipts = False # Print VVPAT immediately after each election
        self.receipt_buffer = [] # Store print data for batching 
        self.print_enabled = True
        self.pending_print_job = None
        self.pending_batch_receipts = None
        self.print_status_after_id = None
        self.batch_print_status_after_id = None
        self.session_complete_after_id = None
        self.clock_after_id = None
        self.clock_label = None
        self.inactive_check_after_id = None
        self.election_schedule = None
        self.election_schedule_path = None
        self._last_schedule_active = None
        self.failed_usb_mount_path = None
        self.last_usb_import_error = None

        self.main_container = tk.Frame(self.root, bg="#ffffff")
        self.main_container.pack(fill=tk.BOTH, expand=True)
        
        # Start with Hardware Check Screen
        self.show_hardware_check_screen()

    def show_hardware_check_screen(self):
        self.clear_container()
        frame = tk.Frame(self.main_container, bg="#E8F5E9")
        frame.pack(expand=True, fill=tk.BOTH)
        
        tk.Label(frame, text="Hardware Diagnostics", font=('Helvetica', 32, 'bold'), bg="#E8F5E9", fg="#2E7D32").pack(pady=(150, 20))
        tk.Label(frame, text="Checking critical hardware components...", font=('Helvetica', 24), bg="#E8F5E9", fg="#333").pack(pady=20)

        self.hw_status_label = tk.Label(frame, text="", font=('Helvetica', 18), bg="#E8F5E9", fg="#1565C0", justify="center")
        self.hw_status_label.pack(pady=20)
        
        self.root.after(500, self._perform_hardware_check)

    def _perform_hardware_check(self):
        # Check Printer
        from printer_service import PrinterService
        if not getattr(self, 'printer_service', None):
            self.printer_service = PrinterService(None)
            
        printer_ok = self.printer_service.is_printer_connected()
        
        # Check RFID
        try:
            if not getattr(self.rfid_service, 'connected', False):
                self.rfid_service.connect()
            rfid_ok = getattr(self.rfid_service, 'connected', False)
        except Exception:
            rfid_ok = False
            
        if printer_ok and rfid_ok:
            self.hw_status_label.config(text="All critical hardware detected.\nProceeding to initialization...", fg="#2E7D32")
            self.root.after(1500, self.show_usb_waiting_screen)
        else:
            missing = []
            if not printer_ok: missing.append("Thermal Printer")
            if not rfid_ok: missing.append("RFID Reader")
            
            error_text = f"Missing Critical Hardware:\n{', '.join(missing)}\n\nPlease connect the devices. Retrying in 3 seconds..."
            self.hw_status_label.config(text=error_text, fg="#C62828")
            
            # Reset the printer service so it tries reconnecting fully next time
            if not printer_ok:
                self.printer_service = None
                
            self.root.after(3000, self._perform_hardware_check)

    def _enforce_kiosk_mode(self):
        if self._kiosk_enforcing:
            return

        # Do not re-assert root fullscreen while admin overlay is active,
        # otherwise some window managers push the overlay behind root.
        admin_overlay = getattr(self, "_admin_overlay", None)
        if admin_overlay:
            try:
                if admin_overlay.winfo_exists():
                    return
            except Exception:
                pass

        self._kiosk_enforcing = True
        try:
            self.root.overrideredirect(True)
            self.root.resizable(False, False)
            self.root.attributes('-fullscreen', True)
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry(f"{sw}x{sh}+0+0")
        except Exception:
            pass
        finally:
            self._kiosk_enforcing = False

    def _on_root_configure(self, _event=None):
        self._enforce_kiosk_mode()

    def show_usb_waiting_screen(self, error_message=None):
        self.clear_container()
        frame = tk.Frame(self.main_container, bg="#E8F5E9")
        frame.pack(expand=True, fill=tk.BOTH)
        
        tk.Label(frame, text="System Initialization", font=('Helvetica', 32, 'bold'), bg="#E8F5E9", fg="#2E7D32").pack(pady=(150, 20))
        tk.Label(frame, text="Please insert the Election Data USB Drive to start.", font=('Helvetica', 24), bg="#E8F5E9", fg="#333").pack(pady=20)
        tk.Label(frame, text="(Waiting for USB with 'ballot_<bmd_id>' folder)", font=('Helvetica', 14), bg="#E8F5E9", fg="#666").pack(pady=5)

        message = error_message or self.last_usb_import_error
        if message:
            tk.Label(
                frame,
                text=message,
                font=('Helvetica', 14),
                bg="#E8F5E9",
                fg="#C62828",
                wraplength=900,
                justify=tk.CENTER
            ).pack(pady=(10, 0))

        tk.Label(
            frame,
            text="Scan authorized Polling Officer RFID card to open restricted menu.",
            font=('Helvetica', 14, 'italic'),
            bg="#E8F5E9",
            fg="#555"
        ).pack(pady=(16, 0))

        # Ensure RFID is initialized on USB waiting screen too.
        try:
            self.rfid_service.load_key()
            self.rfid_service.connect()
        except Exception as e:
            print(f"RFID init warning on USB wait screen: {e}")

        # USB waiting screen allows polling officer menu access only via RFID authorization.
        self.stop_scanning = False
        self.officer_scan_queue = queue.Queue()
        self.officer_scan_thread = threading.Thread(target=self.officer_scan_loop)
        self.officer_scan_thread.daemon = True
        self.officer_scan_thread.start()
        self.check_officer_scan_queue()

        self.check_usb_loop()

    def check_usb_loop(self):
        # Try to find the USB drive with ballot_<bmd_id> (or legacy ballot) folder
        usb_path = self.ballot_manager._find_usb_drive(None)
        ballot_path = self.ballot_manager._find_ballot_folder(usb_path) if usb_path else None

        # If last import failed for this same USB mount, wait for physical removal/reinsert
        # before trying again to avoid an infinite decrypt-fail loop.
        if usb_path and self.failed_usb_mount_path:
            try:
                same_mount = os.path.abspath(usb_path) == os.path.abspath(self.failed_usb_mount_path)
            except Exception:
                same_mount = usb_path == self.failed_usb_mount_path
            if same_mount:
                self.root.after(2000, self.check_usb_loop)
                return

        if ballot_path and os.path.exists(ballot_path):
            # Found USB with encrypted ballot folder - trigger import
            self.stop_scanning = True
            self.last_usb_import_error = None
            self.ballot_manager.usb_mount_point = usb_path
            self.import_encrypted_ballots(usb_path)
        else:
            if self.failed_usb_mount_path:
                self.failed_usb_mount_path = None
            self.root.after(2000, self.check_usb_loop)

    def import_encrypted_ballots(self, usb_path):
        """Import encrypted ballots from USB and prepare for voting."""
        self.stop_scanning = True
        self.clear_container()
        frame = tk.Frame(self.main_container, bg="#E8F5E9")
        frame.pack(expand=True, fill=tk.BOTH)
        
        tk.Label(frame, text="Importing Ballots", font=('Helvetica', 32, 'bold'), bg="#E8F5E9", fg="#2E7D32").pack(pady=(150, 20))
        status_label = tk.Label(frame, text="Decrypting and importing ballots...", font=('Helvetica', 18), bg="#E8F5E9", fg="#333")
        status_label.pack(pady=20)
        
        def run_import():
            try:
                from usb_ballot_import import USBBallotImporter
                
                ballot_path = self.ballot_manager._find_ballot_folder(usb_path)
                if not ballot_path:
                    raise Exception("No ballot_<bmd_id> or ballot folder found on USB drive.")
                
                # Create importer (demo_mode=False requires RPi hardware)
                importer = USBBallotImporter(
                    private_key_path=os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), "private.pem"
                    ),
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
                    self.failed_usb_mount_path = None
                    self.last_usb_import_error = None
                    os.environ["EVOTING_AES_KEY_PATH"] = os.path.join(ballot_path, "aes_key.dec")
                    status_label.config(
                        text=f"✓ Successfully imported {summary['total_ballots']} ballots\nProceeding to initialization...",
                        fg="#2E7D32"
                    )
                    self.root.after(2000, self.initialize_core_services)
                else:
                    error_msg = "\\n".join(summary["errors"])
                    self.failed_usb_mount_path = usb_path
                    self.last_usb_import_error = (
                        f"Last import failed: {error_msg}\\n"
                        "Remove this USB and insert a valid Election Data USB to retry."
                    )
                    self.root.after(0, self.show_usb_waiting_screen)
                    
            except Exception as e:
                self.failed_usb_mount_path = usb_path
                self.last_usb_import_error = (
                    f"Last import error: {str(e)}\\n"
                    "Remove this USB and insert a valid Election Data USB to retry."
                )
                self.root.after(0, self.show_usb_waiting_screen)
        
        # Run import in background thread to prevent UI freeze
        import_thread = threading.Thread(target=run_import, daemon=True)
        import_thread.start()

    def end_election(self):
        """Triggers secure export process without automatic shutdown."""
        if self._show_custom_confirm("Confirm End Election", "Are you sure you want to officially end the election?\nThis will export data to USB."):
            self.stop_scanning = True
            
            try:
                schedule = self._load_election_schedule()
                schedule["end_election_completed"] = True
                self._save_election_schedule()
            except Exception as exc:
                print(f"[schedule] Warning: could not persist end-election completion flag early: {exc}")
                
            self.show_idle_screen()
            
            self.show_printing_modal(text="Ending election and exporting logs...")
            threading.Thread(target=self._end_election_worker, daemon=True).start()

    def _end_election_worker(self):
        try:
            # Find the USB drive explicitly in case it was unplugged.
            usb_path = self.ballot_manager._find_usb_drive(None)
            if not usb_path:
                raise Exception("USB Drive not found! Please insert the admin USB drive to export logs.")

            from export_service import ExportService
            exporter = ExportService("private.pem", usb_mount_point=usb_path)
            export_path = exporter.export_election_data(self.log_dir, usb_path)

            # Fetch final hash and force printing of final receipt before shutdown.
            if self.print_enabled and hasattr(self, 'data_handler') and hasattr(self, 'printer_service'):
                final_hash = self.data_handler.last_hash or "UNKNOWN_HASH"
                self.printer_service.print_end_election_ticket(final_hash, export_path)
            elif self.print_enabled:
                raise Exception("Core services unavailable for end-of-election receipt printing.")

            self.root.after(0, lambda: self._complete_end_election(export_path))
        except Exception as e:
            self.root.after(0, lambda err=str(e): self._fail_end_election(err))

    def _complete_end_election(self, export_path):
        try:
            schedule = self._load_election_schedule()
            schedule["end_election_completed"] = True
            self._save_election_schedule()
        except Exception as exc:
            print(f"[schedule] Warning: could not persist end-election completion flag: {exc}")

        # --- LOCAL EXPORT TRANSFER ---
        try:
            import datetime
            import shutil
            ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            local_export_dir = os.path.join(self.log_dir, ts)
            os.makedirs(local_export_dir, exist_ok=True)
            
            files_to_transfer = [
                getattr(self, 'election_schedule_path', None),
                getattr(self, 'db_path', None),
                getattr(self, 'tokens_log', None),
                getattr(self, 'votes_log', None)
            ]
            
            for fpath in files_to_transfer:
                if fpath and os.path.exists(fpath):
                    try:
                        shutil.move(fpath, local_export_dir)
                    except Exception as move_err:
                        print(f"Move failed for {fpath}, falling back to copy: {move_err}")
                        shutil.copy2(fpath, local_export_dir)
                        
            print(f"Transferred local log files to {local_export_dir}")
        except Exception as e:
            print(f"Warning: Failed to transfer local log files: {e}")
        # -----------------------------

        self.close_printing_modal()
        self._show_custom_messagebox(
            "Export Successful",
            f"Election successfully ended.\nEncrypted logs safely exported to:\n{export_path}\n\nAutomatic shutdown is temporarily disabled."
        )
        self.show_idle_screen()

    def _fail_end_election(self, error_message):
        self.close_printing_modal()
        self._show_custom_messagebox("Export Error", f"A critical error occurred during export:\n{error_message}", alert_type='error')

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
            
            if not getattr(self, 'printer_service', None):
                self.printer_service = PrinterService(self.data_handler)
            else:
                self.printer_service.data_handler = self.data_handler
            
            # Perform an initial cut to clear the printer roll on startup
            if not self.printer_service.is_printer_connected():
                self._show_custom_messagebox("Printer Error", "No USB thermal printer detected! Cannot safely run election. Please connect printer and restart system.", alert_type='error')
                return

            try:
                if not self.print_enabled:
                    print("Printing disabled: skipping startup cut.")
                else:
                    # Just do an initial feed+cut to clear any previous partial print on the roll.
                    # The genesis/startup ticket is printed later when the election window first activates.
                    self.printer_service.printer.text("\n\n\n\n\n\n\n\n\n\n") # Feed past blade
                    self.printer_service.printer.cut()
                    self.printer_service.printer.text("\n\n\n\n\n\n") # Extra feed after cut
                    print("Printer initialized with a startup cut.")
            except Exception as e:
                self._show_custom_messagebox("Printer Error", f"Startup print failed, printer may be jammed: {e}", alert_type='error')
                return
                    
            # Initialize RFID
            self.rfid_service.load_key()
            self.rfid_service.connect()
            
            # Try to load base candidates mapping
            try:
                self.data_handler.load_candidates()
            except Exception as e:
                print(f"Base candidate load failed (normal if generic): {e}")

            # Proceed to the correct idle screen based on election schedule.
            self.show_idle_screen()

        except Exception as e:
            self._show_custom_messagebox("System Security Error", f"Failed to initialize election data from USB: {e}", alert_type='error')
            # Keep polling in case they inserted the wrong USB
            self.root.after(3000, self.show_usb_waiting_screen)

    def clear_container(self):
        if self.clock_after_id:
            try:
                self.root.after_cancel(self.clock_after_id)
            except Exception:
                pass
            self.clock_after_id = None
        self.clock_label = None

        if self.inactive_check_after_id:
            try:
                self.root.after_cancel(self.inactive_check_after_id)
            except Exception:
                pass
            self.inactive_check_after_id = None

        for widget in self.main_container.winfo_children():
            widget.destroy()

    def _schedule_file_path(self):
        if self.election_schedule_path:
            return self.election_schedule_path

        base_dir = self.log_dir if self.log_dir and os.path.isdir(self.log_dir) else os.path.dirname(os.path.abspath(__file__))
        self.election_schedule_path = os.path.join(base_dir, "election_schedule.json")
        return self.election_schedule_path

    def _default_election_schedule(self):
        # Secure default: election stays inactive until a valid start/end window is set.
        return {
            "enabled": True,
            "start": "",
            "end": "",
            "start_ticket_printed_for": "",
            "end_election_completed": False,
        }

    def _load_election_schedule(self):
        if self.election_schedule is not None:
            return self.election_schedule

        path = self._schedule_file_path()
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    merged = self._default_election_schedule()
                    merged.update(loaded)
                    self.election_schedule = merged
                    return self.election_schedule
        except Exception as e:
            print(f"Schedule load warning: {e}")

        self.election_schedule = self._default_election_schedule()
        return self.election_schedule

    def _save_election_schedule(self):
        schedule = self._load_election_schedule()
        path = self._schedule_file_path()
        try:
            parent = os.path.dirname(path)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(schedule, f, indent=2)
            return True
        except Exception as e:
            self._show_custom_messagebox("Schedule Save Failed", f"Could not save election schedule:\n{e}", alert_type='error')
            return False

    def _parse_schedule_datetime(self, value):
        text = str(value or "").strip()
        if not text:
            raise ValueError("Empty datetime value")

        formats = [
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%d-%m-%Y %H:%M",
            "%d-%m-%Y %H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H:%M:%S",
        ]
        for fmt in formats:
            try:
                return datetime.datetime.strptime(text, fmt)
            except ValueError:
                continue

        try:
            return datetime.datetime.fromisoformat(text)
        except Exception as exc:
            raise ValueError(
                "Invalid datetime format. Use 'YYYY-MM-DD HH:MM' (or ISO)."
            ) from exc

    def _get_schedule_window(self):
        schedule = self._load_election_schedule()
        if not schedule.get("enabled", False):
            return None, None

        start_text = str(schedule.get("start", "") or "").strip()
        end_text = str(schedule.get("end", "") or "").strip()
        if not start_text or not end_text:
            return None, None

        start_dt = self._parse_schedule_datetime(start_text)
        end_dt = self._parse_schedule_datetime(end_text)
        return start_dt, end_dt

    def _is_election_active_now(self):
        schedule = self._load_election_schedule()
        
        if schedule.get("end_election_completed"):
            return False

        if not schedule.get("enabled", False):
            return True

        try:
            start_dt, end_dt = self._get_schedule_window()
            if not start_dt or not end_dt:
                return False
            now = datetime.datetime.now()
            return start_dt <= now <= end_dt
        except Exception:
            return False

    def _current_schedule_text(self):
        schedule = self._load_election_schedule()
        if not schedule.get("enabled", False):
            return "Schedule not set (always active)."
        start = str(schedule.get("start", "") or "").strip() or "N/A"
        end = str(schedule.get("end", "") or "").strip() or "N/A"
        end_done = bool(schedule.get("end_election_completed", False))
        status = "End election done" if end_done else "End election pending"
        return f"Active window: {start} -> {end} | {status}"

    def _ensure_start_ticket_for_active_window(self):
        schedule = self._load_election_schedule()
        if not schedule.get("enabled", False):
            return

        start_text = str(schedule.get("start", "") or "").strip()
        if not start_text:
            return

        if schedule.get("start_ticket_printed_for", "") == start_text:
            return

        if not self.print_enabled:
            schedule["start_ticket_printed_for"] = start_text
            self._save_election_schedule()
            return

        if not hasattr(self, 'printer_service') or not self.printer_service:
            return

        if not self.printer_service.is_printer_connected():
            print("[schedule] Start-window ticket pending: printer not connected.")
            return

        try:
            election_hash = getattr(self.data_handler, 'last_hash', None) if hasattr(self, 'data_handler') else None
            self.printer_service.print_startup_ticket(election_hash or "UNKNOWN_HASH", self.log_dir)
            schedule["start_ticket_printed_for"] = start_text
            self._save_election_schedule()
            print("[schedule] Start-window ticket printed.")
        except Exception as exc:
            print(f"[schedule] Failed printing start-window ticket: {exc}")

    def show_idle_screen(self):
        # One-time startup check for unresolved PENDING journal entries.
        if not self._journal_startup_checked:
            self._journal_startup_checked = True
            self.root.after(400, self._check_pending_journal)

        is_active = self._is_election_active_now()

        if is_active and self._last_schedule_active is not True:
            self._ensure_start_ticket_for_active_window()

        self._last_schedule_active = is_active

        if is_active:
            self.show_rfid_screen()
        else:
            self.show_election_inactive_screen()

    def show_election_inactive_screen(self):
        self.clear_container()
        frame = tk.Frame(self.main_container, bg="#FFF3E0")
        frame.pack(expand=True, fill=tk.BOTH)

        schedule = self._load_election_schedule()
        is_ended = schedule.get("end_election_completed", False)
        
        title_text = "Elections have ended!" if is_ended else "Election is Inactive"
        desc_text = "The polling process has been officially concluded." if is_ended else "Voting is currently disabled outside the configured time window."

        tk.Label(
            frame,
            text=title_text,
            font=('Helvetica', 34, 'bold'),
            bg="#FFF3E0",
            fg="#E65100"
        ).pack(pady=(140, 18))

        tk.Label(
            frame,
            text=desc_text,
            font=('Helvetica', 20),
            bg="#FFF3E0",
            fg="#333"
        ).pack(pady=8)

        tk.Label(
            frame,
            text=self._current_schedule_text(),
            font=('Helvetica', 16, 'italic'),
            bg="#FFF3E0",
            fg="#555"
        ).pack(pady=(14, 6))

        schedule = self._load_election_schedule()
        try:
            _, end_dt = self._get_schedule_window()
        except Exception:
            end_dt = None
        now = datetime.datetime.now()
        show_pending_end_msg = bool(end_dt and now > end_dt and not schedule.get("end_election_completed", False))

        if show_pending_end_msg:
            tk.Label(
                frame,
                text="Election window ended. Polling Officer must run End Election and Export.",
                font=('Helvetica', 14, 'bold'),
                bg="#FFF3E0",
                fg="#B45309",
                wraplength=900,
                justify='center'
            ).pack(pady=(4, 8))

        tk.Label(
            frame,
            text="Scan authorized Polling Officer RFID card to manage election timings.",
            font=('Helvetica', 14, 'italic'),
            bg="#FFF3E0",
            fg="#666"
        ).pack(pady=(8, 0))

        self.clock_label = tk.Label(
            frame,
            text="",
            font=('Helvetica', 16, 'bold'),
            bg="#111",
            fg="#FFFFFF",
            padx=14,
            pady=6,
        )
        self.clock_label.place(relx=0.985, rely=0.03, anchor='ne')
        self._refresh_clock_label()

        self.stop_scanning = False
        self.officer_scan_queue = queue.Queue()
        self.officer_scan_thread = threading.Thread(target=self.officer_scan_loop)
        self.officer_scan_thread.daemon = True
        self.officer_scan_thread.start()
        self.check_officer_scan_queue()

        self._schedule_inactive_recheck()

    def _schedule_inactive_recheck(self):
        if self._is_election_active_now():
            self.show_rfid_screen()
            return
        self.inactive_check_after_id = self.root.after(5000, self._schedule_inactive_recheck)

    def _refresh_clock_label(self):
        if not self.clock_label or not self.clock_label.winfo_exists():
            self.clock_after_id = None
            return

        now_text = datetime.datetime.now().strftime("%d-%b-%Y  %I:%M:%S %p")
        self.clock_label.config(text=now_text)
        self.clock_after_id = self.root.after(1000, self._refresh_clock_label)

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
        if self.session_complete_after_id:
            try:
                self.root.after_cancel(self.session_complete_after_id)
            except Exception:
                pass
            self.session_complete_after_id = None

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
            
            # Use full area; this screen should not show action buttons.
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

        # Top-right live clock for polling staff visibility.
        self.clock_label = tk.Label(
            frame,
            text="",
            font=('Helvetica', 16, 'bold'),
            bg="#111",
            fg="#FFFFFF",
            padx=14,
            pady=6,
        )
        self.clock_label.place(relx=0.985, rely=0.03, anchor='ne')
        self._refresh_clock_label()

        # Start Scanning Thread — handles both voter and officer cards (AES mode).
        self.stop_scanning = False
        self.scan_queue = queue.Queue()
        self.scan_thread = threading.Thread(target=self.rfid_scan_loop)
        self.scan_thread.daemon = True
        self.scan_thread.start()
        
        self.check_scan_queue()

    def rfid_scan_loop(self):
        while not self.stop_scanning:
            if not getattr(self.rfid_service, 'connected', False):
                try:
                    self.rfid_service.connect()
                except Exception:
                    pass
                time.sleep(0.5)
                continue

            # Both voter and officer cards are AES-encrypted — single scan path.
            # on_card_scanned routes officer phrases to on_officer_card_scanned.
            result = self.rfid_service.read_card(mode='encrypted')
            if result:
                self.scan_queue.put(result)
                if result[0] != "error":
                    break
                # Error (e.g. unprovisioned card): show in UI but keep scanning.
                time.sleep(1.0)
                continue
            # No card or transient failure — short poll before next attempt.
            time.sleep(0.15)

    def check_scan_queue(self):
        try:
            result = self.scan_queue.get_nowait()
            if result:
                uid, token = result
                if uid == "error":
                    # Update status label with the error message instead of failing
                    if hasattr(self, 'rfid_status_label') and self.rfid_status_label.winfo_exists():
                        self.rfid_status_label.config(text=f"Read Failed! {token}", fg="#D32F2F")
                        self.root.after(3000, lambda: self.rfid_status_label.config(text="Waiting for Card...", fg="#fff") if self.rfid_status_label.winfo_exists() else None)
                    # Keep scanning
                    self.root.after(200, self.check_scan_queue)
                    return
                self.on_card_scanned(token)
                return
        except queue.Empty:
            pass
            
        if not self.active_token: 
             self.root.after(200, self.check_scan_queue)

    def reset_token_log(self):
        try:
            import os
            token_log = getattr(self.data_handler, 'token_log_file', "tokens.log")
            if os.path.exists(token_log):
                os.remove(token_log)
                self._show_custom_messagebox("Dev Tool", "Token Log Cleared!\nAll cards can be used again.")
            else:
                self._show_custom_messagebox("Dev Tool", "Token Log is already empty.")
        except Exception as e:
            self._show_custom_messagebox("Error", f"Failed to reset log: {e}", alert_type='error')

    def skip_rfid_check(self):
        self.stop_scanning = True
        # Simulate a dev token that grants access only to election_id_1.
        payload = '{"v":"DEV_SKIP_' + str(int(time.time())) + '","e":"election_id_1","b":1}'
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

    def _get_bmd_id(self):
        """Resolve this device's BMD ID (integer). Returns None if not determinable."""
        # 1. Environment variable (highest priority, set by first_boot_provision)
        env_val = os.environ.get("EVOTING_BMD_ID", "").strip()
        if env_val:
            try:
                return int(env_val)
            except ValueError:
                pass

        # 2. /etc/evoting/bmd_id (Linux/RPi system file)
        bmd_file = "/etc/evoting/bmd_id"
        if os.path.exists(bmd_file):
            try:
                raw = open(bmd_file).read().strip()
                if raw:
                    return int(raw)
            except Exception:
                pass

        # 3. bmd_config.json in project directory (written by provisioner)
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bmd_config.json")
        if os.path.exists(config_path):
            try:
                data = json.load(open(config_path))
                bmd_id = data.get("bmd_id")
                if bmd_id is not None:
                    return int(bmd_id)
            except Exception:
                pass

        return None

    def on_card_scanned(self, token_payload):
        if self.data_handler is None:
            print("❌ DataHandler not initialized. Rejecting voter session.")
            self.show_rfid_error("System Loading\nPlease wait, loading elections...")
            return

        if self._is_polling_officer_token(token_payload):
            self.on_officer_card_scanned(token_payload)
            return

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
                # Compact format: {"v":"...","e":"...","b":...}
                # Legacy format:  {"token_id":"...","voter_id":"...","eid_vector":"...","booth":...}
                voter_id = data.get('v') or data.get('voter_id') or data.get('entry_number')
                eid_raw  = data.get('e') or data.get('eid_vector')
                booth    = data.get('b') or data.get('booth')

                # voter_id doubles as token_id in the compact format (no separate token_id)
                token_id = data.get('token_id') or voter_id or token_id
                self.current_token_id = token_id

                if voter_id:
                    self.current_voter_id = voter_id

                if eid_raw is not None:
                    if isinstance(eid_raw, list):
                        eid_vector_str = ";".join(str(x) for x in eid_raw)
                    else:
                        eid_vector_str = str(eid_raw)

                if booth is not None:
                    self.current_booth = booth

            elif isinstance(data, list):
                # Legacy array payload: [token_id, voter_id, eid_vector, booth]
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
            
        # 2. Booth validation — card's booth must match this device's BMD ID
        bmd_id = self._get_bmd_id()
        if bmd_id is not None and self.current_booth is not None:
            try:
                card_booth = int(self.current_booth)
                device_booth = int(bmd_id)
                if card_booth != device_booth:
                    print(f"❌ Booth mismatch: card={card_booth}, device={device_booth}")
                    self.show_rfid_error(
                        f"Wrong Booth!\nPlease go to Booth {card_booth}."
                    )
                    return
            except (ValueError, TypeError):
                pass

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

        # 4. Filter out already-voted elections using per-election tracking
        primary_identity = self.current_voter_id if self.current_voter_id and self.current_voter_id != "UNKNOWN_VOTER" else token_id
        
        filtered_queue = []
        for eid in self.election_queue:
            if not self.ballot_manager.has_voter_voted(primary_identity, eid):
                filtered_queue.append(eid)
                
        if not filtered_queue and self.election_queue:
            print(f"❌ Voter/Token {primary_identity} already voted in all assigned elections!")
            self.show_rfid_error("Token Already Used\nVoter has already cast a vote for all assigned elections.")
            return
            
        self.election_queue = filtered_queue

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
            is_block = hasattr(self.data_handler, 'is_block_election') and self.data_handler.is_block_election()

            if is_block:
                self.start_block_voting()
            elif is_preferential or is_pair_layout:
                self.start_preferential_voting()
            else:
                self.start_normal_voting()
        else:
            # Abort session and return to home screen
            self.election_queue = []
            self.active_token = None
            self.current_election_id = None
            self.show_idle_screen()

    def finish_voter_session(self, aborted=False):
        """Called when all eligible elections are completed."""
        # 1. BATCH PRINTING IF ENABLED
        if not aborted and self.merge_receipts and hasattr(self, 'receipt_buffer') and self.receipt_buffer and self.print_enabled:
            self.pending_batch_receipts = list(self.receipt_buffer)
            self.show_printing_modal(text="Printing Consolidated VVPAT...")
            
            self.batch_print_queue = queue.Queue()
            
            def batch_printer_worker(receipts):
                try:
                    result = self.printer_service.print_session_receipts(receipts, stage="vvpat")
                    self.batch_print_queue.put(result)
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
            all_records = []
            for entry in self.receipt_buffer:
                vr = entry.get('vote_record')
                if isinstance(vr, list):
                    all_records.extend(vr)
                elif vr:
                    all_records.append(vr)
            for r in all_records:
                self.data_handler.save_json(r)
            self.receipt_buffer = []
            self.pending_batch_receipts = None

        self._finalize_session(aborted)

    def check_batch_print_status(self, aborted=False):
        try:
            result = self.batch_print_queue.get_nowait()
            if isinstance(result, dict) and result.get('stage') == 'vvpat_complete':
                self.close_printing_modal()
                self._show_vvpat_confirmation_modal(
                        "",
                    self._start_receipt_stage_for_batch,
                )
                return
            self.close_printing_modal()
            if result is True:
                # 2. Log Votes (Only if Print Succeeded)
                all_records = []
                source_buffer = self.pending_batch_receipts if self.pending_batch_receipts is not None else self.receipt_buffer
                for entry in source_buffer:
                    vr = entry.get('vote_record')
                    if isinstance(vr, list):
                        all_records.extend(vr)
                    elif vr:
                        all_records.append(vr)
                
                if all_records:
                    for r in all_records:
                        self.data_handler.save_json(r)
                self.receipt_buffer = []
                self.pending_batch_receipts = None
                self._cancel_pending_print_polling()
                self._finalize_session(aborted)
            else:
                print(f"Batch print error: {result}")
                if self._show_custom_confirm("Printer Error", f"Failed to print session receipt: {result}\n\nRetry?", yes_text="Retry", no_text="Cancel"):
                    self.finish_voter_session(aborted)
                else:
                    self.receipt_buffer = []
                    self.pending_batch_receipts = None
                    # Pass True so we don't log votes if the receipt failed to print!
                    self._finalize_session(True)
            return
        except queue.Empty:
            pass

        elapsed = (datetime.datetime.now() - self.batch_print_start_time).total_seconds()
        if elapsed > 60:
            self.close_printing_modal()
            if self._show_custom_confirm("Printer Timeout", "Printer is taking too long.\n\nRetry?"):
                self.finish_voter_session(aborted)
            else:
                self.receipt_buffer = []
                self._finalize_session(True)
            return

        self.batch_print_status_after_id = self.root.after(500, self.check_batch_print_status, aborted)

    def _finalize_session(self, aborted=False):
        # 2. LOG SESSION TOKEN
        if not aborted and self.active_token:
            self.data_handler.log_token(getattr(self, 'current_token_id', None) or self.active_token)
            
        if not aborted:
            self.active_token = None
            self.current_election_id = None
            self._show_session_complete_screen()
            return
        else:
            self._show_custom_messagebox("Session Aborted", "Your session has been cancelled.")
            
        self.active_token = None
        self.current_election_id = None
        self.show_idle_screen()

    def _show_session_complete_screen(self):
        self.clear_container()
        frame = tk.Frame(self.main_container, bg="#E8F5E9")
        frame.pack(expand=True, fill=tk.BOTH)

        tk.Label(
            frame,
            text="Thank You For Voting",
            font=('Helvetica', 38, 'bold'),
            bg="#E8F5E9",
            fg="#1B5E20"
        ).pack(pady=(180, 24))

        countdown_label = tk.Label(
            frame,
            text="Returning to home screen in 5 seconds...",
            font=('Helvetica', 24),
            bg="#E8F5E9",
            fg="#2E7D32"
        )
        countdown_label.pack(pady=10)

        if self.session_complete_after_id:
            try:
                self.root.after_cancel(self.session_complete_after_id)
            except Exception:
                pass
            self.session_complete_after_id = None

        def tick(seconds_left):
            countdown_label.config(text=f"Returning to home screen in {seconds_left}...")
            if seconds_left <= 1:
                self._return_home_after_complete()
                return
            self.session_complete_after_id = self.root.after(1000, lambda: tick(seconds_left - 1))

        tick(5)

    def _return_home_after_complete(self):
        self.session_complete_after_id = None
        self.show_idle_screen()

    def show_rfid_error(self, message):
        self.clear_container()
        frame = tk.Frame(self.main_container, bg="#FFEBEE") # Reddish bg
        frame.pack(expand=True, fill=tk.BOTH)
        
        tk.Label(frame, text="❌ Access Denied", font=('Helvetica', 32, 'bold'), bg="#FFEBEE", fg="#D32F2F").pack(pady=(150, 20))
        tk.Label(frame, text=message, font=('Helvetica', 24), bg="#FFEBEE", fg="#555").pack(pady=20)
        
        # Auto-retry after 3 seconds
        tk.Label(frame, text="(Resetting in 3 seconds...)", font=('Helvetica', 16), bg="#FFEBEE", fg="#777").pack(pady=40)
        self.root.after(3000, self.show_idle_screen)

    def start_session(self, election_id=None):
        """Fetches a fresh ballot for the new session."""
        try:
            new_id, new_file = self.ballot_manager.get_unused_ballot(election_id)
            print(f"Starting Session for {election_id} with Ballot ID: {new_id}")
            self.data_handler.set_ballot_file(new_file)
            return True
        except Exception as e:
            print(f"Failed to load new ballot: {e}")
            self._show_custom_messagebox("Ballot Error", f"Could not load new ballot for {election_id}: {e}", alert_type='error')
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

    def start_block_voting(self):
        self.voting_mode = 'block'
        self.selections = {}
        self.current_rank = 1
        requested = int(getattr(self.data_handler, 'number_of_preferences', 1) or 1)
        self.max_ranks = max(1, min(requested, len(self.data_handler.candidates_base)))
        self.show_selection_screen()

    def show_selection_screen(self):
        self.clear_container()

        if self.voting_mode == 'normal':
            header_bg = "#E3F2FD"
        elif self.voting_mode == 'block':
            header_bg = "#FFF3E0"
        else:
            header_bg = "#F3E5F5"
        header = tk.Frame(self.main_container, bg=header_bg, pady=5)
        header.pack(fill=tk.X)

        if self.voting_mode == 'normal':
            mode_text = "Single Choice Vote"
        elif self.voting_mode == 'block':
            mode_text = f"Select {self.max_ranks} candidates"
        else:
            mode_text = f"Select Preference #{self.current_rank}"
        
        # Dynamic Header
        e_name = getattr(self.data_handler, 'election_name', 'General Election')
        e_id = getattr(self.data_handler, 'election_id', 'E01')
        short_ballot_id = self.data_handler.get_short_ballot_id()
        
        tk.Label(header, text=e_name, font=('Helvetica', 16, 'bold'), bg=header_bg).pack()
        tk.Label(header, text=f"Election ID: {e_id} | Ballot ID: {short_ballot_id}", font=('Helvetica', 10), bg=header_bg, fg="#555").pack()
        tk.Label(header, text=mode_text, font=('Helvetica', 20, 'bold'), bg=header_bg, fg="#333").pack(pady=2)
        
        content = tk.Frame(self.main_container, bg="#ffffff", pady=5, padx=20)
        content.pack(expand=True, fill=tk.BOTH)
        
        if self.voting_mode != 'block':
            self.current_selection_var = tk.IntVar(value=-1)
            if self.current_rank in self.selections:
                 self.current_selection_var.set(self.selections[self.current_rank])
        else:
            self.block_selection_vars = {}
            self.block_option_widgets = []
            preselected_ids = set(self.selections.values())

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

            if self.voting_mode == 'block':
                is_selected = cand['id'] in preselected_ids
                sel_var = tk.IntVar(value=1 if is_selected else 0)
                self.block_selection_vars[cand['id']] = sel_var

                btn = tk.Checkbutton(
                    frame,
                    text=cand_text,
                    variable=sel_var,
                    onvalue=1,
                    offvalue=0,
                    indicatoron=0,
                    font=btn_font,
                    bg=bg_color,
                    fg=fg_color,
                    selectcolor='#e8f5e9',
                    activebackground='#f5f5f5',
                    padx=10,
                    pady=btn_pady,
                    bd=2,
                    relief=tk.RAISED,
                    justify=tk.CENTER,
                    command=self._refresh_block_selection_states,
                    state=state_val
                )
                btn.pack(fill=tk.BOTH, expand=True)
                self.block_option_widgets.append((cand['id'], sel_var, btn))
            else:
                tk.Radiobutton(
                    frame, text=cand_text, variable=self.current_selection_var, value=cand['id'],
                    indicatoron=0, font=btn_font, bg=bg_color, fg=fg_color,
                    selectcolor='#e8f5e9', activebackground='#f5f5f5',
                    padx=10, pady=btn_pady, bd=2, relief=tk.RAISED,
                    justify=tk.CENTER, state=state_val
                ).pack(fill=tk.BOTH, expand=True)

        if self.voting_mode == 'block':
            self._refresh_block_selection_states()

        footer = tk.Frame(self.main_container, bg="#f0f0f0")
        footer.pack(fill=tk.X, side=tk.BOTTOM, pady=10)

        if self.voting_mode == 'normal':
            tk.Button(footer, text="Review Vote", font=('Helvetica', 16, 'bold'), bg="#4CAF50", fg="white", command=self.go_next, padx=15, pady=8).pack(side=tk.RIGHT, padx=30)
        elif self.voting_mode == 'block':
            tk.Button(footer, text="Review Vote", font=('Helvetica', 16, 'bold'), bg="#4CAF50", fg="white", command=self.go_next, padx=15, pady=8).pack(side=tk.RIGHT, padx=30)
        else:
            if self.current_rank > 1:
                tk.Button(footer, text="< Previous", font=('Helvetica', 16), command=self.go_previous, padx=15, pady=8).pack(side=tk.LEFT, padx=30)

            next_text = "Next >" if self.current_rank < self.max_ranks else "Finish"
            tk.Button(footer, text=next_text, font=('Helvetica', 16, 'bold'), bg="#2196F3", fg="white", command=self.go_next, padx=15, pady=8).pack(side=tk.RIGHT, padx=30)

    def abort_session(self):
        """Cancels the voter's session entirely without casting the current vote and clears queue."""
        self.election_queue = []
        self.receipt_buffer = [] # Clear unprinted receipts from this session
        self.finish_voter_session(aborted=True)

    def go_next(self):
        if self.voting_mode == 'block':
            selected_ids = sorted([cid for cid, var in self.block_selection_vars.items() if var.get() == 1])
            if len(selected_ids) != self.max_ranks:
                self._show_custom_messagebox("Selection Required", f"Please select exactly {self.max_ranks} candidates to proceed.")
                return

            self.selections = {idx + 1: cid for idx, cid in enumerate(selected_ids)}
            self.show_confirmation_screen()
            return

        selection = self.current_selection_var.get()
        if selection == -1:
            self._show_custom_messagebox("No Selection", "Please make a selection to proceed.")
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
        elif self.voting_mode == 'block':
            tk.Label(content, text=f"You have selected {self.max_ranks} candidate(s):", font=('Helvetica', 16), bg="white").pack(pady=5)
            for idx in range(1, self.max_ranks + 1):
                cid = self.selections.get(idx)
                cand = self.data_handler.get_candidate_by_id(cid)
                row = tk.Frame(content, bg="white", pady=5)
                row.pack(fill=tk.X)
                if cand:
                    label_text = f"Choice Number {cand['id']} - {cand['name']}"
                    if cand.get('candidate_number'):
                        label_text += f" ({cand['candidate_number']})"
                    tk.Label(row, text=label_text, font=('Helvetica', 20), bg="white", anchor='w').pack(side=tk.LEFT, padx=20)
                else:
                    tk.Label(row, text="[No Selection]", font=('Helvetica', 20), fg="#aaa", bg="white", anchor='w').pack(side=tk.LEFT, padx=20)
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

    def restart_editing(self):
        if self.voting_mode != 'block':
            self.current_rank = 1
        self.show_selection_screen()

    def _refresh_block_selection_states(self):
        if self.voting_mode != 'block' or not hasattr(self, 'block_option_widgets'):
            return

        selected_count = sum(var.get() for _, var, _ in self.block_option_widgets)
        lock_unselected = selected_count >= self.max_ranks
        for _, var, btn in self.block_option_widgets:
            if var.get() == 1:
                btn.config(state=tk.NORMAL)
            else:
                btn.config(state=tk.DISABLED if lock_unselected else tk.NORMAL)

    def cast_vote(self):
        if getattr(self, '_cast_vote_in_progress', False):
            return
        self._cast_vote_in_progress = True
        
        # Prepare Receipt Data Snapshot
        e_name = getattr(self.data_handler, 'election_name', 'General Election')
        ballot_id = self.data_handler.get_short_ballot_id()
        timestamp = datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")

        # Helper to find candidate display string (Captured now!)
        def get_cand_display(cid):
            cand = self.data_handler.get_candidate_by_id(cid)
            if cand:
                return str(cand.get('id') or cid)
            return str(cid)

        def get_vvpat_display(cid):
            cand = self.data_handler.get_candidate_by_id(cid)
            if cand:
                candidate_name = str(cand.get('name') or cand.get('candidate_name') or cand.get('candidate_number') or cand.get('id') or cid).strip()
                candidate_number = str(cand.get('candidate_number') or cand.get('id') or cid).strip()
                if candidate_name and candidate_number and candidate_name != candidate_number:
                    return f"{candidate_name} ({candidate_number})"
                return candidate_name or candidate_number
            return str(cid)

        # Prepare strings
        if self.voting_mode == 'normal':
            cid = self.selections.get(1)
            sel_str = get_cand_display(cid)
            vvpat_sel_str = get_vvpat_display(cid)
            qr_data = self.data_handler.build_receipt_qr_payload(self.selections, self.voting_mode)
        else:
            ranks = sorted(self.selections.keys())
            vals = []
            vvpat_vals = []
            for r in ranks:
                c = self.selections[r]
                vals.append(get_cand_display(c))
                vvpat_vals.append(get_vvpat_display(c))
            sel_str = ", ".join(vals)
            vvpat_sel_str = ", ".join(vvpat_vals)
            qr_data = self.data_handler.build_receipt_qr_payload(self.selections, self.voting_mode)

        # Pre-generate log JSON while context is valid.
        # Block mode produces multiple equal-weight single-choice records.
        if self.voting_mode == 'block':
            vote_record = []
            for rank in sorted(self.selections.keys()):
                cid = self.selections[rank]
                vote_record.append(
                    self.data_handler.generate_vote_json(
                        {'selections': {1: cid}, 'timestamp': timestamp},
                        'normal',
                        getattr(self, 'current_voter_id', 'UNKNOWN'),
                        getattr(self, 'current_booth', 1),
                        getattr(self, 'current_token_id', 'UNKNOWN')
                    )
                )
        else:
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
            'vvpat_choice_str': vvpat_sel_str,
            'qr_choice_data': qr_data,
            'voter_qr_data': voter_qr_data,
            'election_hash': self.data_handler.election_hash,
            # Data for deferred logging
            'vote_record': vote_record,
            'internal_ballot_id': ballot_id
        }
        self.pending_print_job = {
            'kind': 'vote',
            'mode': self.voting_mode,
            'selections': dict(self.selections),
            'receipt_entry': receipt_entry,
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
                if isinstance(vote_record, list):
                    for rec in vote_record:
                        self.data_handler.save_json(rec)
                else:
                    self.data_handler.save_json(vote_record)
                self._cast_vote_in_progress = False
                self.start_next_election()
                return

            # Phase 1: write PENDING to journal before any print attempt
            import uuid as _uuid
            self._pending_journal_id = str(_uuid.uuid4())
            if self._vote_journal:
                self._vote_journal.write_pending(
                    self._pending_journal_id,
                    getattr(self, 'current_voter_id', 'UNKNOWN'),
                    str(self.current_election_id or ''),
                    getattr(self.data_handler, 'election_name', ''),
                    vvpat_sel_str,
                    vote_record,
                    self.voting_mode,
                    dict(self.selections),
                )

            self.show_printing_modal()
            self.print_queue = queue.Queue()

            def printer_worker(mode, sel):
                try:
                    result = self.printer_service.print_vote(mode, sel, is_final=True, stage="vvpat")
                    self.print_queue.put(result)
                except Exception as e:
                    self.print_queue.put(e)

            self.print_thread = threading.Thread(target=printer_worker, args=(self.voting_mode, self.selections))
            self.print_thread.daemon = True
            self.print_thread.start()

            self.print_start_time = datetime.datetime.now()
            self.check_print_status()

    def _show_vvpat_confirmation_modal(self, message, on_ok):
        self.close_printing_modal()
        self._cancel_pending_print_polling()
        self.close_vvpat_confirmation_modal()
        self.vvpat_confirmation_overlay = tk.Toplevel(self.root)
        self.vvpat_confirmation_overlay.title("VVPAT Confirmation")
        w, h = 920, 420
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.vvpat_confirmation_overlay.geometry(f"{w}x{h}+{x}+{y}")
        self.vvpat_confirmation_overlay.transient(self.root)
        self.vvpat_confirmation_overlay.grab_set()
        self.vvpat_confirmation_overlay.overrideredirect(True)

        frame = tk.Frame(self.vvpat_confirmation_overlay, bg="#FFF8E1", bd=4, relief=tk.RAISED)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame,
            text="VVPAT printed.",
            font=('Helvetica', 28, 'bold'),
            bg="#FFF8E1",
            fg="#6D4C41"
        ).pack(pady=(150, 30))

        self.vvpat_countdown_after_id = None

        def proceed_after_brief_pause():
            if not (hasattr(self, 'vvpat_confirmation_overlay') and self.vvpat_confirmation_overlay):
                return
            self.vvpat_countdown_after_id = None
            self.close_vvpat_confirmation_modal()
            on_ok()

        self.vvpat_countdown_after_id = self.root.after(1200, proceed_after_brief_pause)

    def _show_large_yes_no_dialog(self, title, message, yes_text="Yes", no_text="No"):
        result = {"value": False}
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        w, h = 980, 520
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")
        dlg.transient(self.root)
        dlg.grab_set()

        frame = tk.Frame(dlg, bg="#FFFDE7", bd=4, relief=tk.RAISED)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame,
            text=title,
            font=('Helvetica', 30, 'bold'),
            bg="#FFFDE7",
            fg="#4E342E"
        ).pack(pady=(30, 16))

        tk.Label(
            frame,
            text=message,
            font=('Helvetica', 22),
            bg="#FFFDE7",
            fg="#3E2723",
            wraplength=900,
            justify=tk.CENTER
        ).pack(pady=(0, 26))

        btn_row = tk.Frame(frame, bg="#FFFDE7")
        btn_row.pack(pady=20)

        def choose(value):
            result["value"] = value
            dlg.destroy()

        tk.Button(
            btn_row,
            text=yes_text,
            font=('Helvetica', 24, 'bold'),
            bg="#2E7D32",
            fg="white",
            padx=44,
            pady=16,
            command=lambda: choose(True)
        ).pack(side=tk.LEFT, padx=18)

        tk.Button(
            btn_row,
            text=no_text,
            font=('Helvetica', 24, 'bold'),
            bg="#C62828",
            fg="white",
            padx=44,
            pady=16,
            command=lambda: choose(False)
        ).pack(side=tk.LEFT, padx=18)

        dlg.attributes('-topmost', True)
        dlg.overrideredirect(True)
        dlg.protocol("WM_DELETE_WINDOW", lambda: choose(False))
        dlg.wait_window()
        return result["value"]

    def close_vvpat_confirmation_modal(self):
        after_id = getattr(self, 'vvpat_countdown_after_id', None)
        if after_id:
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
            self.vvpat_countdown_after_id = None

        if hasattr(self, 'vvpat_confirmation_overlay') and self.vvpat_confirmation_overlay:
            self.vvpat_confirmation_overlay.destroy()
            self.vvpat_confirmation_overlay = None

    def _cancel_pending_print_polling(self):
        for attr in ("print_status_after_id", "batch_print_status_after_id"):
            after_id = getattr(self, attr, None)
            if after_id:
                try:
                    self.root.after_cancel(after_id)
                except Exception:
                    pass
                setattr(self, attr, None)

    def _start_receipt_stage_for_vote(self):
        if not self.pending_print_job:
            return

        self._complete_vote_after_vvpat()

    def _start_receipt_stage_for_batch(self):
        if not self.pending_batch_receipts:
            return

        self._complete_batch_after_vvpat()

    def _complete_vote_after_vvpat(self):
        self.close_vvpat_confirmation_modal()
        self._cancel_pending_print_polling()

        try:
            if not self.merge_receipts:
                vote_data = {'selections': self.selections}
                self.data_handler.save_vote(
                    vote_data,
                    self.voting_mode,
                    getattr(self, 'current_voter_id', 'UNKNOWN'),
                    getattr(self, 'current_booth', 1),
                    getattr(self, 'current_token_id', 'UNKNOWN')
                )

            self.ballot_manager.mark_as_used(self.data_handler.ballot_file_id, self.current_election_id)

            vid = getattr(self, 'current_voter_id', 'UNKNOWN')
            tid = getattr(self, 'current_token_id', 'UNKNOWN')
            primary_identity = vid if vid and vid != 'UNKNOWN_VOTER' else tid
            self.ballot_manager.mark_voter_election_used(primary_identity, self.current_election_id)

            self.data_handler.store_used_ballot_snapshot(
                election_id=self.current_election_id,
                ballot_file_id=self.data_handler.ballot_file_id,
                status="USED"
            )

            # Phase 2: COMMITTED — vote is durably saved
            if self._vote_journal:
                self._vote_journal.write_committed(self._pending_journal_id)
            self._pending_journal_id = None

            self.pending_print_job = None
            self._cast_vote_in_progress = False
            self.start_next_election()
        except Exception as e:
            self._cast_vote_in_progress = False
            self._show_custom_messagebox("System Error", f"Vote recorded but processing failed: {e}", alert_type="error")

    def _complete_batch_after_vvpat(self):
        self.close_vvpat_confirmation_modal()
        self._cancel_pending_print_polling()

        try:
            all_records = []
            source_buffer = self.pending_batch_receipts if self.pending_batch_receipts is not None else self.receipt_buffer
            for entry in source_buffer:
                vr = entry.get('vote_record')
                if isinstance(vr, list):
                    all_records.extend(vr)
                elif vr:
                    all_records.append(vr)

            if all_records:
                for r in all_records:
                    self.data_handler.save_json(r)

            self.receipt_buffer = []
            self.pending_batch_receipts = None
            self._finalize_session(False)
        except Exception as e:
            self._show_custom_messagebox("System Error", f"Vote recorded but processing failed: {e}", alert_type="error")

    def challenge_vote(self):
        """Voter challenges the ballot: print a challenge receipt (no VVPAT, no vote recorded).

        The ballot is marked CHALLENGED so it cannot be cast or reused.
        The voter sees a receipt showing their ballot ID and selection so they
        can independently verify the cryptographic commitments.
        """
        current_challenges = self.challenge_counts_by_election.get(self.current_election_id, 0)
        if current_challenges >= self.max_challenges_per_election:
            self._show_custom_messagebox(
                "Challenge Limit Reached",
                "You have already used your one allowed challenge in this election.\n"
                "Please cast your vote."
            )
            return

        if not self._show_large_yes_no_dialog(
            "Challenge Ballot",
            "Challenging this ballot will:\n\n"
            "- Print a receipt with your Ballot ID and selection\n"
            "- NOT count your vote\n"
            "- Invalidate this ballot (it cannot be used again)\n\n"
            "Do you want to challenge?",
            yes_text="Yes",
            no_text="No"
        ):
            return

        ballot_id = self.data_handler.ballot_id
        timestamp = datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")

        def get_cand_display(cid):
            cand = self.data_handler.get_candidate_by_id(cid)
            if cand:
                return str(cand.get('id') or cid)
            return str(cid)

        if self.voting_mode == 'normal':
            cid = self.selections.get(1)
            sel_str = get_cand_display(cid)
        else:
            ranks = sorted(self.selections.keys())
            sel_str = ", ".join(get_cand_display(self.selections[r]) for r in ranks)

        selected_commitment = self.data_handler.build_receipt_qr_payload(self.selections, self.voting_mode)
        raw_election_id = str(getattr(self, 'current_election_id', '') or getattr(self.data_handler, 'election_id', ''))
        election_id_for_qr = raw_election_id
        if raw_election_id.lower().startswith("election_id_"):
            election_id_for_qr = raw_election_id[len("election_id_"):]
        elif raw_election_id.upper().startswith("E") and raw_election_id[1:].isdigit():
            election_id_for_qr = raw_election_id[1:]

        bid_for_qr = str(self.data_handler.get_short_ballot_id(ballot_id) or "")

        import json
        voter_qr_data = json.dumps([
            str(election_id_for_qr or ""),
            str(selected_commitment or ""),
            bid_for_qr
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
                self._show_custom_messagebox(
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
                    satisfied = self._show_large_yes_no_dialog(
                        "Challenge Verification",
                        "Are you satisfied after the challenge verification?\n\n"
                        "Yes: You will vote again in this same election using a new ballot.\n"
                        "No: Session will be paused/aborted for Presiding Officer review.",
                        yes_text="Yes",
                        no_text="No"
                    )
                    chosen_label = "SATISFIED" if satisfied else "NOT SATISFIED"
                    confirmed = self._show_large_yes_no_dialog(
                        "Confirm Selection",
                        f"You selected: {chosen_label}.\n\n"
                        "Press Yes to confirm this choice, or No to choose again.",
                        yes_text="Yes",
                        no_text="No"
                    )
                    if confirmed:
                        break
                if satisfied:
                    self.restart_current_election_after_challenge()
                else:
                    self.show_temporarily_down_screen()
            else:
                self.close_printing_modal()
                if self._show_custom_confirm("Printer Error", f"Printing Failed: {result}\n\nRetry?", yes_text="Retry", no_text="Cancel"):
                    self.challenge_vote()
            return
        except queue.Empty:
            elapsed = (datetime.datetime.now() - self.print_start_time).total_seconds()
            if elapsed > 30:
                self.close_printing_modal()
                self._show_custom_messagebox("Timeout", "Challenge receipt print timed out.", alert_type='error')
                return
            self.root.after(200, self._check_challenge_print_status)

    def restart_current_election_after_challenge(self):
        """Load a fresh ballot and restart the same election after a successful challenge."""
        if not self.current_election_id:
            self._show_custom_messagebox("Session Error", "No active election context found.", alert_type='error')
            self.finish_voter_session(aborted=True)
            return

        success = self.start_session(self.current_election_id)
        if not success:
            self.finish_voter_session(aborted=True)
            return

        e_type = self.data_handler.election_type.lower()
        if "block" in e_type:
            self.start_block_voting()
        elif "preferential" in e_type or "ranked" in e_type:
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

    def _on_polling_officer_button_clicked(self):
        """Called when the Polling Officer button is pressed on the voter RFID screen.

        Pauses the voter scan loop and shows a modal overlay instructing the officer
        to scan their RFID card.  A background thread reads the card in plain mode
        and, on success, routes to on_officer_card_scanned.  A Cancel button lets
        voters return to normal waiting without leaving the unit in a broken state.
        """
        # Pause voter scan loop
        self.stop_scanning = True

        # ── Officer scan overlay ──────────────────────────────────────────────
        overlay = tk.Toplevel(self.root)
        overlay.title("Polling Officer Verification")
        overlay.configure(bg="#0D1B6E")
        overlay.attributes("-topmost", True)
        overlay.grab_set()  # modal

        # Center the overlay
        ow, oh = 560, 340
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        overlay.geometry(f"{ow}x{oh}+{(sw - ow) // 2}+{(sh - oh) // 2}")
        overlay.resizable(False, False)
        overlay.overrideredirect(True)  # borderless

        tk.Label(
            overlay,
            text="\U0001F6E1  Polling Officer Verification",
            font=('Helvetica', 18, 'bold'),
            bg="#0D1B6E",
            fg="#FFFFFF",
        ).pack(pady=(30, 8))

        tk.Label(
            overlay,
            text="Please scan your Polling Officer RFID card now.",
            font=('Helvetica', 14),
            bg="#0D1B6E",
            fg="#90CAF9",
            wraplength=500,
            justify="center",
        ).pack(pady=(0, 10))

        status_lbl = tk.Label(
            overlay,
            text="Waiting for card...",
            font=('Helvetica', 13, 'italic'),
            bg="#0D1B6E",
            fg="#FFD54F",
        )
        status_lbl.pack(pady=6)

        cancelled = [False]
        result_holder = [None]

        def _cancel():
            cancelled[0] = True
            overlay.grab_release()
            overlay.destroy()
            # Resume normal voter scanning
            self.stop_scanning = False
            self.scan_queue = queue.Queue()
            self.scan_thread = threading.Thread(target=self.rfid_scan_loop)
            self.scan_thread.daemon = True
            self.scan_thread.start()
            self.check_scan_queue()

        tk.Button(
            overlay,
            text="Cancel",
            font=('Helvetica', 13),
            bg="#B71C1C",
            fg="white",
            activebackground="#C62828",
            activeforeground="white",
            relief=tk.FLAT,
            padx=24,
            pady=8,
            cursor="hand2",
            command=_cancel,
        ).pack(pady=(16, 0))

        # ── Background thread: plain-mode officer card scan ───────────────────
        officer_q = queue.Queue()

        def _officer_scan_worker():
            # Reconnect if needed
            if not getattr(self.rfid_service, 'connected', False):
                try:
                    self.rfid_service.connect()
                except Exception:
                    pass
            # Poll until we get a result or a cancel signal
            deadline = time.time() + 30  # 30-second scan window
            while time.time() < deadline:
                if cancelled[0]:
                    return
                result = self.rfid_service.read_card(mode='plain')
                if result:
                    if result[0] != "error":
                        officer_q.put(result)
                        return
                    # Unprovisioned card — log and keep scanning.
                    print(f"Officer scan: {result[1]}, retrying.")
                    time.sleep(1.0)
                    continue
                time.sleep(0.4)
            # Timeout
            officer_q.put(None)

        scan_thread = threading.Thread(target=_officer_scan_worker, daemon=True)
        scan_thread.start()

        # ── Poll queue from the Tkinter main loop ────────────────────────────
        def _check_officer_q():
            if cancelled[0]:
                return
            try:
                res = officer_q.get_nowait()
                overlay.grab_release()
                overlay.destroy()
                if res is None:
                    # Timeout — update status and resume voter scan
                    self.stop_scanning = False
                    self.scan_queue = queue.Queue()
                    self.scan_thread = threading.Thread(target=self.rfid_scan_loop)
                    self.scan_thread.daemon = True
                    self.scan_thread.start()
                    self.check_scan_queue()
                    self._show_custom_messagebox(
                        "Timeout",
                        "No officer card detected within 30 seconds.\nReturning to voter screen.",
                        alert_type="error"
                    )
                    return
                # Got a card — route to officer handler
                uid, token_payload = res
                self.on_officer_card_scanned(token_payload)
                return
            except queue.Empty:
                pass
            # Update the waiting animation
            dots = getattr(self, '_officer_wait_dots', 0)
            self._officer_wait_dots = (dots + 1) % 4
            try:
                status_lbl.config(text="Waiting for card" + "." * self._officer_wait_dots)
            except Exception:
                pass
            self.root.after(400, _check_officer_q)

        self.root.after(400, _check_officer_q)

    def officer_scan_loop(self):
        while not self.stop_scanning:
            # Reconnect automatically if RFID wasn't initialized yet.
            if not getattr(self.rfid_service, 'connected', False):
                try:
                    self.rfid_service.connect()
                except Exception:
                    pass
                time.sleep(0.5)
                continue

            # Admin/officer cards carry an AES-encrypted phrase — use explicit plain mode.
            result = self.rfid_service.read_card(mode='plain')
            if result:
                if result[0] != "error":
                    self.officer_scan_queue.put(result)
                    break
                # Unprovisioned card — log and keep scanning.
                print(f"Officer scan: {result[1]}, retrying.")
                time.sleep(1.0)
                continue
            time.sleep(0.5)

    def check_officer_scan_queue(self):
        if self.stop_scanning:
            return

        try:
            result = self.officer_scan_queue.get_nowait()
            if result:
                uid, token_payload = result
                if uid == "ERROR":
                    # Restart the background thread, then show a message box
                    self.stop_scanning = False
                    import threading
                    threading.Thread(target=self.officer_scan_loop, daemon=True).start()
                    self.root.after(500, self.check_officer_scan_queue)
                    
                    try:
                        self._show_custom_messagebox("Card Error", "Card Read Failed! Please try again.", alert_type="error")
                    except Exception:
                        pass
                    return
                self.on_officer_card_scanned(token_payload)
                return
        except queue.Empty:
            pass

        self.root.after(500, self.check_officer_scan_queue)

    def _normalize_officer_command(self, raw_command):
        cmd = str(raw_command or "").strip().upper().replace("-", "_").replace(" ", "_")
        aliases = {
            "END_ELECTION_AND_EXPORT": "END_ELECTION_EXPORT",
            "END_ELECTION": "END_ELECTION_EXPORT",
            "EXPORT": "END_ELECTION_EXPORT",
            "STATUS": "SYSTEM_STATUS",
            "PRINT_TOGGLE": "TOGGLE_PRINT",
            "REPRINT_SLIP": "REPRINT_DEVICE_SLIP",
            "REPRINT_DEVICE": "REPRINT_DEVICE_SLIP",
            "UPDATE": "UPDATE_FIRMWARE",
            "FIRMWARE_UPDATE": "UPDATE_FIRMWARE",
            "RETURN_USB": "RETURN_USB_SCREEN",
            "USB_SCREEN": "RETURN_USB_SCREEN",
            "EXIT": "CLOSE_APPLICATION",
            "CLOSE_APP": "CLOSE_APPLICATION",
            "SET_ELECTION_WINDOW": "SET_WINDOW",
            "EXTEND_END": "EXTEND_END_MINUTES",
            "EXTEND": "EXTEND_END_MINUTES",
            "EXTEND_END_TIME": "EXTEND_END_MINUTES",
        }
        return aliases.get(cmd, cmd)

    def _parse_officer_command_line(self, command_line):
        line = str(command_line or "").strip()
        if not line:
            return "", ""

        if "=" in line and line.upper().startswith(("CMD=", "COMMAND=")):
            line = line.split("=", 1)[1].strip()

        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 1 and "," in line:
            parts = [p.strip() for p in line.split(",")]

        command = self._normalize_officer_command(parts[0])
        args = "|".join(parts[1:]).strip() if len(parts) > 1 else ""
        return command, args

    def _has_polling_officer_phrase(self, token_payload):
        phrase = self.polling_officer_phrase
        text = str(token_payload or "").strip().replace("\\n", "\n")

        if text == phrase:
            return True

        if text.upper().startswith(phrase.upper()):
            remainder = text[len(phrase):]
            if not remainder:
                return True
            if remainder[0] in " \t\r\n:;|,-":
                return True

        try:
            import json
            data = json.loads(text)
            if isinstance(data, dict):
                embedded_phrase = str(data.get('phrase', '') or data.get('admin_phrase', '')).strip()
                return embedded_phrase.upper() == phrase.upper()
        except Exception:
            pass

        return False

    def _extract_polling_officer_command(self, token_payload):
        """Extract optional command from phrase-authorized officer card payload."""
        phrase = self.polling_officer_phrase
        text = str(token_payload or "").strip().replace("\\n", "\n")

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                embedded_phrase = str(data.get('phrase', '') or data.get('admin_phrase', '')).strip()
                if embedded_phrase.upper() == phrase.upper():
                    return self._parse_officer_command_line(data.get('command', ''))
        except Exception:
            pass

        if not text.upper().startswith(phrase.upper()):
            return "", ""

        remainder = text[len(phrase):].strip()
        while remainder and remainder[0] in ":;|,-":
            remainder = remainder[1:].strip()

        if not remainder:
            return "", ""

        lines = [ln.strip() for ln in remainder.splitlines() if ln.strip()]
        if not lines:
            return "", ""

        command_line = lines[0]
        if len(lines) > 1 and ("|" not in command_line and "," not in command_line):
            command_line = command_line + "|" + "|".join(lines[1:])
        return self._parse_officer_command_line(command_line)

    def _accepted_officer_commands_text(self):
        return (
            "END_ELECTION_EXPORT\n"
            "SYSTEM_STATUS\n"
            "TOGGLE_PRINT\n"
            "RESET_TOKEN_LOG\n"
            "REPRINT_DEVICE_SLIP\n"
            "UPDATE_FIRMWARE\n"
            "RETURN_USB_SCREEN\n"
            "CLOSE_APPLICATION\n"
            "SET_WINDOW|YYYY-MM-DD HH:MM|YYYY-MM-DD HH:MM\n"
            "EXTEND_END_MINUTES|X"
        )

    def _run_end_election_without_prompt(self):
        self.stop_scanning = True
        self.show_printing_modal(text="Ending election and exporting logs...")
        threading.Thread(target=self._end_election_worker, daemon=True).start()

    def _execute_officer_command(self, command, args=""):
        handlers = {
            "END_ELECTION_EXPORT": self._run_end_election_without_prompt,
            "SYSTEM_STATUS": self._admin_system_status,
            "TOGGLE_PRINT": self.toggle_printing,
            "RESET_TOKEN_LOG": self.reset_token_log,
            "REPRINT_DEVICE_SLIP": self._admin_reprint_device_slip,
            "UPDATE_FIRMWARE": lambda: (
                self.show_printing_modal(text="Updating firmware...\nRunning git pull"),
                threading.Thread(target=self._admin_update_firmware_worker, daemon=True).start(),
            ),
            "RETURN_USB_SCREEN": self.show_usb_waiting_screen,
            "CLOSE_APPLICATION": self.exit_app,
        }

        if command == "SET_WINDOW":
            pieces = [p.strip() for p in str(args or "").split("|") if p.strip()]
            if len(pieces) < 2:
                self._show_custom_messagebox("Invalid COMMAND", "SET_ELECTION_WINDOW|YYYY-MM-DD HH:MM:SS|YYYY-MM-DD HH:MM:SS", alert_type='error')
                return
            self._admin_set_election_window(start_text=pieces[0], end_text=pieces[1], show_messages=True)
            return True

        if command == "EXTEND_END_MINUTES":
            pieces = [p.strip() for p in str(args or "").split("|") if p.strip()]
            if len(pieces) < 1:
                self._show_custom_messagebox("Invalid EXTEND_END_MINUTES", "Use: EXTEND_END_MINUTES|X", alert_type='error')
                return
            try:
                self._admin_extend_end_time(int(pieces[0]))
            except Exception:
                self._show_custom_messagebox("Invalid Minutes", "Please provide numeric minutes.", alert_type='error')
            return True

        handler = handlers.get(command)
        if not handler:
            self._show_custom_messagebox("Invalid Command", f"Unknown command: {command}", alert_type='error')
            return False

        handler()
        return True

    def _is_polling_officer_token(self, token_payload):
        """Only phrase-based cards are authorized for polling-officer actions."""
        return self._has_polling_officer_phrase(token_payload)

    def on_officer_card_scanned(self, token_payload):
        token_text = str(token_payload or "").strip().replace("\\n", "\n")
        phrase_upper = self.polling_officer_phrase.upper()
        token_upper = token_text.upper()
        if token_text and len(token_text) < len(self.polling_officer_phrase) and phrase_upper.startswith(token_upper):
            self._show_custom_messagebox("Incomplete Card Data", "Polling officer card data appears incomplete.\nPlease scan again or rewrite the card payload.", alert_type='error')
            self.stop_scanning = False
            self.officer_scan_queue = queue.Queue()
            self.officer_scan_thread = threading.Thread(target=self.officer_scan_loop)
            self.officer_scan_thread.daemon = True
            self.officer_scan_thread.start()
            self.check_officer_scan_queue()
            return

        if not self._is_polling_officer_token(token_payload):
            self._show_custom_messagebox("Authorization Failed", "This card is not authorized.\nUse the configured phrase card for polling-officer access.", alert_type='error')
            self.stop_scanning = False
            self.officer_scan_queue = queue.Queue()
            self.officer_scan_thread = threading.Thread(target=self.officer_scan_loop)
            self.officer_scan_thread.daemon = True
            self.officer_scan_thread.start()
            self.check_officer_scan_queue()
            return

        self.stop_scanning = True
        command, args = self._extract_polling_officer_command(token_payload)
        if command:
            ran = self._execute_officer_command(command, args)
            if not ran:
                self.stop_scanning = False
                self.officer_scan_queue = queue.Queue()
                self.officer_scan_thread = threading.Thread(target=self.officer_scan_loop)
                self.officer_scan_thread.daemon = True
                self.officer_scan_thread.start()
                self.check_officer_scan_queue()
            return

        self.show_polling_officer_action_menu()

    def show_polling_officer_action_menu(self):
        self.stop_scanning = True
        self.show_admin_menu()

    def _on_key_press(self, event):
        """Accumulate keystrokes and open polling officer menu on 'Aman'."""
        if event.char and event.char.isprintable():
            self._admin_key_buffer += event.char
            self._admin_key_buffer = self._admin_key_buffer[-10:]
            if self._admin_key_buffer.endswith("Aman"):
                self._admin_key_buffer = ""
                self.show_admin_menu()

    def show_admin_menu(self):
        """Full-screen polling officer menu overlay with administrative actions."""
        if self._admin_overlay:
            try:
                if self._admin_overlay.winfo_exists():
                    self._admin_overlay.attributes('-topmost', True)
                    self._admin_overlay.lift()
                    self._admin_overlay.focus_force()
                    return
            except Exception:
                pass

        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.attributes('-fullscreen', True)
        overlay.attributes('-topmost', True)
        overlay.configure(bg="#0d1117")
        overlay.transient(self.root)
        overlay.lift()
        overlay.focus_force()
        self._admin_overlay = overlay

        screen_h = self.root.winfo_screenheight()
        compact_layout = screen_h < 900
        header_pad_y = 12 if compact_layout else 22
        header_title_font = ('Helvetica', 22, 'bold') if compact_layout else ('Helvetica', 28, 'bold')
        header_sub_font = ('Helvetica', 12) if compact_layout else ('Helvetica', 14)
        grid_pad_x = 34 if compact_layout else 60
        grid_pad_y = 10 if compact_layout else 20
        btn_font = ('Helvetica', 16, 'bold') if compact_layout else ('Helvetica', 22, 'bold')
        btn_internal_pad_y = 18 if compact_layout else 36
        btn_internal_pad_x = 16 if compact_layout else 24
        btn_wrap = 280 if compact_layout else 400
        btn_outer_pad_y = 10 if compact_layout else 16

        header = tk.Frame(overlay, bg="#161b22", pady=header_pad_y)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="POLLING OFFICER MENU",
            font=header_title_font,
            bg="#161b22",
            fg="#f0f6fc"
        ).pack()
        tk.Label(
            header,
            text="Restricted Access",
            font=header_sub_font,
            bg="#161b22",
            fg="#8b949e"
        ).pack(pady=(4, 0))

        grid = tk.Frame(overlay, bg="#0d1117", pady=grid_pad_y)
        grid.pack(expand=True, fill=tk.BOTH, padx=grid_pad_x)
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)
        for row_idx in range(9):
            grid.grid_rowconfigure(row_idx, weight=1)

        def _btn(text, cmd, bg, fg="white", row=0, col=0, colspan=1):
            tk.Button(
                grid,
                text=text,
                command=cmd,
                font=btn_font,
                bg=bg,
                fg=fg,
                activebackground=bg,
                padx=btn_internal_pad_x,
                pady=btn_internal_pad_y,
                relief=tk.FLAT,
                bd=0,
                cursor='hand2',
                wraplength=btn_wrap
            ).grid(
                row=row,
                column=col,
                columnspan=colspan,
                padx=12,
                pady=btn_outer_pad_y,
                sticky='nsew'
            )

        _btn("End Election and Export", self._admin_end_election, "#b71c1c", row=0, col=0)
        _btn("System Status", self._admin_system_status, "#1565c0", row=0, col=1)

        _btn("Set Election Window", lambda: self._admin_set_election_window(show_messages=True), "#4a148c", row=1, col=0)
        _btn("Extend Election End Time", self._admin_extend_end_time_prompt, "#4a148c", row=1, col=1)

        _btn("Error State", self._admin_error_state, "#d32f2f", row=2, col=0, colspan=2)

        _btn("Export & Reset Session", self._admin_export_and_reset, "#e65100", row=3, col=0, colspan=2)

        _btn(
            "Close Polling Officer Menu",
            self._close_admin_menu,
            "#21262d",
            fg="#cdd9e5",
            row=4,
            col=0,
            colspan=2
        )

    def _close_admin_menu(self):
        if self._admin_overlay:
            try:
                current_grab = self.root.grab_current()
                if current_grab is self._admin_overlay:
                    self._admin_overlay.grab_release()
                self._admin_overlay.destroy()
            except Exception:
                pass
            self._admin_overlay = None
        self._enforce_kiosk_mode()
        self.show_idle_screen()

    def _admin_export_and_reset(self):
        log_dir = getattr(self, 'log_dir', None)
        if not log_dir or not os.path.isdir(log_dir):
            self._show_custom_messagebox("Error", "Log partition not accessible.", alert_type="error")
            return

        if not self._show_custom_confirm(
            "Export & Reset Session",
            "All session data (votes, logs, database) will be archived to a\ntimestamped folder on the log partition.\n\n"
            "The device will restart with a clean session.\nThe .provisioned flag is kept — no re-provisioning needed.\n\n"
            "Continue?",
            yes_text="Export & Reset",
            no_text="Cancel"
        ):
            return

        self._close_admin_menu()
        self.show_printing_modal(text="Archiving session data…\nPlease wait.")

        def _worker():
            try:
                import shutil
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                archive_dir = os.path.join(log_dir, ts)
                os.makedirs(archive_dir, exist_ok=True)

                moved, errors = [], []
                for entry in os.scandir(log_dir):
                    if entry.name == '.provisioned':
                        continue
                    if os.path.abspath(entry.path) == os.path.abspath(archive_dir):
                        continue
                    try:
                        shutil.move(entry.path, os.path.join(archive_dir, entry.name))
                        moved.append(entry.name)
                    except Exception as mv_err:
                        errors.append(f"{entry.name}: {mv_err}")

                # Checkpoint and close the DB so WAL is fully written before move.
                try:
                    bm = getattr(self, 'ballot_manager', None)
                    if bm and getattr(bm, 'conn', None):
                        bm.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        bm.conn.close()
                        bm.conn = None
                except Exception:
                    pass

                try:
                    os.sync()
                except AttributeError:
                    pass

                print(f"[export_reset] Archived {len(moved)} items to {archive_dir}. Errors: {errors}")
                self.root.after(0, _restart)
            except Exception as e:
                self.root.after(0, lambda err=str(e): _fail(err))

        def _restart():
            self.close_printing_modal()
            import subprocess
            try:
                subprocess.Popen(['sudo', 'reboot'])
            except Exception as e:
                print(f"[export_reset] reboot failed ({e}), falling back to process restart")
                import sys
                os.execv(sys.executable, [sys.executable] + sys.argv)

        def _fail(err):
            self.close_printing_modal()
            self._show_custom_messagebox("Export Error", f"Failed to archive session:\n{err}", alert_type="error")

        threading.Thread(target=_worker, daemon=True).start()

    # ── Vote Recovery (two-phase journal) ────────────────────────────────────

    def _check_pending_journal(self):
        """Called once at startup. Shows recovery screen if any PENDING votes found."""
        if not self._vote_journal:
            return
        try:
            pending = self._vote_journal.get_pending()
        except Exception as e:
            print(f"[journal] Error scanning for pending votes: {e}")
            return
        if not pending:
            return
        print(f"[journal] {len(pending)} PENDING vote(s) found — showing officer recovery screen.")
        self._show_vote_recovery_screen(pending)

    def _show_vote_recovery_screen(self, pending_entries):
        """
        Two-phase recovery screen for unresolved PENDING votes.

        Phase 1 — full-screen alert, waits for officer RFID card.
        Phase 2 — compact action dialog shown only after officer authenticates.
        """
        if not pending_entries:
            self.root.after(0, self.show_idle_screen)
            return

        # Pause regular voter scan loop for the duration of recovery.
        self.stop_scanning = True

        entry     = pending_entries[0]
        remaining = pending_entries[1:]

        # ── Phase 1: full-screen "call officer" screen ────────────────────────
        phase1 = tk.Toplevel(self.root)
        phase1.overrideredirect(True)
        phase1.attributes('-fullscreen', True)
        phase1.attributes('-topmost', True)
        phase1.configure(bg="#1a0000")
        phase1.grab_set()
        phase1.lift()
        phase1.focus_force()

        tk.Label(phase1, text="⚠", font=('Helvetica', 72), bg="#1a0000", fg="#ff4444").pack(pady=(60, 0))
        tk.Label(phase1, text="POWER LOSS DETECTED",
                 font=('Helvetica', 28, 'bold'), bg="#1a0000", fg="white").pack(pady=(0, 8))
        tk.Label(phase1,
                 text="A vote may not have been recorded properly.\nPlease call a Polling Officer for verification.",
                 font=('Helvetica', 16), bg="#1a0000", fg="#ffaaaa",
                 justify=tk.CENTER).pack(pady=(0, 40))

        tk.Frame(phase1, bg="#7f0000", height=2).pack(fill=tk.X, padx=80)

        tk.Label(phase1, text="Polling Officer: scan your RFID card to proceed",
                 font=('Helvetica', 15, 'italic'), bg="#1a0000", fg="#ffdd88").pack(pady=(30, 10))

        status_lbl = tk.Label(phase1, text="Waiting for officer card…",
                              font=('Helvetica', 13), bg="#1a0000", fg="#888888")
        status_lbl.pack()

        scan_active = [True]

        def _stop_scan():
            scan_active[0] = False

        # Background thread polls RFID for officer card
        def _scan_loop():
            while scan_active[0]:
                try:
                    result = self.rfid_service.read_card(mode='encrypted')
                    if result and result[0] != 'error':
                        payload = result[1] if len(result) > 1 else result[0]
                        if self._is_polling_officer_token(payload):
                            phase1.after(0, _officer_verified)
                            return
                        else:
                            phase1.after(0, lambda: status_lbl.config(
                                text="Not an officer card. Try again.", fg="#ff8888"))
                except Exception:
                    pass
                import time as _t
                _t.sleep(0.3)

        def _officer_verified():
            _stop_scan()
            phase1.grab_release()
            phase1.destroy()
            self.root.after(100, lambda: _show_phase2())

        threading.Thread(target=_scan_loop, daemon=True).start()

        # ── Phase 2: compact action dialog ────────────────────────────────────
        def _show_phase2():
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            dw, dh = min(760, sw - 40), min(560, sh - 40)
            dx = (sw - dw) // 2
            dy = (sh - dh) // 2

            dlg = tk.Toplevel(self.root)
            dlg.overrideredirect(True)
            dlg.geometry(f"{dw}x{dh}+{dx}+{dy}")
            dlg.attributes('-topmost', True)
            dlg.configure(bg="#1a0000")
            dlg.grab_set()
            dlg.lift()

            def _done():
                dlg.grab_release()
                dlg.destroy()
                if remaining:
                    self.root.after(200, lambda: self._show_vote_recovery_screen(remaining))
                else:
                    # show_idle_screen restarts the scan thread (or shows inactive screen)
                    self.root.after(0, self.show_idle_screen)

            def _run_with_modal(modal_text, worker_fn, error_title):
                """Show a status modal, run worker_fn in a thread, then call _done()."""
                self.show_printing_modal(text=modal_text)
                dlg.grab_release()  # let the modal take grab

                def _thread():
                    err = None
                    try:
                        worker_fn()
                    except Exception as e:
                        err = str(e)
                    def _finish():
                        self.close_printing_modal()
                        if err:
                            self._show_custom_messagebox(error_title, err, alert_type="error")
                        else:
                            _done()
                    self.root.after(0, _finish)

                threading.Thread(target=_thread, daemon=True).start()

            def _commit():
                def _work():
                    self._recovery_save_vote(entry)
                    self._vote_journal.write_committed(entry['id'])
                    try:
                        os.sync()
                    except AttributeError:
                        pass
                    print(f"[recovery] Committed {entry['id']} without reprint.")
                _run_with_modal("Committing Vote…\nPlease wait.", _work, "Recovery Error")

            def _reprint_commit():
                ps = getattr(self, 'printer_service', None)
                if not ps:
                    self._show_custom_messagebox(
                        "Printer Not Ready",
                        "Import ballot USB first, then retry.",
                        alert_type="error"
                    )
                    return

                def _work():
                    ps.print_recovery_vvpat(
                        entry.get('election_name', 'Election'),
                        entry.get('vvpat_choice_str', 'Unknown'),
                        entry.get('timestamp', ''),
                    )
                    self._recovery_save_vote(entry)
                    self._vote_journal.write_committed(entry['id'])
                    try:
                        os.sync()
                    except AttributeError:
                        pass
                    print(f"[recovery] Reprinted and committed {entry['id']}.")
                _run_with_modal("Reprinting VVPAT…\nPlease wait.", _work, "Reprint Error")

            def _discard():
                if not self._show_custom_confirm(
                    "Discard Vote",
                    "DISCARD this vote?\nIt will NOT be recorded.",
                    yes_text="Discard",
                    no_text="Cancel"
                ):
                    return

                def _work():
                    self._vote_journal.write_discarded(entry['id'])
                    try:
                        os.sync()
                    except AttributeError:
                        pass
                    print(f"[recovery] Discarded {entry['id']}.")
                _run_with_modal("Discarding Vote…\nPlease wait.", _work, "Discard Error")

            # Header
            hdr = tk.Frame(dlg, bg="#7f0000", pady=10)
            hdr.pack(fill=tk.X)
            tk.Label(hdr, text="⚠  Vote Recovery — Officer Verified",
                     font=('Helvetica', 16, 'bold'), bg="#7f0000", fg="white").pack()

            # Info rows
            info = tk.Frame(dlg, bg="#2d0000", pady=6)
            info.pack(fill=tk.X, padx=16, pady=(10, 6))

            def _row(lbl, val):
                r = tk.Frame(info, bg="#2d0000")
                r.pack(fill=tk.X, padx=12, pady=2)
                tk.Label(r, text=lbl, font=('Helvetica', 12, 'bold'),
                         bg="#2d0000", fg="#ff9999", width=12, anchor='w').pack(side=tk.LEFT)
                tk.Label(r, text=val, font=('Helvetica', 12),
                         bg="#2d0000", fg="white", anchor='w', wraplength=500).pack(side=tk.LEFT)

            _row("Voter ID:", entry.get('voter_id', '?'))
            _row("Election:", entry.get('election_id', '?'))
            _row("Selection:", entry.get('vvpat_choice_str', '?'))
            ts = entry.get('timestamp', '')
            try:
                import datetime as _dt
                ts = _dt.datetime.fromisoformat(ts).strftime("%d-%m-%Y %H:%M:%S")
            except Exception:
                pass
            _row("Vote Time:", ts)

            tk.Label(dlg, text="Check the printer slip and choose:",
                     font=('Helvetica', 13), bg="#1a0000", fg="#ffdddd").pack(pady=(8, 4))

            bf = dict(font=('Helvetica', 14, 'bold'), relief=tk.FLAT, bd=0,
                      cursor='hand2', pady=12, padx=12)

            tk.Button(dlg, text="Slip Fully Printed — Commit Vote",
                      bg="#1b5e20", fg="white", command=_commit, **bf).pack(fill=tk.X, padx=16, pady=4)
            tk.Button(dlg, text="No / Partial Slip — Reprint & Commit",
                      bg="#e65100", fg="white", command=_reprint_commit, **bf).pack(fill=tk.X, padx=16, pady=4)
            tk.Button(dlg, text="Discard This Vote",
                      bg="#37474f", fg="#ff8888", command=_discard, **bf).pack(fill=tk.X, padx=16, pady=4)

            if remaining:
                tk.Label(dlg, text=f"{len(remaining)} more pending vote(s) after this.",
                         font=('Helvetica', 11, 'italic'), bg="#1a0000", fg="#ffcc00").pack(pady=(6, 0))

    def _recovery_save_vote(self, entry):
        """Save a recovered vote record directly to the votes log and mark DB."""
        vote_record = entry.get('vote_record')
        voter_id    = entry.get('voter_id', 'UNKNOWN')
        election_id = entry.get('election_id', 'UNKNOWN')

        if vote_record:
            votes_path = getattr(self, 'votes_log', None) or os.path.join(self.log_dir, 'votes.json')
            try:
                with open(votes_path, 'a', encoding='utf-8') as f:
                    records = vote_record if isinstance(vote_record, list) else [vote_record]
                    for rec in records:
                        f.write(json.dumps(rec) + '\n')
                    f.flush()
                    os.fsync(f.fileno())
            except Exception as e:
                print(f"[recovery] Error writing vote record: {e}")

        try:
            self.ballot_manager.mark_voter_election_used(voter_id, election_id)
        except Exception as e:
            print(f"[recovery] Error marking voter+election in DB: {e}")

    # ─────────────────────────────────────────────────────────────────────────

    def _admin_error_state(self):
        self._close_admin_menu()
        self._show_error_state_screen()

    def _show_error_state_screen(self):
        self.clear_container()
        
        bg_color = "#ffebee"
        frame = tk.Frame(self.main_container, bg=bg_color)
        frame.pack(expand=True, fill=tk.BOTH)
        
        tk.Label(frame, text="Sorry this booth is down.", font=('Helvetica', 32, 'bold'), fg="#c62828", bg=bg_color).pack(pady=(80, 20))
        tk.Label(frame, text="Enter Developer Pin for Repair", font=('Helvetica', 20), fg="#333", bg=bg_color).pack(pady=(0, 30))
        
        pin_var = tk.StringVar(value="")
        
        pin_display = tk.Label(frame, text="", font=('Consolas', 36, 'bold'), bg="white", fg="black", width=12, relief="solid", bd=2)
        pin_display.pack(pady=20)
        
        def update_display():
            val = pin_var.get()
            pin_display.config(text="*" * len(val))
            
        def press(num):
            current = pin_var.get()
            if len(current) < 10:
                pin_var.set(current + str(num))
                update_display()
                
        def clear_pin():
            pin_var.set("")
            update_display()
            
        def submit_pin():
            if pin_var.get() == "042026":
                import sys
                sys.exit(42)
            else:
                pin_var.set("")
                update_display()
                
        keypad = tk.Frame(frame, bg=bg_color)
        keypad.pack(pady=20)
        
        btn_font = ('Helvetica', 18, 'bold')
        
        # Row 0
        tk.Button(keypad, text="1", font=btn_font, width=4, height=1, command=lambda: press(1)).grid(row=0, column=0, padx=8, pady=8)
        tk.Button(keypad, text="2", font=btn_font, width=4, height=1, command=lambda: press(2)).grid(row=0, column=1, padx=8, pady=8)
        tk.Button(keypad, text="3", font=btn_font, width=4, height=1, command=lambda: press(3)).grid(row=0, column=2, padx=8, pady=8)
        # Row 1
        tk.Button(keypad, text="4", font=btn_font, width=4, height=1, command=lambda: press(4)).grid(row=1, column=0, padx=8, pady=8)
        tk.Button(keypad, text="5", font=btn_font, width=4, height=1, command=lambda: press(5)).grid(row=1, column=1, padx=8, pady=8)
        tk.Button(keypad, text="6", font=btn_font, width=4, height=1, command=lambda: press(6)).grid(row=1, column=2, padx=8, pady=8)
        # Row 2
        tk.Button(keypad, text="7", font=btn_font, width=4, height=1, command=lambda: press(7)).grid(row=2, column=0, padx=8, pady=8)
        tk.Button(keypad, text="8", font=btn_font, width=4, height=1, command=lambda: press(8)).grid(row=2, column=1, padx=8, pady=8)
        tk.Button(keypad, text="9", font=btn_font, width=4, height=1, command=lambda: press(9)).grid(row=2, column=2, padx=8, pady=8)
        # Row 3
        tk.Button(keypad, text="CLEAR", font=('Helvetica', 14, 'bold'), width=5, height=2, bg="#e57373", fg="white", command=clear_pin).grid(row=3, column=0, padx=8, pady=8)
        tk.Button(keypad, text="0", font=btn_font, width=4, height=1, command=lambda: press(0)).grid(row=3, column=1, padx=8, pady=8)
        tk.Button(keypad, text="OK", font=('Helvetica', 14, 'bold'), width=5, height=2, bg="#81c784", fg="white", command=submit_pin).grid(row=3, column=2, padx=8, pady=8)

        tk.Button(frame, text="Cancel", font=('Helvetica', 14), bg="#b0bec5", command=self.show_idle_screen).pack(pady=20)

    def _admin_end_election(self):
        self._close_admin_menu()
        self.end_election()

    def _admin_reprint_device_slip(self):
        self._close_admin_menu()
        self.show_printing_modal(text="Re-printing device slip...")
        threading.Thread(target=self._admin_reprint_device_slip_worker, daemon=True).start()

    def _admin_reprint_device_slip_worker(self):
        try:
            project_dir = os.path.dirname(os.path.abspath(__file__))

            pub_key_path = os.path.join(project_dir, "public.pem")
            if not os.path.exists(pub_key_path):
                raise FileNotFoundError("public.pem not found. Provisioning may be incomplete.")

            with open(pub_key_path, "r", encoding="utf-8") as f:
                public_key_pem = f.read()

            bmd_id = "UNKNOWN"
            cfg_path = os.path.join(project_dir, "bmd_config.json")
            if os.path.exists(cfg_path):
                try:
                    import json
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    bmd_id = cfg.get("bmd_id", "UNKNOWN")
                except Exception:
                    pass

            machine_id = "UNKNOWN"
            try:
                import hardware_crypto
                machine_id = hardware_crypto.get_machine_id()
            except Exception:
                pass

            if not hasattr(self, 'printer_service') or not self.printer_service:
                from printer_service import PrinterService
                self.printer_service = PrinterService(self.data_handler)

            if not self.printer_service.is_printer_connected():
                raise Exception("Printer not connected")

            self.printer_service.print_provisioning_ticket(bmd_id, public_key_pem, machine_id)
            self.root.after(0, self._admin_reprint_device_slip_done)
        except Exception as e:
            self.root.after(0, lambda err=str(e): self._admin_reprint_device_slip_failed(err))

    def _admin_reprint_device_slip_done(self):
        self.close_printing_modal()
        self._show_custom_messagebox("Reprint Complete", "Device slip was printed successfully.")

    def _admin_reprint_device_slip_failed(self, error_message):
        self.close_printing_modal()
        self._show_custom_messagebox("Reprint Failed", f"Could not print device slip:\n{error_message}", alert_type='error')

    def _admin_update_firmware(self):
        # Close admin overlay first so confirmation dialog is never hidden behind it.
        self._close_admin_menu()

        if not self._show_custom_confirm(
            "Update Firmware",
            "This will run 'git pull --ff-only' in the app directory.\n\nContinue?"
        ):
            self.root.after(80, self.show_admin_menu)
            return

        self.show_printing_modal(text="Updating firmware...\nRunning git pull")
        threading.Thread(target=self._admin_update_firmware_worker, daemon=True).start()

    def _admin_update_firmware_worker(self):
        try:
            project_dir = os.path.dirname(os.path.abspath(__file__))
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=120,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )

            output = (result.stdout or "").strip()
            error_output = (result.stderr or "").strip()
            combined = "\n".join([x for x in [output, error_output] if x]).strip()

            if result.returncode != 0:
                raise Exception(combined or "git pull failed")

            self.root.after(0, lambda out=combined: self._admin_update_firmware_done(out))
        except subprocess.TimeoutExpired:
            self.root.after(0, lambda: self._admin_update_firmware_failed("git pull timed out after 120s"))
        except Exception as e:
            self.root.after(0, lambda err=str(e): self._admin_update_firmware_failed(err))

    def _admin_update_firmware_done(self, output_text):
        detail = output_text if output_text else "Already up to date."
        self._show_custom_messagebox(
            "Firmware Update Complete",
            f"{detail}\n\nRestarting application to apply updates."
        )

        import sys
        self.root.destroy()
        os.execv(sys.executable, [sys.executable] + sys.argv)

        self.close_printing_modal()
        self._show_custom_messagebox("Firmware Update Failed", error_message, alert_type='error')

    def _admin_toggle_print(self):
        self._close_admin_menu()
        self.toggle_printing()
        self.root.after(80, self.show_admin_menu)

    def _admin_reset_token_log(self):
        self.reset_token_log()

    def _admin_dev_skip(self):
        self._close_admin_menu()
        self.skip_rfid_check()

    def _admin_dev_restart_usb(self):
        self._close_admin_menu()
        self.show_usb_waiting_screen()

    def _admin_exit_app(self):
        self._close_admin_menu()
        self.exit_app()

    def _admin_system_status(self):
        """Show system status inside the polling officer menu."""
        try:
            import hardware_crypto
            machine_id = hardware_crypto.get_machine_id()
            if machine_id.startswith("OTP_"):
                hw_status = "OTP Silicon (clone-resistant)"
            elif machine_id.startswith("CPUSERIAL_"):
                hw_status = "CPU Serial (clone-resistant)"
            elif machine_id.startswith("DMI_"):
                hw_status = "DMI UUID (clone-resistant)"
            else:
                hw_status = "Fallback identity (not clone-resistant)"
        except Exception as e:
            hw_status = f"Error: {e}"

        try:
            import json
            cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bmd_config.json")
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            bmd_id = cfg.get("bmd_id", "UNKNOWN")
            provisioned_at = str(cfg.get("provisioned_at", ""))[:10]
        except Exception:
            bmd_id = "UNKNOWN"
            provisioned_at = ""

        if hasattr(self, 'printer_service') and self.printer_service and self.printer_service.is_printer_connected():
            printer_status = "Connected"
        else:
            printer_status = "Not connected"

        msg = (
            f"BMD ID        : {bmd_id}"
            + (f"  (provisioned {provisioned_at})" if provisioned_at else "") + "\n"
            + f"HW Binding    : {hw_status}\n"
            + f"Printer       : {printer_status}\n"
            + f"Print Mode    : {'ON' if self.print_enabled else 'OFF'}\n"
            + f"Election Time : {self._current_schedule_text()}\n"
            + f"Log Dir       : {getattr(self, 'log_dir', 'N/A')}\n"
        )
        self._show_custom_messagebox("System Status", msg)

    def _show_custom_messagebox(self, title, message, alert_type='info'):
        parent = getattr(self, '_admin_overlay', None) or self.root
        dlg = tk.Toplevel(parent)
        dlg.title(title)
        dlg.transient(parent)
        dlg.attributes('-topmost', True)
        dlg.overrideredirect(True)
        
        w, h = 600, 380
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")
        dlg.configure(bg="#0d1117")
        
        frame = tk.Frame(dlg, bg="#0d1117", bd=2, relief=tk.RAISED, highlightbackground="#30363d", highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(frame, text=title, font=('Helvetica', 18, 'bold'), bg="#0d1117", fg="#f0f6fc").pack(pady=(30, 10))
        tk.Label(frame, text=message, font=('Helvetica', 14), bg="#0d1117", fg="#c9d1d9", wraplength=540, justify=tk.CENTER).pack(pady=20, padx=20, expand=True)
        
        btn_bg = "#238636" if alert_type == 'info' else "#da3633"
        tk.Button(frame, text="OK", font=('Helvetica', 14, 'bold'), bg=btn_bg, fg="white", 
                  activebackground=btn_bg, bd=0, padx=40, pady=10, cursor="hand2", command=dlg.destroy).pack(pady=(0, 30))
        
        dlg.grab_set()
        self.root.wait_window(dlg)

    def _show_custom_confirm(self, title, message, yes_text="Confirm", no_text="Cancel"):
        parent = getattr(self, '_admin_overlay', None) or self.root
        dlg = tk.Toplevel(parent)
        dlg.title(title)
        dlg.transient(parent)
        dlg.attributes('-topmost', True)
        dlg.overrideredirect(True)
        
        w, h = 650, 420
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")
        dlg.configure(bg="#0d1117")
        
        result = {"value": False}
        def choose(val):
            result["value"] = val
            dlg.destroy()
            
        frame = tk.Frame(dlg, bg="#0d1117", bd=2, relief=tk.RAISED, highlightbackground="#30363d", highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(frame, text=title, font=('Helvetica', 20, 'bold'), bg="#0d1117", fg="#f0f6fc").pack(pady=(30, 10))
        tk.Label(frame, text=message, font=('Helvetica', 14), bg="#0d1117", fg="#c9d1d9", wraplength=600, justify=tk.CENTER).pack(pady=20, padx=20, expand=True)
        
        btn_row = tk.Frame(frame, bg="#0d1117")
        btn_row.pack(pady=(0, 35))
        
        tk.Button(btn_row, text=yes_text, font=('Helvetica', 14, 'bold'), bg="#238636", fg="white", 
                  activebackground="#2ea043", bd=0, padx=30, pady=10, cursor="hand2", command=lambda: choose(True)).pack(side=tk.LEFT, padx=15)
        
        tk.Button(btn_row, text=no_text, font=('Helvetica', 14, 'bold'), bg="#30363d", fg="#f0f6fc", 
                  activebackground="#3c444d", bd=0, padx=30, pady=10, cursor="hand2", command=lambda: choose(False)).pack(side=tk.LEFT, padx=15)
        
        dlg.grab_set()
        self.root.wait_window(dlg)
        return result["value"]

    def _show_numeric_keypad_dialog(self, title, prompt, initial_value=""):
        parent = self._admin_overlay if self._admin_overlay and self._admin_overlay.winfo_exists() else self.root

        dlg = tk.Toplevel(parent)
        dlg.title(title)
        dlg.transient(parent)
        dlg.attributes('-topmost', True)
        dlg.overrideredirect(True)

        w, h = 760, 620
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")
        dlg.configure(bg="#0d1117")
        dlg.lift()
        dlg.focus_force()

        tk.Label(
            dlg,
            text=title,
            font=('Helvetica', 24, 'bold'),
            bg="#0d1117",
            fg="#f0f6fc",
        ).pack(pady=(18, 6))

        tk.Label(
            dlg,
            text=prompt,
            font=('Helvetica', 14),
            bg="#0d1117",
            fg="#9da7b3",
        ).pack(pady=(0, 10))

        value_var = tk.StringVar(value=str(initial_value or ""))
        entry = tk.Entry(
            dlg,
            textvariable=value_var,
            font=('Helvetica', 26, 'bold'),
            justify='center',
            bd=0,
            relief=tk.FLAT,
            bg="#161b22",
            fg="#f0f6fc",
            insertbackground="#f0f6fc",
        )
        entry.pack(fill=tk.X, padx=30, pady=(0, 12), ipady=12)

        pad = tk.Frame(dlg, bg="#0d1117")
        pad.pack(expand=True, fill=tk.BOTH, padx=30, pady=8)

        result = {"value": None}

        def add_digit(d):
            value_var.set(value_var.get() + d)

        def backspace():
            value_var.set(value_var.get()[:-1])

        def clear_all():
            value_var.set("")

        def cancel():
            result["value"] = None
            dlg.destroy()

        def save():
            result["value"] = value_var.get().strip()
            dlg.destroy()

        buttons = [
            ("1", lambda: add_digit("1")), ("2", lambda: add_digit("2")), ("3", lambda: add_digit("3")),
            ("4", lambda: add_digit("4")), ("5", lambda: add_digit("5")), ("6", lambda: add_digit("6")),
            ("7", lambda: add_digit("7")), ("8", lambda: add_digit("8")), ("9", lambda: add_digit("9")),
            ("Clear", clear_all), ("0", lambda: add_digit("0")), ("Back", backspace),
        ]

        for idx, (label, cmd) in enumerate(buttons):
            r, c = divmod(idx, 3)
            tk.Button(
                pad,
                text=label,
                command=cmd,
                font=('Helvetica', 20, 'bold'),
                bg="#1f6feb" if label.isdigit() else "#30363d",
                fg="#f0f6fc",
                activebackground="#1f6feb" if label.isdigit() else "#484f58",
                relief=tk.FLAT,
                bd=0,
            ).grid(row=r, column=c, sticky='nsew', padx=8, pady=8)

        for i in range(4):
            pad.grid_rowconfigure(i, weight=1)
        for i in range(3):
            pad.grid_columnconfigure(i, weight=1)

        action_row = tk.Frame(dlg, bg="#0d1117")
        action_row.pack(fill=tk.X, padx=30, pady=(8, 18))

        tk.Button(
            action_row,
            text="Cancel",
            command=cancel,
            font=('Helvetica', 16, 'bold'),
            bg="#30363d",
            fg="#f0f6fc",
            relief=tk.FLAT,
            bd=0,
            padx=20,
            pady=10,
        ).pack(side=tk.LEFT)

        tk.Button(
            action_row,
            text="Save",
            command=save,
            font=('Helvetica', 16, 'bold'),
            bg="#238636",
            fg="#f0f6fc",
            relief=tk.FLAT,
            bd=0,
            padx=24,
            pady=10,
        ).pack(side=tk.RIGHT)

        dlg.protocol("WM_DELETE_WINDOW", cancel)
        entry.focus_set()
        dlg.grab_set()
        dlg.wait_window()
        return result["value"]

    def _show_datetime_picker_dialog(self, title, initial_dt=None):
        parent = self._admin_overlay if self._admin_overlay and self._admin_overlay.winfo_exists() else self.root
        if initial_dt is None:
            initial_dt = datetime.datetime.now().replace(second=0, microsecond=0)

        dlg = tk.Toplevel(parent)
        dlg.title(title)
        dlg.transient(parent)
        dlg.attributes('-topmost', True)
        dlg.overrideredirect(True)

        w, h = 600, 600
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")
        dlg.configure(bg="#6FAFA8")
        dlg.minsize(580, 600)
        dlg.lift()
        dlg.focus_force()

        tk.Label(
            dlg,
            text=title,
            font=('Helvetica', 22, 'bold'),
            bg="#6FAFA8",
            fg="#1d2a2a",
        ).pack(pady=(18, 8))

        card = tk.Frame(dlg, bg="#6FAFA8")
        card.pack(expand=True, fill=tk.BOTH, padx=36, pady=10)

        selected_date = datetime.date(initial_dt.year, initial_dt.month, initial_dt.day)
        selected_time = datetime.time(initial_dt.hour, initial_dt.minute)

        date_var = tk.StringVar(value=selected_date.strftime("%d %b %Y"))
        preview_var = tk.StringVar(value="")

        time_var = tk.StringVar(value="")

        cal_popup = {"win": None}
        cal_year = tk.IntVar(value=selected_date.year)
        cal_month = tk.IntVar(value=selected_date.month)

        def refresh_preview(*_):
            preview_var.set(f"{date_var.get()}  {time_var.get()}")

        tk.Label(
            card,
            text="Select Date",
            font=('Helvetica', 14, 'bold'),
            bg="#6FAFA8",
            fg="#1d2a2a",
            anchor='w',
        ).pack(fill=tk.X, pady=(8, 4))

        date_btn = tk.Button(
            card,
            textvariable=date_var,
            command=lambda: open_calendar_popup(),
            font=('Helvetica', 18, 'bold'),
            bg="#f7f7f7",
            fg="#1f2933",
            relief=tk.FLAT,
            bd=0,
            padx=12,
            pady=8,
            anchor='w',
        )
        date_btn.pack(fill=tk.X, pady=(0, 16))

        tk.Label(
            card,
            text="Select Time",
            font=('Helvetica', 12, 'bold'),
            bg="#6FAFA8",
            fg="#1d2a2a",
            anchor='w',
        ).pack(fill=tk.X, pady=(0, 4))

        # --- Hour/Minute spinner (replaces scrolling Combobox) ---
        # Snap initial time to nearest 30-min slot
        snap_minute = 0 if selected_time.minute < 30 else 30
        time_hour = tk.IntVar(value=selected_time.hour)
        time_minute = tk.IntVar(value=snap_minute)

        def _fmt_time():
            return datetime.time(time_hour.get(), time_minute.get()).strftime("%I:%M %p")

        def _update_time_var(*_):
            time_var.set(_fmt_time())
            refresh_preview()

        spinner_frame = tk.Frame(card, bg="#6FAFA8")
        spinner_frame.pack(fill=tk.X, pady=(0, 14))

        def _make_spinner(parent, label, var, lo, hi, step, fmt=lambda v: str(v).zfill(2)):
            col = tk.Frame(parent, bg="#6FAFA8")
            col.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=4)

            tk.Label(col, text=label, font=('Helvetica', 11, 'bold'),
                     bg="#6FAFA8", fg="#1d2a2a").pack()

            def inc():
                v = var.get() + step
                if v > hi: v = lo
                var.set(v)
                _update_time_var()

            def dec():
                v = var.get() - step
                if v < lo: v = hi
                var.set(v)
                _update_time_var()

            tk.Button(col, text="▲", command=inc,
                      font=('Helvetica', 14, 'bold'), bg="#2f6f69", fg="white",
                      relief=tk.FLAT, bd=0, padx=10, pady=4).pack(fill=tk.X, pady=(0, 2))
            tk.Label(col, textvariable=var, font=('Helvetica', 22, 'bold'),
                     bg="#f7f7f7", fg="#1f2933", pady=6,
                     width=3, anchor='center').pack(fill=tk.X)
            tk.Button(col, text="▼", command=dec,
                      font=('Helvetica', 14, 'bold'), bg="#2f6f69", fg="white",
                      relief=tk.FLAT, bd=0, padx=10, pady=4).pack(fill=tk.X, pady=(2, 0))

        _make_spinner(spinner_frame, "Hour", time_hour, 0, 23, 1)
        tk.Label(spinner_frame, text=":", font=('Helvetica', 28, 'bold'),
                 bg="#6FAFA8", fg="#1d2a2a").pack(side=tk.LEFT, pady=10)
        _make_spinner(spinner_frame, "Min", time_minute, 0, 30, 30)

        # Initialise time_var to match spinner position
        time_var.set(_fmt_time())
        # --------------------------------------------------------


        tk.Label(
            card,
            text="Selected DateTime",
            font=('Helvetica', 12),
            bg="#6FAFA8",
            fg="#2b3a3a",
            anchor='w',
        ).pack(fill=tk.X, pady=(0, 2))

        tk.Label(
            card,
            textvariable=preview_var,
            font=('Consolas', 16, 'bold'),
            bg="#e8eef0",
            fg="#1f2933",
            padx=16,
            pady=12,
        ).pack(fill=tk.X, ipady=12, pady=(0, 20))

        def render_calendar(container):
            for wdg in container.winfo_children():
                wdg.destroy()

            title_row = tk.Frame(container, bg="#ffffff")
            title_row.pack(fill=tk.X, pady=(6, 4))

            def prev_month():
                y, m = cal_year.get(), cal_month.get() - 1
                if m < 1:
                    y -= 1
                    m = 12
                cal_year.set(y)
                cal_month.set(m)
                render_calendar(container)

            def next_month():
                y, m = cal_year.get(), cal_month.get() + 1
                if m > 12:
                    y += 1
                    m = 1
                cal_year.set(y)
                cal_month.set(m)
                render_calendar(container)

            tk.Button(title_row, text="<", command=prev_month, font=('Helvetica', 14, 'bold'), bg="#f1f5f9", relief=tk.FLAT).pack(side=tk.LEFT, padx=8)
            tk.Label(
                title_row,
                text=f"{calendar.month_name[cal_month.get()]} {cal_year.get()}",
                font=('Helvetica', 14, 'bold'),
                bg="#ffffff",
                fg="#111827",
            ).pack(side=tk.LEFT, expand=True)
            tk.Button(title_row, text=">", command=next_month, font=('Helvetica', 14, 'bold'), bg="#f1f5f9", relief=tk.FLAT).pack(side=tk.RIGHT, padx=8)

            grid = tk.Frame(container, bg="#ffffff")
            grid.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

            for i, wd in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
                tk.Label(grid, text=wd, font=('Helvetica', 11, 'bold'), bg="#ffffff", fg="#4b5563").grid(row=0, column=i, sticky='nsew', pady=(0, 4))

            month_rows = calendar.monthcalendar(cal_year.get(), cal_month.get())

            def choose_day(day):
                nonlocal selected_date
                selected_date = datetime.date(cal_year.get(), cal_month.get(), day)
                date_var.set(selected_date.strftime("%d %b %Y"))
                refresh_preview()
                if cal_popup["win"]:
                    cal_popup["win"].destroy()
                    cal_popup["win"] = None

            for r, week in enumerate(month_rows, start=1):
                for c, day in enumerate(week):
                    if day == 0:
                        tk.Label(grid, text="", bg="#ffffff").grid(row=r, column=c, sticky='nsew')
                    else:
                        is_selected = (
                            selected_date.year == cal_year.get()
                            and selected_date.month == cal_month.get()
                            and selected_date.day == day
                        )
                        tk.Button(
                            grid,
                            text=str(day),
                            command=lambda d=day: choose_day(d),
                            font=('Helvetica', 11, 'bold') if is_selected else ('Helvetica', 11),
                            bg="#2563eb" if is_selected else "#f8fafc",
                            fg="white" if is_selected else "#111827",
                            relief=tk.FLAT,
                            bd=0,
                        ).grid(row=r, column=c, sticky='nsew', padx=2, pady=2)

            for i in range(7):
                grid.grid_columnconfigure(i, weight=1)
            for i in range(1, len(month_rows) + 1):
                grid.grid_rowconfigure(i, weight=1)

        def open_calendar_popup():
            if cal_popup["win"] and cal_popup["win"].winfo_exists():
                cal_popup["win"].lift()
                return

            pop = tk.Toplevel(dlg)
            pop.title("Select Date")
            pop.transient(dlg)
            pop.attributes('-topmost', True)
            pop.overrideredirect(True)
            pop.configure(bg="#ffffff")
            pop.geometry("430x380")
            cal_popup["win"] = pop
            pop.lift()
            pop.focus_force()

            wrap = tk.Frame(pop, bg="#ffffff")
            wrap.pack(expand=True, fill=tk.BOTH, padx=8, pady=8)
            render_calendar(wrap)

            def close_popup():
                if cal_popup["win"]:
                    cal_popup["win"].destroy()
                    cal_popup["win"] = None

            pop.protocol("WM_DELETE_WINDOW", close_popup)

        result = {"value": None}

        action = tk.Frame(dlg, bg="#6FAFA8")
        action.pack(fill=tk.X, padx=36, pady=(0, 18))

        def use_now():
            now = datetime.datetime.now()
            nonlocal selected_date
            selected_date = now.date()
            date_var.set(selected_date.strftime("%d %b %Y"))
            
            # Update spinner vars
            snap_min = 30 if now.minute >= 30 else 0
            time_hour.set(now.hour)
            time_minute.set(snap_min)
            
            _update_time_var()

        def cancel():
            result["value"] = None
            dlg.destroy()

        def save():
            try:
                dt = datetime.datetime(
                    selected_date.year,
                    selected_date.month,
                    selected_date.day,
                    time_hour.get(),
                    time_minute.get(),
                    0,
                )
            except Exception as exc:
                self._show_custom_messagebox("Invalid DateTime", str(exc), alert_type='error')
                return
            result["value"] = dt
            dlg.destroy()

        tk.Button(
            action,
            text="Now",
            command=use_now,
            font=('Helvetica', 14, 'bold'),
            bg="#2f6f69",
            fg="#ffffff",
            relief=tk.FLAT,
            bd=0,
            padx=16,
            pady=10,
        ).pack(side=tk.LEFT)

        tk.Button(
            action,
            text="Cancel",
            command=cancel,
            font=('Helvetica', 14, 'bold'),
            bg="#4b5563",
            fg="#ffffff",
            relief=tk.FLAT,
            bd=0,
            padx=16,
            pady=10,
        ).pack(side=tk.RIGHT, padx=(10, 0))

        tk.Button(
            action,
            text="Confirm & Next" if "Start" in title else "Save",
            command=save,
            font=('Helvetica', 14, 'bold'),
            bg="#f97316",
            fg="#ffffff",
            relief=tk.FLAT,
            bd=0,
            padx=20,
            pady=10,
        ).pack(side=tk.RIGHT)

        refresh_preview()

        dlg.protocol("WM_DELETE_WINDOW", cancel)
        dlg.grab_set()
        dlg.wait_window()
        return result["value"]

    def _show_minutes_spinner_dialog(self, title, prompt, initial_value=30, min_val=5, max_val=480, step=5):
        parent = self._admin_overlay if self._admin_overlay and self._admin_overlay.winfo_exists() else self.root

        dlg = tk.Toplevel(parent)
        dlg.title(title)
        dlg.transient(parent)
        dlg.attributes('-topmost', True)
        dlg.overrideredirect(True)

        w, h = 500, 480
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")
        dlg.configure(bg="#6FAFA8")
        dlg.lift()
        dlg.focus_force()

        tk.Label(
            dlg,
            text=title,
            font=('Helvetica', 22, 'bold'),
            bg="#6FAFA8",
            fg="#1d2a2a",
        ).pack(pady=(24, 8))

        tk.Label(
            dlg,
            text=prompt,
            font=('Helvetica', 14),
            bg="#6FAFA8",
            fg="#1d2a2a",
            wraplength=400,
            justify='center'
        ).pack(pady=(0, 20))

        card = tk.Frame(dlg, bg="#6FAFA8")
        card.pack(expand=True, fill=tk.BOTH, padx=40)

        value_var = tk.IntVar(value=initial_value)

        def inc():
            v = value_var.get() + step
            if v > max_val: v = min_val
            value_var.set(v)

        def dec():
            v = value_var.get() - step
            if v < min_val: v = max_val
            value_var.set(v)

        spinner_frame = tk.Frame(card, bg="#6FAFA8")
        spinner_frame.pack(pady=10)

        tk.Button(
            spinner_frame,
            text="▲",
            command=inc,
            font=('Helvetica', 20, 'bold'),
            bg="#2f6f69",
            fg="white",
            relief=tk.FLAT,
            bd=0,
            padx=20,
            pady=10
        ).pack(fill=tk.X, pady=(0, 5))

        tk.Label(
            spinner_frame,
            textvariable=value_var,
            font=('Helvetica', 42, 'bold'),
            bg="#f7f7f7",
            fg="#1f2933",
            pady=15,
            width=4,
            anchor='center'
        ).pack(fill=tk.X)

        tk.Label(
            spinner_frame,
            text="minutes",
            font=('Helvetica', 12, 'bold'),
            bg="#f7f7f7",
            fg="#555",
        ).place(relx=0.5, rely=0.85, anchor='center')

        tk.Button(
            spinner_frame,
            text="▼",
            command=dec,
            font=('Helvetica', 20, 'bold'),
            bg="#2f6f69",
            fg="white",
            relief=tk.FLAT,
            bd=0,
            padx=20,
            pady=10
        ).pack(fill=tk.X, pady=(5, 0))

        result = {"value": None}

        def cancel():
            result["value"] = None
            dlg.destroy()

        def save():
            result["value"] = value_var.get()
            dlg.destroy()

        action_row = tk.Frame(dlg, bg="#6FAFA8")
        action_row.pack(fill=tk.X, padx=40, pady=(20, 30))

        tk.Button(
            action_row,
            text="Cancel",
            command=cancel,
            font=('Helvetica', 16, 'bold'),
            bg="#4a6e6a",
            fg="white",
            relief=tk.FLAT,
            bd=0,
            padx=25,
            pady=10,
            cursor="hand2"
        ).pack(side=tk.LEFT)

        tk.Button(
            action_row,
            text="Save",
            command=save,
            font=('Helvetica', 16, 'bold'),
            bg="#1d2a2a",
            fg="white",
            relief=tk.FLAT,
            bd=0,
            padx=35,
            pady=10,
            cursor="hand2"
        ).pack(side=tk.RIGHT)

        dlg.protocol("WM_DELETE_WINDOW", cancel)
        dlg.grab_set()
        dlg.wait_window()
        return result["value"]

    def _admin_set_election_window(self, start_text=None, end_text=None, show_messages=True):
        had_admin_overlay = bool(self._admin_overlay and self._admin_overlay.winfo_exists())

        if start_text is None:
            start_dt = self._show_datetime_picker_dialog("Set Election Start Time")
            if start_dt is None:
                return False
            start_text = start_dt.strftime("%Y-%m-%d %H:%M:%S")

        if end_text is None:
            suggested_end = None
            try:
                parsed_start = self._parse_schedule_datetime(start_text)
                suggested_end = parsed_start + datetime.timedelta(hours=2)
            except Exception:
                suggested_end = datetime.datetime.now() + datetime.timedelta(hours=2)

            end_dt = self._show_datetime_picker_dialog("Set Election End Time", initial_dt=suggested_end)
            if end_dt is None:
                return False
            end_text = end_dt.strftime("%Y-%m-%d %H:%M:%S")

        try:
            start_dt = self._parse_schedule_datetime(start_text)
            end_dt = self._parse_schedule_datetime(end_text)
            if end_dt <= start_dt:
                raise ValueError("End time must be after start time.")
        except Exception as exc:
            self._show_custom_messagebox("Invalid Time Window", str(exc), alert_type='error')
            return False

        schedule = self._load_election_schedule()
        schedule["enabled"] = True
        schedule["start"] = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        schedule["end"] = end_dt.strftime("%Y-%m-%d %H:%M:%S")
        schedule["start_ticket_printed_for"] = ""
        schedule["end_election_completed"] = False
        if not self._save_election_schedule():
            return False

        if show_messages:
            self._show_custom_messagebox("Election Window Set", self._current_schedule_text())

        self._close_admin_menu()
        self.show_idle_screen()
        return True

    def _admin_extend_end_time(self, minutes, show_messages=True):
        try:
            minutes = int(minutes)
        except Exception:
            self._show_custom_messagebox("Invalid Minutes", "Minutes must be an integer.", alert_type='error')
            return False

        if minutes <= 0:
            self._show_custom_messagebox("Invalid Minutes", "Minutes must be greater than zero.", alert_type='error')
            return False

        schedule = self._load_election_schedule()
        if not schedule.get("enabled", False):
            self._show_custom_messagebox("Schedule Not Set", "Set election window first, then extend end time.", alert_type='error')
            return False

        try:
            _, end_dt = self._get_schedule_window()
            if not end_dt:
                raise ValueError("Current end time is missing.")
            end_dt = end_dt + datetime.timedelta(minutes=minutes)
        except Exception as exc:
            self._show_custom_messagebox("Extend Failed", str(exc), alert_type='error')
            return False

        schedule["end"] = end_dt.strftime("%Y-%m-%d %H:%M:%S")
        schedule["end_election_completed"] = False
        if not self._save_election_schedule():
            return False

        if show_messages:
            self._show_custom_messagebox("Election End Extended", self._current_schedule_text())

        self._close_admin_menu()
        self.show_idle_screen()
        return True

    def _admin_extend_end_time_prompt(self):
        minutes = self._show_minutes_spinner_dialog(
            "Extend Election End",
            "Select minutes to extend the election end time",
            initial_value=30,
            step=15
        )
        if minutes is None:
            return
        
        self._admin_extend_end_time(minutes, show_messages=True)

    def _admin_reset_device(self):
        """Wipe provisioning artifacts and relaunch into first-boot provisioning."""
        if not self._show_custom_confirm(
            "Reset Device",
            "WARNING: This will permanently delete:\n\n"
            "  - private.pem (signing key)\n"
            "  - public.pem (public key)\n"
            "  - bmd_config.json\n"
            "  - .provisioned flag\n\n"
            "The device will restart into the first provisioning menu.\n"
            "A new BMD ID and key pair must be assigned.\n\n"
            "Continue?"
        ):
            return

        if not self._show_custom_confirm(
            "Final Confirmation",
            "This action cannot be undone.\n\n"
            "All existing keys will be destroyed.\n"
            "Any ballots encrypted with the current public key\n"
            "will no longer be decryptable on this device.\n\n"
            "Are you absolutely sure?"
        ):
            return

        project_dir = os.path.dirname(os.path.abspath(__file__))
        to_delete = [
            os.path.join(project_dir, "private.pem"),
            os.path.join(project_dir, "public.pem"),
            os.path.join(project_dir, "bmd_config.json"),
        ]

        log_dir = getattr(self, 'log_dir', None)
        if log_dir:
            # Delete from both canonical path and the legacy LOGS/LOGS nested path.
            to_delete.append(os.path.join(log_dir, ".provisioned"))
            to_delete.append(os.path.join(log_dir, "LOGS", ".provisioned"))

        failed = []
        for path in to_delete:
            if not os.path.exists(path):
                continue
            deleted = False
            try:
                os.remove(path)
                deleted = True
                print(f"[reprovision] Deleted: {path}")
            except Exception as e:
                print(f"[reprovision] os.remove failed ({e}), trying sudo: {path}")

            if not deleted and os.name != 'nt':
                import subprocess
                try:
                    subprocess.run(
                        ['sudo', 'rm', '-f', path],
                        check=True, timeout=5, capture_output=True
                    )
                    deleted = True
                    print(f"[reprovision] Deleted via sudo: {path}")
                except Exception as e2:
                    print(f"[reprovision] sudo rm also failed: {e2}")

            if not deleted:
                failed.append(path)

        # The .provisioned flag MUST be gone — otherwise execv will reload the
        # voting app instead of the provisioning wizard.
        provisioned_flag = os.path.join(log_dir, ".provisioned") if log_dir else None
        if provisioned_flag and os.path.exists(provisioned_flag):
            self._show_custom_messagebox(
                "Reprovision Failed",
                "Could not delete the .provisioned flag.\n\n"
                f"Path: {provisioned_flag}\n\n"
                "Try running the app as root, or delete it manually.",
                alert_type="error"
            )
            return

        if failed:
            print(f"[reprovision] Warning — could not delete: {failed}")

        self._close_admin_menu()
        import sys
        # os.execv replaces this process entirely; no need to destroy root first.
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def show_printing_modal(self, text="Printing VVPAT..."):
        self.printing_overlay = tk.Toplevel(self.root)
        self.printing_overlay.title("Processing")
        w, h = 560, 260
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.printing_overlay.geometry(f"{w}x{h}+{x}+{y}")
        self.printing_overlay.transient(self.root)
        self.printing_overlay.attributes('-topmost', True)
        self.printing_overlay.lift()
        self.printing_overlay.overrideredirect(True)
        self.printing_overlay.grab_set()  # block all input to underlying windows
        f = tk.Frame(self.printing_overlay, bg="#E3F2FD", bd=2, relief=tk.RAISED)
        f.pack(fill=tk.BOTH, expand=True)
        tk.Label(f, text=text, font=('Helvetica', 22, 'bold'), bg="#E3F2FD", wraplength=500, justify=tk.CENTER).pack(pady=36)
        tk.Label(f, text="Please Wait", font=('Helvetica', 18), bg="#E3F2FD").pack(pady=10)

    def close_printing_modal(self):
        if hasattr(self, 'printing_overlay') and self.printing_overlay:
            try:
                current_grab = self.root.grab_current()
                if current_grab is self.printing_overlay:
                    self.printing_overlay.grab_release()
            except Exception:
                pass
            self.printing_overlay.destroy()
            self.printing_overlay = None

    def check_print_status(self):
        try:
            result = self.print_queue.get_nowait()
            
            if isinstance(result, dict) and result.get('stage') == 'vvpat_complete':
                self.close_printing_modal()
                self._show_vvpat_confirmation_modal(
                    "",
                    self._start_receipt_stage_for_vote,
                )
                return
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

                    vid = getattr(self, 'current_voter_id', 'UNKNOWN')
                    tid = getattr(self, 'current_token_id', 'UNKNOWN')
                    primary_identity = vid if vid and vid != 'UNKNOWN_VOTER' else tid
                    self.ballot_manager.mark_voter_election_used(primary_identity, self.current_election_id)

                    self.data_handler.store_used_ballot_snapshot(
                        election_id=self.current_election_id,
                        ballot_file_id=self.data_handler.ballot_file_id,
                        status="USED"
                    )

                    # Phase 2: COMMITTED
                    if self._vote_journal:
                        self._vote_journal.write_committed(self._pending_journal_id)
                    self._pending_journal_id = None

                    self.pending_print_job = None
                    self._cancel_pending_print_polling()
                    self._cast_vote_in_progress = False
                    self.start_next_election()
                    
                except Exception as e:
                    self._cast_vote_in_progress = False
                    self._show_custom_messagebox("System Error", f"Vote recorded but processing failed: {e}", alert_type="error")
            else:
                self._cast_vote_in_progress = False
                print(f"Async print error: {result}")
                if self._show_custom_confirm("Printer Error", f"Printing Failed: {result}\n\nRetry?", yes_text="Retry", no_text="Cancel"):
                    self.cast_vote()
            return
        except queue.Empty:
            pass

        elapsed = (datetime.datetime.now() - self.print_start_time).total_seconds()
        if elapsed > 20:
            self._cast_vote_in_progress = False
            self.close_printing_modal()
            if self._show_custom_confirm("Printer Timeout", "Printer is taking too long.\n\nRetry?", yes_text="Retry", no_text="Cancel"):
                self.cast_vote()
            return

        self.print_status_after_id = self.root.after(500, self.check_print_status)

    def exit_app(self, event=None):
        self.root.quit()
