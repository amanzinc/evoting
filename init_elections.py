import os
import json
import uuid
import random
import copy
import pymongo

ELECTIONS_ROOT = "elections"
CONFIGS = {
    "E1": {"name": "Student Council", "candidates": ["Alice", "Bob", "Charlie", "NAFS"]},
    "E3": {"name": "Sports Committee", "candidates": ["David", "Eve", "Frank", "NAFS"]},
    "E6": {"name": "Cultural Society", "candidates": ["Grace", "Heidi", "Ivan", "NAFS"]}
}

def setup_election(eid, info):
    print(f"Setting up {eid} - {info['name']}...")
    
    # 1. Directories
    base_dir = os.path.join(ELECTIONS_ROOT, eid)
    ballots_dir = os.path.join(base_dir, "ballots")
    os.makedirs(ballots_dir, exist_ok=True)
    
    # 2. Template
    candidates_dict = {}
    
    # Create valid candidates
    serial_counter = 1
    # Ensure NAFS is handled specifically if needed, but generic loop works
    # Just need to make sure we assign IDs.
    
    # We'll shuffle strictly for the template? No, template usually standard.
    # Actually, standard template has fixed serial_ids usually? 
    # Let's just assign simple IDs 0..N
    
    for i, name in enumerate(info['candidates']):
        candidates_dict[str(i)] = {
            "candidate_number": str(i),
            "serial_id": i, # Initial assignment
            "candidate_name": name,
            "id": i # Helper
        }

    template = {
        "election_id": eid,
        "election_name": info['name'],
        "candidates": candidates_dict
    }
    
    with open(os.path.join(base_dir, "candidates.json"), 'w') as f:
        json.dump(template, f, indent=4)
        
    # 3. Generate Ballots
    generate_ballots(eid, base_dir, ballots_dir, template, count=20)
    
    # 4. Status File
    # Will be created by BallotManager, or we simply don't need to pre-create.
    # But let's verify logic.

def generate_ballots(eid, base_dir, ballots_dir, template, count=20):
    usage_map = {}
    
    for _ in range(count):
        bid = uuid.uuid4().hex[:8].upper()
        usage_map[bid] = "UNUSED"
        
        # Deep copy template
        ballot_data = copy.deepcopy(template)
        ballot_data['ballot_id'] = bid
        
        # Use Hardcoded Hash as requested by User
        simulated_hash = "'[[\"d618d908eacb6fa43f28c627fabb492d432eb43d601a3c0963e748b0178629ad\", \"49a7c2cbe199497023b94bda4efb33a6e15effe17e5563f423503e05f12cbde1\", \"e4f0f24bf5e2e1dfb3a467819b39c95e037e2c6b2faffe403c3dfd7ad14b0286\", \"e5abf187c7f1c33b40881774d89b80e89a7e651051f91e8b5a3f4f7e789f524a\"], [1, \"[7843901705889157855030183509219937208058978663083704502957876214011927609198, 14815156419145346489492942119494738359375770505643515459839277797820291735746]\"]]'"
        ballot_data['hash_string'] = simulated_hash
        
        # --- SHUFFLE CANDIDATES ---
        # Get list of candidates
        c_list = list(ballot_data['candidates'].values())
        
        # Collect Serial IDs (0, 1, 2, 3...)
        available_serials = [c['serial_id'] for c in c_list]
        random.shuffle(available_serials)
        
        # Assign new shuffled Serial IDs back
        # Note: 'id' key in dict remains '0', '1'... but 'serial_id' changes
        # This effectively shuffles the order if UI sorts by serial_id.
        # WAIT: The previous logic relied on 'serial_id'.
        for idx, cand in enumerate(c_list):
            cand['serial_id'] = available_serials[idx]
            
        # Write Ballot File
        b_path = os.path.join(ballots_dir, f"{bid}.json")
        with open(b_path, 'w') as f:
            json.dump(ballot_data, f, indent=4)
            
    # Insert into MongoDB
    try:
        client = pymongo.MongoClient("mongodb://localhost:27017/")
        db = client["evoting_db"]
        collection = db["ballots"]
        
        docs = []
        for bid in usage_map:
             docs.append({
                 "election_id": eid,
                 "ballot_id": bid,
                 "status": "UNUSED"
             })
             
        if docs:
            collection.insert_many(docs)
            print(f"  -> Inserted {len(docs)} ballots into MongoDB for {eid}")
            
    except Exception as e:
        print(f"  -> Failed to insert into MongoDB: {e}")
        
    print(f"  -> Generated {count} ballots for {eid}")

if __name__ == "__main__":
    if os.path.exists(ELECTIONS_ROOT):
        import shutil
        print("Cleaning old elections data...")
        shutil.rmtree(ELECTIONS_ROOT)
        
        # Clear MongoDB Collection
        try:
             client = pymongo.MongoClient("mongodb://localhost:27017/")
             client["evoting_db"]["ballots"].delete_many({})
             print("Cleared MongoDB ballots collection.")
        except: pass
        
    os.makedirs(ELECTIONS_ROOT)
    
    for eid, info in CONFIGS.items():
        setup_election(eid, info)
        
    print("\nSearch complete. Run 'main.py' to start app.")
