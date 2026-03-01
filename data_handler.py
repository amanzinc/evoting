import json
import csv
import os

class DataHandler:
    def __init__(self, candidates_file, log_file="votes.json"):
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
            with open(self.candidates_file, mode='rb') as f:
                file_content = f.read()

            try:
                # Try parsing as plain JSON first
                data = json.loads(file_content.decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                # If plain JSON parsing fails, try to decrypt
                from cryptography.fernet import Fernet
                key_path = "secret.key"
                if not os.path.exists(key_path):
                    raise Exception(f"File appears encrypted but {key_path} not found!")
                with open(key_path, "rb") as kf:
                    key = kf.read().strip()
                f_crypto = Fernet(key)
                decrypted_bytes = f_crypto.decrypt(file_content)
                data = json.loads(decrypted_bytes.decode('utf-8'))
                
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

    def generate_vote_json(self, vote_data, voting_mode, voter_id="UNKNOWN_VOTER", booth_num=1):
        """Generates a JSON object matching the MongoDB schema."""
        import datetime
        timestamp = vote_data.get('timestamp', datetime.datetime.now().isoformat())
        
        selections = vote_data.get('selections', {})
        
        # Determine preference ID based on mode
        # If normal, pref_id is just the chosen candidate's serial ID.
        # If preferential, pre_id is a formatted string of choices.
        if voting_mode == 'normal':
            cid = selections.get(1)
            cand = self.get_candidate_by_id(cid)
            pref_id = str(cand['id']) if cand else ""
        else:
            # For preferential, we join the candidate IDs by rank
            ranks = sorted(selections.keys())
            pref_id = "_".join(str(self.get_candidate_by_id(selections[r])['id']) for r in ranks if self.get_candidate_by_id(selections[r]))
            
        # Commitment is not explicitly calculated here right now, we will use a placeholder
        # However, we can use the encrypted ballot hash string as the commitment
        commitment = self.election_hash # Using election hash as placeholder for ballot hash/commitment

        vote_record = {
            "election_id": self.election_id,
            "voter_id": voter_id,
            "booth_num": booth_num,
            "commitment": commitment,
            "pref_id": pref_id,
            "hash_value": self.election_hash, # Could be a hash of the vote itself, using election_hash for now
            "timestamp": timestamp
        }
        
        return vote_record

    def save_json(self, record):
        """Writes the JSON object as a new line in the log file (JSONL format)."""
        try:
            with open(self.log_file, "a", encoding='utf-8') as f:
                f.write(json.dumps(record) + "\n")
            print("Vote committed to JSON log.")
        except Exception as e:
            print(f"Error saving JSON: {e}")
            raise e

    def save_vote(self, vote_data, voting_mode, voter_id="UNKNOWN_VOTER", booth_num=1):
        """Saves the vote data as a JSON line."""
        record = self.generate_vote_json(vote_data, voting_mode, voter_id, booth_num)
        self.save_json(record)
