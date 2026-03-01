import json
import os
import pymongo

class BallotManager:
    def __init__(self, usb_mount_point=None):
        self.usb_mount_point = self._find_usb_drive(usb_mount_point)
        print(f"BallotManager using USB Path: {self.usb_mount_point}")
        
        try:
             self.client = pymongo.MongoClient("mongodb://localhost:27017/")
             self.db = self.client["evoting_db"]
             self.collection = self.db["ballots"]
             print("Connected to MongoDB.")
        except Exception as e:
             print(f"Failed to connect to MongoDB: {e}")
             self.collection = None

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

        if self.collection is None:
             raise Exception("MongoDB not connected! Cannot verify ballot usage.")

        # Construct USB Path
        ballots_dir = os.path.join(self.usb_mount_point, "elections", election_id, "ballots")
        
        if not os.path.exists(ballots_dir):
            raise Exception(f"USB drive or election folder not found at: {ballots_dir}")

        # Get all JSON files from the USB drive
        available_files = [f for f in os.listdir(ballots_dir) if f.endswith('.json')]
        if not available_files:
            raise Exception(f"No ballot files found in {ballots_dir}")

        # Fetch all USED ballot IDs for this election from MongoDB
        used_ballots_cursor = self.collection.find({"election_id": election_id, "status": "USED"})
        used_ids = {doc["ballot_id"] for doc in used_ballots_cursor}

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
                    self.collection.update_one(
                        {"ballot_id": ballot_id, "election_id": election_id},
                        {"$set": {"status": "CORRUPT"}},
                        upsert=True
                    )
                    used_ids.add(ballot_id) # Skip in this loop

        raise Exception(f"No unused ballots remaining for {election_id} on the USB drive!")

    def mark_as_used(self, ballot_id, election_id=None):
        """
        Marks a ballot ID as USED in MongoDB so it cannot be drawn again from the USB.
        """
        if self.collection is None:
            return

        try:
            self.collection.update_one(
                {"ballot_id": ballot_id, "election_id": election_id},
                {"$set": {"status": "USED"}},
                upsert=True # Insert it if it's the first time we've seen it
            )
            print(f"Marked ballot {ballot_id} as USED in DB.")
        except Exception as e:
            print(f"Error updating MongoDB: {e}")

if __name__ == "__main__":
    pass
