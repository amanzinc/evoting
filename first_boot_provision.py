"""
first_boot_provision.py
-----------------------
First-boot provisioning wizard for the Ballot Marking Device.

Launched automatically by main.py when the .provisioned flag is absent from
the LOGS partition.  Walks an operator through:
  1. Prerequisite checks (OTP binding, printer, LOGS partition)
  2. BMD ID entry via touchscreen numpad
  3. Confirmation screen
  4. Key generation + printing + flag write
  5. Done / auto-restart into the voting app

After successful provisioning the process restarts via os.execv so that
main.py re-runs and picks up the newly written .provisioned flag cleanly.
"""

import tkinter as tk
from tkinter import messagebox
import os
import sys
import json
import datetime
import threading

# ── Colour palette (dark, matches admin menu) ─────────────────────────────────
P = {
    "bg":      "#0d1117",
    "panel":   "#161b22",
    "accent":  "#238636",
    "danger":  "#da3633",
    "text":    "#f0f6fc",
    "muted":   "#8b949e",
    "btn":     "#21262d",
    "numpad":  "#30363d",
    "warn_bg": "#2d1b00",
    "warn_fg": "#ffa657",
    "err_bg":  "#2d1a1a",
    "err_fg":  "#f85149",
    "ok_fg":   "#3fb950",
}

PROVISIONED_FILENAME = ".provisioned"


