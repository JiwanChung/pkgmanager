"""Tests for manifest parsing and package entry handling."""

import pytest
import tempfile
import os
from pathlib import Path

import yaml

from onepkg.manifest import (
    parse_package_entry,
    parse_custom_entry,
    package_in_list,
    find_package_manifest_type,
    resolve_package_manager,
    resolve_all_packages,
)
from onepkg.utils import platform_matches
from onepkg.models import CustomPackageConfig
from onepkg.managers import CUSTOM_MANAGER

# Aliases for compatibility with existing tests
_parse_package_entry = parse_package_entry
_parse_custom_entry = parse_custom_entry
_platform_matches = platform_matches
_package_in_list = package_in_list
_find_package_manifest_type = find_package_manifest_type
_resolve_package_manager = resolve_package_manager
_resolve_all_packages = resolve_all_packages


class TestParsePackageEntry:
    """Tests for _parse_package_entry function."""

    def test_simple_package_name(self):
        """Simple package name without preferred manager."""
        name, preferred = _parse_package_entry("ripgrep")
        assert name == "ripgrep"
        assert preferred is None

    def test_package_with_preferred_manager(self):
        """Package with preferred manager using fallback syntax."""
        name, preferred = _parse_package_entry("tmux:brew")
        assert name == "tmux"
        assert preferred == "brew"

    def test_package_with_complex_name(self):
        """Package with multiple colons in name (shouldn't happen but test edge case)."""
        name, preferred = _parse_package_entry("some:package:name")
        assert name == "some"
        assert preferred == "package:name"

    def test_empty_string(self):
        """Empty string should return empty name."""
        name, preferred = _parse_package_entry("")
        assert name == ""
        assert preferred is None


class TestParseCustomEntry:
    """Tests for _parse_custom_entry function."""

    def test_simple_string_entry(self):
        """Simple string entry returns name and no platforms."""
        name, platforms = _parse_custom_entry("fisher")
        assert name == "fisher"
        assert platforms is None

    def test_dict_entry_with_name(self):
        """Dict entry with just name."""
        entry = {"name": "my-tool"}
        name, platforms = _parse_custom_entry(entry)
        assert name == "my-tool"
        assert platforms is None

    def test_dict_entry_with_platform(self):
        """Dict entry with platform constraint."""
        entry = {"name": "linux-tool", "platform": "linux"}
        name, platforms = _parse_custom_entry(entry)
        assert name == "linux-tool"
        assert platforms == "linux"

    def test_dict_entry_with_platforms_list(self):
        """Dict entry with platforms list."""
        entry = {"name": "multi-platform", "platforms": ["darwin", "linux"]}
        name, platforms = _parse_custom_entry(entry)
        assert name == "multi-platform"
        assert platforms == ["darwin", "linux"]

    def test_invalid_entry_type(self):
        """Invalid entry type returns None."""
        name, platforms = _parse_custom_entry(123)
        assert name is None
        assert platforms is None


class TestPlatformMatches:
    """Tests for _platform_matches function."""

    def test_no_platforms_always_matches(self):
        """No platforms constraint always matches."""
        assert _platform_matches(None) is True
        assert _platform_matches([]) is True

    def test_string_platform(self):
        """Single platform as string."""
        import sys
        current = sys.platform
        assert _platform_matches(current) is True
        assert _platform_matches("nonexistent_platform") is False

    def test_list_of_platforms(self):
        """List of platforms."""
        import sys
        current = sys.platform
        assert _platform_matches([current, "other"]) is True
        assert _platform_matches(["other1", "other2"]) is False


class TestPackageInList:
    """Tests for _package_in_list function."""

    def test_simple_package_in_list(self):
        """Simple package name found in list."""
        pkg_list = ["ripgrep", "fzf", "bat"]
        assert _package_in_list("ripgrep", pkg_list) is True
        assert _package_in_list("unknown", pkg_list) is False

    def test_package_with_fallback_syntax(self):
        """Package with fallback syntax found."""
        pkg_list = ["ripgrep", "tmux:brew", "bat"]
        assert _package_in_list("tmux", pkg_list) is True
        assert _package_in_list("brew", pkg_list) is False


class TestFindPackageManifestType:
    """Tests for _find_package_manifest_type function."""

    def test_find_in_standard_type(self):
        """Find package in standard type."""
        data = {
            "brew": ["ripgrep", "fzf"],
            "python": ["ruff", "pyright"],
        }
        assert _find_package_manifest_type("ripgrep", data) == "brew"
        assert _find_package_manifest_type("ruff", data) == "python"

    def test_find_in_custom(self):
        """Find package in custom type."""
        data = {
            "brew": ["ripgrep"],
            "custom": ["fisher", "my-tool"],
        }
        assert _find_package_manifest_type("fisher", data) == "custom"

    def test_package_not_found(self):
        """Package not in manifest returns None."""
        data = {
            "brew": ["ripgrep"],
        }
        assert _find_package_manifest_type("unknown", data) is None

    def test_find_with_fallback_syntax(self):
        """Find package with fallback syntax."""
        data = {
            "conda": ["python", "tmux:brew"],
        }
        assert _find_package_manifest_type("tmux", data) == "conda"


class TestResolveAllPackages:
    """Tests for _resolve_all_packages function."""

    def test_simple_resolution(self):
        """Simple packages stay in their sections."""
        data = {
            "brew": ["ripgrep", "fzf"],
            "python": ["ruff"],
        }
        resolved = _resolve_all_packages(data)
        assert "ripgrep" in resolved.get("brew", [])
        assert "fzf" in resolved.get("brew", [])
        assert "ruff" in resolved.get("python", [])

    def test_custom_preserved(self):
        """Custom packages are preserved as-is."""
        data = {
            "custom": ["fisher", "my-tool"],
        }
        resolved = _resolve_all_packages(data)
        assert resolved.get("custom") == ["fisher", "my-tool"]


class TestCustomPackageConfig:
    """Tests for CustomPackageConfig dataclass."""

    def test_minimal_config(self):
        """Minimal config with just name and install."""
        config = CustomPackageConfig(name="test", install="echo install")
        assert config.name == "test"
        assert config.install == "echo install"
        assert config.check == ""
        assert config.remove == ""
        assert config.shell == ""
        assert config.depends == []
        assert config.description == ""

    def test_full_config(self):
        """Full config with all fields."""
        config = CustomPackageConfig(
            name="test",
            install="echo install",
            check="which test",
            remove="echo remove",
            shell="fish",
            depends=["dep1", "dep2"],
            description="A test package",
        )
        assert config.depends == ["dep1", "dep2"]
        assert config.shell == "fish"


class TestCustomManagerParseConfig:
    """Tests for CustomManager.parse_config method."""

    def test_parse_string_config(self):
        """Parse simple string config."""
        config = CUSTOM_MANAGER.parse_config("test", "echo install")
        assert config.name == "test"
        assert config.install == "echo install"

    def test_parse_dict_config(self):
        """Parse dict config."""
        spec = {
            "install": "echo install",
            "check": "which test",
            "remove": "echo remove",
            "shell": "fish",
            "depends": ["dep1"],
            "description": "Test package",
        }
        config = CUSTOM_MANAGER.parse_config("test", spec)
        assert config.name == "test"
        assert config.install == "echo install"
        assert config.check == "which test"
        assert config.shell == "fish"
        assert config.depends == ["dep1"]
