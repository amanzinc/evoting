import json
from data_handler import DataHandler

def generate_sample():
    # Mock ballot data reflecting the exact new schema
    mock_ballot = {
        "election_id": "1",
        "election_type": "Preferential",
        "election_name": "Student Council",
        "commitments": "[[\"2f81f466b78abe3496d0477dd4f8f027fe841fbddd71210e6589c3af729ccf08\", \"b6ce81f3522177caa50fabc567b4c5930484972d0b54960760fc267a80cd6e57\", \"c1ca0daf3b04ffbf31ef8f09c76c53619438ab780523c1a0475fc1345328980b\", \"356f12b8ae61f2f9f13d7bcac91ab5e772de08758730a0fca87b19eede9e81e3\"], [1, \"[...]\"]]",
        "candidates": [
            {
                "pref_id": "0",
                "entry_number": "012",
                "candidate_name": "NAFS"
            },
            {
                "pref_id": "1",
                "entry_number": "001",
                "candidate_name": "Alice"
            }
        ],
        "ballot_id": "[8263740266090787671808355637161517737897157608076513055213713811038704697847, \"...\"]"
    }
    
    with open("mock_plain_ballot.json", "w") as f:
        json.dump(mock_ballot, f)

    # Clean old test logs
    with open("mock_votes.json", "w") as f: f.write("")

    dh = DataHandler("unused", log_file="mock_votes.json")
    dh.set_ballot_file("mock_plain_ballot.json")
    
    vote_data = {'selections': {1: 1}}  # Vote for Alice who is ID 1
    # Save vote!
    dh.save_vote(vote_data, "normal", "VOTER-1234", 5)

    print("\n[SAMPLE votes.json OUTPUT]")
    with open("mock_votes.json", "r") as f:
        print(f.read())
        
generate_sample()