class ProvisionApp:
    """5-screen first-boot provisioning wizard."""

    def __init__(self, root: tk.Tk, log_dir: str | None):
        self.root      = root
        self.log_dir   = log_dir   # may be None on entry; updated by _check_logs()
        self.bmd_id_str = ""       # digits entered on numpad
        self._step_icons: dict[str, tk.Label] = {}
        self._status_var: tk.StringVar | None  = None
        self._countdown_var: tk.StringVar | None = None

        self.root.title("BMD First-Boot Provisioning")
        self.root.attributes("-fullscreen", True)
        self.root.resizable(False, False)
        # Force to stay on top
        self.root.lift()
        self.root.focus_force()
        self.root.configure(bg=P["bg"])

        self._frame = tk.Frame(self.root, bg=P["bg"])
        self._frame.pack(fill=tk.BOTH, expand=True)

        self.show_welcome()

    # ──────────────────────────────────────────────────────────────────────────
    # Shared helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _clear(self):
        for w in self._frame.winfo_children():
            w.destroy()

    def _header(self, title: str, subtitle: str = ""):
        h = tk.Frame(self._frame, bg=P["panel"], pady=26)
        h.pack(fill=tk.X)
        tk.Label(h, text=title, font=("Helvetica", 30, "bold"),
                 bg=P["panel"], fg=P["text"]).pack()
        if subtitle:
            tk.Label(h, text=subtitle, font=("Helvetica", 14),
                     bg=P["panel"], fg=P["muted"]).pack(pady=(6, 0))

    def _footer(self):
        """Return a frame pinned to the bottom for action buttons."""
        f = tk.Frame(self._frame, bg=P["bg"], pady=18)
        f.pack(side=tk.BOTTOM, fill=tk.X, padx=60)
        return f

    def _flat_btn(self, parent, text, command, bg, fg="white",
                  side=tk.RIGHT, padx_outer=0):
        tk.Button(parent, text=text, command=command,
                  font=("Helvetica", 17, "bold"),
                  bg=bg, fg=fg, activebackground=bg,
                  padx=28, pady=14, relief=tk.FLAT, bd=0, cursor="hand2"
                  ).pack(side=side, padx=(padx_outer, 0))

    # ──────────────────────────────────────────────────────────────────────────
    # Prerequisite checks
    # ──────────────────────────────────────────────────────────────────────────

    def _check_hw_binding(self) -> tuple[bool, str]:
        try:
            import hardware_crypto
            mid = hardware_crypto.get_machine_id()
            if mid.startswith("OTP_"):
                return True, "OTP silicon fuses (best)"
            elif mid.startswith("CPUSERIAL_"):
                return True, "CPU serial register"
            elif mid.startswith("DMI_"):
                return True, "DMI product UUID"
            else:
                return False, "Filesystem fallback — NOT clone-resistant"
        except Exception as e:
            return False, str(e)

    def _check_printer(self) -> tuple[bool, str]:
        # Look for known device files first (fast, no USB probe needed)
        for dev in ("/dev/usb/lp0", "/dev/usb/lp1", "/dev/lp0", "/dev/lp1"):
            if os.path.exists(dev):
                return True, dev
        # USB probe
        try:
            import usb.core
            for vid, pid in [(0x0483, 0x5743), (0x0416, 0x5011), (0x04b8, 0x0202)]:
                if usb.core.find(idVendor=vid, idProduct=pid):
                    return True, f"USB {hex(vid)}:{hex(pid)}"
        except Exception:
            pass
        return False, "Not found (ticket print will be skipped)"

    def _check_logs(self) -> tuple[bool, str]:
        candidates = [
            os.environ.get("EVOTING_LOG_DIR", ""),
            "/media/evoting/LOGS",
            "/logs",
        ]
        for path in candidates:
            if path and os.path.isdir(path):
                self.log_dir = path
                return True, path
        return False, "Not found — mount at /media/evoting/LOGS"

    # ──────────────────────────────────────────────────────────────────────────
    # Screen 1 — Welcome / prerequisite checks
    # ──────────────────────────────────────────────────────────────────────────

    def show_welcome(self):
        self._clear()
        self._header(
            "🗳  BMD First-Boot Setup",
            "This device has not been provisioned yet.",
        )

        body = tk.Frame(self._frame, bg=P["bg"], pady=10, padx=60)
        body.pack(expand=True, fill=tk.BOTH)

        hw_ok,      hw_msg      = self._check_hw_binding()
        printer_ok, printer_msg = self._check_printer()
        logs_ok,    logs_msg    = self._check_logs()

        checks = [
            ("Hardware Binding (OTP)",    hw_ok,      hw_msg),
            ("Thermal Printer",           printer_ok, printer_msg),
            ("LOGS Partition",            logs_ok,    logs_msg),
        ]

        cf = tk.Frame(body, bg=P["bg"])
        cf.pack(pady=20)
        for label, ok, detail in checks:
            row = tk.Frame(cf, bg=P["bg"])
            row.pack(fill=tk.X, pady=8)
            icon  = "✅" if ok else "⚠️"
            color = P["ok_fg"] if ok else P["warn_fg"]
            tk.Label(row, text=f"{icon}  {label}",
                     font=("Helvetica", 16, "bold"),
                     bg=P["bg"], fg=color, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=detail,
                     font=("Helvetica", 14),
                     bg=P["bg"], fg=P["muted"], anchor="w"
                     ).pack(side=tk.LEFT, padx=(14, 0))

        # Critical warning when LOGS partition missing
        if not logs_ok:
            wb = tk.Frame(body, bg=P["warn_bg"], pady=14, padx=18)
            wb.pack(fill=tk.X, pady=12)
            tk.Label(
                wb,
                text=(
                    "⚠️  LOGS partition is required to continue.\n"
                    "Please ensure the storage device is mounted at "
                    "/media/evoting/LOGS and press Retry."
                ),
                font=("Helvetica", 14), bg=P["warn_bg"], fg=P["warn_fg"],
                justify=tk.LEFT,
            ).pack(anchor="w")

        foot = self._footer()
        if logs_ok:
            self._flat_btn(foot, "Continue →", self.show_bmd_id, P["accent"])
        else:
            self._flat_btn(foot, "↺  Retry Checks", self.show_welcome, "#1f6feb")

    # ──────────────────────────────────────────────────────────────────────────
    # Screen 2 — BMD ID numpad
    # ──────────────────────────────────────────────────────────────────────────

    def show_bmd_id(self):
        self._clear()
        self._header(
            "Enter BMD ID",
            "Each Ballot Marking Device must have a unique ID number.",
        )

        body = tk.Frame(self._frame, bg=P["bg"])
        body.pack(expand=True, fill=tk.BOTH, padx=60, pady=16)

        # Display strip — compact, fixed-height so numpad gets the rest
        disp = tk.Frame(body, bg=P["panel"], pady=10, padx=22)
        disp.pack(fill=tk.X, pady=(0, 10))
        tk.Label(disp, text="BMD ID:", font=("Helvetica", 13),
                 bg=P["panel"], fg=P["muted"]).pack(anchor="w")
        self._bmd_disp = tk.StringVar(value="_")
        tk.Label(disp, textvariable=self._bmd_disp,
                 font=("Helvetica", 38, "bold"),
                 bg=P["panel"], fg=P["text"]).pack(anchor="w")

        self.bmd_id_str = ""

        # Numpad
        pad = tk.Frame(body, bg=P["bg"])
        pad.pack()

        layout = [
            ["1", "2", "3"],
            ["4", "5", "6"],
            ["7", "8", "9"],
            ["⌫", "0", "✓"],
        ]
        for r, row in enumerate(layout):
            for c, key in enumerate(row):
                if key == "✓":
                    bg, cmd = P["accent"], self._bmd_confirm
                elif key == "⌫":
                    bg, cmd = "#6e3030", self._bmd_backspace
                else:
                    bg  = P["numpad"]
                    cmd = lambda k=key: self._bmd_append(k)
                tk.Button(
                    pad, text=key,
                    font=("Helvetica", 18, "bold"),
                    bg=bg, fg=P["text"],
                    width=5, pady=10,
                    relief=tk.FLAT, cursor="hand2",
                    command=cmd,
                ).grid(row=r, column=c, padx=4, pady=4)

        foot = self._footer()
        self._flat_btn(foot, "← Back", self.show_welcome, P["btn"],
                       fg=P["muted"], side=tk.LEFT)

    def _bmd_append(self, digit: str):
        if len(self.bmd_id_str) < 4:
            self.bmd_id_str += digit
            self._bmd_disp.set(self.bmd_id_str or "_")

    def _bmd_backspace(self):
        self.bmd_id_str = self.bmd_id_str[:-1]
        self._bmd_disp.set(self.bmd_id_str or "_")

    def _bmd_confirm(self):
        if not self.bmd_id_str:
            messagebox.showwarning("No ID", "Please enter a BMD ID first.")
            return
        try:
            bmd_id = int(self.bmd_id_str)
            if bmd_id < 1:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Invalid", "BMD ID must be a positive integer.")
            return
        self.show_confirm(bmd_id)

    # ──────────────────────────────────────────────────────────────────────────
    # Screen 3 — Confirm
    # ──────────────────────────────────────────────────────────────────────────

    def show_confirm(self, bmd_id: int):
        self._clear()
        self._header(
            "Confirm Provisioning",
            "Verify the details below before generating keys.",
        )

        body = tk.Frame(self._frame, bg=P["bg"], pady=20, padx=80)
        body.pack(expand=True, fill=tk.BOTH)

        box = tk.Frame(body, bg=P["panel"], pady=28, padx=36)
        box.pack(fill=tk.X, pady=16)

        _, hw_msg = self._check_hw_binding()
        rows = [
            ("BMD ID",        str(bmd_id)),
            ("HW Binding",    hw_msg),
            ("LOGS Partition", self.log_dir or "NOT FOUND"),
            ("Action",        "Generate RSA-2048 key pair + print public key"),
        ]
        for label, val in rows:
            r = tk.Frame(box, bg=P["panel"])
            r.pack(fill=tk.X, pady=7)
            tk.Label(r, text=f"{label}:", font=("Helvetica", 16, "bold"),
                     bg=P["panel"], fg=P["muted"], width=18, anchor="w",
                     ).pack(side=tk.LEFT)
            tk.Label(r, text=val, font=("Helvetica", 16),
                     bg=P["panel"], fg=P["text"], anchor="w",
                     ).pack(side=tk.LEFT)

        wb = tk.Frame(body, bg=P["warn_bg"], pady=12, padx=16)
        wb.pack(fill=tk.X)
        tk.Label(
            wb,
            text=(
                "⚠️  This will OVERWRITE any existing private.pem / public.pem.\n"
                "Only proceed if no ballots have been encrypted with a previous key."
            ),
            font=("Helvetica", 13), bg=P["warn_bg"], fg=P["warn_fg"],
            justify=tk.LEFT,
        ).pack(anchor="w")

        foot = self._footer()
        self._flat_btn(
            foot, "✓  Confirm & Generate Keys",
            lambda: self.run_provisioning(bmd_id), P["accent"],
        )
        self._flat_btn(foot, "← Change ID", self.show_bmd_id, P["btn"],
                       fg=P["muted"], side=tk.LEFT)

    # ──────────────────────────────────────────────────────────────────────────
    # Screen 4 — Running provisioning
    # ──────────────────────────────────────────────────────────────────────────

    def run_provisioning(self, bmd_id: int):
        self._clear()
        self._header(
            f"Provisioning BMD #{bmd_id}…",
            "Please wait — do not power off.",
        )

        body = tk.Frame(self._frame, bg=P["bg"], pady=30, padx=80)
        body.pack(expand=True, fill=tk.BOTH)

        self._status_var = tk.StringVar(value="Starting…")
        tk.Label(body, textvariable=self._status_var,
                 font=("Helvetica", 17), bg=P["bg"], fg=P["text"],
                 justify=tk.LEFT).pack(anchor="w", pady=(0, 20))

        STEPS = [
            ("keys",   "Generating RSA-2048 key pair…"),
            ("config", "Writing BMD configuration…"),
            ("print",  "Printing public key receipt…"),
            ("flag",   "Writing provisioned flag…"),
        ]
        self._step_icons = {}
        for step_id, label in STEPS:
            row = tk.Frame(body, bg=P["bg"])
            row.pack(fill=tk.X, pady=5)
            icon_lbl = tk.Label(row, text="⏳", font=("Helvetica", 16),
                                bg=P["bg"], fg=P["muted"], width=3)
            icon_lbl.pack(side=tk.LEFT)
            tk.Label(row, text=label, font=("Helvetica", 15),
                     bg=P["bg"], fg=P["muted"], anchor="w").pack(side=tk.LEFT)
            self._step_icons[step_id] = icon_lbl

        threading.Thread(
            target=self._provision_worker, args=(bmd_id,), daemon=True
        ).start()

    # ──────────────────────────────────────────────────────────────────────────
    # Background provisioning worker
    # ──────────────────────────────────────────────────────────────────────────

    def _set_step(self, step_id: str, state: str):
        icons = {"running": "⏳", "done": "✅", "error": "❌", "skip": "⏭"}
        lbl = self._step_icons.get(step_id)
        if lbl:
            self.root.after(0, lambda: lbl.config(text=icons.get(state, "?")))

    def _set_status(self, msg: str):
        if self._status_var:
            self.root.after(0, lambda: self._status_var.set(msg))  # type: ignore[arg-type]

    def _provision_worker(self, bmd_id: int):
        errors: list[str] = []
        project_dir = os.path.dirname(os.path.abspath(__file__))

        # ── Step 1: Generate RSA keys ─────────────────────────────────────────
        try:
            self._set_step("keys", "running")
            self._set_status(f"Generating RSA-2048 key pair for BMD #{bmd_id}…")
            os.environ["EVOTING_BMD_ID"] = str(bmd_id)
            from generate_rpi_keys import generate_keys
            generate_keys()
            self._set_step("keys", "done")
        except Exception as exc:
            self._set_step("keys", "error")
            errors.append(f"Key generation: {exc}")

        # ── Step 2: Write bmd_config.json ────────────────────────────────────
        try:
            self._set_step("config", "running")
            self._set_status("Writing BMD configuration…")
            cfg = {
                "bmd_id": bmd_id,
                "provisioned_at": datetime.datetime.now().isoformat(),
            }
            cfg_path = os.path.join(project_dir, "bmd_config.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            self._set_step("config", "done")
        except Exception as exc:
            self._set_step("config", "error")
            errors.append(f"Config write: {exc}")

        # ── Step 3: Print provisioning ticket ────────────────────────────────
        try:
            self._set_step("print", "running")
            self._set_status("Connecting to printer…")
            pub_key_path = os.path.join(project_dir, "public.pem")
            with open(pub_key_path, "r", encoding="utf-8") as f:
                public_key_pem = f.read()
            import hardware_crypto
            machine_id = hardware_crypto.get_machine_id()
            self._print_ticket(bmd_id, public_key_pem, machine_id)
            self._set_step("print", "done")
        except Exception as exc:
            self._set_step("print", "skip")
            errors.append(f"Print (non-critical): {exc}")

        # ── Step 4: Write .provisioned flag ──────────────────────────────────
        try:
            self._set_step("flag", "running")
            self._set_status("Writing provisioned flag to LOGS partition…")
            if not self.log_dir:
                raise RuntimeError("LOGS partition not mounted")
            flag_path = os.path.join(self.log_dir, PROVISIONED_FILENAME)
            with open(flag_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "bmd_id": bmd_id,
                        "provisioned_at": datetime.datetime.now().isoformat(),
                    },
                    f,
                    indent=2,
                )
            try:
                os.chmod(flag_path, 0o444)   # make read-only
            except Exception:
                pass
            self._set_step("flag", "done")
        except Exception as exc:
            self._set_step("flag", "error")
            errors.append(f"Flag write: {exc}")

        self.root.after(0, lambda: self.show_done(bmd_id, errors))

    # ──────────────────────────────────────────────────────────────────────────
    # Printer helper (self-contained, no PrinterService dependency)
    # ──────────────────────────────────────────────────────────────────────────

    def _get_printer(self):
        """Return an escpos printer instance or None."""
        try:
            from escpos.printer import Usb, File
        except ImportError:
            return None

        # Try File devices first (faster, no USB probe)
        for dev in ("/dev/usb/lp0", "/dev/usb/lp1", "/dev/lp0", "/dev/lp1"):
            if os.path.exists(dev):
                try:
                    return File(dev, profile="default")
                except Exception:
                    pass

        # USB class probe
        for vid, pid in [(0x0483, 0x5743), (0x0416, 0x5011), (0x04b8, 0x0202)]:
            try:
                return Usb(vid, pid, profile="default")
            except Exception:
                pass

        return None

    def _print_ticket(self, bmd_id: int, public_key_pem: str, machine_id: str):
        """Print the provisioning receipt.

        QR encodes the SHA-256 fingerprint (64 hex chars) rather than the full
        PEM: this keeps the QR small enough to scan reliably on narrow paper.
        The RGB-canvas wrapping is mandatory — qrcode.make() returns a 1-bit
        image that many ESC/POS drivers cannot render correctly.
        """
        import qrcode          # type: ignore
        from PIL import Image
        import hashlib

        printer = self._get_printer()
        if not printer:
            raise RuntimeError("No thermal printer found")

        timestamp   = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        paper_width = 384      # dots (80 mm printer); use 302 for 58 mm
        bar = "=" * 32

        if "OTP_" in machine_id:
            hw_label = "OTP (clone-resistant)"
        elif "CPUSERIAL_" in machine_id:
            hw_label = "CPU Serial (clone-resistant)"
        elif "DMI_" in machine_id:
            hw_label = "DMI UUID (clone-resistant)"
        else:
            hw_label = "FALLBACK (not secure)"

        # Fingerprint QR: compact, always scannable on narrow thermal strip
        fingerprint = hashlib.sha256(public_key_pem.strip().encode()).hexdigest()
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6, border=2,
        )
        qr.add_data(fingerprint)
        qr.make(fit=True)
        qr_raw     = qr.make_image(fill_color="black", back_color="white")
        qr_size    = min(paper_width - 20, 300)
        qr_resized = qr_raw.resize((qr_size, qr_size))
        # RGB canvas — required for correct ESC/POS rendering
        canvas = Image.new("RGB", (paper_width, qr_size), "white")
        canvas.paste(qr_resized, ((paper_width - qr_size) // 2, 0))
        tmp_qr = f"/tmp/bmd_qr_{bmd_id}.png"
        canvas.save(tmp_qr)

        try:
            printer.set(align="center", bold=True)
            printer.text(f"{bar}\n")
            printer.text("BALLOT MARKING DEVICE\n")
            printer.text("PROVISIONING RECEIPT\n")
            printer.text(f"{bar}\n\n")

            printer.set(align="left", bold=False)
            printer.text(f"Date/Time  : {timestamp}\n")
            printer.text(f"BMD ID     : {bmd_id}\n")
            printer.text(f"HW Binding : {hw_label}\n\n")

            printer.set(align="center", bold=True)
            printer.text("PUBLIC KEY FINGERPRINT (SHA-256)\n")
            printer.text("Scan QR or compare text below:\n\n")
            printer.image(tmp_qr)
            printer.text("\n")

            printer.set(align="left", bold=False)
            fp = fingerprint
            printer.text(f"{fp[:32]}\n{fp[32:]}\n\n")

            printer.set(align="center", bold=True)
            printer.text(f"{bar}\nFULL PUBLIC KEY:\n{bar}\n")
            printer.set(align="left", bold=False)
            for line in public_key_pem.strip().splitlines():
                printer.text(f"{line}\n")

            printer.set(align="center", bold=True)
            printer.text(f"\n{bar}\n")
            printer.text("SEND TO ELECTION ADMIN\n")
            printer.text(f"{bar}\n")

            # Feed paper so all content clears the auto-cutter blade
            printer.text("\n\n\n\n\n\n")
            printer.cut(mode="FULL")

        finally:
            if os.path.exists(tmp_qr):
                os.remove(tmp_qr)


    # ──────────────────────────────────────────────────────────────────────────
    # Screen 5 — Done
    # ──────────────────────────────────────────────────────────────────────────

    def show_done(self, bmd_id: int, errors: list[str]):
        self._clear()
        # Determine whether critical steps succeeded
        critical_failed = any(
            kw in e
            for e in errors
            for kw in ("Key generation", "Flag write")
        )

        if critical_failed:
            title    = "⚠️  Provisioning Incomplete"
            subtitle = "Critical step(s) failed — please retry."
        else:
            title    = f"✅  BMD #{bmd_id} Provisioned"
            subtitle = "Device is ready. Voting app will start automatically."

        self._header(title, subtitle)

        body = tk.Frame(self._frame, bg=P["bg"], pady=20, padx=80)
        body.pack(expand=True, fill=tk.BOTH)

        if errors:
            eb = tk.Frame(body, bg=P["err_bg"], pady=14, padx=18)
            eb.pack(fill=tk.X, pady=10)
            tk.Label(eb, text="Issues encountered:",
                     font=("Helvetica", 15, "bold"),
                     bg=P["err_bg"], fg=P["err_fg"]).pack(anchor="w")
            for e in errors:
                tk.Label(eb, text=f"•  {e}",
                         font=("Helvetica", 13),
                         bg=P["err_bg"], fg=P["warn_fg"],
                         wraplength=700, justify=tk.LEFT).pack(anchor="w")

        if not critical_failed:
            # ── Device summary card ───────────────────────────────────────────
            # Read back what was just written so the operator can verify.
            project_dir = os.path.dirname(os.path.abspath(__file__))
            pub_fingerprint = "(unavailable)"
            try:
                from cryptography.hazmat.primitives.serialization import load_pem_public_key
                from cryptography.hazmat.primitives import hashes
                pub_path = os.path.join(project_dir, "public.pem")
                with open(pub_path, "rb") as f:
                    pub_key = load_pem_public_key(f.read())
                # SHA-256 fingerprint of the DER-encoded public key
                from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
                der = pub_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
                import hashlib
                digest = hashlib.sha256(der).hexdigest()
                pub_fingerprint = ":" .join(digest[i:i+4] for i in range(0, 32, 4))
            except Exception:
                pass

            hw_ok, hw_msg = self._check_hw_binding()
            summary_box = tk.Frame(body, bg=P["panel"], pady=16, padx=24)
            summary_box.pack(fill=tk.X, pady=(8, 4))
            for lbl, val, col in [
                ("BMD ID",      str(bmd_id),        P["text"]),
                ("HW Binding",  hw_msg,             P["ok_fg"] if hw_ok else P["warn_fg"]),
                ("Key SHA-256", pub_fingerprint,     P["muted"]),
                ("LOGS Path",   self.log_dir or "?", P["muted"]),
            ]:
                row = tk.Frame(summary_box, bg=P["panel"])
                row.pack(fill=tk.X, pady=3)
                tk.Label(row, text=f"{lbl}:",
                         font=("Helvetica", 13, "bold"),
                         bg=P["panel"], fg=P["muted"],
                         width=14, anchor="w").pack(side=tk.LEFT)
                tk.Label(row, text=val,
                         font=("Helvetica", 13),
                         bg=P["panel"], fg=col,
                         anchor="w", wraplength=600).pack(side=tk.LEFT)

            self._countdown_var = tk.StringVar(value="Starting in 10…")
            tk.Label(body, textvariable=self._countdown_var,
                     font=("Helvetica", 18, "bold"),
                     bg=P["bg"], fg=P["ok_fg"]).pack(pady=(12, 0))
            self._tick(10)
            self._last_bmd_id = bmd_id   # save for reprint

        foot = self._footer()
        if critical_failed:
            self._flat_btn(foot, "↺  Retry", self.show_welcome, "#1f6feb")
        else:
            self._flat_btn(
                foot, "▶  Start Voting App Now",
                self._launch_voting_app, P["accent"],
            )
            self._flat_btn(
                foot, "🖨  Reprint Ticket",
                self._reprint_ticket, "#1565c0", side=tk.LEFT,
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Countdown + restart
    # ──────────────────────────────────────────────────────────────────────────

    def _tick(self, n: int):
        if n <= 0:
            self._launch_voting_app()
            return
        if self._countdown_var:
            self._countdown_var.set(f"Starting in {n}…")
        self.root.after(1000, lambda: self._tick(n - 1))

    def _reprint_ticket(self):
        """Reprint the provisioning ticket from the Done screen."""
        project_dir = os.path.dirname(os.path.abspath(__file__))
        try:
            pub_key_path = os.path.join(project_dir, "public.pem")
            with open(pub_key_path, "r", encoding="utf-8") as f:
                public_key_pem = f.read()
            import hardware_crypto
            machine_id = hardware_crypto.get_machine_id()
            bmd_id = getattr(self, "_last_bmd_id", 0)
            self._print_ticket(bmd_id, public_key_pem, machine_id)
            messagebox.showinfo("Reprint", "Ticket reprinted successfully.")
        except Exception as exc:
            messagebox.showerror("Reprint Failed", str(exc))

    def _launch_voting_app(self):
        """Restart main.py — the .provisioned flag now exists, so the voting app loads."""
        self.root.destroy()
        os.execv(sys.executable, [sys.executable] + sys.argv)


# Allow running standalone for testing
if __name__ == "__main__":
    root = tk.Tk()
    app  = ProvisionApp(root, log_dir=None)
    root.mainloop()
