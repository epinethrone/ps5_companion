"""PS5 Companion media_player entity.

A single entity that consolidates everything you previously needed several
template sensors, an automation, a shell_command, and the
custom_universal_media_player HACS integration to do:

- Resolves which PSN profile is "active" right now from all profiles the
  playstation_network integration exposes (no hardcoded user names).
- Reflects the active game's title and trophy progress.
- Caches the current game's cover art locally so the dashboard tile loads
  instantly instead of round-tripping PSN's CDN on every render.
- Falls back to a bundled default cover (PSN logo on white) when the PS5
  is idle or no profile is online.
- Routes turn_on / turn_off to the user-selected MQTT switch from the
  ps5-mqtt addon (PS5 wake protocol — Wake-on-LAN won't work on PS5).
- Routes volume controls to an optional user-selected media_player (the
  speaker your PS5 audio actually plays through). Hidden if unconfigured.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import slugify

from .const import (
    CONF_POWER_SWITCH,
    CONF_PSN_ENTRY_ID,
    CONF_VOLUME_DELEGATE,
    COVER_FILENAME_FMT,
    DEFAULT_COVER_DIR,
    DEFAULT_COVER_FILENAME,
    DOMAIN,
    LOCAL_URL_PREFIX,
    PROFILE_IDLE_VALUES,
    PSN_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Regex to identify PSN per-profile sensors we iterate over
_NOW_PLAYING_RE = re.compile(r"^sensor\.(.+)_now_playing$")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the PS5 Companion media_player from a config entry."""
    async_add_entities([PS5CompanionMediaPlayer(hass, entry)], update_before_add=True)


