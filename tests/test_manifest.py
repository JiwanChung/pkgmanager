"""Tests for manifest loading and saving functionality."""

import pytest
import tempfile
import os
from pathlib import Path

import yaml

from onepkg.manifest import (
    load_manifest,
    save_manifest,
    update_raw_manifest,
    get_category_for_type,
)
from onepkg.managers import CATEGORIES

# Aliases for compatibility with existing tests
_load_manifest = load_manifest
_save_manifest = save_manifest
_update_raw_manifest = update_raw_manifest
_get_category_for_type = get_category_for_type


@pytest.fixture
def temp_manifest():
    """Create a temporary manifest file."""
    content = {
        "mac": {
            "brew": ["ripgrep", "fzf"],
            "cask": ["raycast"],
        },
        "general": {
            "python": ["ruff", "pyright"],
            "rust": ["bat", "eza"],
        },
        "custom": ["fisher"],
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        yaml.dump(content, f)
        yield f.name
    os.unlink(f.name)


@pytest.fixture
def empty_manifest():
    """Create an empty temporary manifest file."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        yaml.dump({}, f)
        yield f.name
    os.unlink(f.name)


class TestLoadManifest:
    """Tests for _load_manifest function."""

    def test_load_existing_manifest(self, temp_manifest):
        """Load an existing manifest file."""
        data, raw_data, path = _load_manifest(temp_manifest)
        assert path == Path(temp_manifest)
        assert isinstance(data, dict)
        assert isinstance(raw_data, dict)

    def test_load_empty_manifest(self, empty_manifest):
        """Load an empty manifest file."""
        data, raw_data, path = _load_manifest(empty_manifest)
        assert data == {}
        assert raw_data == {}

    def test_load_nonexistent_manifest(self):
        """Loading nonexistent file should exit."""
        with pytest.raises(SystemExit):
            _load_manifest("/nonexistent/path/manifest.yaml")

    def test_manifest_flattens_structure(self, temp_manifest):
        """Manifest should flatten nested structure."""
        data, raw_data, path = _load_manifest(temp_manifest)
        # Flattened data should have package types as top-level keys
        # (depending on platform, mac packages may or may not be present)
        assert "python" in data or "brew" in data or "rust" in data


class TestSaveManifest:
    """Tests for _save_manifest function."""

    def test_save_and_reload(self):
        """Save manifest and reload to verify."""
        content = {
            "general": {
                "python": ["ruff"],
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            temp_path = Path(f.name)

        try:
            _save_manifest(content, temp_path)
            with open(temp_path) as f:
                loaded = yaml.safe_load(f)
            assert loaded == content
        finally:
            os.unlink(temp_path)


class TestUpdateRawManifest:
    """Tests for _update_raw_manifest function."""

    def test_add_package_to_existing_type(self):
        """Add package to an existing type."""
        raw_data = {
            "general": {
                "python": ["ruff"],
            },
        }
        _update_raw_manifest(raw_data, "python", "pyright", "add")
        assert "pyright" in raw_data["general"]["python"]

    def test_add_package_to_new_type(self):
        """Add package to a new type."""
        raw_data = {
            "general": {
                "python": ["ruff"],
            },
        }
        _update_raw_manifest(raw_data, "rust", "bat", "add")
        assert "bat" in raw_data["general"]["rust"]

    def test_remove_package(self):
        """Remove package from manifest."""
        raw_data = {
            "general": {
                "python": ["ruff", "pyright"],
            },
        }
        _update_raw_manifest(raw_data, "python", "ruff", "remove")
        assert "ruff" not in raw_data["general"]["python"]
        assert "pyright" in raw_data["general"]["python"]

    def test_add_custom_package(self):
        """Add custom package."""
        raw_data = {}
        _update_raw_manifest(raw_data, "custom", "my-tool", "add")
        assert "my-tool" in raw_data["custom"]

    def test_remove_custom_package(self):
        """Remove custom package."""
        raw_data = {
            "custom": ["fisher", "my-tool"],
        }
        _update_raw_manifest(raw_data, "custom", "fisher", "remove")
        assert "fisher" not in raw_data["custom"]
        assert "my-tool" in raw_data["custom"]

    def test_add_duplicate_package(self):
        """Adding duplicate package should not create duplicate."""
        raw_data = {
            "general": {
                "python": ["ruff"],
            },
        }
        _update_raw_manifest(raw_data, "python", "ruff", "add")
        assert raw_data["general"]["python"].count("ruff") == 1


class TestGetCategoryForType:
    """Tests for _get_category_for_type function."""

    def test_mac_types(self):
        """Mac types should return 'mac' category."""
        assert _get_category_for_type("brew") == "mac"
        assert _get_category_for_type("cask") == "mac"
        assert _get_category_for_type("mas") == "mac"

    def test_general_types(self):
        """General types should return 'general' category."""
        assert _get_category_for_type("python") == "general"
        assert _get_category_for_type("rust") == "general"
        assert _get_category_for_type("conda") == "general"
        assert _get_category_for_type("bun") == "general"

    def test_wsl_types(self):
        """WSL types should return 'wsl' category."""
        assert _get_category_for_type("winget") == "wsl"

    def test_custom_type(self):
        """Custom type should return 'custom' category."""
        assert _get_category_for_type("custom") == "custom"

    def test_unknown_type(self):
        """Unknown type should return None."""
        assert _get_category_for_type("unknown") is None
