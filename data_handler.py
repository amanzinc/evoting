import json
import csv
import os

class DataHandler:
    def __init__(self, candidates_file, log_file="votes.log"):
        # candidates_file is now the specific ballot file path
        self.candidates_file = candidates_file 
        self.log_file = log_file
        self.election_id = ""
        self.election_hash = ""
        self.ballot_id = "" # Store the specific ballot ID
        self.candidates_base = []

    def load_candidates(self):
        """Loads candidates from the specific ballot/candidate file."""
        self.candidates_base = []
        
        if not os.path.exists(self.candidates_file):
            raise FileNotFoundError(f"{self.candidates_file} not found!")

        try:
            with open(self.candidates_file, mode='r', encoding='utf-8') as f:
                data = json.load(f)
                
                self.election_id = data.get("election_id", "")
                self.election_hash = data.get("hash_string", "")
                self.ballot_id = data.get("ballot_id", "UNKNOWN")
                
                candidates_data = data.get("candidates", [])
                if isinstance(candidates_data, dict):
                    candidates_list = candidates_data.values()
                else:
                    candidates_list = candidates_data

                for cand in candidates_list:
                    self.candidates_base.append({
                        "id": int(cand["serial_id"]),
                        "name": cand["candidate_name"],
                        "candidate_number": cand["candidate_number"],
                        "party": cand.get("candidate_party", "")
                    })
            
            self.candidates_base.sort(key=lambda x: x['id'])
            return self.candidates_base

        except Exception as e:
            raise Exception(f"Failed to load candidates from {self.candidates_file}: {e}")

    def get_candidate_by_id(self, cid):
        return next((c for c in self.candidates_base if c['id'] == cid), None)

    def save_vote(self, vote_data, voting_mode):
        try:
            timestamp = vote_data.get('timestamp')
            import datetime
            if not timestamp:
                timestamp = datetime.datetime.now().isoformat()
            
            selections = vote_data.get('selections', {})
            
            # Include Ballot ID in log if desired, though not strictly in CSV format previously. 
            # Keeping CSV format same for compatibility, but we might want to log it.
            # writer.writerow([timestamp, voting_mode, rank, cid, cand['name'], self.ballot_id]) # Future enhancement
            
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
