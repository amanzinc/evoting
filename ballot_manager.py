import json
import os
import random
import uuid
import shutil

import copy

class BallotManager:
    def __init__(self, tracking_file="ballots.json", template_file="candidates.json", ballots_dir="ballots"):
        self.tracking_file = tracking_file
        self.template_file = template_file
        self.ballots_dir = ballots_dir
        self.ballots = {}
        
        if os.path.exists(tracking_file):
            self.load_ballots()

    def generate_ballots(self, n=50):
        """Generates N unique ballot IDs and creates individual JSON files."""
        current_ids = set()
        
        # Load Template
        if not os.path.exists(self.template_file):
             raise FileNotFoundError(f"Template {self.template_file} not found!")
        
        with open(self.template_file, 'r') as f:
            template_data = json.load(f)

        # Create Directory
        if not os.path.exists(self.ballots_dir):
            os.makedirs(self.ballots_dir)
        
        # Generate IDs
        while len(current_ids) < n:
            new_id = uuid.uuid4().hex[:8].upper()
            try:
                 # Check if this ID is physically already used if preserving (not doing complex sync for now)
                 pass 
            except: pass
            current_ids.add(new_id)

        # Create Files
        for bid in current_ids:
            ballot_data = copy.deepcopy(template_data)
            ballot_data['ballot_id'] = bid
            
            # --- SHUFFLE LOGIC ---
            # Shuffle ALL candidates, including NAFS.
            
            candidates_dict = ballot_data.get("candidates", {})
            cand_list = []
            if isinstance(candidates_dict, dict):
                cand_list = list(candidates_dict.values())
            else:
                cand_list = candidates_dict # List format
            
            # Collect available Serial IDs from ALL candidates
            available_ids = [c["serial_id"] for c in cand_list]
            random.shuffle(available_ids)
            
            # Re-assign Serial IDs
            for i, c in enumerate(cand_list):
                c["serial_id"] = available_ids[i]
                
            # ---------------------
            
            filepath = os.path.join(self.ballots_dir, f"{bid}.json")
            with open(filepath, 'w') as f:
                json.dump(ballot_data, f, indent=4)
            
        # Update Tracking File
        # We assume we are RESTARTING the pool. If appending, we'd need to load first.
        self.ballots = {bid: "UNUSED" for bid in current_ids}
        self.save_ballots()
        print(f"Generated {n} ballot files in '{self.ballots_dir}/' and updated tracking.")

    def load_ballots(self):
        try:
            with open(self.tracking_file, 'r') as f:
                data = json.load(f)
                self.ballots = data.get("ballots", {})
        except Exception as e:
            print(f"Error loading ballots: {e}")
            self.ballots = {}

    def save_ballots(self):
        data = {
            "total_count": len(self.ballots),
            "ballots": self.ballots
        }
        temp_file = self.tracking_file + ".tmp"
        with open(temp_file, 'w') as f:
            json.dump(data, f, indent=4)
        
        if os.path.exists(self.tracking_file):
            os.remove(self.tracking_file)
        os.rename(temp_file, self.tracking_file)

    def get_unused_ballot(self):
        """Randomly selects an unused ballot ID."""
        self.load_ballots()
        
        # FILTER: Only UNUSED
        unused = [bid for bid, status in self.ballots.items() if status == "UNUSED"]
        
        if not unused:
            raise Exception("No unused ballots remaining!")
            
        selected_id = random.choice(unused)
        selected_file = os.path.abspath(os.path.join(self.ballots_dir, f"{selected_id}.json"))
        
        if not os.path.exists(selected_file):
             # Consistency check
             print(f"Warning: File for {selected_id} missing. Marking USED and skipping.")
             self.mark_as_used(selected_id)
             return self.get_unused_ballot() # Recursive try

        return selected_id, selected_file

    def mark_as_used(self, ballot_id):
        if ballot_id not in self.ballots:
             print(f"Warning: Ballot {ballot_id} not in tracking.")
             return
             
        self.ballots[ballot_id] = "USED"
        self.save_ballots()
        print(f"Ballot {ballot_id} marked as USED.")

if __name__ == "__main__":
    bm = BallotManager()
    bm.generate_ballots(10)
