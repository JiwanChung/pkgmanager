"""
pkgmanager - A unified package manager for conda, python (uv), rust (cargo), and bun

Manage packages across multiple package managers with a single YAML manifest.
"""

import os
import re
import shutil
import shlex
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Optional

import yaml
from cyclopts import App, Parameter
from importlib import resources
from rich.columns import Columns
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


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


__version__ = "0.3.0"

# Initialize Rich console for colored output
console = Console()

# Create the main app with better help text
app = App(
    name="pkgmanager",
    help="""
[bold cyan]pkgmanager[/] - Unified package manager for your dotfiles

Manage packages across [bright_yellow]brew[/], [bright_blue]cask[/], [bright_cyan]mas[/], [green]conda[/], [yellow]python (uv)[/], [red]rust (cargo)[/], [bright_magenta]bun[/], and [cyan]winget (WSL)[/]
with a single YAML manifest file.

[dim]Examples:[/]
  pkgmanager init                    Install all packages from manifest
  pkgmanager install brew ripgrep    Install a brew formula
  pkgmanager install cask raycast    Install a cask app
  pkgmanager install mas 937984704   Install from Mac App Store
  pkgmanager install bun typescript  Install a bun global package
  pkgmanager list                    List all installed packages
  pkgmanager update                  Update all packages
  pkgmanager sync                    Sync packages from manifest (alias for init)
""",
    version=__version__,
)


# =============================================================================
# Package Manager Abstraction
# =============================================================================


@dataclass
class CommandResult:
    """Result of a command execution"""

    success: bool
    message: str = ""


