import os
import json
import uuid
import random
import copy
import pymongo

ELECTIONS_ROOT = "elections"
CONFIGS = {
    "E1": {"name": "Student Council", "type": "Preferential", "candidates": ["Alice", "Bob", "Charlie", "NAFS"]},
    "E3": {"name": "Sports Committee", "type": "Preferential", "candidates": ["David", "Eve", "Frank", "NAFS"]},
    "E6": {"name": "Cultural Society", "type": "Preferential", "candidates": ["Grace", "Heidi", "Ivan", "NAFS"]}
}

def setup_election(eid, info):
    print(f"Setting up {eid} - {info['name']}...")
    
    # 1. Directories
    base_dir = os.path.join(ELECTIONS_ROOT, eid)
    ballots_dir = os.path.join(base_dir, "ballots")
    os.makedirs(ballots_dir, exist_ok=True)
    
    # 2. Template
    candidates_list = []
    for i, name in enumerate(info['candidates']):
        candidates_list.append({
            "pref_id": str(i),
            "entry_number": str(i).zfill(3),
            "candidate_name": name,
            "id": i # Helper
        })

    template = {
        "election_id": str(eid),
        "election_type": info.get("type", "Preferential"),
        "election_name": info['name'],
        "candidates": candidates_list
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
    
    for i in range(count):
        bid = uuid.uuid4().hex[:8].upper()
        file_id = f"ballot_{i+1}_{eid}"
        usage_map[file_id] = "UNUSED"
        
        # Deep copy template
        ballot_data = copy.deepcopy(template)
        ballot_data['ballot_id'] = bid
        
        # Use stringified array as requested by User for commitments
        simulated_commitments = "[[\"2f81f466b78abe3496d0477dd4f8f027fe841fbddd71210e6589c3af729ccf08\", \"b6ce81f3522177caa50fabc567b4c5930484972d0b54960760fc267a80cd6e57\", \"c1ca0daf3b04ffbf31ef8f09c76c53619438ab780523c1a0475fc1345328980b\", \"356f12b8ae61f2f9f13d7bcac91ab5e772de08758730a0fca87b19eede9e81e3\"], [1, \"[10139390530918078908084553188769788274531616515479454518879697877373004453692, 661415122062567411495962927288547756272641839894596131339603044389075159256]\"]]"
        ballot_data['commitments'] = simulated_commitments
        
        # --- SHUFFLE CANDIDATES ---
        # Get list of candidates
        c_list = ballot_data['candidates']
        
        # Collect Pref IDs
        available_ids = [c['pref_id'] for c in c_list]
        random.shuffle(available_ids)
        
        # Assign new shuffled Pref IDs back
        for idx, cand in enumerate(c_list):
            cand['pref_id'] = available_ids[idx]
            
        # Write Ballot File
        b_path = os.path.join(ballots_dir, f"{file_id}.json")
        with open(b_path, 'w') as f:
            json.dump(ballot_data, f, indent=4)
            
    print(f"  -> Generated {count} ballots for {eid}")

if __name__ == "__main__":
    if os.path.exists(ELECTIONS_ROOT):
        import shutil
        print("Cleaning old elections data...")
        shutil.rmtree(ELECTIONS_ROOT)
        
    os.makedirs(ELECTIONS_ROOT)
    
    for eid, info in CONFIGS.items():
        setup_election(eid, info)
        
    print("\nSearch complete. Run 'main.py' to start app.")
