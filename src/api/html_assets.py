"""Cache-busting for the dashboard's static JS/CSS asset URLs.

After a dashboard self-update, browsers kept executing stale cached
JS against the freshly deployed index.html — features died silently
with no console errors until a manual "Empty Cache and Hard Reload"
(bit twice: dead backup buttons after the v0.7.7 merge apply, dead
topbar chips after the chip unification).

Fix: the ``/`` route rewrites every local ``.js``/``.css`` URL in
index.html to carry a ``?v=<token>`` query. The token is minted once
per process, and every dashboard apply ends in a service restart, so
each deploy serves new asset URLs and the browser refetches. External
URLs (http/https/protocol-relative) are left untouched.

Kept free of FastAPI imports so the rewrite logic unit-tests on the
Mac (same pattern as src/serve.py keeping uvicorn inside main()).
"""

from __future__ import annotations

import re
import time

# Per-process token: hex timestamp, minted at import (= service start).
BOOT_TOKEN = f"{int(time.time()):x}"

# src="..." / href="..." values ending in .js or .css, skipping
# external URLs (http://, https://, //cdn...). Matches relative
# ("js/app.js") and root-relative ("/vendor/xterm/xterm.js") paths.
_ASSET_URL_RE = re.compile(
    r'((?:src|href)=")(?!https?://|//)([^"?]+\.(?:js|css))(")'
)


def bust_asset_urls(html: str, token: str = BOOT_TOKEN) -> str:
    """Append ``?v=<token>`` to every local JS/CSS asset URL in *html*."""
    return _ASSET_URL_RE.sub(rf'\g<1>\g<2>?v={token}\g<3>', html)