class PackageManager(ABC):
    """Abstract base class for package managers"""

    name: str
    color: str
    tool: str
    # Commands to install this manager itself (platform -> command)
    install_cmds: dict[str, list[str]] = {}

    @abstractmethod
    def install(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        pass

    @abstractmethod
    def remove(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        pass

    @abstractmethod
    def get_installed_packages(self) -> list[PackageInfo]:
        """Get list of installed packages with versions"""
        pass

    @abstractmethod
    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get detailed information about a specific package"""
        pass

    @abstractmethod
    def update(
        self, packages: Optional[list[str]] = None, dry_run: bool = False
    ) -> CommandResult:
        pass

    def is_available(self) -> bool:
        """Check if the package manager tool is available"""
        return shutil.which(self.tool) is not None

    def install_self(self, dry_run: bool = False) -> CommandResult:
        """Install this package manager itself"""
        if not self.install_cmds:
            return CommandResult(
                success=False,
                message=f"No install command defined for {self.name}",
            )
        # Get platform-specific command
        platform = "darwin" if sys.platform == "darwin" else "linux"
        cmd = self.install_cmds.get(platform) or self.install_cmds.get("all")
        if not cmd:
            return CommandResult(
                success=False,
                message=f"No install command for {self.name} on {platform}",
            )
        return self._run_command(cmd, dry_run)

    def _run_command(
        self, cmd: list[str], dry_run: bool = False, check: bool = True
    ) -> CommandResult:
        """Execute a command with proper shell integration"""
        cmd_str = " ".join(cmd)

        if dry_run:
            console.print(f"  [dim]Would run:[/] {cmd_str}")
            return CommandResult(success=True)

        console.print(f"  [dim]$[/] {cmd_str}")

        try:
            shell = _detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", cmd_str],
                check=check,
                capture_output=False,
            )
            return CommandResult(success=result.returncode == 0)
        except subprocess.CalledProcessError as e:
            return CommandResult(success=False, message=str(e))


class CondaManager(PackageManager):
    """Conda package manager (via micromamba)"""

    name = "conda"
    color = "green"
    tool = "micromamba"
    install_cmds = {
        "darwin": ["brew", "install", "micromamba"],
        "linux": ["sh", "-c", "curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba && mv bin/micromamba ~/.local/bin/"],
    }
    env_name = "base"

    def install(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        return self._run_command(
            ["micromamba", "install", "-n", self.env_name, "-y", *packages], dry_run
        )

    def remove(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        return self._run_command(
            ["micromamba", "remove", "-n", self.env_name, "-y", *packages], dry_run
        )

    def get_installed_packages(self) -> list[PackageInfo]:
        """Get conda packages, excluding pypi-installed ones"""
        try:
            shell = _detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", f"micromamba list -n {self.env_name}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            packages = []
            for line in result.stdout.splitlines():
                # Skip comments and empty lines
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 3:
                    name, version, channel = parts[0], parts[1], parts[-1]
                    # Skip pypi packages
                    if channel == "pypi":
                        continue
                    packages.append(PackageInfo(name=name, version=version))
            return packages
        except subprocess.CalledProcessError:
            return []

    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get detailed info about a conda package"""
        try:
            shell = _detect_shell()
            # Get package info from conda list
            result = subprocess.run(
                [shell, "-l", "-c", f"micromamba list -n {self.env_name} '^{name}$'"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            for line in result.stdout.splitlines():
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 4 and parts[0] == name:
                    pkg_name, version, build, channel = parts[0], parts[1], parts[2], parts[3]
                    return PackageDetails(
                        name=pkg_name,
                        version=version,
                        location=f"channel: {channel}",
                        summary=f"build: {build}",
                    )
            return None
        except subprocess.CalledProcessError:
            return None

    def update(
        self, packages: Optional[list[str]] = None, dry_run: bool = False
    ) -> CommandResult:
        if packages:
            return self._run_command(
                ["conda", "update", "-n", self.env_name, "-y", *packages], dry_run
            )
        return self._run_command(
            ["conda", "update", "-n", self.env_name, "--all", "-y"], dry_run
        )


class PythonManager(PackageManager):
    """Python package manager (via uv)"""

    name = "python"
    color = "yellow"
    tool = "uv"
    install_cmds = {
        "darwin": ["brew", "install", "uv"],
        "linux": ["micromamba", "install", "-n", "base", "-y", "uv"],
    }

    def install(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        for pkg in packages:
            result = self._run_command(
                ["uv", "tool", "install", pkg, "--force"], dry_run
            )
            if not result.success:
                return result
        return CommandResult(success=True)

    def remove(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        for pkg in packages:
            result = self._run_command(["uv", "tool", "uninstall", pkg], dry_run)
            if not result.success:
                return result
        return CommandResult(success=True)

    def get_installed_packages(self) -> list[PackageInfo]:
        """Get uv tool packages"""
        try:
            shell = _detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", "uv tool list"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            packages = []
            # uv tool list format: "package-name v1.2.3"
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("-"):
                    continue
                # Match "name vX.Y.Z" pattern
                match = re.match(r"^(\S+)\s+v?(\S+)$", line)
                if match:
                    packages.append(PackageInfo(name=match.group(1), version=match.group(2)))
            return packages
        except subprocess.CalledProcessError:
            return []

    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get detailed info about a python tool package"""
        try:
            shell = _detect_shell()
            # First check if package is installed via uv tool list
            packages = self.get_installed_packages()
            pkg_info = next((p for p in packages if p.name == name), None)
            if not pkg_info:
                return None

            # Get more details using the tool's venv pip
            # uv tools are installed in ~/.local/share/uv/tools/<name>
            home = os.path.expanduser("~")
            tool_path = os.path.join(home, ".local", "share", "uv", "tools", name)
            pip_path = os.path.join(tool_path, "bin", "pip")

            details = PackageDetails(name=name, version=pkg_info.version)

            if os.path.exists(pip_path):
                result = subprocess.run(
                    [pip_path, "show", name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        if line.startswith("Summary:"):
                            details.summary = line.split(":", 1)[1].strip()
                        elif line.startswith("Home-page:"):
                            details.homepage = line.split(":", 1)[1].strip()
                        elif line.startswith("License:"):
                            details.license = line.split(":", 1)[1].strip()
                        elif line.startswith("Location:"):
                            details.location = line.split(":", 1)[1].strip()
                        elif line.startswith("Requires:"):
                            reqs = line.split(":", 1)[1].strip()
                            if reqs:
                                details.requires = [r.strip() for r in reqs.split(",")]

            # Get binaries from uv tool list output
            result = subprocess.run(
                [shell, "-l", "-c", "uv tool list"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            if result.returncode == 0:
                in_package = False
                for line in result.stdout.splitlines():
                    if line.startswith(name + " "):
                        in_package = True
                    elif in_package:
                        if line.startswith("-"):
                            details.binaries.append(line.strip("- ").strip())
                        elif line.strip() and not line.startswith(" "):
                            break

            return details
        except Exception:
            return None

    def update(
        self, packages: Optional[list[str]] = None, dry_run: bool = False
    ) -> CommandResult:
        if packages:
            for pkg in packages:
                result = self._run_command(["uv", "tool", "upgrade", pkg], dry_run)
                if not result.success:
                    return result
            return CommandResult(success=True)
        return self._run_command(["uv", "tool", "upgrade", "--all"], dry_run)


class RustManager(PackageManager):
    """Rust package manager (via cargo)"""

    name = "rust"
    color = "red"
    tool = "cargo"
    install_cmds = {
        "all": ["sh", "-c", "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"],
    }

    def install(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        return self._run_command(["cargo", "install", "--locked", *packages], dry_run)

    def remove(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        return self._run_command(["cargo", "uninstall", *packages], dry_run)

    def get_installed_packages(self) -> list[PackageInfo]:
        """Get cargo installed packages"""
        try:
            shell = _detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", "cargo install --list"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            packages = []
            # cargo install --list format:
            # package-name v1.2.3:
            #     binary1
            #     binary2
            for line in result.stdout.splitlines():
                # Match "name vX.Y.Z:" pattern (top-level package lines)
                match = re.match(r"^(\S+)\s+v(\S+):$", line)
                if match:
                    packages.append(PackageInfo(name=match.group(1), version=match.group(2)))
            return packages
        except subprocess.CalledProcessError:
            return []

    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get detailed info about a cargo package"""
        try:
            shell = _detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", "cargo install --list"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            # cargo install --list format:
            # package-name v1.2.3:
            #     binary1
            #     binary2
            current_pkg = None
            binaries = []
            for line in result.stdout.splitlines():
                match = re.match(r"^(\S+)\s+v(\S+):$", line)
                if match:
                    if current_pkg and current_pkg.name == name:
                        current_pkg.binaries = binaries
                        return current_pkg
                    pkg_name, version = match.group(1), match.group(2)
                    if pkg_name == name:
                        current_pkg = PackageDetails(name=pkg_name, version=version)
                        binaries = []
                    else:
                        current_pkg = None
                        binaries = []
                elif current_pkg and line.strip():
                    binaries.append(line.strip())

            if current_pkg and current_pkg.name == name:
                current_pkg.binaries = binaries
                return current_pkg

            return None
        except subprocess.CalledProcessError:
            return None

    def update(
        self, packages: Optional[list[str]] = None, dry_run: bool = False
    ) -> CommandResult:
        if not self._is_cargo_update_installed():
            console.print(
                "  [yellow]![/] cargo-update not installed. "
                "Run: [dim]cargo install cargo-update --locked[/]"
            )
            return CommandResult(success=False, message="cargo-update not installed")
        if packages:
            return self._run_command(["cargo", "install-update", *packages], dry_run)
        return self._run_command(["cargo", "install-update", "-a"], dry_run)

    def _is_cargo_update_installed(self) -> bool:
        """Check if cargo-update is installed"""
        packages = self.get_installed_packages()
        return any(p.name == "cargo-update" for p in packages)


class BrewManager(PackageManager):
    """Homebrew package manager (formulae)"""

    name = "brew"
    color = "bright_yellow"
    tool = "brew"

    def install(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        return self._run_command(["brew", "install", *packages], dry_run)

    def remove(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        return self._run_command(["brew", "uninstall", *packages], dry_run)

    def get_installed_packages(self) -> list[PackageInfo]:
        """Get installed brew formulae"""
        try:
            shell = _detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", "brew list --formula --versions"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            packages = []
            for line in result.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    name = parts[0]
                    version = parts[-1]  # Last version if multiple
                    packages.append(PackageInfo(name=name, version=version))
            return packages
        except subprocess.CalledProcessError:
            return []

    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get detailed info about a brew package"""
        try:
            shell = _detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", f"brew info {name}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            lines = result.stdout.splitlines()
            if not lines:
                return None

            # First line: "name: stable X.Y.Z (bottled)"
            first_line = lines[0]
            match = re.match(r"^==> (\S+): .*?(\d+\.\d+[\.\d]*)", first_line)
            if match:
                pkg_name, version = match.group(1), match.group(2)
            else:
                # Fallback: just get from brew list
                pkg_name = name
                version = "unknown"

            details = PackageDetails(name=pkg_name, version=version)

            # Parse the rest
            for line in lines[1:]:
                if line.startswith("==>"):
                    continue
                if not details.summary and line.strip() and not line.startswith("http"):
                    details.summary = line.strip()
                elif line.strip().startswith("http"):
                    details.homepage = line.strip()
                    break

            return details
        except subprocess.CalledProcessError:
            return None

    def update(
        self, packages: Optional[list[str]] = None, dry_run: bool = False
    ) -> CommandResult:
        result = self._run_command(["brew", "update"], dry_run)
        if not result.success:
            return result
        if packages:
            return self._run_command(["brew", "upgrade", *packages], dry_run)
        return self._run_command(["brew", "upgrade"], dry_run)


class CaskManager(PackageManager):
    """Homebrew Cask manager (GUI apps)"""

    name = "cask"
    color = "bright_blue"
    tool = "brew"

    def install(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        return self._run_command(["brew", "install", "--cask", *packages], dry_run)

    def remove(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        return self._run_command(["brew", "uninstall", "--cask", *packages], dry_run)

    def get_installed_packages(self) -> list[PackageInfo]:
        """Get installed brew casks"""
        try:
            shell = _detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", "brew list --cask --versions"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            packages = []
            for line in result.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    name = parts[0]
                    version = parts[-1]
                    packages.append(PackageInfo(name=name, version=version))
            return packages
        except subprocess.CalledProcessError:
            return []

    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get detailed info about a cask"""
        try:
            shell = _detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", f"brew info --cask {name}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            lines = result.stdout.splitlines()
            if not lines:
                return None

            # First line: "==> name: version"
            first_line = lines[0]
            match = re.match(r"^==> (\S+): (.+)$", first_line)
            if match:
                pkg_name, version = match.group(1), match.group(2).strip()
            else:
                pkg_name = name
                version = "unknown"

            details = PackageDetails(name=pkg_name, version=version)

            for line in lines[1:]:
                if line.startswith("==>"):
                    continue
                if not details.summary and line.strip() and not line.startswith("http"):
                    details.summary = line.strip()
                elif line.strip().startswith("http"):
                    details.homepage = line.strip()
                    break

            return details
        except subprocess.CalledProcessError:
            return None

    def update(
        self, packages: Optional[list[str]] = None, dry_run: bool = False
    ) -> CommandResult:
        if packages:
            return self._run_command(["brew", "upgrade", "--cask", *packages], dry_run)
        return self._run_command(["brew", "upgrade", "--cask"], dry_run)


class MasManager(PackageManager):
    """Mac App Store manager (via mas-cli)"""

    name = "mas"
    color = "bright_cyan"
    tool = "mas"
    install_cmds = {
        "darwin": ["brew", "install", "mas"],
    }

    def install(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        # packages are app IDs for mas
        for app_id in packages:
            result = self._run_command(["mas", "install", str(app_id)], dry_run)
            if not result.success:
                return result
        return CommandResult(success=True)

    def remove(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        # mas doesn't have uninstall - apps must be removed via Finder/Launchpad
        console.print(
            "  [yellow]Warning:[/] mas cannot uninstall apps. "
            "Remove via Finder or Launchpad."
        )
        return CommandResult(success=True, message="Manual removal required")

    def get_installed_packages(self) -> list[PackageInfo]:
        """Get installed Mac App Store apps"""
        try:
            shell = _detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", "mas list"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            packages = []
            # mas list format: "123456789 App Name (1.2.3)"
            for line in result.stdout.splitlines():
                match = re.match(r"^(\d+)\s+(.+?)\s+\(([^)]+)\)$", line.strip())
                if match:
                    app_id, app_name, version = match.groups()
                    # Store ID as name (for tracking), app name for display
                    packages.append(PackageInfo(
                        name=app_id,
                        version=version,
                        display_name=app_name,
                    ))
            return packages
        except subprocess.CalledProcessError:
            return []

    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get details about a Mac App Store app (by ID)"""
        try:
            shell = _detect_shell()
            # First get the list to find the app name
            result = subprocess.run(
                [shell, "-l", "-c", "mas list"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            for line in result.stdout.splitlines():
                match = re.match(r"^(\d+)\s+(.+?)\s+\(([^)]+)\)$", line.strip())
                if match:
                    app_id, app_name, version = match.groups()
                    if app_id == name:
                        return PackageDetails(
                            name=app_name,
                            version=version,
                            summary=f"Mac App Store (ID: {app_id})",
                        )
            return None
        except subprocess.CalledProcessError:
            return None

    def update(
        self, packages: Optional[list[str]] = None, dry_run: bool = False
    ) -> CommandResult:
        if packages:
            return self._run_command(["mas", "upgrade", *packages], dry_run)
        return self._run_command(["mas", "upgrade"], dry_run)


class WingetManager(PackageManager):
    """Windows Package Manager (winget) via WSL"""

    name = "winget"
    color = "cyan"
    tool = "winget.exe"

    def install(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        results = []
        for pkg in packages:
            pkg_escaped = shlex.quote(pkg)
            results.append(
                self._run_command(
                    [
                        "winget.exe",
                        "install",
                        pkg_escaped,
                        "--silent",
                        "--accept-package-agreements",
                        "--accept-source-agreements",
                    ],
                    dry_run,
                )
            )
        return CommandResult(success=all(r.success for r in results))

    def remove(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        results = []
        for pkg in packages:
            pkg_escaped = shlex.quote(pkg)
            results.append(
                self._run_command(
                    ["winget.exe", "uninstall", pkg_escaped],
                    dry_run,
                )
            )
        return CommandResult(success=all(r.success for r in results))

    def get_installed_packages(self) -> list[PackageInfo]:
        """Get installed winget packages (Name/Id/Version)"""
        try:
            shell = _detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", "winget.exe list"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            packages = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("Name") or line.startswith("---"):
                    continue
                parts = re.split(r"\s{2,}", line)
                if len(parts) >= 3:
                    name, pkg_id, version = parts[0], parts[1], parts[2]
                    packages.append(
                        PackageInfo(name=pkg_id, version=version, display_name=name)
                    )
            return packages
        except subprocess.CalledProcessError:
            return []

    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get detailed info about a winget package"""
        try:
            shell = _detect_shell()
            name_escaped = shlex.quote(name)
            result = subprocess.run(
                [shell, "-l", "-c", f"winget.exe show {name_escaped}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            details = PackageDetails(name=name, version="unknown")
            for line in result.stdout.splitlines():
                if ":" not in line:
                    continue
                key, value = (s.strip() for s in line.split(":", 1))
                if key == "Version":
                    details.version = value
                elif key == "Homepage":
                    details.homepage = value
                elif key == "Description" and not details.summary:
                    details.summary = value
                elif key == "License":
                    details.license = value
            return details
        except subprocess.CalledProcessError:
            return None

    def update(
        self, packages: Optional[list[str]] = None, dry_run: bool = False
    ) -> CommandResult:
        if packages:
            results = []
            for pkg in packages:
                pkg_escaped = shlex.quote(pkg)
                results.append(
                    self._run_command(
                        ["winget.exe", "upgrade", pkg_escaped], dry_run
                    )
                )
            return CommandResult(success=all(r.success for r in results))
        return self._run_command(["winget.exe", "upgrade", "--all"], dry_run)


class BunManager(PackageManager):
    """Bun package manager (global packages via bun add -g)"""

    name = "bun"
    color = "bright_magenta"
    tool = "bun"
    install_cmds = {
        "darwin": ["brew", "install", "oven-sh/bun/bun"],
        "linux": ["sh", "-c", "curl -fsSL https://bun.sh/install | bash"],
    }

    def install(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        for pkg in packages:
            result = self._run_command(["bun", "add", "-g", pkg], dry_run)
            if not result.success:
                return result
        return CommandResult(success=True)

    def remove(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        for pkg in packages:
            result = self._run_command(["bun", "remove", "-g", pkg], dry_run)
            if not result.success:
                return result
        return CommandResult(success=True)

    def get_installed_packages(self) -> list[PackageInfo]:
        """Get globally installed bun packages"""
        try:
            shell = _detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", "bun pm ls -g"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            packages = []
            for line in result.stdout.splitlines():
                # bun pm ls -g format: "└── package@version" or "├── package@version"
                # Extract package@version from tree output
                match = re.search(r"([^@\s├└─│]+)@([^\s\[]+)", line)
                if match:
                    packages.append(PackageInfo(name=match.group(1), version=match.group(2)))
            return packages
        except subprocess.CalledProcessError:
            return []

    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get detailed info about a bun global package"""
        try:
            packages = self.get_installed_packages()
            pkg_info = next((p for p in packages if p.name == name), None)
            if not pkg_info:
                return None

            # Get more info from npm registry
            shell = _detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", f"bun pm info {name}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )

            details = PackageDetails(name=name, version=pkg_info.version)

            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if ":" not in line:
                        continue
                    key, value = (s.strip() for s in line.split(":", 1))
                    key_lower = key.lower()
                    if key_lower == "description" and not details.summary:
                        details.summary = value
                    elif key_lower == "homepage":
                        details.homepage = value
                    elif key_lower == "license":
                        details.license = value

            return details
        except Exception:
            return None

    def update(
        self, packages: Optional[list[str]] = None, dry_run: bool = False
    ) -> CommandResult:
        if packages:
            for pkg in packages:
                result = self._run_command(["bun", "update", "-g", pkg], dry_run)
                if not result.success:
                    return result
            return CommandResult(success=True)
        return self._run_command(["bun", "update", "-g"], dry_run)


class CustomManager:
    """Manager for custom script-based packages"""

    name = "custom"
    color = "magenta"
    tool = "custom"

    def is_available(self) -> bool:
        return True

    def _get_shell(self, pkg_config: CustomPackageConfig) -> str:
        """Get the shell to use for running commands"""
        if pkg_config.shell:
            return pkg_config.shell
        return _detect_shell()

    def _run_script(
        self, script: str, shell: str, dry_run: bool = False
    ) -> CommandResult:
        """Run a script in the specified shell"""
        if dry_run:
            console.print(f"  [dim]Would run in {shell}:[/]")
            for line in script.strip().split("\n"):
                console.print(f"    {line}")
            return CommandResult(success=True)

        console.print(f"  [dim]Running in {shell}...[/]")
        try:
            result = subprocess.run(
                [shell, "-l", "-c", script],
                check=False,
                capture_output=False,
            )
            return CommandResult(success=result.returncode == 0)
        except Exception as e:
            return CommandResult(success=False, message=str(e))

    def is_installed(self, pkg_config: CustomPackageConfig) -> bool:
        """Check if a custom package is installed"""
        if not pkg_config.check:
            return False  # Can't determine without check command

        shell = self._get_shell(pkg_config)
        try:
            result = subprocess.run(
                [shell, "-l", "-c", pkg_config.check],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return result.returncode == 0
        except Exception:
            return False

    def install(
        self, pkg_config: CustomPackageConfig, dry_run: bool = False
    ) -> CommandResult:
        """Install a custom package"""
        shell = self._get_shell(pkg_config)
        console.print(f"  [dim]Shell:[/] {shell}")
        return self._run_script(pkg_config.install, shell, dry_run)

    def remove(
        self, pkg_config: CustomPackageConfig, dry_run: bool = False
    ) -> CommandResult:
        """Remove a custom package"""
        if not pkg_config.remove:
            return CommandResult(
                success=False, message="No remove command specified for this package"
            )
        shell = self._get_shell(pkg_config)
        return self._run_script(pkg_config.remove, shell, dry_run)

    def get_installed_packages(
        self, custom_configs: dict[str, dict]
    ) -> list[PackageInfo]:
        """Get list of installed custom packages"""
        packages = []
        for name, config in custom_configs.items():
            pkg_config = self._parse_config(name, config)
            if self.is_installed(pkg_config):
                packages.append(PackageInfo(name=name, version="custom"))
        return packages

    def get_package_details(
        self, name: str, config: dict
    ) -> Optional[PackageDetails]:
        """Get details about a custom package"""
        pkg_config = self._parse_config(name, config)
        if not self.is_installed(pkg_config):
            return None

        return PackageDetails(
            name=name,
            version="custom",
            summary=pkg_config.description or f"Custom package ({pkg_config.shell or 'default shell'})",
            binaries=[],
            requires=pkg_config.depends,
        )

    @staticmethod
    def _parse_config(name: str, config: dict) -> CustomPackageConfig:
        """Parse a config dict into CustomPackageConfig"""
        if isinstance(config, str):
            # Simple format: just the install command
            return CustomPackageConfig(name=name, install=config)
        return CustomPackageConfig(
            name=name,
            install=config.get("install", ""),
            check=config.get("check", ""),
            remove=config.get("remove", ""),
            shell=config.get("shell", ""),
            depends=config.get("depends", []),
            description=config.get("description", ""),
        )


# Registry of available package managers
MANAGERS: dict[str, PackageManager] = {
    "conda": CondaManager(),
    "python": PythonManager(),
    "rust": RustManager(),
    "brew": BrewManager(),
    "cask": CaskManager(),
    "mas": MasManager(),
    "winget": WingetManager(),
    "bun": BunManager(),
}

# Custom manager instance (separate since it has different interface)
CUSTOM_MANAGER = CustomManager()

# Preferred order for processing
MANAGER_ORDER = ["brew", "cask", "mas", "winget", "conda", "python", "rust", "bun", "custom"]

# Category definitions for grouping package types
CATEGORIES = {
    "mac": {
        "title": "macOS",
        "types": ["brew", "cask", "mas"],
        "platform": "darwin",  # Only show on macOS
    },
    "wsl": {
        "title": "WSL",
        "types": ["winget"],
        "platform": "wsl",  # Only show on WSL
    },
    "general": {
        "title": "General",
        "types": ["conda", "python", "rust", "bun"],
        "platform": None,  # Show on all platforms
    },
    "custom": {
        "title": "Custom",
        "types": ["custom"],
        "platform": None,
    },
}

CATEGORY_ORDER = ["mac", "wsl", "general", "custom"]


def _is_macos() -> bool:
    """Check if running on macOS"""
    return sys.platform == "darwin"


def _is_wsl() -> bool:
    """Check if running under WSL"""
    if sys.platform != "linux":
        return False
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def _get_active_categories() -> list[str]:
    """Get categories that should be shown on current platform"""
    active = []
    for cat_name in CATEGORY_ORDER:
        cat = CATEGORIES[cat_name]
        if cat["platform"] is None:
            active.append(cat_name)
        elif cat["platform"] == "wsl" and _is_wsl():
            active.append(cat_name)
        elif cat["platform"] == sys.platform:
            active.append(cat_name)
    return active


def _get_category_for_type(pkg_type: str) -> Optional[str]:
    """Get the category name for a package type"""
    for cat_name, cat in CATEGORIES.items():
        if pkg_type in cat["types"]:
            return cat_name
    return None


def _update_raw_manifest(
    raw_data: dict, pkg_type: str, name: str, action: str = "add"
) -> None:
    """Update the raw manifest data structure.

    Args:
        raw_data: The nested manifest data
        pkg_type: Package type (brew, conda, winget, custom, etc.)
        name: Package name to add/remove
        action: "add" or "remove"
    """
    cat_name = _get_category_for_type(pkg_type)
    if not cat_name:
        return

    if cat_name == "custom":
        # Custom packages are handled separately (list structure)
        custom_list = raw_data.get("custom", [])
        if action == "remove":
            if "custom" in raw_data:
                raw_data["custom"] = [
                    entry
                    for entry in custom_list
                    if _parse_custom_entry(entry)[0] != name
                ]
                if not raw_data["custom"]:
                    del raw_data["custom"]
        else:
            if not any(_parse_custom_entry(entry)[0] == name for entry in custom_list):
                if "custom" not in raw_data:
                    raw_data["custom"] = []
                raw_data["custom"].append(name)
    else:
        # Standard package types (list structure)
        if cat_name not in raw_data:
            raw_data[cat_name] = {}
        if pkg_type not in raw_data[cat_name]:
            raw_data[cat_name][pkg_type] = []

        pkg_list = raw_data[cat_name][pkg_type]
        if action == "add" and name not in pkg_list:
            pkg_list.append(name)
        elif action == "remove":
            # Handle fallback syntax: find entry matching the name
            # (could be "name" or "name:preferred")
            to_remove = None
            for entry in pkg_list:
                pkg_name, _ = _parse_package_entry(entry)
                if pkg_name == name:
                    to_remove = entry
                    break
            if to_remove:
                pkg_list.remove(to_remove)


# =============================================================================
# Helper Functions
# =============================================================================


def _detect_shell() -> str:
    """Detect the current shell from parent process"""
    env_shell = os.environ.get("SHELL")
    if env_shell and Path(env_shell).is_file():
        return env_shell

    result = subprocess.run(
        ["ps", "-p", str(os.getppid()), "-o", "comm="],
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )
    candidate = result.stdout.strip()
    if candidate:
        candidate_path = shutil.which(candidate) or (
            candidate if Path(candidate).is_file() else None
        )
        if candidate_path:
            shell_name = Path(candidate_path).name
            if shell_name in {"bash", "zsh", "fish", "sh", "ksh", "tcsh"}:
                return candidate_path

    return "/bin/bash" if Path("/bin/bash").is_file() else "sh"


def _load_specs() -> dict:
    """Load custom package specs from the bundled specs.yaml"""
    try:
        specs_file = resources.files("pkgmanager").joinpath("specs.yaml")
        with resources.as_file(specs_file) as path:
            with open(path) as f:
                return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _platform_matches(platforms: Optional[object]) -> bool:
    """Check if current platform matches any of the provided platform tags."""
    if not platforms:
        return True
    if isinstance(platforms, str):
        platforms = [platforms]
    for platform in platforms:
        if platform == "wsl" and _is_wsl():
            return True
        if platform == "darwin" and _is_macos():
            return True
        if platform == "linux" and sys.platform == "linux":
            return True
        if platform in {"windows", "win32"} and sys.platform == "win32":
            return True
        if platform == sys.platform:
            return True
    return False


def _parse_custom_entry(entry: object) -> tuple[Optional[str], Optional[object]]:
    """Parse custom entries that may include platform conditions."""
    if isinstance(entry, dict):
        name = entry.get("name")
        platforms = entry.get("platforms") or entry.get("platform")
        return name, platforms
    if isinstance(entry, str):
        return entry, None
    return None, None


def _find_custom_entry(raw_data: dict, name: str) -> Optional[object]:
    """Find a custom entry in raw manifest data by name."""
    for entry in raw_data.get("custom", []):
        entry_name, platforms = _parse_custom_entry(entry)
        if entry_name == name:
            return platforms
    return None


def _parse_package_entry(entry: str) -> tuple[str, Optional[str]]:
    """Parse 'pkg' or 'pkg:manager' -> (name, preferred_manager)"""
    if isinstance(entry, str) and ':' in entry:
        name, preferred = entry.split(':', 1)
        return name, preferred
    return entry, None


def _package_in_list(name: str, pkg_list: list) -> bool:
    """Check if a package name exists in a list (handling fallback syntax)."""
    for entry in pkg_list:
        pkg_name, _ = _parse_package_entry(entry)
        if pkg_name == name:
            return True
    return False


def _find_package_manifest_type(name: str, data: dict) -> Optional[str]:
    """Find which manifest section a package is defined in (before resolution).

    Unlike _find_package_type which returns the resolved manager,
    this returns the section where the package is actually listed.
    """
    # Check custom first
    if name in data.get("custom", []):
        return "custom"

    # Check standard types, parsing fallback syntax
    for manifest_type in MANAGERS.keys():
        packages = data.get(manifest_type, [])
        if _package_in_list(name, packages):
            return manifest_type

    return None


def _resolve_package_manager(
    pkg_name: str,
    default_type: str,
    preferred_type: Optional[str],
) -> str:
    """Resolve which manager to use based on platform availability.

    If preferred_type is specified and available on current platform,
    use it. Otherwise fall back to default_type.
    """
    if preferred_type:
        manager = MANAGERS.get(preferred_type)
        if manager and manager.is_available():
            # Check if this manager type is active on current platform
            for cat_name in _get_active_categories():
                if preferred_type in CATEGORIES[cat_name]["types"]:
                    return preferred_type
    return default_type


def _resolve_all_packages(data: dict) -> dict[str, list[str]]:
    """Resolve all packages to their actual managers based on platform.

    Takes flattened manifest data and returns a new dict where packages
    are grouped by their resolved manager (not their manifest section).

    Example:
        Input: {"conda": ["python", "tmux:brew"]}
        Output on macOS: {"conda": ["python"], "brew": ["tmux"]}
        Output on Linux: {"conda": ["python", "tmux"]}
    """
    resolved: dict[str, list[str]] = {}

    for default_type, packages in data.items():
        if default_type == "custom":
            # Custom packages don't support fallback syntax
            resolved["custom"] = packages
            continue

        if not packages:
            continue

        for entry in packages:
            name, preferred = _parse_package_entry(entry)
            actual_type = _resolve_package_manager(name, default_type, preferred)

            if actual_type not in resolved:
                resolved[actual_type] = []
            resolved[actual_type].append(name)

    return resolved


def _get_manager(pkg_type: str) -> PackageManager:
    """Get a package manager by type, with validation"""
    if pkg_type not in MANAGERS:
        valid_types = ", ".join(MANAGERS.keys())
        console.print(
            f"[red]Error:[/] Unknown package type '[bold]{pkg_type}[/]'\n"
            f"Valid types: {valid_types}"
        )
        raise SystemExit(1)

    manager = MANAGERS[pkg_type]
    if not manager.is_available():
        console.print(
            f"[red]Error:[/] Required tool '[bold]{manager.tool}[/]' not found in PATH"
        )
        raise SystemExit(1)

    return manager


def _reorder_types(types: list[str]) -> list[str]:
    """Reorder package types to preferred order"""
    ordered = [t for t in MANAGER_ORDER if t in types]
    ordered.extend(t for t in types if t not in ordered)
    return ordered


DEFAULT_MANIFEST = Path.home() / ".config" / "packages.yaml"


def _load_manifest(
    env: Optional[str] = None,
) -> tuple[dict, dict, Path]:
    """Load the package manifest from YAML file.

    Returns:
        Tuple of (flattened_data, raw_data, path)
        - flattened_data: dict with package types as keys (filtered by platform)
        - raw_data: original nested structure for saving
        - path: manifest file path
    """
    if not env:
        env = os.environ.get("PACKAGE_CONFIG")

    if not env:
        env_path = DEFAULT_MANIFEST
    else:
        env_path = Path(env)
    if not env_path.is_file():
        console.print(f"[red]Error:[/] Manifest file not found: [dim]{env_path}[/]")
        raise SystemExit(1)

    with open(env_path) as f:
        raw_data = yaml.safe_load(f) or {}

    # Flatten the nested structure
    flattened = {}
    for cat_name in _get_active_categories():
        cat = CATEGORIES[cat_name]
        if cat_name == "custom":
            # Custom is special - it's at the top level
            if "custom" in raw_data:
                custom_names = []
                for entry in raw_data["custom"]:
                    name, platforms = _parse_custom_entry(entry)
                    if name and _platform_matches(platforms):
                        custom_names.append(name)
                if custom_names:
                    flattened["custom"] = custom_names
        else:
            # Get packages from category (mac or general)
            cat_data = raw_data.get(cat_name, {})
            for pkg_type in cat["types"]:
                if pkg_type in cat_data:
                    # Parse entries to handle platform-specific packages (dict format)
                    pkg_names = []
                    for entry in cat_data[pkg_type]:
                        name, platforms = _parse_custom_entry(entry)
                        if name and _platform_matches(platforms):
                            pkg_names.append(name)
                    if pkg_names:
                        flattened[pkg_type] = pkg_names

    return flattened, raw_data, env_path


def _save_manifest(raw_data: dict, path: Path) -> None:
    """Save the package manifest to YAML file"""
    with open(path, "w") as f:
        yaml.dump(raw_data, f, default_flow_style=False, sort_keys=False)


def _print_header(action: str, pkg_type: str, packages: Optional[list[str]] = None):
    """Print a styled header for an action"""
    manager = MANAGERS.get(pkg_type)
    color = manager.color if manager else "white"

    if packages:
        pkg_list = (
            ", ".join(packages) if len(packages) <= 3 else f"{len(packages)} packages"
        )
        console.print(
            f"\n[bold {color}]▶ {action.capitalize()}[/] [{color}]{pkg_type}[/]: {pkg_list}"
        )
    else:
        console.print(
            f"\n[bold {color}]▶ {action.capitalize()}[/] [{color}]{pkg_type}[/]"
        )


def _print_success(message: str = "Done"):
    """Print a success message"""
    console.print(f"[green]✓[/] {message}")


def _print_error(message: str):
    """Print an error message"""
    console.print(f"[red]✗[/] {message}")


def _get_installed_names(manager: PackageManager) -> set[str]:
    """Return installed package names, handling winget name/id matching."""
    installed_packages = manager.get_installed_packages()
    names = {p.name for p in installed_packages}
    if manager.name == "winget":
        for pkg in installed_packages:
            if pkg.display_name:
                names.add(pkg.display_name)
        names |= {name.lower() for name in names}
    return names


# =============================================================================
# CLI Commands
# =============================================================================


@app.command
def init(
    *,
    env: Annotated[
        Optional[str],
        Parameter(
            name=["--env", "-e"],
            help="Path to YAML manifest file (default: ~/.config/packages.yaml)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        Parameter(
            name=["--types", "-t"],
            help="Comma-separated package types to install (e.g., conda,python)",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        Parameter(
            name=["--dry-run", "-n"],
            help="Show what would be done without executing",
        ),
    ] = False,
):
    """
    Install all packages from the YAML manifest.

    Reads the manifest file and installs all listed packages for each
    configured package manager. Packages are installed in order:
    conda → python → rust.

    [dim]Examples:[/]
      pkgmanager init
      pkgmanager init --env ~/packages.yaml
      pkgmanager init --types conda,python
      pkgmanager init --dry-run
    """
    data, raw_data, path = _load_manifest(env)

    # Resolve packages to their actual managers based on platform preferences
    data = _resolve_all_packages(data)

    if dry_run:
        console.print(
            Panel("[yellow]DRY RUN[/] - No changes will be made", style="yellow")
        )

    all_types = list(data.keys())
    if types:
        all_types = [t.strip() for t in types.split(",")]

    all_types = _reorder_types(all_types)

    console.print(f"[dim]Manifest:[/] {path}")
    console.print(f"[dim]Package types:[/] {', '.join(all_types)}")

    success_count = 0
    error_count = 0

    for pkg_type in all_types:
        packages = data.get(pkg_type, [])
        if not packages:
            continue

        if pkg_type == "custom":
            # Handle custom packages - packages is now a list of names
            pkg_names = packages if isinstance(packages, list) else []

            specs = _load_specs()
            # Filter to only missing packages
            missing = []
            for name in pkg_names:
                if name not in specs:
                    console.print(f"  [red]Error:[/] No spec found for '{name}'")
                    error_count += 1
                    continue
                pkg_config = CUSTOM_MANAGER._parse_config(name, specs[name])
                if not CUSTOM_MANAGER.is_installed(pkg_config):
                    missing.append(name)

            if not missing:
                console.print(f"\n[{CUSTOM_MANAGER.color}]{pkg_type}[/]: all {len(pkg_names)} packages installed")
                continue

            _print_header("Installing", pkg_type, missing)
            console.print(f"  [dim]Skipping {len(pkg_names) - len(missing)} already installed[/]")

            for name in missing:
                pkg_config = CUSTOM_MANAGER._parse_config(name, specs[name])
                console.print(f"\n  [magenta]{name}[/]")

                if pkg_config.depends:
                    console.print(f"  [dim]Depends:[/] {', '.join(pkg_config.depends)}")

                result = CUSTOM_MANAGER.install(pkg_config, dry_run=dry_run)
                if result.success:
                    _print_success(f"{name} installed")
                else:
                    error_count += 1
                    _print_error(result.message or f"{name} installation failed")
        else:
            # Handle standard package managers
            manager = _get_manager(pkg_type)

            # Get installed packages and filter to only missing ones
            installed = _get_installed_names(manager)
            if manager.name == "winget":
                missing = [p for p in packages if p not in installed and p.lower() not in installed]
            else:
                missing = [p for p in packages if p not in installed]

            if not missing:
                console.print(f"\n[{manager.color}]{pkg_type}[/]: all {len(packages)} packages installed")
                continue

            _print_header("Installing", pkg_type, missing)
            console.print(f"  [dim]Skipping {len(packages) - len(missing)} already installed[/]")

            result = manager.install(missing, dry_run=dry_run)

            if result.success:
                success_count += 1
                _print_success()
            else:
                error_count += 1
                _print_error(result.message or "Installation failed")

    console.print()
    if error_count == 0:
        console.print(
            Panel("[green]All packages installed successfully![/]", style="green")
        )
    else:
        console.print(
            Panel(
                f"[yellow]Completed with {error_count} error(s)[/]",
                style="yellow",
            )
        )


@app.command
def sync(
    *,
    env: Annotated[
        Optional[str],
        Parameter(
            name=["--env", "-e"],
            help="Path to YAML manifest file (default: ~/.config/packages.yaml)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        Parameter(
            name=["--types", "-t"],
            help="Comma-separated package types to install (e.g., conda,python)",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        Parameter(
            name=["--dry-run", "-n"],
            help="Show what would be done without executing",
        ),
    ] = False,
):
    """
    Sync packages from the YAML manifest (alias for init).

    [dim]Examples:[/]
      pkgmanager sync
      pkgmanager sync --types conda
    """
    init(env=env, types=types, dry_run=dry_run)


@app.command
def install(
    pkg_type: Annotated[str, Parameter(help="Package type (brew, cask, mas, winget, conda, python, rust, bun, custom)")],
    name: Annotated[str, Parameter(help="Package name (or app ID for mas)")],
    *,
    env: Annotated[
        Optional[str],
        Parameter(
            name=["--env", "-e"],
            help="Path to YAML manifest file (default: ~/.config/packages.yaml)",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        Parameter(
            name=["--dry-run", "-n"],
            help="Show what would be done without executing",
        ),
    ] = False,
):
    """
    Install a package and add it to the manifest.

    Installs the specified package using the appropriate package manager
    and updates the YAML manifest to track it.

    For custom packages, the package must be defined in the manifest first.
    Use 'pkgmanager edit' to add custom package definitions.

    [dim]Examples:[/]
      pkgmanager install brew ripgrep
      pkgmanager install cask raycast
      pkgmanager install mas 937984704
      pkgmanager install conda python
      pkgmanager install python ruff
      pkgmanager install rust miniserve
      pkgmanager install bun typescript
      pkgmanager install custom fisher
    """
    data, raw_data, path = _load_manifest(env)

    if dry_run:
        console.print(
            Panel("[yellow]DRY RUN[/] - No changes will be made", style="yellow")
        )

    if pkg_type == "custom":
        # Handle custom package installation - look up spec internally
        specs = _load_specs()
        if name not in specs:
            console.print(
                f"[red]Error:[/] No spec found for custom package '{name}'.\n"
                f"Available specs: {', '.join(specs.keys())}"
            )
            raise SystemExit(1)

        platforms = _find_custom_entry(raw_data, name)
        if platforms and not _platform_matches(platforms):
            console.print(
                f"[red]Error:[/] Custom package '{name}' is not supported on this platform."
            )
            raise SystemExit(1)

        pkg_config = CUSTOM_MANAGER._parse_config(name, specs[name])
        _print_header("Installing", pkg_type, [name])

        if pkg_config.depends:
            console.print(f"  [dim]Depends:[/] {', '.join(pkg_config.depends)}")

        result = CUSTOM_MANAGER.install(pkg_config, dry_run=dry_run)

        if result.success:
            _print_success()
            # Add to manifest if not already there
            if not dry_run:
                custom_list = data.get("custom", [])
                if name not in custom_list:
                    if "custom" not in raw_data:
                        raw_data["custom"] = []
                    raw_data["custom"].append(name)
                    _save_manifest(raw_data, path)
                    console.print(f"[dim]Added to manifest:[/] {path}")
        else:
            _print_error(result.message or "Installation failed")
            raise SystemExit(1)
    else:
        # Handle standard package managers
        _print_header("Installing", pkg_type, [name])
        manager = _get_manager(pkg_type)
        result = manager.install([name], dry_run=dry_run)

        if result.success:
            _print_success()

            # Update manifest
            if not dry_run:
                if name not in data.get(pkg_type, []):
                    _update_raw_manifest(raw_data, pkg_type, name, "add")
                    _save_manifest(raw_data, path)
                    console.print(f"[dim]Added to manifest:[/] {path}")
        else:
            _print_error(result.message or "Installation failed")
            raise SystemExit(1)


def _find_package_type(name: str, data: dict) -> Optional[str]:
    """Find which package type a package belongs to in the manifest.

    Returns the resolved package type (accounting for fallback syntax).
    For example, if 'tmux:brew' is listed under conda, returns 'brew' on macOS.
    """
    # Check custom first
    if name in data.get("custom", []):
        return "custom"

    # Check standard types, parsing fallback syntax
    for default_type in MANAGERS.keys():
        packages = data.get(default_type, [])
        for entry in packages:
            pkg_name, preferred = _parse_package_entry(entry)
            if pkg_name == name:
                # Found it - resolve to actual manager
                return _resolve_package_manager(name, default_type, preferred)

    return None


@app.command
def remove(
    name: Annotated[str, Parameter(help="Package name (or app ID for mas)")],
    pkg_type: Annotated[
        Optional[str],
        Parameter(
            name=["--type", "-t"],
            help="Package type (auto-detected if not specified)",
        ),
    ] = None,
    *,
    env: Annotated[
        Optional[str],
        Parameter(
            name=["--env", "-e"],
            help="Path to YAML manifest file (default: ~/.config/packages.yaml)",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        Parameter(
            name=["--dry-run", "-n"],
            help="Show what would be done without executing",
        ),
    ] = False,
    keep_in_manifest: Annotated[
        bool,
        Parameter(
            name=["--keep", "-k"],
            help="Keep the package definition in manifest (custom only)",
        ),
    ] = False,
):
    """
    Remove a package and update the manifest.

    Removes the specified package using the appropriate package manager
    and updates the YAML manifest to stop tracking it. Package type is
    auto-detected from the manifest if not specified.

    Note: mas apps cannot be uninstalled via CLI - use Finder/Launchpad.

    [dim]Examples:[/]
      pkgmanager remove ripgrep
      pkgmanager remove fisher
      pkgmanager remove raycast --type cask
      pkgmanager remove fisher --keep
    """
    data, raw_data, path = _load_manifest(env)

    # Auto-detect package type if not specified
    if pkg_type is None:
        pkg_type = _find_package_type(name, data)
        if pkg_type is None:
            console.print(
                f"[red]Error:[/] Package '{name}' not found in manifest.\n"
                f"Use [dim]--type[/] to specify the package type."
            )
            raise SystemExit(1)
        console.print(f"[dim]Detected type:[/] {pkg_type}")

    if dry_run:
        console.print(
            Panel("[yellow]DRY RUN[/] - No changes will be made", style="yellow")
        )

    if pkg_type == "custom":
        # Handle custom package removal - look up spec internally
        specs = _load_specs()
        if name not in specs:
            console.print(
                f"[red]Error:[/] No spec found for custom package '{name}'."
            )
            raise SystemExit(1)

        pkg_config = CUSTOM_MANAGER._parse_config(name, specs[name])
        _print_header("Removing", pkg_type, [name])

        if not pkg_config.remove:
            console.print(
                f"[yellow]Warning:[/] No remove command defined for '{name}'.\n"
                f"The package may need to be removed manually."
            )
            # Still allow removing from manifest
            result = CommandResult(success=True)
        else:
            result = CUSTOM_MANAGER.remove(pkg_config, dry_run=dry_run)

        if result.success:
            _print_success()

            # Update manifest - remove from list
            if not dry_run and not keep_in_manifest:
                custom_list = raw_data.get("custom", [])
                if name in custom_list:
                    custom_list.remove(name)
                    _save_manifest(raw_data, path)
                    console.print(f"[dim]Removed from manifest:[/] {path}")
            elif keep_in_manifest:
                console.print(f"[dim]Kept in manifest (--keep)[/]")
        else:
            _print_error(result.message or "Removal failed")
            raise SystemExit(1)
    else:
        # Handle standard package managers
        _print_header("Removing", pkg_type, [name])
        manager = _get_manager(pkg_type)
        result = manager.remove([name], dry_run=dry_run)

        if result.success:
            _print_success()

            # Update manifest - find the section where package is defined
            # (may differ from resolved pkg_type due to fallback syntax)
            if not dry_run:
                manifest_type = _find_package_manifest_type(name, data)
                if manifest_type:
                    _update_raw_manifest(raw_data, manifest_type, name, "remove")
                    _save_manifest(raw_data, path)
                    console.print(f"[dim]Removed from manifest:[/] {path}")
        else:
            _print_error(result.message or "Removal failed")
            raise SystemExit(1)


def _build_package_panel(
    pkg_type: str,
    data: dict,
    verbose: bool,
) -> Optional[Panel]:
    """Build a panel for a package type. Returns None if no packages to show."""
    if pkg_type == "custom":
        color = CUSTOM_MANAGER.color
        custom_list = data.get("custom", [])
        if not custom_list and not verbose:
            return None

        specs = _load_specs()
        manifest_pkgs = set(custom_list)
        custom_configs = {name: specs[name] for name in specs if name in manifest_pkgs or verbose}
        installed_packages = CUSTOM_MANAGER.get_installed_packages(custom_configs)
        installed_names = {p.name for p in installed_packages}

        if verbose:
            all_names = set(specs.keys())
        else:
            all_names = manifest_pkgs

        if not all_names:
            return None

        # Build package lines
        lines = []
        for name in sorted(all_names):
            if name in installed_names:
                if verbose and name not in manifest_pkgs:
                    lines.append(f"[dim]{name}[/]")
                else:
                    lines.append(f"[green]{name}[/]")
            else:
                lines.append(f"[red]{name}[/]")

        count = len(manifest_pkgs)
        title = f"[bold {color}]{pkg_type}[/] [dim]({count})[/]"

        return Panel(
            "\n".join(lines),
            title=title,
            title_align="left",
            border_style=color,
            padding=(0, 1),
        )
    elif pkg_type == "winget":
        manager = MANAGERS.get(pkg_type)
        if not manager:
            return None

        color = manager.color

        if not manager.is_available():
            return Panel(
                "[dim]not available[/]",
                title=f"[bold {color}]{pkg_type}[/]",
                title_align="left",
                border_style="dim",
                padding=(0, 1),
            )

        installed_packages = manager.get_installed_packages()
        installed_by_id = {p.name: p for p in installed_packages}
        installed_by_name = {p.display_name: p for p in installed_packages if p.display_name}
        installed_by_id_lower = {
            name.lower(): pkg for name, pkg in installed_by_id.items()
        }
        installed_by_name_lower = {
            name.lower(): pkg for name, pkg in installed_by_name.items()
        }

        manifest_pkgs = set(data.get(pkg_type, []))
        manifest_pkgs_lower = {name.lower() for name in manifest_pkgs}

        if verbose:
            installed_names = {p.display_name or p.name for p in installed_packages}
            all_names = manifest_pkgs | installed_names
        else:
            all_names = manifest_pkgs

        if not all_names:
            return None

        def _find_installed(pkg_name: str) -> Optional[PackageInfo]:
            if pkg_name in installed_by_id:
                return installed_by_id[pkg_name]
            if pkg_name in installed_by_name:
                return installed_by_name[pkg_name]
            key = pkg_name.lower()
            return installed_by_id_lower.get(key) or installed_by_name_lower.get(key)

        lines = []
        for name in sorted(all_names):
            pkg = _find_installed(name)
            if pkg:
                display = pkg.display_name or pkg.name
                if verbose and name.lower() not in manifest_pkgs_lower:
                    lines.append(f"[dim]{display}[/]")
                else:
                    lines.append(f"[green]{display}[/]")
            else:
                lines.append(f"[red]{name}[/]")

        count = len(manifest_pkgs)
        title = f"[bold {color}]{pkg_type}[/] [dim]({count})[/]"

        return Panel(
            "\n".join(lines),
            title=title,
            title_align="left",
            border_style=color,
            padding=(0, 1),
        )
    else:
        manager = MANAGERS.get(pkg_type)
        if not manager:
            return None

        color = manager.color

        if not manager.is_available():
            return Panel(
                "[dim]not available[/]",
                title=f"[bold {color}]{pkg_type}[/]",
                title_align="left",
                border_style="dim",
                padding=(0, 1),
            )

        installed_packages = manager.get_installed_packages()
        installed_map = {p.name: p for p in installed_packages}
        manifest_pkgs = set(data.get(pkg_type, []))

        if verbose:
            all_names = manifest_pkgs | set(installed_map.keys())
        else:
            all_names = manifest_pkgs

        if not all_names:
            return None

        # Build package lines
        lines = []
        for name in sorted(all_names):
            pkg = installed_map.get(name)
            if pkg:
                display = pkg.display_name or pkg.name
                if verbose and name not in manifest_pkgs:
                    lines.append(f"[dim]{display}[/]")
                else:
                    lines.append(f"[green]{display}[/]")
            else:
                lines.append(f"[red]{name}[/]")

        count = len(manifest_pkgs)
        title = f"[bold {color}]{pkg_type}[/] [dim]({count})[/]"

        return Panel(
            "\n".join(lines),
            title=title,
            title_align="left",
            border_style=color,
            padding=(0, 1),
        )


@app.command(name="list")
def list_packages(
    *,
    env: Annotated[
        Optional[str],
        Parameter(
            name=["--env", "-e"],
            help="Path to YAML manifest file (default: ~/.config/packages.yaml)",
        ),
    ] = None,
    verbose: Annotated[
        bool,
        Parameter(
            name=["--verbose", "-v"],
            help="Show all packages, including untracked ones",
        ),
    ] = False,
    types: Annotated[
        Optional[str],
        Parameter(
            name=["--types", "-t"],
            help="Comma-separated package types to list (e.g., conda,python)",
        ),
    ] = None,
):
    """
    List tracked packages grouped by category.

    Packages are grouped into: macOS (brew/cask/mas), WSL (winget), General (conda/python/rust), and Custom.
    macOS packages are only shown when running on macOS. WSL packages only on WSL.

    [dim]Examples:[/]
      pkgmanager list
      pkgmanager list --verbose
      pkgmanager list --types conda,python
    """
    data, raw_data, path = _load_manifest(env)

    # Resolve packages to their actual managers based on platform preferences
    data = _resolve_all_packages(data)

    console.print(f"[dim]Manifest:[/] {path}")
    if not verbose:
        console.print("[dim]Showing tracked packages only. Use -v for all.[/]")
    console.print("[dim]Legend:[/] [green]installed[/] [red]missing[/]" + (" [dim]untracked[/]" if verbose else ""))

    # Filter types if specified
    filter_types = None
    if types:
        filter_types = set(t.strip() for t in types.split(","))

    # Display packages grouped by category
    for cat_name in _get_active_categories():
        cat = CATEGORIES[cat_name]
        cat_types = cat["types"]

        # Check if any types in this category should be shown
        if filter_types:
            cat_types = [t for t in cat_types if t in filter_types]

        # Build panels for this category
        panels = []
        for pkg_type in cat_types:
            panel = _build_package_panel(pkg_type, data, verbose)
            if panel:
                panels.append(panel)

        if not panels:
            continue

        # Print category header and panels side-by-side
        console.print()
        console.print(f"[bold cyan]━━━ {cat['title']} ━━━[/]")
        console.print(Columns(panels, equal=False, expand=False, padding=(0, 1)))


@app.command
def update(
    name: Annotated[
        Optional[str],
        Parameter(help="Package name to update (updates all if not specified)"),
    ] = None,
    *,
    pkg_type: Annotated[
        Optional[str],
        Parameter(
            name=["--type", "-t"],
            help="Package type (auto-detected if not specified)",
        ),
    ] = None,
    env: Annotated[
        Optional[str],
        Parameter(
            name=["--env", "-e"],
            help="Path to YAML manifest file (default: ~/.config/packages.yaml)",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        Parameter(
            name=["--dry-run", "-n"],
            help="Show what would be done without executing",
        ),
    ] = False,
):
    """
    Update packages.

    Updates a specific package or all packages if no name is given.

    [dim]Examples:[/]
      pkgmanager update              # Update all packages
      pkgmanager update tmux         # Update specific package
      pkgmanager update ruff -t python
      pkgmanager update --dry-run
    """
    data, raw_data, path = _load_manifest(env)

    if dry_run:
        console.print(
            Panel("[yellow]DRY RUN[/] - No changes will be made", style="yellow")
        )

    # Single package update
    if name:
        # Auto-detect type if not specified
        if pkg_type is None:
            pkg_type = _find_package_type(name, data)
            if pkg_type is None:
                # Try to find in any available manager
                for ptype, manager in MANAGERS.items():
                    if manager.is_available():
                        installed = _get_installed_names(manager)
                        if name in installed or (manager.name == "winget" and name.lower() in installed):
                            pkg_type = ptype
                            break
            if pkg_type is None:
                console.print(
                    f"[red]Error:[/] Package '{name}' not found.\n"
                    f"Use [dim]--type[/] to specify the package type."
                )
                raise SystemExit(1)
            console.print(f"[dim]Detected type:[/] {pkg_type}")

        _print_header("Updating", pkg_type, [name])
        manager = _get_manager(pkg_type)
        result = manager.update([name], dry_run=dry_run)

        if result.success:
            _print_success()
        else:
            _print_error(result.message or "Update failed")
        return

    # Update all packages
    all_types = list(data.keys())
    all_types = _reorder_types(all_types)

    console.print(f"[dim]Updating:[/] {', '.join(all_types)}\n")

    for pkg_type in all_types:
        _print_header("Updating", pkg_type)
        manager = _get_manager(pkg_type)
        result = manager.update(dry_run=dry_run)

        if result.success:
            _print_success()
        else:
            _print_error(result.message or "Update failed")


@app.command
def status(
    *,
    env: Annotated[
        Optional[str],
        Parameter(
            name=["--env", "-e"],
            help="Path to YAML manifest file (default: ~/.config/packages.yaml)",
        ),
    ] = None,
):
    """
    Show status of package managers and manifest.

    Displays information about available package managers grouped by category.
    macOS packages are only shown when running on macOS.

    [dim]Examples:[/]
      pkgmanager status
    """
    data, raw_data, path = _load_manifest(env)

    console.print(Panel("[bold]Package Manager Status[/]", style="cyan"))
    console.print(f"\n[dim]Manifest:[/] {path}")
    console.print(f"[dim]Shell:[/] {_detect_shell()}")
    console.print(f"[dim]Platform:[/] {sys.platform}\n")

    # Display status grouped by category
    for cat_name in _get_active_categories():
        cat = CATEGORIES[cat_name]

        table = Table(
            title=f"[bold cyan]{cat['title']}[/]",
            show_header=True,
            title_justify="left",
        )
        table.add_column("Manager", style="cyan", width=10)
        table.add_column("Tool", width=12)
        table.add_column("Available", width=10)
        table.add_column("Packages", justify="right", width=10)

        for pkg_type in cat["types"]:
            if pkg_type == "custom":
                custom_list = data.get("custom", [])
                table.add_row(
                    Text("custom", style=CUSTOM_MANAGER.color),
                    "scripts",
                    "[green]✓[/]",
                    str(len(custom_list)) if custom_list else "[dim]0[/]",
                )
            else:
                manager = MANAGERS.get(pkg_type)
                if not manager:
                    continue
                available = manager.is_available()
                status_text = "[green]✓[/]" if available else "[red]✗[/]"
                pkg_count = len(data.get(pkg_type, []))

                table.add_row(
                    Text(pkg_type, style=manager.color),
                    manager.tool,
                    status_text,
                    str(pkg_count) if pkg_count > 0 else "[dim]0[/]",
                )

        console.print(table)
        console.print()


@app.command
def bootstrap(
    name: Annotated[
        Optional[str],
        Parameter(help="Manager to install (conda, python, rust, mas, bun). Omit to install all."),
    ] = None,
    *,
    dry_run: Annotated[
        bool,
        Parameter(
            name=["--dry-run", "-n"],
            help="Show what would be done without executing",
        ),
    ] = False,
):
    """
    Install package managers themselves.

    Installs the underlying tools needed for each package manager type.
    For example, 'bun' installs bun, 'python' installs uv, 'rust' installs rustup.

    [dim]Examples:[/]
      pkgmanager bootstrap           Install all available managers
      pkgmanager bootstrap bun       Install bun
      pkgmanager bootstrap python    Install uv
      pkgmanager bootstrap rust      Install rustup
    """
    if dry_run:
        console.print("[dim]Dry run mode - no changes will be made[/]\n")

    # Filter managers that can be bootstrapped
    bootable = {k: v for k, v in MANAGERS.items() if v.install_cmds}

    if name:
        if name not in MANAGERS:
            console.print(f"[red]Error:[/] Unknown manager: {name}")
            console.print(f"[dim]Available:[/] {', '.join(MANAGERS.keys())}")
            raise SystemExit(1)

        manager = MANAGERS[name]
        if not manager.install_cmds:
            console.print(f"[yellow]Warning:[/] No install command defined for {name}")
            raise SystemExit(1)

        if manager.is_available():
            console.print(f"[green]✓[/] {name} is already installed ({manager.tool})")
            return

        console.print(f"[bold]Installing {name}...[/]")
        result = manager.install_self(dry_run)
        if result.success:
            console.print(f"[green]✓[/] {name} installed successfully")
        else:
            console.print(f"[red]✗[/] Failed to install {name}: {result.message}")
            raise SystemExit(1)
    else:
        # Install all missing managers
        console.print("[bold]Bootstrapping package managers...[/]\n")

        for mgr_name, manager in bootable.items():
            if manager.is_available():
                console.print(f"[green]✓[/] {mgr_name} ({manager.tool})")
            else:
                console.print(f"[yellow]○[/] {mgr_name} - installing...")
                result = manager.install_self(dry_run)
                if result.success:
                    console.print(f"  [green]✓[/] Installed {mgr_name}")
                else:
                    console.print(f"  [red]✗[/] Failed: {result.message}")


@app.command
def show(
    name: Annotated[str, Parameter(help="Package name to show")],
    *,
    pkg_type: Annotated[
        Optional[str],
        Parameter(
            name=["--type", "-t"],
            help="Package manager type (conda, python, rust). Auto-detected if not specified.",
        ),
    ] = None,
    env: Annotated[
        Optional[str],
        Parameter(
            name=["--env", "-e"],
            help="Path to YAML manifest file (default: ~/.config/packages.yaml)",
        ),
    ] = None,
):
    """
    Show detailed information about a package.

    Displays version, summary, dependencies, and other metadata
    for the specified package. Auto-detects package type if not specified.

    [dim]Examples:[/]
      pkgmanager show ruff
      pkgmanager show miniserve --type rust
      pkgmanager show fisher --type custom
    """
    data, raw_data, path = _load_manifest(env)

    found_details = None
    found_type = None

    # Check custom packages first if specified or during auto-detect
    if pkg_type == "custom" or pkg_type is None:
        specs = _load_specs()
        if name in specs:
            details = CUSTOM_MANAGER.get_package_details(name, specs[name])
            if details:
                found_details = details
                found_type = "custom"

    # Check standard managers if not found in custom
    if not found_details:
        # Determine which managers to search
        if pkg_type and pkg_type != "custom":
            managers_to_check = [(pkg_type, MANAGERS.get(pkg_type))]
            if not managers_to_check[0][1]:
                console.print(f"[red]Error:[/] Unknown package type: {pkg_type}")
                raise SystemExit(1)
        elif pkg_type is None:
            # Auto-detect: check all managers
            managers_to_check = list(MANAGERS.items())
        else:
            managers_to_check = []

        # Search for the package
        for type_name, manager in managers_to_check:
            if not manager or not manager.is_available():
                continue
            details = manager.get_package_details(name)
            if details:
                found_details = details
                found_type = type_name
                break

    if not found_details:
        console.print(f"[red]Error:[/] Package '{name}' not found")
        if not pkg_type:
            console.print("[dim]Try specifying --type if the package is installed[/]")
        raise SystemExit(1)

    # Check if tracked in manifest
    if found_type == "custom":
        manifest_pkgs = data.get("custom", [])
    else:
        manifest_pkgs = data.get(found_type, [])
    is_tracked = name in manifest_pkgs

    # Display package info
    if found_type == "custom":
        color = CUSTOM_MANAGER.color
    else:
        color = MANAGERS[found_type].color

    # Format version display (no "v" prefix for custom packages)
    if found_type == "custom":
        version_text = f"[dim]({found_details.version})[/]"
    else:
        version_text = f"[dim]v{found_details.version}[/]"

    console.print(
        Panel(
            f"[bold]{found_details.name}[/] {version_text}",
            style=color,
            subtitle=f"[{color}]{found_type}[/]",
            subtitle_align="right",
        )
    )

    # Create info table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="cyan", width=12)
    table.add_column("Value", style="white")

    table.add_row("Version", found_details.version)
    table.add_row("Type", f"[{color}]{found_type}[/]")
    table.add_row("Tracked", "[green]✓ yes[/]" if is_tracked else "[dim]no[/]")

    if found_details.summary:
        table.add_row("Summary", found_details.summary)
    if found_details.homepage:
        table.add_row("Homepage", f"[link={found_details.homepage}]{found_details.homepage}[/link]")
    if found_details.license:
        table.add_row("License", found_details.license)
    if found_details.location:
        table.add_row("Location", found_details.location)
    if found_details.requires:
        table.add_row("Requires", ", ".join(found_details.requires))
    if found_details.binaries:
        table.add_row("Binaries", ", ".join(found_details.binaries))

    console.print(table)


@app.command
def edit(
    *,
    env: Annotated[
        Optional[str],
        Parameter(
            name=["--env", "-e"],
            help="Path to YAML manifest file (default: ~/.config/packages.yaml)",
        ),
    ] = None,
):
    """
    Open the manifest file in your editor.

    Uses $EDITOR environment variable, falling back to 'vim' if not set.

    [dim]Examples:[/]
      pkgmanager edit
      EDITOR=code pkgmanager edit
    """
    _, _, path = _load_manifest(env)

    editor = os.environ.get("EDITOR", "vim")
    console.print(f"[dim]Opening:[/] {path}")

    try:
        subprocess.run([editor, str(path)], check=True)
    except FileNotFoundError:
        console.print(f"[red]Error:[/] Editor '{editor}' not found")
        raise SystemExit(1)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error:[/] Editor exited with code {e.returncode}")
        raise SystemExit(1)


def main():
    """Entry point for the CLI"""
    app()


if __name__ == "__main__":
    main()
