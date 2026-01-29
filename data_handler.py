import json
import csv
import os

class DataHandler:
    def __init__(self, candidates_file="candidates.json", log_file="votes.log"):
        self.candidates_file = candidates_file
        self.log_file = log_file
        self.election_id = ""
        self.election_hash = ""
        self.candidates_base = []

    def load_candidates(self):
        """Loads candidates from the JSON file and sorts them by serial_id."""
        self.candidates_base = []
        
        if not os.path.exists(self.candidates_file):
            raise FileNotFoundError(f"{self.candidates_file} not found!")

        try:
            with open(self.candidates_file, mode='r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Store election metadata
                self.election_id = data.get("election_id", "")
                self.election_hash = data.get("hash_string", "")
                
                candidates_data = data.get("candidates", [])
                if isinstance(candidates_data, dict):
                    candidates_list = candidates_data.values()
                else:
                    candidates_list = candidates_data

                for cand in candidates_list:
                    # Ensure properly typed dictionary
                    self.candidates_base.append({
                        "id": int(cand["serial_id"]),
                        "name": cand["candidate_name"],
                        "candidate_number": cand["candidate_number"],
                        "party": cand.get("candidate_party", "") # Keep flexible
                    })
            
            # SORT BY SERIAL_ID as requested
            self.candidates_base.sort(key=lambda x: x['id'])
            
            return self.candidates_base

        except Exception as e:
            raise Exception(f"Failed to load candidates: {e}")

    def get_candidate_by_id(self, cid):
        return next((c for c in self.candidates_base if c['id'] == cid), None)

    def save_vote(self, vote_data, voting_mode):
        """
        Appends the vote to the log file.
        vote_data is a dictionary: {rank: candidate_id}
        """
        try:
            timestamp = vote_data.get('timestamp') # Expecting timestamp to be passed or generated here? 
            # Ideally generated here if not passed, but let's assume passed for consistency or generate new.
            import datetime
            if not timestamp:
                timestamp = datetime.datetime.now().isoformat()
            
            selections = vote_data.get('selections', {})
            
            with open(self.log_file, "a", newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if voting_mode == 'normal':
                    cid = selections.get(1)
                    cand = self.get_candidate_by_id(cid)
                    if cand:
                        writer.writerow([timestamp, voting_mode, 1, cid, cand['name']])
                else:
                    for rank, cid in selections.items():
                        cand = self.get_candidate_by_id(cid)
                        if cand:
                            writer.writerow([timestamp, voting_mode, rank, cid, cand['name']])
            print("Vote saved to log.")
        except Exception as e:
            print(f"Error saving vote: {e}") 
            raise e
