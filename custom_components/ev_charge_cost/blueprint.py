"""Install the blueprints shipped with the integration."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SOURCE_DIR = Path(__file__).parent / "blueprints"


def _install(target_dir: Path) -> list[str]:
    """Copy missing blueprints; never overwrite a file the user may have edited."""
    installed = []
    for source in sorted(SOURCE_DIR.glob("*.yaml")):
        target = target_dir / source.name
        if target.exists():
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        installed.append(source.name)
    return installed


async def async_install_blueprints(hass: HomeAssistant) -> None:
    target_dir = Path(hass.config.path("blueprints", "automation", DOMAIN))
    try:
        installed = await hass.async_add_executor_job(_install, target_dir)
    except OSError as err:
        _LOGGER.warning("Could not install blueprints in %s: %s", target_dir, err)
        return
    if installed:
        _LOGGER.info("Installed blueprints %s in %s", installed, target_dir)