class PS5CompanionMediaPlayer(MediaPlayerEntity):
    """Single consolidated PS5 media_player entity."""

    _attr_has_entity_name = True
    _attr_name = None  # use device name
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_icon = "mdi:sony-playstation"
    _attr_should_poll = False  # we're event-driven from source-entity state changes

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Init."""
        self.hass = hass
        self._entry = entry

        config = {**entry.data, **entry.options}
        self._psn_entry_id: str = config[CONF_PSN_ENTRY_ID]
        self._power_switch: str = config[CONF_POWER_SWITCH]
        self._volume_delegate: str | None = config.get(CONF_VOLUME_DELEGATE)

        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}"
        self._attr_name = config.get(CONF_NAME)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=config.get(CONF_NAME),
            manufacturer="Sony",
            model="PlayStation 5",
        )

        # Internal state derived from source entities; recomputed on every change.
        self._active_profile_slug: str | None = None
        self._active_profile_display: str | None = None
        self._active_now_playing: str | None = None
        self._active_trophy_level: str | None = None
        self._active_cover_url: str | None = None  # /local/ path
        self._cover_download_task: asyncio.Task | None = None
        self._last_downloaded_slug: str | None = None

        self._unsub_state_listener: callable | None = None

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Expose volume controls only if a delegate is configured."""
        features = (
            MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF
        )
        if self._volume_delegate:
            features |= (
                MediaPlayerEntityFeature.VOLUME_SET
                | MediaPlayerEntityFeature.VOLUME_STEP
                | MediaPlayerEntityFeature.VOLUME_MUTE
            )
        return features

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Subscribe to source-entity state changes."""
        # Watch all PSN-integration entities + the chosen power switch +
        # the optional volume delegate. We re-evaluate state on any change.
        watched = self._collect_watched_entities()
        self._unsub_state_listener = async_track_state_change_event(
            self.hass, watched, self._handle_source_change
        )
        # Initial sync from current state.
        await self._async_recompute()

    async def async_will_remove_from_hass(self) -> None:
        """Cleanup listeners."""
        if self._unsub_state_listener:
            self._unsub_state_listener()
            self._unsub_state_listener = None

    def _collect_watched_entities(self) -> list[str]:
        """All entity_ids whose changes should trigger a recompute."""
        registry = er.async_get(self.hass)
        # Every entity attached to the playstation_network config entry.
        psn_entities = [
            ent.entity_id
            for ent in registry.entities.values()
            if ent.config_entry_id == self._psn_entry_id
        ]
        watched = [*psn_entities, self._power_switch]
        if self._volume_delegate:
            watched.append(self._volume_delegate)
        return watched

    @callback
    def _handle_source_change(self, event: Event) -> None:
        """A watched source entity changed — schedule a recompute."""
        # Recompute can do I/O (cover download) so schedule it as a task.
        self.hass.async_create_task(self._async_recompute())

    # ------------------------------------------------------------------
    # State derivation (the core logic ported from the YAML templates)
    # ------------------------------------------------------------------

    async def _async_recompute(self) -> None:
        """Re-derive all of our state from current source entities + write."""
        self._resolve_active_profile()
        self._resolve_now_playing_and_trophy()
        await self._resolve_cover_url()
        self.async_write_ha_state()

    def _iter_psn_profile_slugs(self) -> list[str]:
        """Yield every profile slug for which the PSN integration exposes
        a sensor.<slug>_now_playing entity."""
        registry = er.async_get(self.hass)
        slugs: list[str] = []
        for ent in registry.entities.values():
            if ent.config_entry_id != self._psn_entry_id:
                continue
            if ent.domain != "sensor":
                continue
            m = _NOW_PLAYING_RE.match(ent.entity_id)
            if m:
                slugs.append(m.group(1))
        return sorted(slugs)  # deterministic order

    def _resolve_active_profile(self) -> None:
        """Two-pass: first non-idle now_playing wins; fallback to first online."""
        active_slug: str | None = None
        # Pass 1: actively playing wins
        for slug in self._iter_psn_profile_slugs():
            state = self.hass.states.get(f"sensor.{slug}_now_playing")
            if state and state.state not in PROFILE_IDLE_VALUES:
                active_slug = slug
                break

        # Pass 2: online (signed in to PSN) but not playing
        if active_slug is None:
            for slug in self._iter_psn_profile_slugs():
                state = self.hass.states.get(f"sensor.{slug}_online_status")
                if state and state.state == "online":
                    active_slug = slug
                    break

        self._active_profile_slug = active_slug

        # Display name = canonical PSN online_id (preserves casing)
        if active_slug:
            display_state = self.hass.states.get(f"sensor.{active_slug}_online_id")
            if display_state and display_state.state not in PROFILE_IDLE_VALUES:
                self._active_profile_display = display_state.state
            else:
                self._active_profile_display = active_slug
        else:
            self._active_profile_display = None

    def _resolve_now_playing_and_trophy(self) -> None:
        """Read the active profile's now_playing + trophy_level into local state."""
        if not self._active_profile_slug:
            self._active_now_playing = None
            self._active_trophy_level = None
            return

        slug = self._active_profile_slug
        np_state = self.hass.states.get(f"sensor.{slug}_now_playing")
        if np_state and np_state.state not in PROFILE_IDLE_VALUES:
            # Title-case the game name (PSN returns inconsistent casing)
            self._active_now_playing = np_state.state.lower().title()
        else:
            self._active_now_playing = None

        trophy_state = self.hass.states.get(f"sensor.{slug}_trophy_level")
        if trophy_state and trophy_state.state not in PROFILE_IDLE_VALUES:
            self._active_trophy_level = trophy_state.state
        else:
            self._active_trophy_level = None

    async def _resolve_cover_url(self) -> None:
        """Determine + materialize the cover image, set _active_cover_url."""
        if not self._active_now_playing:
            # Idle — use the default cover
            self._active_cover_url = (
                f"{LOCAL_URL_PREFIX}/{DEFAULT_COVER_DIR.split('/', 1)[-1]}"
                f"/{DEFAULT_COVER_FILENAME}"
            )
            return

        slug = slugify(self._active_now_playing)
        filename = COVER_FILENAME_FMT.format(slug=slug)
        cover_dir = Path(self.hass.config.path(DEFAULT_COVER_DIR))
        cover_path = cover_dir / filename
        public_url = (
            f"{LOCAL_URL_PREFIX}/{DEFAULT_COVER_DIR.split('/', 1)[-1]}/{filename}"
        )

        # Fast path: file already on disk → just use it
        exists = await self.hass.async_add_executor_job(os.path.exists, cover_path)
        if exists:
            self._active_cover_url = public_url
            # Belt-and-suspenders: also kick off a re-download in the background
            # so the file refreshes if PSN updated the artwork. Only one in
            # flight at a time.
            if (
                self._last_downloaded_slug != slug
                and (self._cover_download_task is None or self._cover_download_task.done())
            ):
                self._cover_download_task = self.hass.async_create_task(
                    self._async_download_cover(slug, cover_path)
                )
            return

        # Cover not cached → show default while we download, then update
        self._active_cover_url = (
            f"{LOCAL_URL_PREFIX}/{DEFAULT_COVER_DIR.split('/', 1)[-1]}"
            f"/{DEFAULT_COVER_FILENAME}"
        )
        if self._cover_download_task is None or self._cover_download_task.done():
            self._cover_download_task = self.hass.async_create_task(
                self._async_download_cover(slug, cover_path)
            )

    async def _async_download_cover(self, slug: str, cover_path: Path) -> None:
        """Download the active profile's PSN cover image to cover_path."""
        if not self._active_profile_slug:
            return
        # Get the image URL from the PSN integration's image.<slug>_now_playing entity
        img_state = self.hass.states.get(
            f"image.{self._active_profile_slug}_now_playing"
        )
        if not img_state:
            return
        ep = img_state.attributes.get("entity_picture")
        if not ep:
            return

        # The entity_picture is a relative path like /api/image_proxy/image.x?token=...
        # We need to fetch it via the local HTTP server. async_get_clientsession is
        # an HA-managed session that handles connection pooling correctly.
        url = f"{self._internal_base_url()}{ep}"
        session = async_get_clientsession(self.hass)
        tmp_path = cover_path.with_suffix(".tmp")
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    _LOGGER.debug(
                        "Cover download for %s returned HTTP %d", slug, resp.status
                    )
                    return
                data = await resp.read()
            await self.hass.async_add_executor_job(_atomic_write, tmp_path, cover_path, data)
            self._last_downloaded_slug = slug
            # After download, refresh state so the tile picks up the new URL
            await self._async_recompute()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Cover download for %s failed: %s", slug, err)

    def _internal_base_url(self) -> str:
        """Internal HA base URL for fetching /api/image_proxy/ paths."""
        try:
            # 2024.6+
            return str(self.hass.config.internal_url or self.hass.config.external_url or "")
        except AttributeError:
            return ""

    # ------------------------------------------------------------------
    # Public entity properties (HA reads these)
    # ------------------------------------------------------------------

    @property
    def state(self) -> MediaPlayerState:
        """Off / idle / playing — driven by power switch + active game."""
        ps = self.hass.states.get(self._power_switch)
        if ps is None or ps.state in ("unavailable", "unknown", "off"):
            return MediaPlayerState.OFF
        if self._active_now_playing:
            return MediaPlayerState.PLAYING
        return MediaPlayerState.IDLE

    @property
    def available(self) -> bool:
        """Available if the playstation_network entry is loaded."""
        # Always considered available — even when the PS5 is off, the entity
        # itself is functional (turn_on works, cover shows default, etc.)
        return True

    @property
    def media_title(self) -> str | None:
        """Active profile's current game, title-cased. None when idle."""
        return self._active_now_playing

    @property
    def media_artist(self) -> str | None:
        """Active profile display name (PSN online_id). None when idle."""
        return self._active_profile_display

    @property
    def app_name(self) -> str | None:
        """Same as media_artist for now."""
        return self._active_profile_display

    @property
    def media_album_name(self) -> str | None:
        """Trophy progress, formatted, when a profile is active."""
        if self._active_trophy_level:
            return f"Trophy Level {self._active_trophy_level}"
        return None

    @property
    def source(self) -> str | None:
        """Active profile name."""
        return self._active_profile_display

    @property
    def entity_picture(self) -> str | None:
        """Local /local/... URL to the cached cover, or the default cover."""
        return self._active_cover_url

    # ------------------------------------------------------------------
    # Power — pass-through to the MQTT switch
    # ------------------------------------------------------------------

    async def async_turn_on(self) -> None:
        """Wake the PS5 via the ps5-mqtt addon's switch."""
        await self.hass.services.async_call(
            "switch", "turn_on",
            {"entity_id": self._power_switch},
            blocking=False,
        )

    async def async_turn_off(self) -> None:
        """Send the PS5 to standby via the ps5-mqtt addon's switch."""
        await self.hass.services.async_call(
            "switch", "turn_off",
            {"entity_id": self._power_switch},
            blocking=False,
        )

    # ------------------------------------------------------------------
    # Volume — pass-through to the configured delegate (Sonos, ATV, etc.)
    # ------------------------------------------------------------------

    @property
    def volume_level(self) -> float | None:
        """Mirror the delegate's volume_level."""
        if not self._volume_delegate:
            return None
        state = self.hass.states.get(self._volume_delegate)
        if state is None:
            return None
        v = state.attributes.get("volume_level")
        return float(v) if v is not None else None

    @property
    def is_volume_muted(self) -> bool | None:
        """Mirror the delegate's is_volume_muted."""
        if not self._volume_delegate:
            return None
        state = self.hass.states.get(self._volume_delegate)
        if state is None:
            return None
        v = state.attributes.get("is_volume_muted")
        return bool(v) if v is not None else None

    async def async_set_volume_level(self, volume: float) -> None:
        """Delegate to the configured speaker."""
        if not self._volume_delegate:
            return
        await self.hass.services.async_call(
            "media_player", "volume_set",
            {"entity_id": self._volume_delegate, "volume_level": volume},
            blocking=False,
        )

    async def async_volume_up(self) -> None:
        """Delegate to the configured speaker."""
        if not self._volume_delegate:
            return
        await self.hass.services.async_call(
            "media_player", "volume_up",
            {"entity_id": self._volume_delegate},
            blocking=False,
        )

    async def async_volume_down(self) -> None:
        """Delegate to the configured speaker."""
        if not self._volume_delegate:
            return
        await self.hass.services.async_call(
            "media_player", "volume_down",
            {"entity_id": self._volume_delegate},
            blocking=False,
        )

    async def async_mute_volume(self, mute: bool) -> None:
        """Delegate to the configured speaker."""
        if not self._volume_delegate:
            return
        await self.hass.services.async_call(
            "media_player", "volume_mute",
            {"entity_id": self._volume_delegate, "is_volume_muted": mute},
            blocking=False,
        )


def _atomic_write(tmp_path: Path, final_path: Path, data: bytes) -> None:
    """Write data to tmp_path then atomically rename to final_path.

    Runs in the executor pool (filesystem I/O).
    """
    final_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "wb") as f:
        f.write(data)
    os.replace(tmp_path, final_path)
