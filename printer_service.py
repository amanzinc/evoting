import os
import uuid
import datetime
import qrcode
from PIL import Image, ImageDraw, ImageFont

try:
    from escpos.printer import File
except ImportError:
    print("Warning: python-escpos not installed. Printing will fail silently or log errors.")
    File = None

class PrinterService:
    def __init__(self, data_handler):
        self.data_handler = data_handler
        self.printer = None
        self.connect_printer()

    def connect_printer(self):
        if File:
            # Try to connect
            if os.path.exists("/dev/usb/lp0"):
                try:
                    self.printer = File("/dev/usb/lp0", profile="TM-T88IV")
                    print("Printer connected successfully.")
                except Exception as e:
                    print(f"Printer Connection Failed: {e}")
                    self.printer = None
            else:
                 print("Printer device file /dev/usb/lp0 not found.")
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
            qr_choice_data = sel_str
        else:
            ranks = sorted(selections.keys())
            vals = []
            for r in ranks:
                c = selections[r]
                vals.append(get_cand_display(c))
            sel_str = ", ".join(vals)
            qr_choice_data = "_".join([get_cand_display(selections[r]) for r in ranks])

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
            
            # QR Generation
            temp_img = self._generate_vvpat_qr(qr_choice_data, ballot_id)
            
            p.text("\n") 
            p.set(align='center')
            p.image(temp_img)
            p.text("\n")
            if os.path.exists(temp_img):
                os.remove(temp_img)

            p.text(BOTTOM_BAR + "\n")
            p.text("\n- - - - - CUT HERE - - - - -\n\n")

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
            temp_img_v = self._generate_voter_qr(election_hash)

            p.set(align='center')
            p.image(temp_img_v)
            p.text("\n")
            if os.path.exists(temp_img_v):
                 os.remove(temp_img_v)

            p.text(BOTTOM_BAR + "\n")
            p.text("Keep this receipt safe.\n")
            p.text("\n")
            
            if is_final:
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
                p.text(f"#{i+1}: {r['election_name']}\n")
                p.set(align='left', bold=False)
                p.text(f"Ballot: {r['ballot_id']}\n")
                p.set(align='left', bold=True)
                p.text(f"Vote  : {r['choice_str']}\n")
                p.set(align='left', bold=False)
                
                # VVPAT Internal QR
                qr_data = r['qr_choice_data']
                temp_qr = self._generate_vvpat_qr(qr_data, r['ballot_id'])
                
                p.set(align='center')
                p.image(temp_qr)
                if os.path.exists(temp_qr): os.remove(temp_qr)
                
                p.text(DIVIDER + "\n")

            p.text("\n- - - - - CUT HERE - - - - -\n\n")
            p.cut() # Cut VVPAT strip
            
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
                p.text(f"#{i+1}: {r['election_name']}\n")
                p.set(align='left', bold=False)
                p.text(f"Choice : {r['choice_str']}\n")
                
                # Voter Hash QR
                # We can generate a combined hash or individual hashes?
                # Using individual for traceability.
                hash_val = r.get('election_hash', 'N/A')
                temp_qr_v = self._generate_voter_qr(hash_val)
                
                p.set(align='center')
                p.image(temp_qr_v)
                if os.path.exists(temp_qr_v): os.remove(temp_qr_v)
                
                p.text(DIVIDER + "\n")
            
            p.text("\nKeep this slip safe.\n")
            p.text("\n\n")
            p.cut() # Cut Voter Receipt strip
            
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
