"""PS5 Companion integration.

Consolidates the PS5 media player experience that was previously spread
across multiple YAML automations, template sensors, and shell commands:
profile detection, cover-art mirroring, MQTT power control, and optional
volume delegation — all behind a single media_player entity.

See README.md for setup instructions and architecture.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .const import (
    CONFLICTING_ENTITY_IDS,
    DEFAULT_COVER_ASSET,
    DEFAULT_COVER_DIR,
    DEFAULT_COVER_FILENAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PS5 Companion from a config entry."""
    # Migration safety check: refuse to set up if the user still has the
    # old YAML-based setup active. See README MIGRATION section.
    registry = er.async_get(hass)
    conflicts = [
        eid for eid in CONFLICTING_ENTITY_IDS
        if registry.async_get(eid) is not None
    ]
    if conflicts:
        _LOGGER.error(
            "PS5 Companion cannot load while the older YAML-based setup is "
            "still active. Please remove these entities first: %s. See the "
            "MIGRATION section in the integration README for cleanup steps. "
            "After cleanup, restart HA and reload this integration.",
            ", ".join(sorted(conflicts)),
        )
        raise ConfigEntryNotReady(
            f"Conflicting legacy entities present ({len(conflicts)}). "
            "See logs and README MIGRATION section."
        )

    # Ensure the default cover image is materialized in /config/www/ps5_companion/
    # so it can be served at /local/ps5_companion/default_cover.jpg
    await hass.async_add_executor_job(_ensure_default_cover, hass)

    hass.data.setdefault(DOMAIN, {})
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _ensure_default_cover(hass: HomeAssistant) -> None:
    """Copy the bundled default-cover asset to /config/www/ps5_companion/
    on first setup. Idempotent — won't overwrite a user-customized file.

    Runs in the executor pool (filesystem I/O).
    """
    src = Path(__file__).parent / "assets" / DEFAULT_COVER_ASSET
    dest_dir = Path(hass.config.path(DEFAULT_COVER_DIR))
    dest = dest_dir / DEFAULT_COVER_FILENAME

    dest_dir.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy(src, dest)
        _LOGGER.debug("Installed default cover to %s", dest)
