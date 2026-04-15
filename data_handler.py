import json
import csv
import os
import base64
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class DataHandler:
    def __init__(self, candidates_file, log_file="votes.json", token_log_file="tokens.log"):
        # candidates_file is now the specific ballot file path
        self.candidates_file = candidates_file 
        self.log_file = log_file
        self.token_log_file = token_log_file
        self.election_id = ""
        self.election_hash = ""
        self.election_type = "Normal"
        self.election_type_normalized = "normal"
        self.number_of_preferences = None
        self.ballot_id = "" # Store the specific generic complex payload ID
        self.ballot_file_id = "" # Store the filename for SQLite logic
        self.candidates_base = []
        self.pref_combo_map = {}
        self.pref_rank_name_sets = {}
        self.pref_tuple_size = 2
        self.max_preferences = 1
        self.decrypted_aes_key = None
        self.pref_debug_log_file = os.path.join("logs", "preferential_debug.jsonl")
        self.current_ballot_plain = None
        
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
        ballot_name = os.path.basename(new_file)
        if ballot_name.endswith('.enc.json'):
            self.ballot_file_id = ballot_name[:-len('.enc.json')]
        elif ballot_name.endswith('.json'):
            self.ballot_file_id = ballot_name[:-len('.json')]
        else:
            self.ballot_file_id = ballot_name
        self.load_candidates()

    def _load_stored_aes_key(self):
        """Load stored AES key generated during USB import."""
        if self.decrypted_aes_key is not None:
            return self.decrypted_aes_key

        key_path = os.path.join("ballot", "aes_key.dec")
        if not os.path.exists(key_path):
            raise FileNotFoundError(f"Stored AES key not found at {key_path}")

        with open(key_path, "r", encoding="utf-8") as f:
            key_data = json.load(f)

        aes_key_b64 = key_data.get("aes_key_b64")
        if not aes_key_b64:
            raise ValueError("aes_key_b64 missing in stored AES key file")

        self.decrypted_aes_key = base64.b64decode(aes_key_b64)
        return self.decrypted_aes_key

    def _decrypt_aes_wrapped_ballot(self, envelope):
        """Decrypt AES-GCM chunked ballot envelope into ballot JSON dict."""
        nonce_b64 = envelope.get("nonce")
        chunks = envelope.get("chunks", [])
        num_chunks = envelope.get("num_chunks")

        if not nonce_b64 or not chunks:
            raise ValueError("Invalid encrypted ballot envelope: missing nonce/chunks")
        if num_chunks is not None and int(num_chunks) != len(chunks):
            raise ValueError(
                f"Chunk count mismatch: num_chunks={num_chunks}, actual={len(chunks)}"
            )

        nonce_base = base64.b64decode(nonce_b64)
        if len(nonce_base) != 12:
            raise ValueError(f"Invalid nonce length {len(nonce_base)}; expected 12 bytes")

        aes_key = self._load_stored_aes_key()
        aesgcm = AESGCM(aes_key)

        plaintext_parts = []
        for chunk_index, chunk_b64 in enumerate(chunks):
            chunk_ciphertext = base64.b64decode(chunk_b64)

            chunk_nonce = bytearray(nonce_base)
            idx_bytes = struct.pack(">I", chunk_index)
            for i in range(4):
                chunk_nonce[-(i + 1)] ^= idx_bytes[-(i + 1)]

            aad = struct.pack(">I", chunk_index)
            chunk_plaintext = aesgcm.decrypt(bytes(chunk_nonce), chunk_ciphertext, aad)
            plaintext_parts.append(chunk_plaintext)

        decrypted_ballot = b"".join(plaintext_parts)
        return json.loads(decrypted_ballot.decode("utf-8"))

    def load_candidates(self):
        """Loads candidates from the specific ballot/candidate file."""
        self.candidates_base = []
        self.pref_combo_map = {}
        self.pref_rank_name_sets = {}
        self.pref_tuple_size = 2
        
        if not os.path.exists(self.candidates_file):
            raise FileNotFoundError(f"{self.candidates_file} not found!")

        try:
            with open(self.candidates_file, mode='rb') as f:
                file_content = f.read()

            try:
                # Try parsing as plain JSON first.
                data = json.loads(file_content.decode('utf-8'))
                # If this is an encrypted envelope JSON, decrypt on-demand.
                # Supports variants like "AES-256-GCM" and "RSA-OAEP+AES-GCM-256".
                if (
                    isinstance(data, dict)
                    and data.get("nonce")
                    and isinstance(data.get("chunks"), list)
                    and len(data.get("chunks")) > 0
                ):
                    data = self._decrypt_aes_wrapped_ballot(data)
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
            self.election_type_normalized = self._normalize_election_type(self.election_type)
            self.election_name = data.get("election_name", "General Election")
            self.current_ballot_plain = data

            raw_pref_count = data.get("number_of_preferences", None)
            try:
                parsed_pref_count = int(raw_pref_count) if raw_pref_count is not None else None
                self.number_of_preferences = parsed_pref_count if parsed_pref_count and parsed_pref_count > 0 else None
            except Exception:
                self.number_of_preferences = None
            
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

            if has_pair_layout:
                # Pair-layout ballots are inherently preferential even if election_type
                # text is inconsistent or mislabeled.
                self.election_type = "preferential"
                self.election_type_normalized = "preferential"
                unique_by_name = {}
                ordered_names = []

                detected_tuple_size = 2
                if self.number_of_preferences and self.number_of_preferences > 0:
                    detected_tuple_size = self.number_of_preferences
                else:
                    for cand in candidates_list:
                        raw_name = str(cand.get("candidate_name", ""))
                        parts_len = len([p for p in raw_name.split(",") if p.strip()])
                        if parts_len > detected_tuple_size:
                            detected_tuple_size = parts_len

                self.pref_tuple_size = max(2, detected_tuple_size)
                self.pref_rank_name_sets = {rank: set() for rank in range(1, self.pref_tuple_size + 1)}

                for i, cand in enumerate(candidates_list):
                    cand_commitment = self.commitments_list[i] if i < len(self.commitments_list) else ""
                    pref_id = cand.get("pref_id", cand.get("serial_id", i))
                    raw_name = str(cand.get("candidate_name", "Unknown"))
                    raw_num = str(cand.get("entry_number", cand.get("candidate_number", "")))

                    name_parts = [p.strip() for p in raw_name.split(",")]
                    num_parts = [p.strip() for p in raw_num.split(",")]

                    while len(num_parts) < len(name_parts):
                        num_parts.append("")

                    normalized_parts = []
                    for part in name_parts:
                        normalized_part = part
                        if self._is_nota_name(part):
                            existing_nota = next(
                                (k for k in unique_by_name.keys() if self._is_nota_name(k)),
                                None
                            )
                            if existing_nota:
                                normalized_part = existing_nota
                        normalized_parts.append(normalized_part)

                    # Build preference tuple -> (pref_id, commitment) lookup.
                    if len(normalized_parts) >= self.pref_tuple_size:
                        pref_key = tuple(normalized_parts[:self.pref_tuple_size])
                        self.pref_combo_map[pref_key] = {
                            "pref_id": str(pref_id),
                            "commitment": cand_commitment
                        }
                        for rank_idx in range(self.pref_tuple_size):
                            self.pref_rank_name_sets[rank_idx + 1].add(normalized_parts[rank_idx])

                    # Extract unique candidate options for UI rendering.
                    for idx, name in enumerate(normalized_parts):
                        if name and name not in unique_by_name:
                            unique_by_name[name] = {
                                "name": name,
                                "candidate_number": num_parts[idx] if idx < len(num_parts) else "",
                                "party": cand.get("candidate_party", "")
                            }
                            ordered_names.append(name)

                for idx, name in enumerate(ordered_names):
                    item = unique_by_name[name]
                    self.candidates_base.append({
                        "id": idx,
                        "name": item["name"],
                        "candidate_number": item["candidate_number"],
                        "party": item["party"],
                        "commitment": ""
                    })

                # Pair-based ballots need exactly two preference picks.
                max_allowed = max(1, len(self.candidates_base))
                requested = self.number_of_preferences if self.number_of_preferences else 2
                self.max_preferences = min(max_allowed, max(1, requested))
                return self.candidates_base

            for i, cand in enumerate(candidates_list):
                cand_commitment = self.commitments_list[i] if i < len(self.commitments_list) else ""
                
                # Support new "pref_id" & "entry_number" or fallback to old schema
                pref_id = cand.get("pref_id", cand.get("serial_id", i))
                entry_number = cand.get("entry_number", cand.get("candidate_number", ""))
                candidate_name = str(cand.get("candidate_name", "Unknown")).strip()

                # Do not add NOTA/NAFS twice if ballot includes multiple aliases.
                if self._is_nota_name(candidate_name) and any(
                    self._is_nota_name(existing.get("name", "")) for existing in self.candidates_base
                ):
                    continue
                
                self.candidates_base.append({
                    "id": int(pref_id),
                    "name": candidate_name,
                    "candidate_number": entry_number,
                    "party": cand.get("candidate_party", ""),
                    "commitment": cand_commitment
                })
            
            self.candidates_base.sort(key=lambda x: x['id'])
            if self.number_of_preferences:
                max_allowed = max(1, len(self.candidates_base))
                self.max_preferences = min(max_allowed, max(1, self.number_of_preferences))
            else:
                self.max_preferences = max(1, len(self.candidates_base) - 1)
            return self.candidates_base

        except Exception as e:
            raise Exception(f"Failed to load candidates from {self.candidates_file}: {e}")

    def get_candidate_by_id(self, cid):
        return next((c for c in self.candidates_base if c['id'] == cid), None)

    def build_receipt_qr_payload(self, selections, voting_mode):
        """
        Build receipt QR payload using commitments mapped to selected candidates.
        - Normal: "<commitment>"
        - Preferential pair-layout: commitment matched from selected candidate-name pair
        """
        if voting_mode == 'normal':
            cid = selections.get(1)
            cand = self.get_candidate_by_id(cid)
            if not cand:
                return ""
            commitment = str(cand.get('commitment', ''))
            return commitment
            
        if voting_mode == 'block':
            # In block mode, we just concatenate all selected commitments
            ranks = sorted(selections.keys())
            commitments = []
            for r in ranks:
                cid = selections[r]
                cand = self.get_candidate_by_id(cid)
                if cand and cand.get('commitment'):
                    commitments.append(str(cand.get('commitment')))
            return "_".join(commitments)

        # Preferential mode
        ranks = sorted(selections.keys())
        choice_nums = []
        for r in ranks:
            cand = self.get_candidate_by_id(selections[r])
            if cand:
                choice_nums.append(str(cand.get('id', selections[r])))

        pref_id, pref_commitment, pref_label = self.resolve_preferential_selection(selections)
        if pref_commitment:
            return str(pref_commitment)

        # Fallback when no exact pair commitment is found.
        return ""

    def get_short_ballot_id(self, ballot_id=None):
        """Return ballot id truncated to the part before first comma."""
        raw = str(self.ballot_id if ballot_id is None else ballot_id)
        short_id = raw.split(",", 1)[0].strip()
        return short_id.lstrip("[").rstrip("]").strip()

    def _normalize_election_type(self, value):
        """Normalize election type to simplify robust matching across case/style variants."""
        return str(value or "").strip().lower()

    def _is_nota_name(self, value):
        text = str(value or "").strip().lower()
        return text in ("nafs", "nota", "none of the above", "none-of-the-above")

    def is_preferential_election(self):
        """Return True for preferential/ranked election types, case-insensitive."""
        et = self.election_type_normalized or self._normalize_election_type(self.election_type)
        keywords = ("preferential", "ranked", "rank", "preference")
        return any(k in et for k in keywords)

    def is_block_election(self):
        """Return True for block election types (multi-select, equal-weight)."""
        et = self.election_type_normalized or self._normalize_election_type(self.election_type)
        return "block" in et

    def get_candidates_for_rank(self, rank):
        """Return unique candidate options for a given preferential rank screen."""
        if self.pref_rank_name_sets and rank in self.pref_rank_name_sets:
            allowed = self.pref_rank_name_sets[rank]
            return [c for c in self.candidates_base if c.get("name") in allowed]
        return self.candidates_base

    def resolve_preferential_selection(self, selections):
        """
        Resolve final preferential pref_id/commitment.
        For pair-layout ballots, map selected pair (name1, name2) to the source row commitment.
        """
        ranks = sorted(selections.keys())

        if self.pref_combo_map:
            tuple_size = max(2, int(getattr(self, "pref_tuple_size", 2) or 2))
            names = []
            for rank in ranks[:tuple_size]:
                cand = self.get_candidate_by_id(selections[rank])
                if cand:
                    names.append(cand["name"])

            if len(names) == tuple_size:
                pref_key = tuple(names)
                hit = self.pref_combo_map.get(pref_key)
                if hit:
                    return str(hit.get("pref_id", "")), str(hit.get("commitment", "")), ",".join(names)

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

    def _log_preferential_debug(self, selections, pref_id, commitment, pref_label, voter_id, token_id, booth_num, timestamp):
        """Write detailed preferential selection mapping for debugging."""
        try:
            os.makedirs("logs", exist_ok=True)

            ranked_selection = []
            for rank in sorted(selections.keys()):
                cid = selections.get(rank)
                cand = self.get_candidate_by_id(cid)
                ranked_selection.append({
                    "rank": rank,
                    "candidate_id": cid,
                    "candidate_name": cand.get("name") if cand else "",
                    "candidate_number": cand.get("candidate_number") if cand else ""
                })

            pair_layout_lookup = None
            if self.pref_combo_map:
                pair_layout_lookup = {
                    "|".join(k): {
                        "pref_id": str(v.get("pref_id", "")),
                        "commitment": str(v.get("commitment", ""))
                    }
                    for k, v in self.pref_combo_map.items()
                }

            debug_record = {
                "timestamp": timestamp,
                "election_id": self.election_id,
                "ballot_id": self.ballot_id,
                "ballot_file_id": self.ballot_file_id,
                "voter_id": voter_id,
                "token_id": token_id,
                "booth_num": booth_num,
                "selections": ranked_selection,
                "resolved_pref_label": pref_label,
                "resolved_pref_id": str(pref_id),
                "resolved_commitment": str(commitment),
                "pair_layout_lookup": pair_layout_lookup
            }

            with open(self.pref_debug_log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(debug_record, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"Warning: failed to write preferential debug log: {e}")

    def store_used_ballot_snapshot(self, election_id=None, ballot_file_id=None, status="USED"):
        """Persist decrypted snapshot of the currently loaded ballot for auditing/debugging."""
        try:
            if not isinstance(self.current_ballot_plain, dict):
                print("Warning: no decrypted ballot payload available to snapshot.")
                return

            eid = str(election_id or self.election_id or "unknown_election")
            bid = str(ballot_file_id or self.ballot_file_id or "unknown_ballot")

            out_dir = os.path.join("logs", "used_ballots", eid)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"{bid}.json")

            payload = {
                "snapshot_timestamp": __import__("datetime").datetime.now().isoformat(),
                "status": str(status),
                "election_id": eid,
                "ballot_file_id": bid,
                "ballot_id": self.ballot_id,
                "ballot": self.current_ballot_plain
            }

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Warning: failed to store used ballot snapshot: {e}")

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
            pref_id, commitment, pref_label = self.resolve_preferential_selection(selections)
            self._log_preferential_debug(
                selections=selections,
                pref_id=pref_id,
                commitment=commitment,
                pref_label=pref_label,
                voter_id=voter_id,
                token_id=token_id,
                booth_num=booth_num,
                timestamp=timestamp
            )
            
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
        """Saves the vote data as a JSON line. In block mode, saves multiple JSON lines."""
        if voting_mode == 'block':
            selections = vote_data.get('selections', {})
            for r in sorted(selections.keys()):
                cid = selections[r]
                # Mock a single choice selection for the loop
                single_vote_data = vote_data.copy()
                single_vote_data['selections'] = {1: cid}
                record = self.generate_vote_json(single_vote_data, 'normal', voter_id, booth_num, token_id)
                self.save_json(record)
        else:
            record = self.generate_vote_json(vote_data, voting_mode, voter_id, booth_num, token_id)
            self.save_json(record)
