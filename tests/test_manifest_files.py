"""Consistency checks between the integration's JSON/YAML files."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent / "custom_components" / "ev_charge_cost"


def _json(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_icons_match_entities_and_services():
    icons = _json("icons.json")
    strings = _json("strings.json")
    for platform, keys in icons["entity"].items():
        assert set(keys) <= set(strings["entity"][platform]), platform
    services = yaml.safe_load((ROOT / "services.yaml").read_text(encoding="utf-8"))
    assert set(icons["services"]) == set(services)
    for icon in [
        *(v["default"] for keys in icons["entity"].values() for v in keys.values()),
        *(v["service"] for v in icons["services"].values()),
    ]:
        assert icon.startswith("mdi:")


def test_translations_have_the_same_keys():
    def keys(data: dict, prefix: str = "") -> set[str]:
        out = set()
        for key, value in data.items():
            path = f"{prefix}.{key}"
            out |= keys(value, path) if isinstance(value, dict) else {path}
        return out

    reference = keys(_json("strings.json"))
    for language in ("en", "fr"):
        assert keys(_json(f"translations/{language}.json")) == reference, language
