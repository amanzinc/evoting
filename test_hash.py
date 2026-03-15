import json
import hashlib

votes = [
    {
        "election_id": "E1", 
        "voter_id": '{"token_id": "DEV_SKIP_1772449349", "eid_vector": "E1;E3;E6"}', 
        "booth_num": 1, 
        "commitment": "c1ca0daf3b04ffbf31ef8f09c76c53619438ab780523c1a0475fc1345328980b_356f12b8ae61f2f9f13d7bcac91ab5e772de08758730a0fca87b19eede9e81e3_b6ce81f3522177caa50fabc567b4c5930484972d0b54960760fc267a80cd6e57", 
        "pref_id": "2_3_1", 
        "previous_hash": "bdfe3352fcde2680f070ef81a0d8dafa5b7a85eb9df3cee4a84cd6020fd2a71a", 
        "hash_value": "b2f13ae231c5b6cb59c16a1c97f9a95d6f951279021829cc7b026963082a2611", 
        "timestamp": "02-03-26 16:32:35"
    },
    {
        "election_id": "E3", 
        "voter_id": '{"token_id": "DEV_SKIP_1772449349", "eid_vector": "E1;E3;E6"}', 
        "booth_num": 1, 
        "commitment": "b6ce81f3522177caa50fabc567b4c5930484972d0b54960760fc267a80cd6e57", 
        "pref_id": "3", 
        "previous_hash": "b2f13ae231c5b6cb59c16a1c97f9a95d6f951279021829cc7b026963082a2611", 
        "hash_value": "51c6f1ee0e37e3a8f2af625d5c21143c3e75957eaffd0dada6df736f4c49816c", 
        "timestamp": "02-03-26 16:32:38"
    },
    {
        "election_id": "E6", 
        "voter_id": '{"token_id": "DEV_SKIP_1772449349", "eid_vector": "E1;E3;E6"}', 
        "booth_num": 1, 
        "commitment": "356f12b8ae61f2f9f13d7bcac91ab5e772de08758730a0fca87b19eede9e81e3", 
        "pref_id": "2", 
        "previous_hash": "51c6f1ee0e37e3a8f2af625d5c21143c3e75957eaffd0dada6df736f4c49816c", 
        "hash_value": "4520b031a264a469d417438c4ca46840026888de418888888883cddd79339b4e", 
        "timestamp": "02-03-26 16:32:41"
    }
]


for idx, v in enumerate(votes):
    hash_payload = {
        "election_id": v["election_id"],
        "voter_id": v["voter_id"],
        "booth_num": v["booth_num"],
        "commitment": v["commitment"],
        "pref_id": v["pref_id"],
        "timestamp": v["timestamp"],
        "previous_hash": v["previous_hash"]
    }
    payload_str = json.dumps(hash_payload, sort_keys=True)
    current_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
    
    print(f"Vote {idx+1} ({v['election_id']}):")
    print(f"  Stored Hash   : {v['hash_value']}")
    print(f"  Computed Hash : {current_hash}")
    if current_hash == v['hash_value']:
        print("  Status        : [VALID]")
    else:
        print("  Status        : [TAMPERED!] <- THE STORED HASH DOES NOT MATCH THE VOTE DATA")
    print()
