# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.8.x   | Yes       |
| < 0.8   | No        |

## Reporting a Vulnerability

If you discover a security vulnerability in this fork of Meshpoint
(`javastraat/meshpoint`), please report it responsibly. **Do not open a public
GitHub issue.**

Report it privately through GitHub: on
[javastraat/meshpoint](https://github.com/javastraat/meshpoint) open the
**Security** tab and choose **Report a vulnerability**
([direct link](https://github.com/javastraat/meshpoint/security/advisories/new)).
Include:

- Description of the vulnerability
- Steps to reproduce
- Affected component (edge, cloud, installer, config)
- Potential impact
- Any suggested fix (optional)

You will receive an acknowledgment within 48 hours. We will work with you to
understand the scope, develop a fix, and coordinate disclosure.

## Scope

The following are in scope for security reports:

- Authentication and authorization flaws
- Encryption or key handling issues
- Remote code execution
- Privilege escalation
- Data exposure (API keys, credentials, user data)
- Installer or provisioning script vulnerabilities
- Denial of service against the edge device

## Out of Scope

- Vulnerabilities in upstream dependencies (report those to the upstream project)
- RF interference or jamming (physical layer, not software)
- Issues requiring physical access to the Raspberry Pi

## Viewer role, web terminal and plugins

What these mean in this fork (adapted from upstream `b91d994b`):

- **Viewer** is a read-only login: every request other than GET/HEAD/OPTIONS
  needs an admin session, for core and plugin routes alike, except changing
  the Viewer's own password. A Viewer can still
  read more than an anonymous visitor, including conversations: only give it
  to people you'd let read your messages. Report any route that lets a Viewer
  change something.
- **Web terminal** is off by default, and needs two switches in `local.yaml`
  (`dashboard.web_terminal_toggle`, then `dashboard.web_terminal_enabled`).
  While it's on, an admin session is effectively root on the Pi. The first
  switch has no dashboard or API route on purpose, so a stolen admin session
  can't turn the terminal on by itself.
- **Plugins** are trusted code, not a sandbox: they run with the service's
  privileges, and a source's `setup.sh` runs as root. Plugin sources are off
  until `plugin_sources_enabled: true` is set by hand in `local.yaml` (no
  dashboard or API route, like the terminal switch); adding one asks for
  confirmation, and installs are pinned to a commit. A pin makes a revision
  explicit, it doesn't certify it. Only install code and restore backups you
  trust.

## Disclosure

We follow coordinated disclosure. We ask that you give us reasonable time to
address the issue before any public disclosure. We will credit reporters in
release notes unless anonymity is requested.
