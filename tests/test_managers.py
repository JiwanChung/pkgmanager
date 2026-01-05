"""Tests for package manager classes."""

import pytest
from unittest.mock import patch, MagicMock

from onepkg.models import (
    PackageInfo,
    PackageDetails,
    CommandResult,
    CustomPackageConfig,
)
from onepkg.managers import (
    BrewManager,
    CaskManager,
    PythonManager,
    RustManager,
    CondaManager,
    BunManager,
    CustomManager,
    MANAGERS,
    MANAGER_ORDER,
)


class TestPackageInfo:
    """Tests for PackageInfo dataclass."""

    def test_basic_info(self):
        """Create basic package info."""
        info = PackageInfo(name="ripgrep", version="14.0.0")
        assert info.name == "ripgrep"
        assert info.version == "14.0.0"
        assert info.display_name == ""

    def test_with_display_name(self):
        """Create package info with display name."""
        info = PackageInfo(name="123456", version="1.0", display_name="My App")
        assert info.display_name == "My App"


class TestPackageDetails:
    """Tests for PackageDetails dataclass."""

    def test_minimal_details(self):
        """Create minimal package details."""
        details = PackageDetails(name="ripgrep", version="14.0.0")
        assert details.name == "ripgrep"
        assert details.version == "14.0.0"
        assert details.requires == []
        assert details.binaries == []

    def test_full_details(self):
        """Create full package details."""
        details = PackageDetails(
            name="ripgrep",
            version="14.0.0",
            summary="Fast grep",
            homepage="https://github.com/BurntSushi/ripgrep",
            license="MIT",
            location="/usr/local/bin",
            requires=["libc"],
            binaries=["rg"],
        )
        assert details.summary == "Fast grep"
        assert details.binaries == ["rg"]


class TestCommandResult:
    """Tests for CommandResult dataclass."""

    def test_success_result(self):
        """Create success result."""
        result = CommandResult(success=True)
        assert result.success is True
        assert result.message == ""

    def test_failure_result(self):
        """Create failure result with message."""
        result = CommandResult(success=False, message="Package not found")
        assert result.success is False
        assert result.message == "Package not found"


class TestManagerRegistry:
    """Tests for the manager registry."""

    def test_all_managers_registered(self):
        """All expected managers are in the registry."""
        expected = {"conda", "python", "rust", "go", "brew", "cask", "mas", "winget", "bun"}
        assert set(MANAGERS.keys()) == expected

    def test_manager_order_includes_all(self):
        """Manager order includes all manager types plus custom."""
        for manager_type in MANAGERS.keys():
            assert manager_type in MANAGER_ORDER
        assert "custom" in MANAGER_ORDER


class TestBrewManager:
    """Tests for BrewManager."""

    def test_manager_properties(self):
        """Check manager properties."""
        manager = BrewManager()
        assert manager.name == "brew"
        assert manager.tool == "brew"
        assert manager.color == "bright_yellow"

    @patch("onepkg.managers.shutil.which")
    def test_is_available_when_installed(self, mock_which):
        """Manager is available when brew is installed."""
        mock_which.return_value = "/opt/homebrew/bin/brew"
        manager = BrewManager()
        assert manager.is_available() is True

    @patch("onepkg.managers.shutil.which")
    def test_is_available_when_not_installed(self, mock_which):
        """Manager is not available when brew is not installed."""
        mock_which.return_value = None
        manager = BrewManager()
        assert manager.is_available() is False


class TestPythonManager:
    """Tests for PythonManager (uv)."""

    def test_manager_properties(self):
        """Check manager properties."""
        manager = PythonManager()
        assert manager.name == "python"
        assert manager.tool == "uv"
        assert manager.color == "yellow"


class TestRustManager:
    """Tests for RustManager (cargo)."""

    def test_manager_properties(self):
        """Check manager properties."""
        manager = RustManager()
        assert manager.name == "rust"
        assert manager.tool == "cargo"
        assert manager.color == "red"


class TestCustomManager:
    """Tests for CustomManager."""

    def test_manager_properties(self):
        """Check manager properties."""
        manager = CustomManager()
        assert manager.name == "custom"
        assert manager.tool == "custom"
        assert manager.color == "magenta"

    def test_is_always_available(self):
        """Custom manager is always available."""
        manager = CustomManager()
        assert manager.is_available() is True

    @patch("onepkg.managers.subprocess.run")
    def test_is_installed_with_check_command(self, mock_run):
        """Check if package is installed using check command."""
        mock_run.return_value = MagicMock(returncode=0)
        manager = CustomManager()
        config = CustomPackageConfig(
            name="test",
            install="echo install",
            check="which test",
        )
        assert manager.is_installed(config) is True

    @patch("onepkg.managers.subprocess.run")
    def test_is_not_installed_when_check_fails(self, mock_run):
        """Package is not installed when check command fails."""
        mock_run.return_value = MagicMock(returncode=1)
        manager = CustomManager()
        config = CustomPackageConfig(
            name="test",
            install="echo install",
            check="which test",
        )
        assert manager.is_installed(config) is False

    def test_is_not_installed_without_check_command(self):
        """Package status unknown without check command."""
        manager = CustomManager()
        config = CustomPackageConfig(
            name="test",
            install="echo install",
        )
        assert manager.is_installed(config) is False

    def test_get_shell_uses_config_shell(self):
        """Use shell from config if specified."""
        manager = CustomManager()
        config = CustomPackageConfig(
            name="test",
            install="echo install",
            shell="fish",
        )
        assert manager._get_shell(config) == "fish"

    @patch("onepkg.managers.detect_shell")
    def test_get_shell_detects_when_not_specified(self, mock_detect):
        """Detect shell when not specified in config."""
        mock_detect.return_value = "/bin/zsh"
        manager = CustomManager()
        config = CustomPackageConfig(
            name="test",
            install="echo install",
        )
        assert manager._get_shell(config) == "/bin/zsh"
