import json
import os
import sqlite3
import random

class BallotManager:
    def __init__(self, usb_mount_point=None, db_path="evoting_ballots.db"):
        self.usb_mount_point = self._find_usb_drive(usb_mount_point)
        self.db_path = db_path
        print(f"BallotManager using USB Path: {self.usb_mount_point}")
        
        self._init_db()

    def _init_db(self):
        """Initializes the SQLite database for tracking used ballots."""
        try:
             self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
             self.cursor = self.conn.cursor()
             self.cursor.execute('''
                 CREATE TABLE IF NOT EXISTS ballots (
                     ballot_id TEXT,
                     election_id TEXT,
                     status TEXT,
                     PRIMARY KEY (ballot_id, election_id)
                 )
             ''')
             self.conn.commit()
             print("Connected to SQLite Database.")
        except Exception as e:
             print(f"Failed to initialize SQLite Database: {e}")
             self.conn = None

    def _find_usb_drive(self, user_provided_path):
        """
        Attempts to find the USB drive automatically by looking for the 'ballot' folder
        (new encrypted ballot structure) in common Raspberry Pi / Linux mount points.
        """
        # 1. If the user explicitly provided a path that works, use it.
        if user_provided_path and os.path.exists(os.path.join(user_provided_path, "ballot")):
            return user_provided_path

        # 2. Check common mount directories where USBs appear
        user = os.environ.get("USER", "pi")
        search_dirs = [
            f"/media/{user}", # Raspberry Pi OS Desktop default auto-mount
            "/media",         # Older OS mounts
            "/mnt",           # Manual mounts
            os.path.dirname(os.path.abspath(__file__)) # Fallback to local project dir for testing
        ]

        for base_dir in search_dirs:
            if not os.path.isdir(base_dir):
                continue
                
            # Look at every folder immediately inside the base_dir
            for item in os.listdir(base_dir):
                potential_usb = os.path.join(base_dir, item)
                if os.path.isdir(potential_usb):
                    # Check for 'ballot' folder only
                    if os.path.isdir(os.path.join(potential_usb, "ballot")):
                        return potential_usb
                        
        # If we failed to find it dynamically, fallback to the hardcoded default so the error
        # messages still make sense later down the line.
        return "/media/pi/USB"

    def get_unused_ballot(self, election_id=None):
        """
        Returns (ballot_id, absolute_path_to_json) by reading from the local elections directory
        (after import from USB) and ensuring the ID is not marked as USED in SQLite.
        
        NOTE: All ballots must be previously imported from USB to local 'elections' directory.
        """
        if not election_id:
             raise Exception("Election ID Required to fetch ballots.")

        if self.conn is None:
             raise Exception("SQLite DB not connected! Cannot verify ballot usage.")

                # Look only in local elections directory (imported from USB).
                # Support both legacy token IDs (E1) and new folder IDs (election_id_1).
                ballots_dir, resolved_election_id = self._resolve_ballots_dir(election_id)
        
        if not os.path.exists(ballots_dir):
            raise Exception(f"Election folder not found at: {ballots_dir}")

        # Get all JSON files from local elections directory
        available_files = [
            f for f in os.listdir(ballots_dir) 
            if f.endswith('.json')
        ]
        if not available_files:
            raise Exception(f"No ballot files found in {ballots_dir}")

        # Fetch all USED ballot IDs for this election from SQLite
        self.cursor.execute("SELECT ballot_id FROM ballots WHERE election_id = ? AND status = 'USED'", (resolved_election_id,))
        used_ids = {row[0] for row in self.cursor.fetchall()}

        # Randomize the selection of available ballots
        random.shuffle(available_files)

        # Find the first available file that hasn't been used
        for file_name in available_files:
            # Strip .json extension
            ballot_id = file_name.replace('.json', '')
            
            if ballot_id not in used_ids:
                # Found an unused ballot!
                selected_file = os.path.join(ballots_dir, file_name)
                
                # Double check the file is actually readable before returning
                try:
                    with open(selected_file, 'rb') as f:
                        file_content = f.read()

                    # Verify it's valid JSON
                    json.loads(file_content.decode('utf-8'))
                    return ballot_id, selected_file
                    
                except Exception as e:
                    print(f"File {selected_file} is corrupt or unreadable: {e}. Skipping...")
                    # Mark it as 'CORRUPT' so we don't try it again
                    self.cursor.execute('''
                        INSERT OR REPLACE INTO ballots (ballot_id, election_id, status)
                        VALUES (?, ?, 'CORRUPT')
                    ''', (ballot_id, resolved_election_id))
                    self.conn.commit()
                    used_ids.add(ballot_id) # Skip in this loop

        raise Exception(f"No unused ballots remaining for {resolved_election_id}!")

    def _resolve_ballots_dir(self, election_id):
        """Resolve local ballots directory for either E1 or election_id_1 style IDs."""
        local_root = "elections"
        direct_dir = os.path.join(local_root, str(election_id), "ballots")
        if os.path.isdir(direct_dir):
            return direct_dir, str(election_id)

        # Legacy token format E<number> -> election_id_<number>
        eid = str(election_id)
        if eid.upper().startswith("E") and eid[1:].isdigit():
            mapped_id = f"election_id_{int(eid[1:])}"
            mapped_dir = os.path.join(local_root, mapped_id, "ballots")
            if os.path.isdir(mapped_dir):
                return mapped_dir, mapped_id

        # Reverse mapping if token already has election_id_<n> and local uses E<n>
        prefix = "election_id_"
        if eid.lower().startswith(prefix):
            suffix = eid[len(prefix):]
            if suffix.isdigit():
                mapped_id = f"E{int(suffix)}"
                mapped_dir = os.path.join(local_root, mapped_id, "ballots")
                if os.path.isdir(mapped_dir):
                    return mapped_dir, mapped_id

        # Keep old error shape for compatibility.
        return os.path.join(local_root, str(election_id), "ballots"), str(election_id)

    def mark_as_challenged(self, ballot_id, election_id=None):
        """
        Marks a ballot ID as CHALLENGED in SQLite.
        A challenged ballot cannot be cast or reused, but is not counted as a vote.
        """
        if self.conn is None:
            return
        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO ballots (ballot_id, election_id, status)
                VALUES (?, ?, 'CHALLENGED')
            ''', (ballot_id, election_id))
            self.conn.commit()
            print(f"Marked ballot {ballot_id} as CHALLENGED in DB.")
        except Exception as e:
            print(f"Error updating SQLite: {e}")

    def mark_as_used(self, ballot_id, election_id=None):
        """
        Marks a ballot ID as USED in SQLite so it cannot be drawn again from the USB.
        """
        if self.conn is None:
            return

        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO ballots (ballot_id, election_id, status)
                VALUES (?, ?, 'USED')
            ''', (ballot_id, election_id))
            self.conn.commit()
            print(f"Marked ballot {ballot_id} as USED in DB.")
        except Exception as e:
            print(f"Error updating SQLite: {e}")

if __name__ == "__main__":
    pass
