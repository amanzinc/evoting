import json
import os
import random
import uuid
import shutil

import copy

class BallotManager:
    def __init__(self, tracking_file="ballots.json", template_file="candidates.json", ballots_dir="ballots"):
        # Legacy support
        self.tracking_file = tracking_file
        self.template_file = template_file
        self.ballots_dir = ballots_dir
        self.ballots = {} # Legacy cache
        
        # Multi-Election Root
        self.elections_root = "elections"
        
        if os.path.exists(tracking_file):
            self.load_ballots_legacy()

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
        Returns (ballot_id, absolute_path_to_json)
        """
        # Determine paths
        if election_id:
            base_path = os.path.join(self.elections_root, election_id)
            ballot_dir = os.path.join(base_path, "ballots")
            status_file = os.path.join(base_path, "ballots_status.json")
            
            if not os.path.exists(status_file):
                raise Exception(f"Election {election_id} not initialized!")
                
            with open(status_file, 'r') as f:
                usage_map = json.load(f)
        else:
            # Legacy
            ballot_dir = self.ballots_dir
            self.load_ballots_legacy()
            usage_map = self.ballots

        # Find Unused
        unused = [bid for bid, status in usage_map.items() if status == "UNUSED"]
        if not unused:
             raise Exception(f"No unused ballots for {election_id or 'General'}!")
             
        selected_id = random.choice(unused)
        selected_file = os.path.abspath(os.path.join(ballot_dir, f"{selected_id}.json"))
        
        if not os.path.exists(selected_file):
             # Self-healing attempt
             self.mark_as_used(selected_id, election_id)
             return self.get_unused_ballot(election_id)
             
        return selected_id, selected_file

    def mark_as_used(self, ballot_id, election_id=None):
        if election_id:
            base_path = os.path.join(self.elections_root, election_id)
            status_file = os.path.join(base_path, "ballots_status.json")
            
            if os.path.exists(status_file):
                with open(status_file, 'r') as f:
                    data = json.load(f)
                if ballot_id in data:
                    data[ballot_id] = "USED"
                    with open(status_file, 'w') as f:
                        json.dump(data, f, indent=4)
        else:
            # Legacy
            if ballot_id in self.ballots:
                self.ballots[ballot_id] = "USED"
                data = {"total_count": len(self.ballots), "ballots": self.ballots}
                with open(self.tracking_file + ".tmp", 'w') as f:
                    json.dump(data, f, indent=4)
                if os.path.exists(self.tracking_file): os.remove(self.tracking_file)
                os.rename(self.tracking_file + ".tmp", self.tracking_file)

if __name__ == "__main__":
    pass
