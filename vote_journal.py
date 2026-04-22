"""
Append-only two-phase commit journal for VVPAT vote recording.

Each vote write goes through two steps:
  1. PENDING  — written before printing starts, fsynced immediately
  2. COMMITTED — written after print+cut confirmed, fsynced immediately

On power loss between steps 1 and 2 the PENDING entry survives.
At next startup, any unresolved PENDING entries trigger the officer
recovery screen.
"""

import json
import os
import datetime


class VoteJournal:
    def __init__(self, log_dir):
        self.journal_path = os.path.join(log_dir, "vote_journal.log")

    def write_pending(self, journal_id, voter_id, election_id, election_name,
                      vvpat_choice_str, vote_record, voting_mode, selections):
        entry = {
            "id": journal_id,
            "voter_id": voter_id,
            "election_id": election_id,
            "election_name": election_name,
            "vvpat_choice_str": vvpat_choice_str,
            "vote_record": vote_record,
            "voting_mode": voting_mode,
            "selections": selections,
            "status": "PENDING",
            "timestamp": datetime.datetime.now().isoformat(),
        }
        self._append(entry)

    def write_committed(self, journal_id):
        if not journal_id:
            return
        self._append({
            "id": journal_id,
            "status": "COMMITTED",
            "timestamp": datetime.datetime.now().isoformat(),
        })

    def write_discarded(self, journal_id):
        if not journal_id:
            return
        self._append({
            "id": journal_id,
            "status": "DISCARDED",
            "timestamp": datetime.datetime.now().isoformat(),
        })

    def get_pending(self):
        """Return all PENDING entries that have no COMMITTED/DISCARDED counterpart."""
        if not os.path.exists(self.journal_path):
            return []

        pending = {}
        resolved = set()

        try:
            with open(self.journal_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        jid = rec.get("id")
                        if not jid:
                            continue
                        status = rec.get("status", "")
                        if status == "PENDING":
                            pending[jid] = rec
                        elif status in ("COMMITTED", "DISCARDED"):
                            resolved.add(jid)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[journal] Error reading journal: {e}")

        return [e for jid, e in pending.items() if jid not in resolved]

    def _append(self, entry):
        try:
            with open(self.journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            print(f"[journal] Warning — could not write: {e}")
