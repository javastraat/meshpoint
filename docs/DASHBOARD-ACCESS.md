# Dashboard access

The dashboard needs a login: the administrator, or an optional read-only
**Viewer**. Next to that there is an optional **public view**: a separate
page with a few aggregate numbers that anyone can open without a login.
It is off by default.

## Access levels

| Login | What it can see | What it can change |
| --- | --- | --- |
| Administrator | Everything: dashboard, stats, messages, radio, configuration, Settings, plugin pages, and the Terminal if it's switched on | Everything |
| Viewer | Dashboard, Stats, Messages, Radio and the configuration pages | Nothing, except its own password |
| Public visitor (no login, only when switched on) | Only the aggregate numbers of the chosen pages, see below | Nothing |

A Viewer is for people you trust: it reads your conversations and node
information. In Messages, New, compose and delete are hidden, and opening a
conversation doesn't mark it read. The server enforces this on its own,
whatever the page shows: every request other than GET/HEAD/OPTIONS from a
Viewer is refused (`403`), for core and plugin routes alike. Settings and
the Terminal are administrator-only.

## Enable a Viewer login

1. Sign in as administrator and open **Settings → Auth**.
2. Under **Viewer role**, enter and confirm a Viewer password, then click
   **Enable viewer**.
3. In a private browser window, sign in as `viewer` and check what it shows.

**Disable viewer** removes the Viewer login again. **Sign out everywhere**
ends all open sessions at once; use it when a password may have leaked.

## Public view (optional)

Settings → Auth → **Public view**: tick *Enable public viewing*, choose the
pages to share, and save. A signed-out visitor who opens the dashboard
address then gets a read-only summary page (with an *Admin sign in* link)
instead of the login page. It refreshes every 15 seconds.

| Page | What a visitor sees |
| --- | --- |
| Dashboard | Number of known nodes, and how many were active in the last 24 hours |
| Stats | Stored packets, packets in the last hour, packets per minute, average RSSI and SNR |
| Radio | Configured region, frequency, bandwidth and spreading factor |

Never shown: node names or IDs, positions, messages, payloads, keys or any
configuration. The visitor gets no login session and no live connection;
every other page and API stays behind the login. The numbers are cached for
10 seconds, so many visitors don't load the Pi. Switching a page off (or the
whole public view) takes effect at once. Check it in a private browser
window before sharing the address.

## Things only the device itself can switch on

Some switches have no dashboard or API route on purpose, so a stolen
administrator session can't turn them on by itself. Set them by hand in
`config/local.yaml` and restart Meshpoint:

- **Web terminal:** `dashboard.web_terminal_toggle: true` shows the
  Settings → System card, which then switches `web_terminal_enabled`. While
  the terminal is on, an administrator session is effectively root on the
  Pi. See [Configuration](CONFIGURATION.md).
- **Plugin sources:** `plugin_sources_enabled: true`. Plugins are trusted
  code with the service's privileges, not a sandbox. See
  [Plugins](PLUGINS.md).

Restoring a backup also brings back its configuration and plugin data: only
restore archives you trust.

## Troubleshooting

- **Viewer gets `403` or sees a control that does nothing:** expected. Sign
  in as administrator to make changes.
- **Still seeing the administrator's view:** use a private window, or sign
  out first; the browser keeps the last session.
- **Viewer login refused:** check under Settings → Auth that the Viewer
  role is enabled. Forgotten passwords and lockouts:
  [Common errors](COMMON-ERRORS.md#authentication).

Security policy and how to report a problem: [SECURITY.md](../.github/SECURITY.md).
