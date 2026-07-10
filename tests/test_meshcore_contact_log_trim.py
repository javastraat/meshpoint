"""Roster log trim: count + first 10 + "… and N more" (Mac-runnable)."""

import unittest

from src.api.meshcore_contacts import (
    _ROSTER_LOG_LIMIT,
    log_meshcore_contact_peers,
)


def _contacts(n):
    return [
        {"public_key": f"{i:012x}", "name": f"Node {i}"} for i in range(n)
    ]


class RosterLogTrimTest(unittest.TestCase):
    LOGGER = "src.api.meshcore_contacts"

    def test_large_roster_logs_summary_not_every_contact(self):
        with self.assertLogs(self.LOGGER, level="INFO") as logs:
            log_meshcore_contact_peers(_contacts(350))
        # count line + limit names + one "and more" line
        self.assertEqual(len(logs.output), 1 + _ROSTER_LOG_LIMIT + 1)
        self.assertIn("MeshCore contacts: 350 peers", logs.output[0])
        self.assertIn("… and 340 more", logs.output[-1])

    def test_small_roster_logs_everything_without_more_line(self):
        with self.assertLogs(self.LOGGER, level="INFO") as logs:
            log_meshcore_contact_peers(_contacts(3))
        self.assertEqual(len(logs.output), 1 + 3)
        self.assertNotIn("more", logs.output[-1])

    def test_exactly_limit_has_no_more_line(self):
        with self.assertLogs(self.LOGGER, level="INFO") as logs:
            log_meshcore_contact_peers(_contacts(_ROSTER_LOG_LIMIT))
        self.assertEqual(len(logs.output), 1 + _ROSTER_LOG_LIMIT)

    def test_unnamed_contacts_do_not_burn_roster_slots(self):
        contacts = [{"public_key": "aa", "name": ""}] * 5 + _contacts(2)
        with self.assertLogs(self.LOGGER, level="INFO") as logs:
            log_meshcore_contact_peers(contacts)
        self.assertIn("7 peers", logs.output[0])
        self.assertEqual(len(logs.output), 1 + 2)  # only the named two


if __name__ == "__main__":
    unittest.main()
