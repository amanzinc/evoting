from ballot_manager import BallotManager

def main():
    print("Initializing Ballot Generation...")
    bm = BallotManager()
    
    # Generate 100 sample ballots
    bm.generate_ballots(100)
    print("Done. Check ballots.json")

if __name__ == "__main__":
    main()
