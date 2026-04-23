import os
import uuid
import datetime
import time
import shutil
import subprocess
import json
import qrcode
from PIL import Image, ImageDraw, ImageFont

try:
    from escpos.printer import Usb, File, Win32Raw
except ImportError:
    print("Warning: python-escpos not installed. Printing will fail silently or log errors.")
    Usb = None
    File = None
    Win32Raw = None

class PrinterService:
    def __init__(self, data_handler):
        self.data_handler = data_handler
        self.printer = None
        self._force_pyusb = False
        self.paper_width_chars = self._read_int_env("EVOTING_PAPER_WIDTH_CHARS", 32)
        self.paper_width_dots = self._read_int_env("EVOTING_PAPER_WIDTH_DOTS", 384)
        self.reverse_print = self._read_bool_env("EVOTING_PRINT_REVERSE", True)
        self.connect_printer()

    def _read_int_env(self, name, default_value):
        raw_value = os.environ.get(name)
        if raw_value is None:
            return default_value
        try:
            return int(raw_value)
        except Exception:
            return default_value

    def _read_bool_env(self, name, default_value):
        raw_value = os.environ.get(name)
        if raw_value is None:
            return default_value
        return str(raw_value).strip().lower() in ("1", "true", "yes", "on")

    def _bar(self, char):
        return char * self.paper_width_chars

    def _center_line(self, text):
        return text.center(self.paper_width_chars)

    def _run_command_text(self, command):
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            output = (result.stdout or result.stderr or "").strip()
            return output
        except Exception:
            return "UNKNOWN"

    def _yes_no_unknown(self, value):
        text = str(value or "").strip().lower()
        if not text:
            return "UNKNOWN"
        if text in ("active", "enabled", "yes", "on", "up"):
            return "ON"
        if text in ("inactive", "disabled", "no", "off", "down", "failed"):
            return "OFF"
        return text.upper()

    def _get_wifi_status(self):
        if shutil.which("nmcli"):
            output = self._run_command_text(["nmcli", "-t", "-f", "WIFI", "general"])
            if output:
                return self._yes_no_unknown(output)
        return self._yes_no_unknown(self._run_command_text(["bash", "-lc", "ip link show wlan0 2>/dev/null | grep -q 'state UP' && echo ON || echo OFF"]))

    def _get_ssh_status(self):
        if shutil.which("systemctl"):
            for service_name in ("ssh", "sshd"):
                output = self._run_command_text(["systemctl", "is-active", service_name])
                if output and output != "unknown":
                    return self._yes_no_unknown(output)
        return "UNKNOWN"

    def _get_bluetooth_status(self):
        if shutil.which("systemctl"):
            output = self._run_command_text(["systemctl", "is-active", "bluetooth"])
            if output and output != "unknown":
                return self._yes_no_unknown(output)
        return "UNKNOWN"

    def _count_votes_cast(self, log_dir):
        votes_file = os.path.join(log_dir or "", "votes.json")
        if not os.path.exists(votes_file):
            return 0
        try:
            with open(votes_file, "r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except Exception:
            return 0

    def _get_candidate_display_text(self, cid):
        cand = self.data_handler.get_candidate_by_id(cid)
        if not cand:
            return str(cid)

        candidate_name = str(
            cand.get("name")
            or cand.get("candidate_name")
            or cand.get("candidate_number")
            or cid
        ).strip()
        candidate_number = str(cand.get("candidate_number") or cand.get("id") or cid).strip()

        if candidate_name and candidate_number and candidate_name != candidate_number:
            return f"{candidate_name} ({candidate_number})"
        return candidate_name or candidate_number or str(cid)

    def _get_candidate_name_and_number(self, cid):
        """Return (name_str, number_str) separately for structured VVPAT printing."""
        cand = self.data_handler.get_candidate_by_id(cid)
        if not cand:
            return str(cid), ""
        name = str(
            cand.get("name") or cand.get("candidate_name") or cand.get("candidate_number") or cid
        ).strip()
        number = str(cand.get("candidate_number") or cand.get("id") or cid).strip()
        if name == number:
            number = ""
        return name, number

    def _build_vote_print_context(self, mode, selections):
        ballot_id = self.data_handler.get_short_ballot_id()
        station_id = "PS-105-DELHI"
        timestamp = datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")

        if mode == 'normal':
            cid = selections.get(1)
            vvpat_sel_str = self._get_candidate_display_text(cid)
            vvpat_candidates = None  # not needed for normal mode
        else:
            ranks = sorted(selections.keys())
            # For block voting: list of (name, number) in rank order
            vvpat_candidates = [self._get_candidate_name_and_number(selections[r]) for r in ranks]
            vvpat_sel_str = ", ".join(
                f"{name} ({num})" if num else name for name, num in vvpat_candidates
            )

        qr_choice_data = self.data_handler.build_receipt_qr_payload(selections, mode)
        short_b_id = self.data_handler.get_short_ballot_id(ballot_id)
        return {
            "ballot_id": ballot_id,
            "station_id": station_id,
            "timestamp": timestamp,
            "vvpat_sel_str": vvpat_sel_str,
            "vvpat_candidates": vvpat_candidates,  # None for normal, list for block
            "qr_choice_data": qr_choice_data,
            "short_b_id": short_b_id,
        }

    def _print_vote_vvpat_section(self, p, context):
        import textwrap
        bar = self._bar("=")
        w   = self.paper_width_chars

        p.text("\n")
        p.text(bar + "\n")

        temp_img = self._generate_vvpat_qr(context["qr_choice_data"], context["short_b_id"])
        p.text("\n")
        p.set(align='left')
        p.image(temp_img)
        p.text("\n")
        if os.path.exists(temp_img):
            os.remove(temp_img)

        candidates = context.get('vvpat_candidates')
        if candidates:
            # Block voting: print each candidate as Name / Entry Number pair
            p.set(align='left', bold=True)
            p.text("Choices:\n")
            p.set(align='left', bold=False)
            for name, number in candidates:
                for line in textwrap.wrap(name, width=w):
                    p.text(line + "\n")
                if number:
                    p.text(number + "\n")
                p.text("\n")
        else:
            # Normal voting: single choice
            p.set(align='left', bold=True)
            p.text("Choice:\n")
            p.set(align='left', bold=False)
            for line in textwrap.wrap(context['vvpat_sel_str'], width=w):
                p.text(line + "\n")

        p.text("\n")

        p.set(align='left', font='a', width=1, height=1, bold=True)
        p.text(self._center_line("** VVPAT SLIP **") + "\n")
        p.text(bar + "\n")
        p.set(align='left', bold=False)

        p.text("\n\n\n\n\n\n")

    def _set_reverse_print_mode(self, enabled):
        if not self.reverse_print or not self.printer:
            return
        try:
            # ESC { n enables/disables upside-down text mode in ESC/POS.
            self.printer._raw(b"\x1b\x7b" + (b"\x01" if enabled else b"\x00"))
        except Exception:
            # Some printer backends may not expose raw ESC/POS commands.
            pass

    def is_printer_connected(self):
        if self.printer is None:
            self.connect_printer()
        return self.printer is not None

    def connect_printer(self):
        if self.printer is not None:
            return

        # Allow deployment-specific printer selection without code edits.
        configured_printer_name = os.environ.get("EVOTING_PRINTER_NAME", "POS50")
        configured_usb_lp = os.environ.get("EVOTING_PRINTER_USB_LP", "0")
        default_device_path = "/dev/usb/lp0" if os.name != "nt" else ""
        configured_device_path = os.environ.get("EVOTING_PRINTER_DEVICE", default_device_path).strip()
        configured_profile = os.environ.get("EVOTING_PRINTER_PROFILE", "default").strip() or "default"

        # On Linux, if a raw lp device is configured and exists, use it first.
        # This avoids unnecessary USB detach/probe paths that can interfere with usblp-backed printers.
        if getattr(self, "_force_pyusb", False):
            pass # Skip straight to PyUSB reset
        elif File and configured_device_path and os.path.exists(configured_device_path):
            try:
                self.printer = File(configured_device_path, profile=configured_profile)
                print(
                    f"Printer connected successfully at {configured_device_path} "
                    f"with {configured_profile} profile."
                )
                return
            except Exception as e:
                print(f"Configured printer device failed on {configured_device_path}: {e}")
            
        # Try to actively detach any OS kernel drivers (usblp) blocking the USB endpoints to prevent Errno 16
        try:
            import usb.core
            # Find ANY device that has a printer interface (Class 7)
            printers = usb.core.find(find_all=True, custom_match=lambda d: any(
                intf.bInterfaceClass == 7 for cfg in d for intf in cfg
            ))
            for pdev in printers:
                try:
                    if pdev.is_kernel_driver_active(0):
                        pdev.detach_kernel_driver(0)
                        print(f"Detached kernel driver for auto-detected printer {hex(pdev.idVendor)}:{hex(pdev.idProduct)}")
                except Exception:
                    pass
        except Exception:
            pass

        if Win32Raw:
            # Try Windows printer queue names in priority order.
            win_names = [
                configured_printer_name,
                "KPOS_58 Printer",
                "POS50",
                "POS-50",
                "POS58",
                "POS-58",
                "POS-80C",
            ]
            seen = set()
            for name in win_names:
                if not name or name in seen:
                    continue
                seen.add(name)
                try:
                    self.printer = Win32Raw(name)
                    print(f"Printer connected via Win32Raw ({name}) successfully.")
                    return
                except Exception:
                    pass

        # First try USB class auto-discovery
        if Usb:
            # 1. Specific STMicroelectronics POS80 (Default endpoints)
            try:
                self.printer = Usb(0x0483, 0x5743, profile="default")
                print("Printer connected via USB (0x0483:0x5743) successfully.")
                return
            except Exception as e:
                pass
                
            # 2. Specific STMicroelectronics POS80 (Explicit out_ep=0x01, some clones need this)
            try:
                self.printer = Usb(0x0483, 0x5743, out_ep=0x01, profile="default")
                print("Printer connected via USB (0x0483:0x5743 with out_ep=0x01) successfully.")
                return
            except Exception as e:
                pass
                
            # 3. Specific STMicroelectronics POS80 (Explicit out_ep=0x03)
            try:
                self.printer = Usb(0x0483, 0x5743, out_ep=0x03, profile="default")
                print("Printer connected via USB (0x0483:0x5743 with out_ep=0x03) successfully.")
                return
            except Exception as e:
                pass

            # 4. Generic POS58/80
            try:
                self.printer = Usb(0x0416, 0x5011, profile="default")
                print("Printer connected via USB (0x0416:0x5011) successfully.")
                return
            except Exception as e:
                pass
            
            # 5. Alternative common Vendor/Product for POS80 (Generic Epson clone)
            try:
                self.printer = Usb(0x04b8, 0x0202, profile="default")
                print("Printer connected via USB (0x04b8:0x0202) successfully.")
                return
            except Exception as e:
                pass

            # 6. Auto-detect any USB printer (Class=7) not listed above
            try:
                import usb.core
                printers = usb.core.find(find_all=True, custom_match=lambda d: any(
                    intf.bInterfaceClass == 7 for cfg in d for intf in cfg
                ))
                for pdev in printers:
                    vid, pid = pdev.idVendor, pdev.idProduct
                    # Skip if it's one we already explicitly tried
                    if (vid, pid) in [(0x0483, 0x5743), (0x0416, 0x5011), (0x04b8, 0x0202)]:
                        continue
                    try:
                        self.printer = Usb(vid, pid, profile="default")
                        print(f"Printer auto-connected via generic USB ({hex(vid)}:{hex(pid)}) successfully.")
                        return
                    except Exception as e:
                        print(f"Failed generic USB connect for {hex(vid)}:{hex(pid)} - {e}")
            except Exception:
                pass
                
        # Fallback to File class (/dev/usb/lpX or /dev/lpX)
        if File:
            connected = False
            device_candidates = []
            if configured_device_path:
                device_candidates.append(configured_device_path)

            if getattr(self, "_force_pyusb", False):
                device_candidates = [] # PyUsb forced

            # Prioritize configured USB port first, then try standard ports.
            port_candidates = []
            try:
                port_candidates.append(int(configured_usb_lp))
            except Exception:
                pass
            port_candidates.extend([0, 1, 2, 3, 4, 5])

            for port_num in port_candidates:
                device_candidates.append(f"/dev/usb/lp{port_num}")
                device_candidates.append(f"/dev/lp{port_num}")

            seen_paths = set()
            for device_path in device_candidates:
                if not device_path or device_path in seen_paths:
                    continue
                seen_paths.add(device_path)
                if os.path.exists(device_path):
                    try:
                        self.printer = File(device_path, profile=configured_profile)
                        print(
                            f"Printer connected successfully at {device_path} "
                            f"with {configured_profile} profile."
                        )
                        connected = True
                        break
                    except Exception as e:
                        print(f"Printer connection failed on {device_path}: {e}")
            
            if not connected:
                 print(
                     "Printer device file not found or could not connect. "
                     "Checked EVOTING_PRINTER_DEVICE, /dev/usb/lp0-/dev/usb/lp5, and /dev/lp0-/dev/lp5."
                 )
                 self.printer = None
        else:
             print("escpos library not available.")

    def print_vote(self, mode, selections, is_final=True, stage="both"):
        """
        Synchronous print function. 
        Returns True if successful, raises Exception if failed.
        Should be called from a background thread.
        """
        # Re-check connection if needed
        if not self.printer:
            self.connect_printer()
            
        if not self.printer:
            # Fallback/Error if still no printer
            raise Exception("Printer not connected")

        context = self._build_vote_print_context(mode, selections)

        p = self.printer

        try:
            self._set_reverse_print_mode(True)

            if stage in ("both", "vvpat", "receipt"):
                self._print_vote_vvpat_section(p, context)
                time.sleep(5)
                p.text("\n" * 2)
                p.cut(mode='FULL')
                p.text("\n" * 12) # Extra feed after cut helps slip clear the printer
                return {"stage": "vvpat_complete", "context": context}

            return True

        except Exception as e:
            try:
                if self.printer:
                    self.printer.close()
            except Exception:
                pass
            if 'Input/' in str(e) or 'Errno 5' in str(e) or 'Device or resource busy' in str(e):
                self._force_pyusb = True
                print('Forcing PyUSB reconnect on next print...\n')
            self.printer = None
            raise e
        finally:
            self._set_reverse_print_mode(False)


    def print_recovery_vvpat(self, election_name, vvpat_choice_str, original_timestamp=""):
        """
        Print a plain-text recovery VVPAT slip when the original print was interrupted.
        Does not need candidate data loaded — uses pre-rendered strings from the journal.
        """
        if not self.printer:
            self.connect_printer()
        if not self.printer:
            raise Exception("Printer not connected")

        p = self.printer
        try:
            self._set_reverse_print_mode(True)
            bar = self._bar("=")
            p.set(align='center', bold=True)
            p.text("\n")
            p.text(bar + "\n")
            p.text("** RECOVERY VVPAT **\n")
            p.text(bar + "\n\n")
            p.set(align='left', bold=False)
            p.text(f"Election : {election_name}\n")
            p.text(f"Choice   : {vvpat_choice_str}\n")
            if original_timestamp:
                try:
                    import datetime as _dt
                    ts = _dt.datetime.fromisoformat(original_timestamp).strftime("%d-%m-%Y %H:%M:%S")
                except Exception:
                    ts = original_timestamp
                p.text(f"Vote Time: {ts}\n")
            p.text(f"Printed  : {datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')}\n")
            p.text("\n")
            p.set(align='center', bold=True)
            p.text("** OFFICER VERIFIED REPRINT **\n")
            p.text(bar + "\n")
            p.set(bold=False)
            p.text("\n\n\n\n")
            p.cut(mode='FULL')
            try:
                time.sleep(0.5)
                p.text("\n" * 6)
            except Exception:
                pass
        except Exception as e:
            try:
                if self.printer:
                    self.printer.close()
            except Exception:
                pass
            self.printer = None
            raise e
        finally:
            self._set_reverse_print_mode(False)

    def _generate_vvpat_qr(self, choice_data, ballot_id):
        try:
            qr_c = qrcode.make(choice_data)
            qr_b = qrcode.make(ballot_id)
            qr_size = 140
            qr_c = qr_c.resize((qr_size, qr_size))
            qr_b = qr_b.resize((qr_size, qr_size))
            
            total_width = self.paper_width_dots
            height = qr_size
            
            img = Image.new('RGB', (total_width, height), 'white')
            
            x_c = 30
            x_b = 214
            # Paste both QRs side by side without text labels
            img.paste(qr_c, (x_c, 0))
            img.paste(qr_b, (x_b, 0))
            if self.reverse_print:
                img = img.rotate(180)
            
            temp_filename = f"temp_qr_vvpat_{uuid.uuid4().hex}.png"
            img.save(temp_filename)
            return temp_filename
        except Exception as e:
            print(f"QR Gen Error: {e}")
            raise e

    def _generate_voter_qr(self, hash_val):
        try:
            qr_h = qrcode.make(hash_val)
            qr_size = 250 
            qr_h = qr_h.resize((qr_size, qr_size))
            
            total_width = self.paper_width_dots
            height = qr_size + 10
            
            img_v = Image.new('RGB', (total_width, height), 'white')
            x_pos = (total_width - qr_size) // 2
            img_v.paste(qr_h, (x_pos, 5))
            if self.reverse_print:
                img_v = img_v.rotate(180)
            
            temp_filename = f"temp_qr_voter_{uuid.uuid4().hex}.png"
            img_v.save(temp_filename)
            return temp_filename
        except Exception as e:
            print(f"Voter QR Error: {e}")
            raise e

    def _generate_provision_qr(self, payload_text):
        """Generate a printer-friendly QR image for provisioning payloads.

        This mirrors the VVPAT image path: render QR -> convert to RGB canvas
        sized to printer width -> print with p.image(...).
        """
        try:
            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=8,
                border=2,
            )
            qr.add_data(payload_text)
            qr.make(fit=True)

            qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

            max_qr_size = min(self.paper_width_dots - 40, 360)
            qr_img.thumbnail((max_qr_size, max_qr_size), Image.Resampling.NEAREST)

            canvas_h = qr_img.height + 10
            canvas = Image.new("RGB", (self.paper_width_dots, canvas_h), "white")
            x_pos = (self.paper_width_dots - qr_img.width) // 2
            canvas.paste(qr_img, (x_pos, 5))

            if self.reverse_print:
                canvas = canvas.rotate(180)

            temp_filename = f"temp_qr_provision_{uuid.uuid4().hex}.png"
            canvas.save(temp_filename)
            return temp_filename
        except Exception as e:
            print(f"Provision QR Error: {e}")
            raise e

    def print_provisioning_ticket(self, bmd_id, public_key_pem, machine_id="UNKNOWN"):
        """Print a provisioning ticket with QR payload containing BMD ID and public key."""
        if not self.is_printer_connected():
            raise Exception("Printer not connected")

        try:
            p = self.printer
            TOP_BAR = self._bar("=")
            timestamp = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")

            if machine_id and "OTP_" in str(machine_id):
                hw_label = "OTP (clone-resistant)"
            elif machine_id and "CPUSERIAL_" in str(machine_id):
                hw_label = "CPU Serial (clone-resistant)"
            elif machine_id and "DMI_" in str(machine_id):
                hw_label = "DMI UUID (clone-resistant)"
            else:
                hw_label = "FALLBACK (not secure)"

            qr_payload = json.dumps(
                [{
                    "bmd_id": int(bmd_id) if str(bmd_id).isdigit() else str(bmd_id),
                    "rsa_public_key_pem": public_key_pem.strip() + "\n",
                    "is_active": True,
                }],
                separators=(",", ":")
            )

            self._set_reverse_print_mode(True)

            p.text("SEND TO ELECTION ADMIN\n")
            p.text(TOP_BAR + "\n")
            p.text("BMD PROVISIONING RECEIPT\n")
            p.text(TOP_BAR + "\n")

            p.set(align='left', bold=False)
            p.text(f"Date/Time  : {timestamp}\n")
            p.text(f"BMD ID     : {bmd_id}\n")
            p.text(f"HW Binding : {hw_label}\n\n")

            p.set(align='left', bold=True)
            p.text("QR: BMD ID + FULL PUBLIC KEY\n")
            p.set(align='left', bold=False)

            temp_qr = self._generate_provision_qr(qr_payload)
            p.set(align='left')
            p.image(temp_qr)
            if os.path.exists(temp_qr):
                os.remove(temp_qr)

            p.text("\n")
            p.set(align='left', bold=True)
            p.text("PUBLIC KEY (PEM):\n")
            p.set(align='left', bold=False)
            for line in public_key_pem.strip().splitlines():
                p.text(f"{line}\n")

            p.text("\n" + TOP_BAR + "\n")
            p.text("KEEP THIS SLIP FOR SETUP\n")
            p.text(TOP_BAR + "\n")
            p.set(align='left', font='a', width=1, height=1, bold=True)
            p.text("\n" * 2)
            import time
            time.sleep(3)  # let print buffer drain before cut
            p.cut(mode='FULL')
            # Best-effort post-cut feed so the slip fully exits the mechanism.
            # Errors here are silently ignored — the cut already succeeded.
            try:
                time.sleep(0.5)
                p.text("\n" * 12)
            except Exception:
                pass
            return True
        except Exception as e:
            try:
                if self.printer:
                    self.printer.close()
            except Exception:
                pass
            if 'Input/' in str(e) or 'Errno 5' in str(e) or 'Device or resource busy' in str(e):
                self._force_pyusb = True
                print('Forcing PyUSB reconnect on next print...\n')
            self.printer = None
            raise Exception(f"Failed to print provisioning ticket: {e}")
        finally:
            self._set_reverse_print_mode(False)

    def print_session_receipts(self, receipts_list, stage="both"):
        """Prints a consolidated VVPAT strip and cuts it for the box."""
        if not self.printer:
            self.connect_printer()
        if not self.printer:
            raise Exception("Printer not connected")
            
        p = self.printer
        TOP_BAR = self._bar("=")
        DIVIDER = self._bar("-")
        
        try:
            self._set_reverse_print_mode(True)

            if stage in ("both", "vvpat", "receipt"):
                p.text("\n")

                for i, r in enumerate(reversed(receipts_list)):
                    idx = len(receipts_list) - i
                    p.text(DIVIDER + "\n")

                    qr_data = r['qr_choice_data']
                    short_b_id = self.data_handler.get_short_ballot_id(r['ballot_id'])
                    temp_qr = self._generate_vvpat_qr(qr_data, short_b_id)

                    p.set(align='left')
                    p.image(temp_qr)
                    if os.path.exists(temp_qr):
                        os.remove(temp_qr)

                    p.set(align='left', bold=False)
                    p.set(align='left', bold=True)
                    p.text(f"Choice: {r.get('vvpat_choice_str', r['choice_str'])}\n")
                    p.set(align='left', bold=False)
                    p.text(f"#{idx}: {r.get('election_id', '???')}\n")

                p.text(TOP_BAR + "\n\n")
                p.text(self._center_line("(Internal Audit Trail)") + "\n")
                p.text(self._center_line("CONSOLIDATED VVPAT SLIPS") + "\n")
                p.text(TOP_BAR + "\n")
                p.set(align='left', font='a', width=1, height=1, bold=True)

                p.text("\n" * 2)
                time.sleep(5)
                p.cut(mode='FULL')
                p.text("\n" * 12) # Extra feed after cut

                return {"stage": "vvpat_complete"}

            return True
            
        except Exception as e:
            print(f"Batch Print Error: {e}")
            try:
                if self.printer:
                    self.printer.close()
            except Exception:
                pass
            if 'Input/' in str(e) or 'Errno 5' in str(e) or 'Device or resource busy' in str(e):
                self._force_pyusb = True
                print('Forcing PyUSB reconnect on next print...\n')
            self.printer = None
            raise e
        finally:
            self._set_reverse_print_mode(False)

    def _get_font(self, size):
        font_candidates = [
            "arial.ttf", 
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
        ]
        for fpath in font_candidates:
            try:
                return ImageFont.truetype(fpath, size)
            except IOError:
                continue
        return ImageFont.load_default()

    def print_startup_ticket(self, genesis_hash, log_dir):
        """Prints a physical ticket with the generated Genesis block and EVM details."""
        import datetime
        try:
            import hardware_crypto
            mac_addr = hardware_crypto.get_mac_address()
        except:
            mac_addr = "UNKNOWN"
            
        try:
            p = self.printer
            TOP_BAR = self._bar("=")
            self._set_reverse_print_mode(True)
            
            # Send in reverse order due to 180° rotation
            p.text("Keep this slip for auditing.\n")
            p.text("ELECTION READY\n")
            p.text(TOP_BAR + "\n")
            p.set(align='left')
            
            # Print QR code of genesis hash
            try:
                if genesis_hash:
                    temp_img = self._generate_voter_qr(genesis_hash)
                    p.set(align='left')
                    p.image(temp_img)
                    if os.path.exists(temp_img):
                        os.remove(temp_img)
            except Exception as e:
                p.text(f"QR Error: {e}\n")
            
            # Print the hash in chunks so it fits nicely
            if genesis_hash:
                p.text(f"{genesis_hash[32:]}\n")
                p.text(f"{genesis_hash[:32]}\n")

            p.set(align='left', bold=False)
            p.text("GENESIS SEED (RECORD THIS):\n")
            p.set(align='left', bold=True)
            
            p.text(f"Log Volume : {log_dir}\n")
            p.text(f"Device MAC : {mac_addr}\n")
            p.text(f"Votes Cast : {self._count_votes_cast(log_dir)}\n")
            p.text(f"Wifi Status : {self._get_wifi_status()}\n")
            p.text(f"SSH Status : {self._get_ssh_status()}\n")
            p.text(f"Bluetooth Status : {self._get_bluetooth_status()}\n")
            p.set(align='left', bold=False)
            
            p.text(TOP_BAR + "\n")
            p.text(self._center_line(datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")) + "\n")
            p.text(self._center_line("GENESIS BLOCK CREATED") + "\n")
            p.text(self._center_line("EVM STARTUP PROTOCOL") + "\n")
            p.text(TOP_BAR + "\n")
            p.set(align='left', font='a', width=1, height=1, bold=True)
            
            p.cut(mode='FULL')
            p.text("\n" * 12) # Extra feed after cut
        except Exception as e:
            print(f"Failed to print startup ticket: {e}")
        finally:
            self._set_reverse_print_mode(False)

    def print_end_election_ticket(self, final_hash, export_path):
        """Prints a physical ticket confirming the election has ended and showing the final hash.

        Returns True on success, raises Exception on printer/connectivity errors.
        """
        import datetime
        try:
            import hardware_crypto
            mac_addr = hardware_crypto.get_mac_address()
        except:
            mac_addr = "UNKNOWN"

        # Ensure we have an active printer handle before attempting to print.
        if not self.is_printer_connected():
            raise Exception("Printer not connected")
            
        try:
            p = self.printer
            TOP_BAR = self._bar("=")
            self._set_reverse_print_mode(True)
            
            # Send in reverse order due to 180° rotation
            p.text("Submit this slip with USB.\n")
            p.text("SAFE TO POWER OFF\n")
            p.text(TOP_BAR + "\n")
            p.set(align='left')
            
            # Print QR code of final hash
            try:
                if final_hash:
                    temp_img = self._generate_voter_qr(final_hash)
                    p.set(align='left')
                    p.image(temp_img)
                    if os.path.exists(temp_img):
                        os.remove(temp_img)
            except Exception as e:
                p.text(f"QR Error: {e}\n")
            
            # Print the hash in chunks
            if final_hash:
                p.text(f"{final_hash[32:]}\n")
                p.text(f"{final_hash[:32]}\n")

            p.set(align='left', bold=False)
            p.text("FINAL SEED (RECORD THIS):\n")
            p.set(align='left', bold=True)
            
            p.text(f"Export Dir : {export_path}\n")
            p.text(f"Device MAC : {mac_addr}\n")
            p.set(align='left', bold=False)
            
            p.text(TOP_BAR + "\n")
            p.text(self._center_line(datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")) + "\n")
            p.text(self._center_line("FINAL BLOCK SEALED") + "\n")
            p.text(self._center_line("ELECTION TERMINATED") + "\n")
            p.text(TOP_BAR + "\n")
            p.set(align='left', font='a', width=1, height=1, bold=True)
            
            p.cut(mode='FULL')
            p.text("\n" * 12) # Extra feed after cut
            return True
        except Exception as e:
            try:
                if self.printer:
                    self.printer.close()
            except Exception:
                pass
            if 'Input/' in str(e) or 'Errno 5' in str(e) or 'Device or resource busy' in str(e):
                self._force_pyusb = True
                print('Forcing PyUSB reconnect on next print...\n')
            self.printer = None
            raise Exception(f"Failed to print end election ticket: {e}")
        finally:
            self._set_reverse_print_mode(False)

    def print_challenge_receipt(self, ballot_id, sel_str, voter_qr_data):
        """Prints a CHALLENGE receipt (voter copy only, no VVPAT).

        Includes the ballot ID so the voter can later verify the cryptographic
        commitment is correct.  The ballot is NOT counted as a cast vote.
        Returns True on success, raises Exception on error.
        """
        if not self.is_printer_connected():
            raise Exception("Printer not connected")

        import datetime
        try:
            p = self.printer
            TOP_BAR = self._bar("=")
            timestamp = datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")
            self._set_reverse_print_mode(True)

            # Send in reverse order due to 180° rotation
            p.text("vote was NOT counted.\n")
            p.text("Keep this slip to verify your\n")
            p.text("This ballot was CHALLENGED.\n")
            p.text(TOP_BAR + "\n")
            
            # QR of voter commitments
            temp_img = self._generate_voter_qr(voter_qr_data)
            p.set(align='left')
            p.image(temp_img)
            if os.path.exists(temp_img):
                os.remove(temp_img)

            p.set(align='left', bold=False)
            p.set(align='left', bold=True)
            p.text(f"Choice    : {sel_str}\n")
            p.set(align='left', bold=False)
            short_b_id = self.data_handler.get_short_ballot_id(ballot_id)
            p.set(align='left')
            p.text(f"Ballot ID : {short_b_id}\n")

            p.text(TOP_BAR + "\n")
            p.text(self._center_line(timestamp) + "\n")
            p.set(align='left', bold=False)
            p.text(self._center_line("  (NOT A CAST VOTE)  ") + "\n")
            p.text(self._center_line("** CHALLENGE RECEIPT **") + "\n")
            p.text(TOP_BAR + "\n")
            p.set(align='left', font='a', width=1, height=1, bold=True)
            
            p.cut(mode='FULL')
            p.text("\n" * 12) # Extra feed after cut
            return True
        except Exception as e:
            try:
                if self.printer:
                    self.printer.close()
            except Exception:
                pass
            if 'Input/' in str(e) or 'Errno 5' in str(e) or 'Device or resource busy' in str(e):
                self._force_pyusb = True
                print('Forcing PyUSB reconnect on next print...\n')
            self.printer = None
            raise Exception(f"Failed to print challenge receipt: {e}")
        finally:
            self._set_reverse_print_mode(False)
