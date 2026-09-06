#!c=1
# ---------------------------------------------------------------------------
# Sample NomadNet node page for the Meshpoint reticulum plugin.
#
# Copy this file to your node's pages directory and restart Meshpoint:
#
#     mkdir -p /opt/meshpoint/data/reticulum/pages
#     cp plugins/apps/reticulum/sample-pages/index.mu \
#        /opt/meshpoint/data/reticulum/pages/index.mu
#     sudo systemctl restart meshpoint
#
# A file at <node_pages_dir>/index.mu REPLACES the built-in landing page.
# The built-in live-stats page keeps working either way at /page/info.mu -
# it's always served, even with a custom index.mu in place, so link to it
# for uptime / peer counts (see the Links section below).
#
# Extra .mu files in the same dir are served at /page/<name>.mu
# Files under a files/ subdir are served at /file/<relpath>
# Handlers are registered once at startup, so new files need a restart.
#
# Micron quick reference:
#   `F0a0 ... `f   foreground colour (3 hex) ... revert
#   `Bf00 ... `b   background colour ... revert
#   `!  `_  `*     bold / underline / italic toggle
#   `c  `r  `a     centre / right align / revert align
#   ``             reset all formatting
#   >  >>  >>>      headings
#   -              horizontal divider
#   `[label`url]        link  (`:/page/x.mu = this node, that path)
#   `<name`Default>     input field (for forms)
# ---------------------------------------------------------------------------

`c`F0a0`!My Meshpoint`!`f
`cA multi-protocol LoRa mesh gateway
`a
-

Welcome. This node runs `*Meshpoint`* on a SenseCap M1 - it captures and
relays Meshtastic, MeshCore, LoRaWAN, POCSAG/DAPNET and Reticulum traffic,
and hosts this NomadNet page on the `!same identity`! as its LXMF address.

You can browse this node here `!and`! message it over LXMF on the same hash.

>Links

`[Live stats & nodes heard`:/page/info.mu]
`[Nodes this Meshpoint has heard`:/page/nodes.mu]
`[Meshpoint on GitHub`https://github.com/javastraat/meshpoint]

>Contact

`Foperator  : `f`!YOURCALL`!
`Flocation  : `fyour town, grid QTHLOC
`Fnotes     : `freply to this address over LXMF

-
`cEdit me: plugins/apps/reticulum/sample-pages/index.mu`a
