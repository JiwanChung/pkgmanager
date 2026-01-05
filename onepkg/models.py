"""Data models for onepkg."""

from dataclasses import dataclass


@dataclass
class PackageInfo:
    """Information about an installed package"""

    name: str
    version: str
    display_name: str = ""  # Optional display name (e.g., app name for mas)


@dataclass
class PackageDetails:
    """Detailed information about a package"""

    name: str
    version: str
    summary: str = ""
    homepage: str = ""
    license: str = ""
    location: str = ""
    requires: list[str] = None
    binaries: list[str] = None

    def __post_init__(self):
        if self.requires is None:
            self.requires = []
        if self.binaries is None:
            self.binaries = []


@dataclass
class CustomPackageConfig:
    """Configuration for a custom package"""

    name: str
    install: str  # Install command/script
    check: str = ""  # Command to check if installed (exit 0 = installed)
    remove: str = ""  # Remove command/script
    shell: str = ""  # Shell to use (default: detect from parent)
    depends: list[str] = None  # Dependencies (other packages)
    description: str = ""  # Optional description

    def __post_init__(self):
        if self.depends is None:
            self.depends = []


@dataclass
class CommandResult:
    """Result of a command execution"""

    success: bool
    message: str = ""
