# PS5 Companion

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
<img width="521" height="206" alt="Screenshot 2026-05-25 at 19 59 42" src="https://github.com/user-attachments/assets/20286c93-b117-420e-8e92-55bd90f5f9d0" />


A single Home Assistant `media_player` entity that consolidates everything you usually need to glue manually for a polished PS5 dashboard tile:

- 🎮 **Active-profile detection** across all PlayStation Network accounts you have configured. No hardcoded usernames — new friends / profiles added to the PSN integration are auto-picked up.
- 🖼️ **Cover-art mirroring** with a local file cache so the dashboard tile loads instantly instead of round-tripping PSN's CDN on every render. Falls back to a bundled PSN-branded default cover when the PS5 is idle.
- ⏻ **Power control** via the [ps5-mqtt add-on](https://github.com/funkypenguin/ps5-mqtt) (PS5 doesn't support standard Wake-on-LAN, so the add-on is a hard requirement).
- 🔊 **Volume delegation** to any `media_player` you pick (Sonos, Apple TV, Echo, etc.). Hidden if not configured.

Replaces what used to be a stack of template sensors, an automation, a shell command, and the `custom_universal_media_player` HACS plugin — all condensed into a single config-flow setup.

## Requirements

- **Home Assistant 2024.10** or newer
- **[PlayStation Network](https://www.home-assistant.io/integrations/playstation_network/)** integration set up with your PSN account (and any friend sub-entries you want to track)
- **[ps5-mqtt](https://github.com/funkypenguin/ps5-mqtt)** Home Assistant add-on installed and paired with your PS5
- Optional: a `media_player` entity you want to use for volume delegation (Sonos, Apple TV, Echo Show, etc.)

## Installation

### Via HACS (custom repository, until accepted into the default list)

1. Open HACS → Integrations → ⋮ menu → **Custom repositories**
2. Add `https://github.com/epinethrone/ps5_companion` with category **Integration**
3. Find **PS5 Companion** in the list → Install
4. Restart Home Assistant
5. Go to **Settings → Devices & Services → Add Integration** and search for **PS5 Companion**

### Manually

1. Copy the `custom_components/ps5_companion/` folder into your `/config/custom_components/` directory
2. Restart Home Assistant
3. **Settings → Devices & Services → Add Integration** → search for **PS5 Companion**

## Configuration

The config flow auto-detects the PSN integration entry and any PS5 MQTT power switches published by the ps5-mqtt add-on. You just:

1. Confirm or rename the entity
2. Pick which MQTT power switch corresponds to this PS5 (if you have multiple)
3. Optionally pick a `media_player` to delegate volume controls to (leave blank to hide volume slider)

That's it. The entity appears as `media_player.ps5_companion` (or whatever name you gave it).

You can change the volume delegate or power switch later via the integration's **Options** menu.

## How active-profile resolution works

The integration iterates every `sensor.<slug>_now_playing` exposed by the PlayStation Network integration and picks the active profile in priority order:

1. **First profile actively playing a game wins** — `now_playing` not in `[unknown, unavailable, none, '']`
2. **Fallback: first profile online but not playing** — `online_status == 'online'`
3. **Otherwise no active profile** — entity reports `idle`/`off`, cover falls back to default

Ties are broken alphabetically by slug for deterministic behavior. Adding a new friend / account to the PSN integration auto-extends — no config changes needed.

## How cover-art caching works

- On game change: compute slug from title (e.g. "Ghost of Tsushima" → `ghost_of_tsushima`)
- If `/config/www/ps5_companion/cover-<slug>.png` already exists → use it instantly
- Otherwise show the default cover, then download in the background and update on completion
- Downloads are atomic (`.tmp` then `os.replace`) so HA never sees a half-written file

## Power control

`turn_on` / `turn_off` are pass-throughs to the MQTT switch you select in the config flow. The ps5-mqtt add-on implements the actual PS5 wake protocol. Wake-on-LAN does **not** work on PS5 — that's why the add-on is mandatory.

## Volume control

If you set a volume delegate, all volume controls on the PS5 Companion entity (`volume_set`, `volume_up`, `volume_down`, `volume_mute`) are forwarded to the delegate. The volume slider in the UI also mirrors the delegate's current level.

If you leave the delegate blank, volume controls are hidden via `supported_features` — no broken slider, no fake states.

## MIGRATION

If you previously used a YAML-based PS5 setup with template sensors, an automation for cover mirroring, and the `custom_universal_media_player` HACS plugin, the integration will refuse to load until those conflicting entities are removed (to prevent duplicate-state weirdness).

Specifically, remove these from your config if present:

**`/config/configuration.yaml`**:
- All `template:` sensors with `unique_id` matching `ps5_active_*` (now_playing, profile, profile_slug, trophy_level, trophy_label, cover_source, local_cover_url)
- The `binary_sensor.ps5_active_cover_cached` command_line sensor
- The `shell_command.ps5_cover_download` entry
- Your `media_player.ps5_enhanced` / `ps5_enhanced_2` `custom_universal_media_player` block

**`/config/automations.yaml`**:
- The `ps5_cover_mirror` automation

**UI helpers** (Settings → Devices & Services → Helpers):
- `input_text.ps5_cover_current_url`
- Any `sensor.ps5_*` template helpers

**Entity registry** (Settings → Devices & Services → Entities, search "ps5"):
- Delete orphan entries for `media_player.ps5_enhanced`, `sensor.ps5_now_playing`, etc. (they'll show "unavailable")

After cleanup, restart HA and reload the PS5 Companion integration. It should pick up clean.

The new entity will be `media_player.ps5_companion` by default (not `_enhanced`), so existing dashboard cards / automations referencing `media_player.ps5_enhanced_2` will need updating.

## What's deliberately not included (yet)

- HDMI input switching (use the [ps5-mqtt addon's MQTT topics directly in an automation](https://github.com/funkypenguin/ps5-mqtt) for HDMI routing)
- Game library / trophy browsing UI
- Activity tracking beyond what PSN exposes
- Multi-PS5 support (one entry at a time for now — file an issue if you need this)
- Saturation / wall-color exposure (the underlying PSN+MQTT APIs don't expose these for the media_player abstraction)

## Reporting issues

Please include:
- Home Assistant version
- PlayStation Network integration entry shape (primary account + how many friend subentries)
- ps5-mqtt add-on version
- Output of HA logs filtered to `ps5_companion`

## License

MIT — see [LICENSE](LICENSE)

## Credits

Built from the lessons of the [home-assistant/core#156776 thread](https://github.com/home-assistant/core/issues/156776) and the YAML-based PS5 dashboard pattern documented at […fill in your reddit post URL once published…].
