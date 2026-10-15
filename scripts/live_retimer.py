#!/usr/bin/env python3
"""Companion of replay_day.py: shifts replayed data to the real prod timestamps *while
the replay runs*, so the platform's historical-day page fills in live.

Rewriting a row that is still inside the API's grouping windows would break sequence
matching and triangulation, so a sequence is only retimed once it is complete (all its
detections posted) AND idle for --age seconds — past every scaled window. Alerts have
their bounds recomputed from their sequences on every pass (idempotent), so an alert's
started_at flips to the historical time as soon as its first sequence is retimed.

Run in parallel with the replay:
  python3 scripts/replay_day.py --day 2026-07-10 --speed 60 --no-restore-times &
  python3 scripts/live_retimer.py

Exits after a final full pass when the replay writes its end-marker.
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

ENVDEV_ROOT = Path(__file__).resolve().parent.parent

CASCADE_SQL = """
UPDATE sequences s SET started_at = sub.mn, last_seen_at = sub.mx
FROM (SELECT sequence_id, MIN(created_at) mn, MAX(created_at) mx
      FROM detections WHERE sequence_id IN ({seq_subquery}) GROUP BY sequence_id) sub
WHERE s.id = sub.sequence_id;
UPDATE alerts a SET started_at = sub.mn, last_seen_at = sub.mx
FROM (SELECT asq.alert_id, MIN(s.started_at) mn, MAX(s.last_seen_at) mx
      FROM alerts_sequences asq JOIN sequences s ON s.id = asq.sequence_id
      GROUP BY asq.alert_id) sub
WHERE a.id = sub.alert_id;
"""


def psql(sql):
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql",
         "-U", "dummy_pg_user", "-d", "dummy_pg_db", "-v", "ON_ERROR_STOP=1", "-f", "-"],
        input=sql, text=True, cwd=ENVDEV_ROOT, capture_output=True,
    )


def retime(entries):
    values = ",".join(f"({e['id']},'{e['ts']}')" for e in entries)
    ids = ",".join(str(e["id"]) for e in entries)
    seq_subquery = f"SELECT DISTINCT sequence_id FROM detections WHERE id IN ({ids}) AND sequence_id IS NOT NULL"
    sql = (
        "BEGIN;\n"
        f"UPDATE detections d SET created_at = v.ts::timestamp FROM (VALUES {values}) AS v(id, ts) WHERE d.id = v.id;\n"
        + CASCADE_SQL.format(seq_subquery=seq_subquery)
        + "COMMIT;\n"
    )
    return psql(sql)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map-file", type=Path, default=ENVDEV_ROOT / ".replay_map.jsonl")
    ap.add_argument("--age", type=float, default=150.0,
                    help="seconds a complete sequence must stay idle before retiming (default 150)")
    ap.add_argument("--interval", type=float, default=15.0)
    args = ap.parse_args()

    while not args.map_file.exists():
        time.sleep(1)

    done_marker = False
    retimed_seqs = set()
    print(f"⏱  live retimer démarré (age {args.age:g}s, passe toutes les {args.interval:g}s)")
    while True:
        by_seq = {}
        for line in args.map_file.read_text().splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("done"):
                done_marker = True
                continue
            by_seq.setdefault(e["seq"], []).append(e)

        now = time.time()
        batch, batch_seqs = [], []
        for seq, entries in by_seq.items():
            if seq in retimed_seqs:
                continue
            complete = len(entries) >= entries[0]["total"]
            idle = now - max(e["posted"] for e in entries)
            if done_marker or (complete and idle >= args.age):
                batch.extend(entries)
                batch_seqs.append(seq)

        if batch:
            proc = retime(batch)
            if proc.returncode != 0:
                print(f"  ✗ retiming KO: {proc.stderr.strip()[:300]}")
            else:
                retimed_seqs.update(batch_seqs)
                first = min(e["ts"] for e in batch)[11:19]
                last = max(e["ts"] for e in batch)[11:19]
                print(f"  ✓ {len(batch_seqs)} séquence(s) re-datée(s) ({len(batch)} détections, {first}->{last} UTC)"
                      f" — total {len(retimed_seqs)} séquences", flush=True)

        if done_marker:
            print("🏁 replay terminé, dernière passe faite — retimer stoppé")
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
