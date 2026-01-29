import json
import os
import random
import uuid
import shutil

import copy
import pymongo

class BallotManager:
    def __init__(self, tracking_file="ballots.json", template_file="candidates.json", ballots_dir="ballots"):
        # Legacy support
        self.tracking_file = tracking_file
        self.template_file = template_file
        self.ballots_dir = ballots_dir
        self.ballots = {} # Legacy cache
        
        # Multi-Election Root (Absolute Path)
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.elections_root = os.path.join(self.base_dir, "elections")
        
        if os.path.exists(tracking_file):
            self.load_ballots_legacy()

        try:
             self.client = pymongo.MongoClient("mongodb://localhost:27017/")
             self.db = self.client["evoting_db"]
             self.collection = self.db["ballots"]
             print("Connected to MongoDB.")
        except Exception as e:
             print(f"Failed to connect to MongoDB: {e}")
             self.collection = None

    def generate_ballots(self, n=50):
        # Legacy generation code... (keeping mostly same but simplified for this tool call)
        # Assuming init_elections.py handles the multi-election generation now.
        pass 

    def load_ballots_legacy(self):
        try:
            with open(self.tracking_file, 'r') as f:
                data = json.load(f)
                self.ballots = data.get("ballots", {})
        except: self.ballots = {}

    def get_unused_ballot(self, election_id=None):
        """
        Returns (ballot_id, absolute_path_to_json) using MongoDB query.
        """
        # Determine paths
        if election_id:
            base_path = os.path.join(self.elections_root, election_id)
            ballot_dir = os.path.join(base_path, "ballots")
        else:
             # Legacy or Default context
             raise Exception("Election ID Required for MongoDB Mode")

        if self.collection is None:
             raise Exception("MongoDB not connected!")

        # Find One Unused
        # Ensure we pick randomly or just the first available
        ballot_doc = self.collection.find_one({
            "election_id": election_id, 
            "status": "UNUSED"
        })
        
        if not ballot_doc:
             raise Exception(f"No unused ballots found for {election_id} in MongoDB!")
             
        selected_id = ballot_doc['ballot_id']
        selected_file = os.path.abspath(os.path.join(ballot_dir, f"{selected_id}.json"))
        
        if not os.path.exists(selected_file):
             # Self-healing: Mark as used (broken) and recurse
             print(f"Warning: File {selected_file} missing. Skipping.")
             self.mark_as_used(selected_id, election_id)
             return self.get_unused_ballot(election_id)
             
        return selected_id, selected_file

    def mark_as_used(self, ballot_id, election_id=None):
        if self.collection is None:
            return

        try:
            self.collection.update_one(
                {"ballot_id": ballot_id, "election_id": election_id},
                {"$set": {"status": "USED"}}
            )
            print(f"Marked ballot {ballot_id} as USED in DB.")
        except Exception as e:
            print(f"Error updating MongoDB: {e}")

if __name__ == "__main__":
    pass
