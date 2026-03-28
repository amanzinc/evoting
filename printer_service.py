import os
import uuid
import datetime
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
        if File and configured_device_path and os.path.exists(configured_device_path):
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
            for vid, pid in [(0x0483, 0x5743), (0x0416, 0x5011), (0x04b8, 0x0202)]:
                dev = usb.core.find(idVendor=vid, idProduct=pid)
                if dev is not None and dev.is_kernel_driver_active(0):
                    dev.detach_kernel_driver(0)
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
                
        # Fallback to File class (/dev/usb/lpX or /dev/lpX)
        if File:
            connected = False
            device_candidates = []
            if configured_device_path:
                device_candidates.append(configured_device_path)

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

    def print_vote(self, mode, selections, is_final=True):
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

        # Mock Data Setup
        ballot_id = self.data_handler.get_short_ballot_id()
        station_id = "PS-105-DELHI"
        timestamp = datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")

        # Helper to find candidate display string
        def get_cand_display(cid):
            cand = self.data_handler.get_candidate_by_id(cid)
            if cand:
                return cand.get('candidate_number', str(cid))
            return str(cid)

        # Prepare strings
        if mode == 'normal':
            cid = selections.get(1)
            sel_str = get_cand_display(cid)
            qr_choice_data = self.data_handler.build_receipt_qr_payload(selections, mode)
        else:
            ranks = sorted(selections.keys())
            vals = []
            for r in ranks:
                c = selections[r]
                vals.append(get_cand_display(c))
            sel_str = ", ".join(vals)
            qr_choice_data = self.data_handler.build_receipt_qr_payload(selections, mode)

        p = self.printer
        TOP_BAR = self._bar("_")
        BOTTOM_BAR = self._bar("_")

        try:
            self._set_reverse_print_mode(True)

            # ==========================================
            # RECEIPT 1: VVPAT (Internal / Box)
            # ==========================================
            p.set(align='left', font='a', width=1, height=1, bold=True)
            p.text(TOP_BAR + "\n")
            p.text(self._center_line("** VVPAT SLIP **") + "\n")
            p.set(align='left', bold=False)
            p.text("\n") 

            p.set(align='left')
            p.text(f"Station: {station_id}\n") 
            p.text(f"Ballot : {ballot_id}\n")
            p.text(f"Session: {timestamp}\n")
            
            p.text("\n")
            p.set(align='left', bold=True)
            p.text(f"Choice : {sel_str}\n")
            p.set(align='left', bold=False)
            
            # Ballot ID for QR is truncated to part before first comma.
            short_b_id = self.data_handler.get_short_ballot_id(ballot_id)
            
            # QR Generation
            temp_img = self._generate_vvpat_qr(qr_choice_data, short_b_id)
            
            p.text("\n") 
            p.set(align='left')
            p.image(temp_img)
            p.text("\n")
            if os.path.exists(temp_img):
                os.remove(temp_img)

            p.text(BOTTOM_BAR + "\n")
            p.text("\n") # Minimal feed before first cut to avoid large blank gap
            p.cut(mode='FULL')

            # ==========================================
            # RECEIPT 2: VOTER RECEIPT
            # ==========================================
            p.set(align='left', font='a', width=1, height=1, bold=True)
            p.text(TOP_BAR + "\n")
            p.text(self._center_line("** VOTER RECEIPT **") + "\n")
            p.set(align='left', bold=False)
            p.text("\n")
            
            p.set(align='left')
            p.text(f"Session: {timestamp}\n")
            p.set(align='left', bold=True)
            p.text(f"Choice : {sel_str}\n")
            p.set(align='left', bold=False)

            # QR Generation
            # Voter receipt QR should contain only selected commitment.
            voter_qr_data = qr_choice_data
            
            temp_img_v = self._generate_voter_qr(voter_qr_data)

            p.set(align='left')
            p.image(temp_img_v)
            p.text("\n")
            if os.path.exists(temp_img_v):
                 os.remove(temp_img_v)

            p.text(BOTTOM_BAR + "\n")
            p.text("Keep this receipt safe.\n")
            p.text("\n")
            
            if is_final:
                p.text("\n") # Minimal feed before second cut
                p.cut(mode='FULL')
                p.text("\n\n\n\n\n") # Larger post-cut feed so the paper drops cleanly
            else:
                p.text("\n\n\n\n_ _ _ _ NEXT ELECTION _ _ _ _\n\n\n")
            
            return True

        except Exception as e:
            try:
                if self.printer:
                    self.printer.close()
            except:
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
            title_height = 30 
            height = qr_size + title_height
            
            img = Image.new('RGB', (total_width, height), 'white')
            draw = ImageDraw.Draw(img)
            
            font = self._get_font(22)

            x_c = 30
            x_b = 214
            # Heuristic centering for titles, or just offset
            draw.text((x_c + 20, 0), "Choice", font=font, fill="black")
            draw.text((x_b + 5, 0), "Ballot ID", font=font, fill="black")
            img.paste(qr_c, (x_c, title_height))
            img.paste(qr_b, (x_b, title_height))
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

    def print_session_receipts(self, receipts_list):
        """
        Prints two consolidated strips:
        1. VVPAT SLIPS (All votes) -> CUT (Falls in box)
        2. VOTER RECEIPTS (All votes) -> CUT (For user)
        """
        if not self.printer:
            self.connect_printer()
        if not self.printer:
            return # Fail silently or log
            
        p = self.printer
        TOP_BAR = self._bar("=")
        DIVIDER = self._bar("-")
        
        try:
            self._set_reverse_print_mode(True)

            # ==============================
            # PART 1: CONSOLIDATED VVPAT
            # ==============================
            p.set(align='left', font='a', width=1, height=1, bold=True)
            p.text(TOP_BAR + "\n")
            p.text(self._center_line("CONSOLIDATED VVPAT SLIPS") + "\n")
            p.text(self._center_line("(Internal Audit Trail)") + "\n")
            p.text(self._center_line(datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")) + "\n")
            p.text(TOP_BAR + "\n\n")
            
            p.set(align='left', bold=False)
            
            for i, r in enumerate(receipts_list):
                p.set(align='left', bold=True)
                p.text(f"#{i+1}: {r.get('election_id', '???')}\n")
                p.set(align='left', bold=False)
                short_b_id = self.data_handler.get_short_ballot_id(r['ballot_id'])
                p.text(f"Ballot: {short_b_id}\n")
                p.set(align='left', bold=True)
                p.text(f"Choice: {r['choice_str']}\n")
                p.set(align='left', bold=False)
                
                # VVPAT Internal QR
                qr_data = r['qr_choice_data']
                
                short_b_id = self.data_handler.get_short_ballot_id(r['ballot_id'])
                
                temp_qr = self._generate_vvpat_qr(qr_data, short_b_id)
                
                p.set(align='left')
                p.image(temp_qr)
                if os.path.exists(temp_qr): os.remove(temp_qr)
                
                p.text(DIVIDER + "\n")
            
            p.text("\n\n\n\n\n\n") # Feed for VVPAT box
            p.cut(mode='FULL')
            
            # ==============================
            # PART 2: CONSOLIDATED VOTER
            # ==============================
            p.set(align='left', font='a', width=1, height=1, bold=True)
            p.text(TOP_BAR + "\n")
            p.text(self._center_line("CONSOLIDATED VOTER RECEIPT") + "\n")
            p.text(self._center_line("(For Voter)") + "\n")
            p.text(self._center_line(datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")) + "\n")
            p.text(TOP_BAR + "\n\n")
            
            p.set(align='left', bold=False)
            
            for i, r in enumerate(receipts_list):
                p.set(align='left', bold=True)
                p.text(f"#{i+1}: {r.get('election_id', '???')}\n")
                p.set(align='left', bold=False)
                p.text(f"Choice: {r['choice_str']}\n")
                
                # Voter Hash QR
                qr_data_v = r.get('voter_qr_data', r.get('election_hash', 'N/A'))
                temp_qr_v = self._generate_voter_qr(qr_data_v)
                
                p.set(align='left')
                p.image(temp_qr_v)
                if os.path.exists(temp_qr_v): os.remove(temp_qr_v)
                
                p.text(DIVIDER + "\n")
            
            p.text("Keep Safe\n\n\n\n\n\n") # Feed past cutter blade
            p.cut(mode='FULL')
            
        except Exception as e:
            print(f"Batch Print Error: {e}")
            try:
                if self.printer:
                    self.printer.close()
            except:
                pass
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
            
            p.set(align='left', font='a', width=1, height=1, bold=True)
            p.text(TOP_BAR + "\n")
            p.text(self._center_line("EVM STARTUP PROTOCOL") + "\n")
            p.text(self._center_line("GENESIS BLOCK CREATED") + "\n")
            p.text(self._center_line(datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")) + "\n")
            p.text(TOP_BAR + "\n\n")
            
            p.set(align='left', bold=False)
            p.text(f"Device MAC : {mac_addr}\n")
            p.text(f"Log Volume : {log_dir}\n\n")
            
            p.set(align='left', bold=True)
            p.text("GENESIS SEED (RECORD THIS):\n")
            p.set(align='left', bold=False)
            
            # Print the hash in chunks so it fits nicely
            if genesis_hash:
                p.text(f"{genesis_hash[:32]}\n")
                p.text(f"{genesis_hash[32:]}\n\n")
            
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
            
            p.set(align='left')
            p.text("\n")
            p.text(TOP_BAR + "\n")
            p.text("ELECTION READY\n")
            p.text("Keep this slip for auditing.\n\n\n\n\n\n")
            p.cut(mode='FULL')
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
            
            p.set(align='left', font='a', width=1, height=1, bold=True)
            p.text(TOP_BAR + "\n")
            p.text(self._center_line("ELECTION TERMINATED") + "\n")
            p.text(self._center_line("FINAL BLOCK SEALED") + "\n")
            p.text(self._center_line(datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")) + "\n")
            p.text(TOP_BAR + "\n\n")
            
            p.set(align='left', bold=False)
            p.text(f"Device MAC : {mac_addr}\n")
            p.text(f"Export Dir : {export_path}\n\n")
            
            p.set(align='left', bold=True)
            p.text("FINAL SEED (RECORD THIS):\n")
            p.set(align='left', bold=False)
            
            # Print the hash in chunks
            if final_hash:
                p.text(f"{final_hash[:32]}\n")
                p.text(f"{final_hash[32:]}\n\n")
            
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
            
            p.set(align='left')
            p.text("\n")
            p.text(TOP_BAR + "\n")
            p.text("SAFE TO POWER OFF\n")
            p.text("Submit this slip with USB.\n\n\n\n\n\n")
            p.cut(mode='FULL')
            return True
        except Exception as e:
            try:
                if self.printer:
                    self.printer.close()
            except Exception:
                pass
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

            p.set(align='left', font='a', width=1, height=1, bold=True)
            p.text(TOP_BAR + "\n")
            p.text(self._center_line("** CHALLENGE RECEIPT **") + "\n")
            p.text(self._center_line("  (NOT A CAST VOTE)  ") + "\n")
            p.set(align='left', bold=False)
            p.text(self._center_line(timestamp) + "\n")
            p.text(TOP_BAR + "\n\n")

            short_b_id = self.data_handler.get_short_ballot_id(ballot_id)
            p.set(align='left')
            p.text(f"Ballot ID : {short_b_id}\n")
            p.text("\n")
            p.set(align='left', bold=True)
            p.text(f"Choice    : {sel_str}\n")
            p.set(align='left', bold=False)
            p.text("\n")

            # QR of voter commitments
            temp_img = self._generate_voter_qr(voter_qr_data)
            p.set(align='left')
            p.image(temp_img)
            p.text("\n")
            if os.path.exists(temp_img):
                os.remove(temp_img)

            p.text(TOP_BAR + "\n")
            p.text("This ballot was CHALLENGED.\n")
            p.text("Keep this slip to verify your\n")
            p.text("vote was NOT counted.\n\n\n\n\n\n")
            p.cut(mode='FULL')
            return True
        except Exception as e:
            try:
                if self.printer:
                    self.printer.close()
            except Exception:
                pass
            self.printer = None
            raise Exception(f"Failed to print challenge receipt: {e}")
        finally:
            self._set_reverse_print_mode(False)
