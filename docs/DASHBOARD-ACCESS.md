# Dashboard access

The dashboard always needs a login. There are two kinds: the administrator,
and an optional read-only **Viewer**. There is no public, no-login view in
this fork.

## Access levels

| Login | What it can see | What it can change |
| --- | --- | --- |
| Administrator | Everything: dashboard, stats, messages, radio, configuration, Settings, plugin pages, and the Terminal if it's switched on | Everything |
| Viewer | Dashboard, Stats, Messages, Radio and the configuration pages | Nothing, except its own password |

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
