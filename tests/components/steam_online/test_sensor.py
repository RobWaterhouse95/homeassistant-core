"""Tests for the Steam sensor."""

from homeassistant.core import HomeAssistant

from tests.test_util.aiohttp import AiohttpClientMocker

from . import (
    ACCOUNT_1,
    RICH_PRESENCE,
    create_entry,
    mock_miniprofile,
    patch_interface,
)


async def test_sensor_rich_presence(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test sensor exposes rich presence."""
    entry = create_entry(hass)
    mock_miniprofile(aioclient_mock)

    with patch_interface():
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(f"sensor.steam_{ACCOUNT_1}")

    assert state
    assert state.state == "online"
    assert state.attributes["rich_presence"] == RICH_PRESENCE


async def test_sensor_no_rich_presence(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test sensor omits rich presence when it is not available."""
    entry = create_entry(hass)
    mock_miniprofile(aioclient_mock, rich_presence=None)

    with patch_interface():
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(f"sensor.steam_{ACCOUNT_1}")

    assert state
    assert "rich_presence" not in state.attributes
