import os
import uuid
import datetime
import qrcode
from PIL import Image, ImageDraw, ImageFont

try:
    from escpos.printer import Usb, File
except ImportError:
    print("Warning: python-escpos not installed. Printing will fail silently or log errors.")
    Usb = None
    File = None

class PrinterService:
    def __init__(self, data_handler):
        self.data_handler = data_handler
        self.printer = None
        self.connect_printer()

    def connect_printer(self):
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
                
        # Fallback to File class (/dev/usb/lpX)
        if File:
            connected = False
            for port_num in range(6):
                port_path = f"/dev/usb/lp{port_num}"
                if os.path.exists(port_path):
                    try:
                        self.printer = File(port_path, profile="POS-80")
                        print(f"Printer connected successfully at {port_path} with POS-80 profile.")
                        connected = True
                        break
                    except Exception as e:
                        print(f"Printer Connection Failed on {port_path}: {e}")
            
            if not connected:
                 print("Printer device file /dev/usb/lp0 through lp5 not found or could not connect.")
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
        ballot_id = self.data_handler.ballot_id
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
            cand = self.data_handler.get_candidate_by_id(cid)
            cand_commitment = cand.get('commitment', '') if cand else ""
            qr_choice_data = f"{sel_str}:{cand_commitment}"
        else:
            ranks = sorted(selections.keys())
            vals = []
            for r in ranks:
                c = selections[r]
                vals.append(get_cand_display(c))
            sel_str = ", ".join(vals)
            
            # For preferential, include all commitments in order
            qr_parts = []
            for r in ranks:
                cand = self.data_handler.get_candidate_by_id(selections[r])
                c_disp = get_cand_display(selections[r])
                c_comm = cand.get('commitment', '') if cand else ""
                qr_parts.append(f"{c_disp}:{c_comm}")
            qr_choice_data = "_".join(qr_parts)

        p = self.printer
        TOP_BAR = "_" * 32
        BOTTOM_BAR = "_" * 32

        try:
            # ==========================================
            # RECEIPT 1: VVPAT (Internal / Box)
            # ==========================================
            p.set(align='center', font='a', width=1, height=1, bold=True)
            p.text(TOP_BAR + "\n")
            p.text("** VVPAT SLIP **\n")
            p.set(align='center', bold=False)
            p.text("\n") 

            p.set(align='left')
            p.text(f"Station: {station_id}\n") 
            p.text(f"Ballot : {ballot_id}\n")
            p.text(f"Session: {timestamp}\n")
            
            p.text("\n")
            p.set(align='left', bold=True)
            p.text(f"Choice : {sel_str}\n")
            p.set(align='left', bold=False)
            
            # Extract clean ballot ID for QR (take anything before first backslash)
            raw_ballot_id = str(ballot_id)
            short_b_id = raw_ballot_id.split('\\')[0] if '\\' in raw_ballot_id else raw_ballot_id.split('"')[0]
            
            # QR Generation
            temp_img = self._generate_vvpat_qr(qr_choice_data, short_b_id)
            
            p.text("\n") 
            p.set(align='center')
            p.image(temp_img)
            p.text("\n")
            if os.path.exists(temp_img):
                os.remove(temp_img)

            p.text(BOTTOM_BAR + "\n")
            p.text("\n\n\n\n\n\n") # Feed paper past the cutter blade (6 blank lines)
            p.cut()

            # ==========================================
            # RECEIPT 2: VOTER RECEIPT
            # ==========================================
            p.set(align='center', font='a', width=1, height=1, bold=True)
            p.text(TOP_BAR + "\n")
            p.text("** VOTER RECEIPT **\n")
            p.set(align='center', bold=False)
            p.text("\n")
            
            p.set(align='left')
            p.text(f"Session: {timestamp}\n")
            p.set(align='left', bold=True)
            p.text(f"Choice : {sel_str}\n")
            p.set(align='left', bold=False)

            # QR Generation
            election_hash = self.data_handler.election_hash or "UNKNOWN_HASH"
            raw_comm = getattr(self.data_handler, 'raw_commitments', '')
            
            # Combine the election hash and the raw commitments JSON string 
            # so the voter has cryptographically verifiable proof of what choices were offered
            voter_qr_data = raw_comm
            
            temp_img_v = self._generate_voter_qr(voter_qr_data)

            p.set(align='center')
            p.image(temp_img_v)
            p.text("\n")
            if os.path.exists(temp_img_v):
                 os.remove(temp_img_v)

            p.text(BOTTOM_BAR + "\n")
            p.text("Keep this receipt safe.\n")
            p.text("\n")
            
            if is_final:
                p.text("\n\n\n\n\n") # Feed paper past the cutter blade (5 blank lines)
                p.cut()
            else:
                p.text("\n\n\n\n_ _ _ _ NEXT ELECTION _ _ _ _\n\n\n")
            
            return True

        except Exception as e:
            # p.text(f"\nError: {e}\n") # Optional: print error on slip?
            raise e


    def _generate_vvpat_qr(self, choice_data, ballot_id):
        try:
            qr_c = qrcode.make(choice_data)
            qr_b = qrcode.make(ballot_id)
            qr_size = 140
            qr_c = qr_c.resize((qr_size, qr_size))
            qr_b = qr_b.resize((qr_size, qr_size))
            
            total_width = 384
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
            
            total_width = 384
            height = qr_size + 10
            
            img_v = Image.new('RGB', (total_width, height), 'white')
            x_pos = (total_width - qr_size) // 2
            img_v.paste(qr_h, (x_pos, 5))
            
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
        TOP_BAR = "=" * 32
        DIVIDER = "-" * 32
        
        try:
            # ==============================
            # PART 1: CONSOLIDATED VVPAT
            # ==============================
            p.set(align='center', font='a', width=1, height=1, bold=True)
            p.text(TOP_BAR + "\n")
            p.text("CONSOLIDATED VVPAT SLIPS\n")
            p.text("(Internal Audit Trail)\n")
            p.text(datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S") + "\n")
            p.text(TOP_BAR + "\n\n")
            
            p.set(align='left', bold=False)
            
            for i, r in enumerate(receipts_list):
                p.set(align='left', bold=True)
                p.text(f"#{i+1}: {r.get('election_id', '???')}\n")
                p.set(align='left', bold=False)
                p.text(f"Ballot: {r['ballot_id']}\n")
                p.set(align='left', bold=True)
                p.text(f"Choice: {r['choice_str']}\n")
                p.set(align='left', bold=False)
                
                # VVPAT Internal QR
                qr_data = r['qr_choice_data']
                
                raw_b_id = str(r['ballot_id'])
                short_b_id = raw_b_id.split('\\')[0] if '\\' in raw_b_id else raw_b_id.split('"')[0]
                
                temp_qr = self._generate_vvpat_qr(qr_data, short_b_id)
                
                p.set(align='center')
                p.image(temp_qr)
                if os.path.exists(temp_qr): os.remove(temp_qr)
                
                p.text(DIVIDER + "\n")
            
            p.text("\n\n\n\n\n\n") # Feed for VVPAT box
            p.cut()
            
            # ==============================
            # PART 2: CONSOLIDATED VOTER
            # ==============================
            p.set(align='center', font='a', width=1, height=1, bold=True)
            p.text(TOP_BAR + "\n")
            p.text("CONSOLIDATED VOTER RECEIPT\n")
            p.text("(For Voter)\n")
            p.text(datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S") + "\n")
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
                
                p.set(align='center')
                p.image(temp_qr_v)
                if os.path.exists(temp_qr_v): os.remove(temp_qr_v)
                
                p.text(DIVIDER + "\n")
            
            p.text("Keep Safe\n\n\n\n\n\n") # Feed past cutter blade
            p.cut()
            
        except Exception as e:
            print(f"Batch Print Error: {e}")
            raise e

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
