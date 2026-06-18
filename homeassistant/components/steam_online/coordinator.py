"""Data update coordinator for the Steam integration."""

import asyncio
from datetime import timedelta
from html.parser import HTMLParser

from aiohttp import ClientError, ClientResponseError
import steam
from steam.api import _interface_method as INTMethod

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ACCOUNTS,
    DOMAIN,
    LOGGER,
    STEAM_ID64_IDENTIFIER,
    STEAM_MINIPROFILE_URL,
)

type SteamConfigEntry = ConfigEntry[SteamDataUpdateCoordinator]


class SteamRichPresenceParser(HTMLParser):
    """Parse rich presence from Steam miniprofile HTML."""

    def __init__(self) -> None:
        """Initialize the parser."""
        super().__init__()
        self.rich_presence: str | None = None
        self._capture_data = False
        self._data: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Handle start tag."""
        if tag != "span":
            return

        attrs_dict = dict(attrs)
        class_names = (attrs_dict.get("class", "") or "").split()
        if "rich_presence" in class_names:
            self._capture_data = True
            self._data = []

    def handle_data(self, data: str) -> None:
        """Handle data."""
        if self._capture_data:
            self._data.append(data)

    def handle_endtag(self, tag: str) -> None:
        """Handle end tag."""
        if tag == "span" and self._capture_data:
            self.rich_presence = "".join(self._data).strip() or None
            self._capture_data = False


class SteamDataUpdateCoordinator(
    DataUpdateCoordinator[dict[str, dict[str, str | int]]]
):
    """Data update coordinator for the Steam integration."""

    config_entry: SteamConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: SteamConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            logger=LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )
        self.game_icons: dict[int, str] = {}
        self.player_interface: INTMethod = None
        self.user_interface: INTMethod = None
        self._session = async_get_clientsession(hass)
        steam.api.key.set(self.config_entry.data[CONF_API_KEY])

    def _update(self) -> dict[str, dict[str, str | int]]:
        """Fetch data from API endpoint."""
        accounts = self.config_entry.options[CONF_ACCOUNTS]
        _ids = list(accounts)
        if not self.user_interface or not self.player_interface:
            self.user_interface = steam.api.interface("ISteamUser")
            self.player_interface = steam.api.interface("IPlayerService")
        if not self.game_icons:
            for _id in _ids:
                res = self.player_interface.GetOwnedGames(
                    steamid=_id, include_appinfo=1
                )["response"]
                self.game_icons = self.game_icons | {
                    game["appid"]: game["img_icon_url"] for game in res.get("games", [])
                }
        response = self.user_interface.GetPlayerSummaries(steamids=_ids)
        players = {
            player["steamid"]: player
            for player in response["response"]["players"]["player"]
            if player["steamid"] in _ids
        }
        for value in players.values():
            data = self.player_interface.GetSteamLevel(steamid=value["steamid"])
            value["level"] = data["response"].get("player_level")
        return players

    async def _async_get_rich_presence(self, steam_id: str) -> str | None:
        """Fetch rich presence from Steam miniprofile."""
        miniprofile_id = int(steam_id) - STEAM_ID64_IDENTIFIER
        try:
            async with self._session.get(
                f"{STEAM_MINIPROFILE_URL}{miniprofile_id}"
            ) as response:
                response.raise_for_status()
                html = await response.text()
        except (ClientError, TimeoutError, ValueError) as ex:
            if not (isinstance(ex, ClientResponseError) and ex.status == 404):
                LOGGER.debug("Failed to fetch Steam rich presence: %s", ex)
            return None

        parser = SteamRichPresenceParser()
        parser.feed(html)
        return parser.rich_presence

    async def _async_add_rich_presence(
        self, players: dict[str, dict[str, str | int]]
    ) -> None:
        """Add rich presence to players."""
        rich_presences = await asyncio.gather(
            *(
                self._async_get_rich_presence(str(player["steamid"]))
                for player in players.values()
            )
        )
        for player, rich_presence in zip(players.values(), rich_presences, strict=True):
            if rich_presence:
                player["rich_presence"] = rich_presence

    async def _async_update_data(self) -> dict[str, dict[str, str | int]]:
        """Send request to the executor."""
        try:
            players = await self.hass.async_add_executor_job(self._update)
            await self._async_add_rich_presence(players)
            return players

        except (steam.api.HTTPError, steam.api.HTTPTimeoutError) as ex:
            if "401" in str(ex):
                raise ConfigEntryAuthFailed from ex
            raise UpdateFailed(ex) from ex
