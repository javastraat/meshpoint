#!/usr/bin/env python3
"""Clear MeshCore node names cross-contaminated by a now-fixed bug.

Root cause (fixed in src/api/server.py and src/api/meshcore_contacts.py):
whenever a MeshCore node's display name couldn't be resolved normally, a
fallback grabbed an ARBITRARY "mc:<name>"-prefixed placeholder row (a
contact known only via the companion's roster, never directly heard
over the air) with no connection whatsoever to the actual packet, and
stamped that unrelated name onto the current node. A second, related
bug let two different roster contacts sharing a short (8/10-char)
public-key prefix silently overwrite each other's cached name too.
Both are fixed going forward -- this script only cleans up names that
were already corrupted by them.

Detection: a name is only flagged when BOTH are true --
  (a) 2+ DISTINCT real (non-"mc:") node_ids currently share the exact
      same long_name (implausible as a coincidence for genuinely
      different devices' own chosen identity), AND
  (b) an existing "mc:"-prefixed placeholder row (a contact known only
      via the companion's roster, never directly heard over the air)
      ALSO carries that exact same name -- this is the specific
      signature of the fixed bug, which always sourced its borrowed
      name FROM an "mc:" row.
Requiring both avoids false positives on real devices that happen to
share a generic factory-default name with no roster/contact connection
at all (e.g. multiple SenseCap units all broadcasting "SenseCap_Solar
Repeater") -- those are left untouched since there's no evidence they
were corrupted by this bug specifically, just a plain quirk of
observing the same product model announce a shared default name.

This clears ALL matching real node_ids for a flagged name, including
whichever one (if any) happens to be the genuinely correct owner --
there is no way to tell from the database alone which of 2+ candidates
is correct, and clearing the correct one too is a small, self-healing
cost: the fixed contact-sync mechanism re-applies it correctly within
~5 minutes (its throttle interval) the next time that companion's
roster is synced. The "mc:"-prefixed placeholder rows themselves are
never touched -- they are the legitimate roster record.

Usage (on the Pi):
    # dry run -- shows what would be cleared, writes nothing
    python3 clear_meshcore_name_contamination.py

    # apply
    python3 clear_meshcore_name_contamination.py --apply
"""

import argparse
import sqlite3
import sys

DB_PATH = "/opt/meshpoint/data/concentrator.db"

_FIND_CONTAMINATED_SQL = """
    SELECT n.node_id, n.long_name, n.short_name, n.packet_count
    FROM nodes n
    WHERE n.protocol = 'meshcore'
      AND n.node_id NOT LIKE 'mc:%'
      AND n.long_name IS NOT NULL AND n.long_name != ''
      AND n.long_name IN (
          -- 2+ distinct REAL node_ids sharing this exact name
          SELECT long_name FROM nodes
          WHERE protocol = 'meshcore' AND node_id NOT LIKE 'mc:%'
            AND long_name IS NOT NULL AND long_name != ''
          GROUP BY long_name
          HAVING COUNT(DISTINCT node_id) > 1
      )
      AND n.long_name IN (
          -- AND a roster placeholder independently carries this same
          -- name -- the specific signature of the fixed bug
          SELECT long_name FROM nodes
          WHERE protocol = 'meshcore'
            AND node_id LIKE 'mc:%'
            AND node_id != 'mc:channel'
            AND long_name IS NOT NULL AND long_name != ''
      )
    ORDER BY n.long_name, n.node_id
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=DB_PATH, help=f"database path (default: {DB_PATH})")
    parser.add_argument("--apply", action="store_true", help="write changes (default is dry run)")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(_FIND_CONTAMINATED_SQL).fetchall()

        if not rows:
            print("No contaminated MeshCore node names found. Nothing to do.")
            return 0

        print(f"Found {len(rows)} real node(s) with a name borrowed from an unrelated roster placeholder:\n")
        for row in rows:
            print(
                f"  {row['node_id']:14s} long_name={row['long_name']!r} "
                f"short_name={row['short_name']!r} packet_count={row['packet_count']}"
            )

        if not args.apply:
            print("\nDry run only. Re-run with --apply to clear long_name/short_name on all of the above.")
            print("(The 'mc:'-prefixed placeholder rows that supplied these names are never touched.)")
            return 0

        node_ids = [row["node_id"] for row in rows]
        placeholders = ",".join("?" for _ in node_ids)
        cursor = conn.execute(
            f"UPDATE nodes SET long_name = '', short_name = '' WHERE node_id IN ({placeholders})",
            node_ids,
        )
        conn.commit()
        print(f"\nCleared {cursor.rowcount} node row(s). Names will re-derive correctly as fresh packets arrive.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
