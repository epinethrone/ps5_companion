# PS5 Companion

A single Home Assistant `media_player` entity that brings together everything you usually need to glue manually for a polished PS5 dashboard:

- 🎮 **Active-profile detection** across all PlayStation Network accounts you have configured (no hardcoded usernames; new friends/profiles auto-extend)
- 🖼️ **Cover-art mirroring** with local file cache so the dashboard tile loads instantly instead of round-tripping PSN's CDN
- ⏻ **Power control** via the [ps5-mqtt add-on](https://github.com/funkypenguin/ps5-mqtt) (PS5 doesn't support standard Wake-on-LAN)
- 🔊 **Volume delegation** to any `media_player` you choose (Sonos, Apple TV, Echo, etc.) — hidden if you don't want it

Replaces what used to be a stack of template sensors, an automation, a shell command, and a `custom_universal_media_player` HACS install — all condensed into a single config-flow setup.

See the README for installation + migration steps.
