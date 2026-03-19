import json
import csv
import os

class DataHandler:
    def __init__(self, candidates_file, log_file="votes.json", token_log_file="tokens.log"):
        # candidates_file is now the specific ballot file path
        self.candidates_file = candidates_file 
        self.log_file = log_file
        self.token_log_file = token_log_file
        self.election_id = ""
        self.election_hash = ""
        self.ballot_id = "" # Store the specific generic complex payload ID
        self.ballot_file_id = "" # Store the filename for SQLite logic
        self.candidates_base = []
        self.pref_combo_map = {}
        self.max_preferences = 1
        
        # Initialize cryptographic hash chain
        self.last_hash = None
        self.is_new_genesis = False
        self._initialize_hash_chain()

    def _initialize_hash_chain(self):
        """Reads the last known hash from votes.json, or generates a secure random genesis seed."""
        import os
        import json
        import secrets
        
        self.is_new_genesis = False
        
        if os.path.exists(self.log_file) and os.path.getsize(self.log_file) > 0:
            try:
                # Read the last line of the JSON file to get the previous hash
                with open(self.log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    if lines:
                        last_record = json.loads(lines[-1].strip())
                        self.last_hash = last_record.get("hash_value")
            except Exception as e:
                print(f"Warning: Failed to read existing hash chain from {self.log_file}: {e}")
                
        # If file didn't exist, was empty, or parsing failed, generate a Random Genesis Seed
        if not self.last_hash:
            self.last_hash = secrets.token_hex(32)
            self.is_new_genesis = True
            print(f"\n=======================================================")
            print(f"NEW ELECTION INSTANCE DETECTED - NO EXISTING VOTE LOG")
            print(f"GENESIS HASH SEED: {self.last_hash}")
            print(f"=======================================================\n")


    def set_ballot_file(self, new_file):
        """Switches to a new ballot file and reloads candidates."""
        self.candidates_file = new_file
        self.ballot_file_id = os.path.basename(new_file).replace('.json', '')
        self.load_candidates()

    def load_candidates(self):
        """Loads candidates from the specific ballot/candidate file."""
        self.candidates_base = []
        self.pref_combo_map = {}
        
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
            self.election_type = data.get("election_type", "Normal")
            self.election_name = data.get("election_name", "General Election")
            
            # Parse commitments array
            self.raw_commitments = data.get("commitments", "")
            self.commitments_list = []
            if self.raw_commitments:
                try:
                    parsed_cmts = json.loads(self.raw_commitments)
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

            # Detect special preferential layout where each row encodes a pair,
            # e.g., candidate_name="NAFS,David" and entry_number="012,E004".
            has_pair_layout = False
            if isinstance(candidates_list, list) and candidates_list:
                for cand in candidates_list:
                    raw_name = str(cand.get("candidate_name", ""))
                    raw_num = str(cand.get("entry_number", cand.get("candidate_number", "")))
                    if "," in raw_name or "," in raw_num:
                        has_pair_layout = True
                        break

            if has_pair_layout and "preferential" in str(self.election_type).lower():
                unique_by_name = {}
                ordered_names = []

                for i, cand in enumerate(candidates_list):
                    cand_commitment = self.commitments_list[i] if i < len(self.commitments_list) else ""
                    pref_id = cand.get("pref_id", cand.get("serial_id", i))
                    raw_name = str(cand.get("candidate_name", "Unknown"))
                    raw_num = str(cand.get("entry_number", cand.get("candidate_number", "")))

                    name_parts = [p.strip() for p in raw_name.split(",")]
                    num_parts = [p.strip() for p in raw_num.split(",")]

                    while len(num_parts) < len(name_parts):
                        num_parts.append("")

                    # Build pair -> (pref_id, commitment) lookup.
                    if len(name_parts) >= 2:
                        pair_key = (name_parts[0], name_parts[1])
                        self.pref_combo_map[pair_key] = {
                            "pref_id": str(pref_id),
                            "commitment": cand_commitment
                        }

                    # Extract unique candidate options for UI rendering.
                    for idx, name in enumerate(name_parts):
                        if name and name not in unique_by_name:
                            unique_by_name[name] = {
                                "name": name,
                                "candidate_number": num_parts[idx] if idx < len(num_parts) else "",
                                "party": cand.get("candidate_party", "")
                            }
                            ordered_names.append(name)

                # Keep NAFS as id 0 so existing UI logic remains stable.
                normalized_names = []
                if "NAFS" in ordered_names:
                    normalized_names.append("NAFS")
                normalized_names.extend([n for n in ordered_names if n != "NAFS"])

                for idx, name in enumerate(normalized_names):
                    item = unique_by_name[name]
                    self.candidates_base.append({
                        "id": idx,
                        "name": item["name"],
                        "candidate_number": item["candidate_number"],
                        "party": item["party"],
                        "commitment": ""
                    })

                # Pair-based ballots need exactly two preference picks.
                self.max_preferences = 2
                return self.candidates_base

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
            self.max_preferences = max(1, len(self.candidates_base) - 1)
            return self.candidates_base

        except Exception as e:
            raise Exception(f"Failed to load candidates from {self.candidates_file}: {e}")

    def get_candidate_by_id(self, cid):
        return next((c for c in self.candidates_base if c['id'] == cid), None)

    def resolve_preferential_selection(self, selections):
        """
        Resolve final preferential pref_id/commitment.
        For pair-layout ballots, map selected pair (name1, name2) to the source row commitment.
        """
        ranks = sorted(selections.keys())

        if self.pref_combo_map:
            names = []
            for rank in ranks[:2]:
                cand = self.get_candidate_by_id(selections[rank])
                if cand:
                    names.append(cand["name"])

            if len(names) == 2:
                pair_key = (names[0], names[1])
                hit = self.pref_combo_map.get(pair_key)
                if hit:
                    return str(hit.get("pref_id", "")), str(hit.get("commitment", "")), f"{names[0]},{names[1]}"

            # Pair layout present but no exact match.
            return "", "", ",".join(names)

        # Default preferential behavior for non-pair ballots.
        pref_id = "_".join(
            str(self.get_candidate_by_id(selections[r])['id'])
            for r in ranks if self.get_candidate_by_id(selections[r])
        )
        commitment = "_".join(
            str(self.get_candidate_by_id(selections[r]).get('commitment', ''))
            for r in ranks if self.get_candidate_by_id(selections[r])
        )
        return pref_id, commitment, pref_id

    def is_token_used(self, token_id):
        """Checks if the token_id has already been logged."""
        if not os.path.exists(self.token_log_file):
            return False
            
        try:
            with open(self.token_log_file, "r", encoding='utf-8') as f:
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
            with open(self.token_log_file, "a", encoding='utf-8') as f:
                f.write(f"{timestamp},{token_id}\n")
            print(f"Token Logged: {token_id}")
        except Exception as e:
            print(f"Error logging token: {e}")

    def generate_vote_json(self, vote_data, voting_mode, voter_id="UNKNOWN_VOTER", booth_num=1, token_id="UNKNOWN"):
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
            pref_id, commitment, _ = self.resolve_preferential_selection(selections)
            
        # Generate secure rolling hash
        import hashlib
        import json
        
        hash_payload = {
            "election_id": self.election_id,
            "voter_id": voter_id,
            "token_id": token_id,
            "booth_num": booth_num,
            "commitment": commitment,
            "pref_id": pref_id,
            "timestamp": timestamp,
            "previous_hash": self.last_hash
        }
        
        # We sort keys to ensure deterministic JSON stringification for standard hashing
        payload_str = json.dumps(hash_payload, sort_keys=True)
        current_hash = hashlib.sha256(payload_str.encode('utf-8')).hexdigest()
        
        vote_record = {
            "election_id": self.election_id,
            "voter_id": voter_id,
            "token_id": token_id,
            "booth_num": booth_num,
            "commitment": commitment,
            "pref_id": pref_id,
            "previous_hash": self.last_hash,
            "hash_value": current_hash,
            "timestamp": timestamp
        }
        
        # Advance the chain in memory for the next vote
        self.last_hash = current_hash
        
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

    def save_vote(self, vote_data, voting_mode, voter_id="UNKNOWN_VOTER", booth_num=1, token_id="UNKNOWN"):
        """Saves the vote data as a JSON line."""
        record = self.generate_vote_json(vote_data, voting_mode, voter_id, booth_num, token_id)
        self.save_json(record)
