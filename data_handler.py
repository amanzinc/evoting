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

    def set_ballot_file(self, new_file):
        """Switches to a new ballot file and reloads candidates."""
        self.candidates_file = new_file
        self.load_candidates()

    def load_candidates(self):
        """Loads candidates from the specific ballot/candidate file."""
        self.candidates_base = []
        
        if not os.path.exists(self.candidates_file):
            raise FileNotFoundError(f"{self.candidates_file} not found!")

        try:
            with open(self.candidates_file, mode='r', encoding='utf-8') as f:
                data = json.load(f)
                
                self.election_id = data.get("election_id", "")
                self.election_name = data.get("election_name", "General Election")
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

    def is_token_used(self, token_id):
        """Checks if the token_id has already been logged."""
        if not os.path.exists("tokens.log"):
            return False
            
        try:
            with open("tokens.log", "r", encoding='utf-8') as f:
                for line in f:
                    # Format: Timestamp,TokenID
                    parts = line.strip().split(',')
                    if len(parts) >= 2:
                        logged_id = parts[1].strip()
                        if logged_id == str(token_id):
                            return True
            return False
        except Exception as e:
            print(f"Error checking token log: {e}")
            return False

    def log_token(self, token_payload):
        """Logs the authenticated token ID to tokens.log."""
        try:
            import datetime
            import json
            
            # Extract simple ID if possible
            token_id = token_payload
            try:
                data = json.loads(token_payload)
                if 'token_id' in data:
                    token_id = data['token_id']
            except:
                pass # Use full string if not JSON

            timestamp = datetime.datetime.now().isoformat()
            with open("tokens.log", "a", encoding='utf-8') as f:
                f.write(f"{timestamp},{token_id}\n")
            print(f"Token Logged: {token_id}")
        except Exception as e:
            print(f"Error logging token: {e}")

    def generate_vote_rows(self, vote_data, voting_mode):
        """Generates the CSV rows for a vote based on CURRENT context."""
        timestamp = vote_data.get('timestamp')
        import datetime
        if not timestamp:
            timestamp = datetime.datetime.now().isoformat()
        
        selections = vote_data.get('selections', {})
        rows = []
        
        if voting_mode == 'normal':
            cid = selections.get(1)
            cand = self.get_candidate_by_id(cid)
            if cand:
                rows.append([timestamp, voting_mode, 1, cid, cand['name']])
        else:
            for rank, cid in selections.items():
                cand = self.get_candidate_by_id(cid)
                if cand:
                    rows.append([timestamp, voting_mode, rank, cid, cand['name']])
        return rows

    def save_rows(self, rows):
        """Writes pre-generated rows to the log file."""
        try:
            with open(self.log_file, "a", newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerows(rows)
            print("Votes committed to log.")
        except Exception as e:
            print(f"Error saving rows: {e}")
            raise e

    def save_vote(self, vote_data, voting_mode):
        """Legacy convenience method."""
        rows = self.generate_vote_rows(vote_data, voting_mode)
        self.save_rows(rows)
