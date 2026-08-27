"""APK-native Fluval classic light effects."""

from __future__ import annotations

from collections.abc import Mapping

# Home Assistant exposes this as the user-selectable way to leave a native
# effect and return to a normal static channel mix.
EFFECT_NONE = "None"

# FluvalConnect weather icons map to these classic 0x680A effect IDs.
# The APK presents them in a different order: 9,10,11,5,6,7,8,1,2,3,4.
WEATHER_EFFECTS: Mapping[str, int] = {
    "Thunderstorm": 1,
    "Lightning": 2,
    "Sun and lightning": 3,
    "Colour cycle": 4,
    "Mostly sunny": 5,
    "Partly sunny": 6,
    "Partly cloudy": 7,
    "Mostly cloudy": 8,
    "Full moon": 9,
    "Half moon": 10,
    "Crescent moon": 11,
}

# FluvalConnect's Plant Pro / mesh picker exposes the asset/command indices
# ``[4, 3, 1, 2]``. The APK resources identify those numbered assets as Sun,
# Crescent Moon, Full Moon, and Half Moon. Reusing the classic 0x680A names for
# these IDs made static sun/moon scenes appear as broken lightning/color-cycle
# effects even though the transmitted mesh IDs were correct.
MESH_WEATHER_EFFECTS: Mapping[str, int] = {
    "Sun": 4,
    "Crescent moon": 3,
    "Full moon": 1,
    "Half moon": 2,
}


def effect_list() -> list[str]:
    """Return the HA effect list for classic Fluval weather effects."""
    return [EFFECT_NONE, *WEATHER_EFFECTS]


def mesh_effect_list() -> list[str]:
    """Return the HA effect list for Plant Pro / mesh weather effects."""
    return [EFFECT_NONE, *MESH_WEATHER_EFFECTS]


def effect_id(effect: str) -> int | None:
    """Return the classic 0x680A effect id for a Home Assistant effect name."""
    return WEATHER_EFFECTS.get(effect)


def mesh_effect_id(effect: str) -> int | None:
    """Return the Plant Pro / mesh key-14 weather effect id."""
    return MESH_WEATHER_EFFECTS.get(effect)
