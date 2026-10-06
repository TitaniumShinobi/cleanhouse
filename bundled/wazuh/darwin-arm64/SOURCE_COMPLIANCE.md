# Corresponding source

The corresponding upstream source for the pinned agent is Wazuh tag `v4.14.7`:

https://github.com/wazuh/wazuh/tree/v4.14.7

The approved vendoring step stores `wazuh-4.14.7-source.tar.gz` beside the
binary package and records its SHA-512 in `manifest.json`. Before a CleanHouse
release redistributes the binary package, its release must publish that source
archive and checksum from the same download location. Release publication
remains blocked until counsel confirms the GPL-2.0-only distribution materials
and source-availability method.
