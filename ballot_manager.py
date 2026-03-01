import json
import os
import pymongo

class BallotManager:
    def __init__(self, usb_mount_point="/media/pi/USB"):
        self.usb_mount_point = usb_mount_point
        
        try:
             self.client = pymongo.MongoClient("mongodb://localhost:27017/")
             self.db = self.client["evoting_db"]
             self.collection = self.db["ballots"]
             print("Connected to MongoDB.")
        except Exception as e:
             print(f"Failed to connect to MongoDB: {e}")
             self.collection = None

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
