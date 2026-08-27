"""Keep release metadata and public documentation synchronized."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_release_version_and_home_assistant_floor_are_documented():
    manifest = json.loads((ROOT / "custom_components/fluvalble/manifest.json").read_text())
    hacs = json.loads((ROOT / "hacs.json").read_text())
    readme = (ROOT / "README.md").read_text()
    changelog = (ROOT / "CHANGELOG.md").read_text()

    assert f"## [{manifest['version']}]" in changelog
    assert f"Home Assistant {hacs['homeassistant']}" in readme


def test_all_registered_action_schemas_are_listed_in_readme():
    services = yaml.safe_load((ROOT / "custom_components/fluvalble/services.yaml").read_text())
    readme = (ROOT / "README.md").read_text()

    assert set(services) == {
        "set_channels",
        "preview_schedule",
        "stop_preview",
        "save_schedule",
        "set_native_auto_schedule",
        "set_native_pro_schedule",
    }
    for service in services:
        assert f"`fluvalble.{service}`" in readme
