import json
import os
import sqlite3

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
        Attempts to find the USB drive automatically by looking for an 'elections' folder
        in common Raspberry Pi / Linux mount points.
        """
        # 1. If the user explicitly provided a path that works, use it.
        if user_provided_path and os.path.exists(os.path.join(user_provided_path, "elections")):
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
                    # Does this potential USB drive have an 'elections' folder?
                    if os.path.isdir(os.path.join(potential_usb, "elections")):
                        return potential_usb
                        
        # If we failed to find it dynamically, fallback to the hardcoded default so the error
        # messages still make sense later down the line.
        return "/media/pi/USB"

    def get_unused_ballot(self, election_id=None):
        """
        Returns (ballot_id, absolute_path_to_json) by reading from the USB drive
        and ensuring the ID is not marked as USED in MongoDB.
        """
        if not election_id:
             raise Exception("Election ID Required to fetch ballots.")

        if self.conn is None:
             raise Exception("SQLite DB not connected! Cannot verify ballot usage.")

        # Construct USB Path
        ballots_dir = os.path.join(self.usb_mount_point, "elections", election_id, "ballots")
        
        if not os.path.exists(ballots_dir):
            raise Exception(f"USB drive or election folder not found at: {ballots_dir}")

        # Get all JSON files from the USB drive
        available_files = [f for f in os.listdir(ballots_dir) if f.endswith('.json')]
        if not available_files:
            raise Exception(f"No ballot files found in {ballots_dir}")

        # Fetch all USED ballot IDs for this election from SQLite
        self.cursor.execute("SELECT ballot_id FROM ballots WHERE election_id = ? AND status = 'USED'", (election_id,))
        used_ids = {row[0] for row in self.cursor.fetchall()}

        # Find the first available file that hasn't been used
        for file_name in available_files:
            ballot_id = file_name.replace('.json', '')
            
            if ballot_id not in used_ids:
                # Found an unused ballot!
                selected_file = os.path.join(ballots_dir, file_name)
                
                # Double check the file is actually readable before returning
                try:
                    with open(selected_file, 'r') as f:
                        json.load(f)
                    return ballot_id, selected_file
                except Exception as e:
                    print(f"File {selected_file} is corrupt or unreadable: {e}. Skipping...")
                    # Mark it as 'CORRUPT' so we don't try it again
                    self.cursor.execute('''
                        INSERT OR REPLACE INTO ballots (ballot_id, election_id, status)
                        VALUES (?, ?, 'CORRUPT')
                    ''', (ballot_id, election_id))
                    self.conn.commit()
                    used_ids.add(ballot_id) # Skip in this loop

        raise Exception(f"No unused ballots remaining for {election_id} on the USB drive!")

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
