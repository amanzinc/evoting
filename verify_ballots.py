from ballot_manager import BallotManager
import time

def verify_system():
    bm = BallotManager()
    
    print("\n--- Step 1: Requesting a Random Ballot ---")
    try:
        ballot_id = bm.get_unused_ballot()
        print(f"Received Ballot ID: {ballot_id}")
    except Exception as e:
        print(f"Error: {e}")
        return

    print(f"\n--- Step 2: Verifying Status in File ---")
    # Peek into internal state or file
    bm.load_ballots()
    status = bm.ballots.get(ballot_id)
    print(f"Status of {ballot_id} is: {status} (Expected: UNUSED)")

    print(f"\n--- Step 3: Marking as USED ---")
    bm.mark_as_used(ballot_id)
    
    print(f"\n--- Step 4: Verifying Status Update ---")
    bm.load_ballots()
    new_status = bm.ballots.get(ballot_id)
    print(f"Status of {ballot_id} is: {new_status} (Expected: USED)")
    
    if new_status == "USED":
        print("\n[SUCCESS] Ballot tracking is working.")
    else:
        print("\n[FAILURE] Status did not update.")

if __name__ == "__main__":
    verify_system()
