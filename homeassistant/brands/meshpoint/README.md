# Brand assets for home-assistant/brands

These are staged for submission to the community
[home-assistant/brands](https://github.com/home-assistant/brands) repo —
that's the only thing that makes the "Select brand" / Add Integration
picker show a Meshpoint icon instead of "icon not available". Files here
have no effect until merged there; nothing in this repo or the integration
itself can supply that icon locally.

Cropped from `MP_logo.png` at the repo root.

## To submit

1. Fork `home-assistant/brands`
2. Add these four files under `custom_integrations/meshpoint/` in the fork:
   `icon.png` (256×256), `icon@2x.png` (512×512), `logo.png`, `logo@2x.png`
3. Open a PR. Their CI (`python3 script/validate.py`) checks size/format —
   these were generated at exactly 256×256 / 512×512 RGBA PNG, should pass.
4. Once merged, the icon shows up everywhere (any HA instance, anyone's
   HACS install) after the brands CDN cache rolls over — not just for you.
