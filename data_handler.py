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
        self.ballot_id = "" # Store the specific generic complex payload ID
        self.ballot_file_id = "" # Store the filename for SQLite logic
        self.candidates_base = []

    def set_ballot_file(self, new_file):
        """Switches to a new ballot file and reloads candidates."""
        self.candidates_file = new_file
        self.ballot_file_id = os.path.basename(new_file).replace('.json', '')
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
                # If plain JSON parsing fails, try to decrypt with RSA Chunks
                from cryptography.hazmat.primitives.asymmetric import padding
                from cryptography.hazmat.primitives import hashes
                from cryptography.hazmat.primitives import serialization
                import hardware_crypto

                key_path = "private.pem"
                if not os.path.exists(key_path):
                    raise Exception(f"File appears encrypted but {key_path} not found!")

                # 1. Unlock Private Key using Hardware Identity
                try:
                    passphrase = hardware_crypto.get_hardware_passphrase()
                    with open(key_path, "rb") as kf:
                        private_key = serialization.load_pem_private_key(
                            kf.read(),
                            password=passphrase
                        )
                except Exception as e:
                    raise Exception(f"Hardware Identity mismatch or corrupt key! Could not unlock private.pem: {e}")

                # 2. Decrypt in Chunks (2048-bit RSA = 256 byte chunks)
                CHUNK_SIZE = 256
                decrypted_bytes = bytearray()
                
                for i in range(0, len(file_content), CHUNK_SIZE):
                    chunk = file_content[i:i+CHUNK_SIZE]
                    if len(chunk) < CHUNK_SIZE:
                         print(f"Warning: Encrypted chunk size {len(chunk)} is less than {CHUNK_SIZE}")
                    
                    decrypted_chunk = private_key.decrypt(
                        chunk,
                        padding.OAEP(
                            mgf=padding.MGF1(algorithm=hashes.SHA256()),
                            algorithm=hashes.SHA256(),
                            label=None
                        )
                    )
                    decrypted_bytes.extend(decrypted_chunk)
                    
                data = json.loads(decrypted_bytes.decode('utf-8'))
                
            self.election_id = str(data.get("election_id", ""))
            self.election_name = data.get("election_name", "General Election")
            
            # Parse commitments array
            raw_commitments = data.get("commitments", "")
            self.commitments_list = []
            if raw_commitments:
                try:
                    parsed_cmts = json.loads(raw_commitments)
                    if isinstance(parsed_cmts, list) and len(parsed_cmts) > 0:
                        self.commitments_list = parsed_cmts[0]
                except Exception as e:
                    print(f"Warning: could not parse commitments: {e}")

            self.ballot_id = data.get("ballot_id", "UNKNOWN")
            self.election_hash = str(self.ballot_id) # Fallback for VVPAT hash QR code

            candidates_data = data.get("candidates", [])
            if isinstance(candidates_data, dict):
                candidates_list = list(candidates_data.values())
            else:
                candidates_list = candidates_data

            for i, cand in enumerate(candidates_list):
                cand_commitment = self.commitments_list[i] if i < len(self.commitments_list) else ""
                
                # Support new "pref_id" & "entry_number" or fallback to old schema
                pref_id = cand.get("pref_id", cand.get("serial_id", i))
                entry_number = cand.get("entry_number", cand.get("candidate_number", ""))
                
                self.candidates_base.append({
                    "id": int(pref_id),
                    "name": cand.get("candidate_name", "Unknown"),
                    "candidate_number": entry_number,
                    "party": cand.get("candidate_party", ""),
                    "commitment": cand_commitment
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
        
        # Determine preference ID and commitment based on mode
        if voting_mode == 'normal':
            cid = selections.get(1)
            cand = self.get_candidate_by_id(cid)
            pref_id = str(cand['id']) if cand else ""
            commitment = cand['commitment'] if cand else ""
        else:
            # For preferential, we join the candidate IDs by rank
            ranks = sorted(selections.keys())
            pref_id = "_".join(str(self.get_candidate_by_id(selections[r])['id']) for r in ranks if self.get_candidate_by_id(selections[r]))
            commitment = "_".join(str(self.get_candidate_by_id(selections[r]).get('commitment', '')) for r in ranks if self.get_candidate_by_id(selections[r]))
            
        vote_record = {
            "election_id": self.election_id,
            "voter_id": voter_id,
            "booth_num": booth_num,
            "commitment": commitment,
            "pref_id": pref_id,
            "hash_value": str(self.ballot_id), # Ballot ID contains the proof needed
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
