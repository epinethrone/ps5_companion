"""Constants for the PS5 Companion integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "ps5_companion"
DEFAULT_NAME: Final = "PS5 Companion"

# Config flow keys
CONF_POWER_SWITCH: Final = "power_switch"
CONF_VOLUME_DELEGATE: Final = "volume_delegate"
CONF_PSN_ENTRY_ID: Final = "psn_entry_id"
CONF_COVER_PATH: Final = "cover_path"

# Defaults
DEFAULT_COVER_DIR: Final = "www/ps5_companion"  # relative to config dir
COVER_FILENAME_FMT: Final = "cover-{slug}.png"
DEFAULT_COVER_ASSET: Final = "default_cover.jpg"  # bundled with the integration
DEFAULT_COVER_FILENAME: Final = "default_cover.jpg"  # copied to www on first setup

# URL prefix HA exposes for /config/www/
LOCAL_URL_PREFIX: Final = "/local"

# Integration we depend on for game/profile metadata
PSN_DOMAIN: Final = "playstation_network"

# Unique-id suffix the ps5-mqtt addon uses for the power switch entity.
# We auto-detect candidate switches by this pattern in config flow.
PS5_MQTT_POWER_SUFFIX: Final = "_power_ps5mqtt"

# Entities from the user's prior YAML-based setup that must be removed
# before this integration can load (migration option A — refuse-to-load).
# See README for the cleanup steps.
CONFLICTING_ENTITY_IDS: Final = frozenset(
    {
        "media_player.ps5_enhanced",
        "media_player.ps5_enhanced_2",
        "sensor.ps5_active_now_playing",
        "sensor.ps5_active_now_playing_clean",
        "sensor.ps5_active_profile",
        "sensor.ps5_active_profile_slug",
        "sensor.ps5_active_trophy_level",
        "sensor.ps5_active_trophy_label",
        "sensor.ps5_active_cover_source",
        "sensor.ps5_local_cover_url",
        "sensor.ps5_now_playing",
        "input_text.ps5_cover_current_url",
        "binary_sensor.ps5_active_cover_cached",
    }
)

# Profile selection priority (alphabetical = deterministic).
# Pass 1: first non-idle now_playing wins. Pass 2: first online_status='online'.
# Pass 3: none.
PROFILE_IDLE_VALUES: Final = frozenset(
    {"unknown", "unavailable", "none", "None", ""}
)

# How often to refresh derived state on coordinator tick (no external poll —
# we listen for source-entity state changes; this is just a safety heartbeat).
SCAN_INTERVAL_SECONDS: Final = 30
