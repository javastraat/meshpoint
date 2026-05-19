# v0.7.4 — Test results log

Append-only record of hardware and browser validation runs. **Ship gate:** every cell in [README.md](README.md) sign-off matrix must be `[x]` (full pass for that feature × column) before tagging `v0.7.4`. Partial passes stay here and in per-feature **Status** lines until the checklist is fully green.

## How to log a run

| Field | What to write |
|-------|----------------|
| **Date** | UTC or local, ISO `YYYY-MM-DD` |
| **Unit** | `.141` (RAK V2), `.15` (SenseCap M1), `.49` (fresh SD), or `browser-only` |
| **Commit** | `git log -1 --oneline` on the Pi or `origin/feat/v0.7.4` SHA |
| **Feature** | Matches a README matrix row or `docs/plans/v0.7.4-tests/<file>.md` section |
| **Result** | `pass`, `partial`, `fail`, or `blocked` |
| **Tester** | Who ran it (human / agent session label) |
| **Notes** | What was exercised, evidence, blockers |

After a **pass** for an entire feature on a unit, tick the matching README matrix cell and set that section's **Status: Pass** in the feature file.

## Legend (sign-off matrix)

| Symbol in matrix | Meaning |
|------------------|---------|
| `[x]` | Full checklist green for that column |
| `partial` | Some steps pass; see RESULTS; **does not** satisfy ship gate |
| `[ ]` | Not started or not complete |
| `n/a` | Column does not apply |

---

## Log

| Date | Unit | Commit | Feature | Result | Tester | Notes |
|------|------|--------|---------|--------|--------|-------|
| 2026-05-19 | .141 | `e64492b` | Configuration > Transmit | partial | agent | Relay: `GET` exposes `transmit.relay`; `PUT` persists `max_relay_per_minute` to `relay:` in `local.yaml`; UI Save shows success; settings survive service restart. Not run: TX power change, relay off/on soak, duty slider walkthrough from configuration.md §4. |
| 2026-05-19 | .141 | `e64492b` | Dangerous > Restart service | pass | agent | `POST /api/dangerous/invoke` → `success: true`, message `service restart initiated` (detached systemctl). Audit `dangerous.restart_service` with `params.success: true`. UI Settings > Meshpoint: Confirm modal → inline `service restart initiated`. Fix: `e64492b` detached restart (was false failure when subprocess killed mid-wait). |
| 2026-05-19 | .141 | `e64492b` | Spectral scan §1 (packet-derived) | pass | agent | Default path: journal shows spectral scan disabled / packet-derived fallback; service stable; sidebar noise floor populates from RX (per spectral_scan.md status). §2–8 and browser §9 not run on this date. |
| 2026-05-19 | .141 | (prior) | Native relay (onboard SX1302) | pass | (prior session) | README matrix already `[x] .141`. See relay.md. |

---

## Open blockers (ship)

| Feature | Unit | Blocker |
|---------|------|---------|
| (none recorded) | | |

---

## Next scheduled runs

1. **foundation.md** §1–5 on `.141` (sidebar + IA + map scrollbars)
2. **configuration.md** remaining subsections on `.141`, then parity on `.15`
3. **dangerous.md** §2–5 on `.141` (concentrator restart, clear DB, wipe phantoms, force NodeInfo)
4. **spectral_scan.md** §1 on `.15`, §9 browser sparkline on `.141`
