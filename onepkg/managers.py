"""Package manager implementations."""

import os
import re
import shlex
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from importlib import resources
from pathlib import Path
from typing import Optional

import yaml

from .models import CommandResult, CustomPackageConfig, PackageDetails, PackageInfo
from .utils import console, detect_shell


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
    def update(self, packages: Optional[list[str]] = None, dry_run: bool = False) -> CommandResult:
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
            shell = detect_shell()
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
        "linux": [
            "sh",
            "-c",
            "curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba && mv bin/micromamba ~/.local/bin/",
        ],
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
            shell = detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", f"micromamba list -n {self.env_name}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            packages = []
            for line in result.stdout.splitlines():
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 3:
                    name, version, channel = parts[0], parts[1], parts[-1]
                    if channel == "pypi":
                        continue
                    packages.append(PackageInfo(name=name, version=version))
            return packages
        except subprocess.CalledProcessError:
            return []

    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get detailed info about a conda package"""
        try:
            shell = detect_shell()
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

    def update(self, packages: Optional[list[str]] = None, dry_run: bool = False) -> CommandResult:
        if packages:
            return self._run_command(
                ["conda", "update", "-n", self.env_name, "-y", *packages], dry_run
            )
        return self._run_command(["conda", "update", "-n", self.env_name, "--all", "-y"], dry_run)


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
            result = self._run_command(["uv", "tool", "install", pkg, "--force"], dry_run)
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
            shell = detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", "uv tool list"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            packages = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("-"):
                    continue
                match = re.match(r"^(\S+)\s+v?(\S+)$", line)
                if match:
                    packages.append(PackageInfo(name=match.group(1), version=match.group(2)))
            return packages
        except subprocess.CalledProcessError:
            return []

    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get detailed info about a python tool package"""
        try:
            shell = detect_shell()
            packages = self.get_installed_packages()
            pkg_info = next((p for p in packages if p.name == name), None)
            if not pkg_info:
                return None

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

    def update(self, packages: Optional[list[str]] = None, dry_run: bool = False) -> CommandResult:
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
        "all": [
            "sh",
            "-c",
            "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y",
        ],
    }

    def install(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        return self._run_command(["cargo", "install", "--locked", *packages], dry_run)

    def remove(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        return self._run_command(["cargo", "uninstall", *packages], dry_run)

    def get_installed_packages(self) -> list[PackageInfo]:
        """Get cargo installed packages"""
        try:
            shell = detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", "cargo install --list"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            packages = []
            for line in result.stdout.splitlines():
                match = re.match(r"^(\S+)\s+v(\S+):$", line)
                if match:
                    packages.append(PackageInfo(name=match.group(1), version=match.group(2)))
            return packages
        except subprocess.CalledProcessError:
            return []

    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get detailed info about a cargo package"""
        try:
            shell = detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", "cargo install --list"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
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

    def update(self, packages: Optional[list[str]] = None, dry_run: bool = False) -> CommandResult:
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


class GoManager(PackageManager):
    """Go package manager (via go install)"""

    name = "go"
    color = "cyan"
    tool = "go"
    install_cmds = {
        "darwin": ["brew", "install", "go"],
        "linux": [
            "sh",
            "-c",
            "curl -fsSL https://go.dev/dl/go1.22.0.linux-amd64.tar.gz | tar -C ~/.local -xzf -",
        ],
    }

    def _get_gobin(self) -> Path:
        """Get GOBIN or default ~/go/bin"""
        gobin = os.environ.get("GOBIN")
        if gobin:
            return Path(gobin)
        gopath = os.environ.get("GOPATH", os.path.expanduser("~/go"))
        return Path(gopath) / "bin"

    def install(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        for pkg in packages:
            pkg_spec = pkg if "@" in pkg else f"{pkg}@latest"
            result = self._run_command(["go", "install", pkg_spec], dry_run)
            if not result.success:
                return result
        return CommandResult(success=True)

    def remove(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        gobin = self._get_gobin()
        for pkg in packages:
            binary_name = pkg.split("/")[-1]
            binary_path = gobin / binary_name

            if dry_run:
                console.print(f"  [dim]Would remove:[/] {binary_path}")
            else:
                if binary_path.exists():
                    binary_path.unlink()
                    console.print(f"  [dim]Removed:[/] {binary_path}")
                else:
                    console.print(f"  [yellow]Not found:[/] {binary_path}")
        return CommandResult(success=True)

    def get_installed_packages(self) -> list[PackageInfo]:
        """Get installed Go binaries with their module paths"""
        try:
            gobin = self._get_gobin()
            if not gobin.exists():
                return []

            packages = []
            shell = detect_shell()

            for binary in gobin.iterdir():
                if not binary.is_file():
                    continue

                result = subprocess.run(
                    [shell, "-l", "-c", f"go version -m {binary}"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    mod_path = binary.name
                    version = "unknown"
                    for line in lines:
                        parts = line.strip().split("\t")
                        if len(parts) >= 2:
                            if parts[0] == "path":
                                mod_path = parts[1]
                            elif parts[0] == "mod" and len(parts) >= 3:
                                version = parts[2]
                    packages.append(PackageInfo(name=mod_path, version=version))
                else:
                    packages.append(PackageInfo(name=binary.name, version="unknown"))

            return packages
        except Exception:
            return []

    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get detailed info about a Go package"""
        packages = self.get_installed_packages()
        for pkg in packages:
            if pkg.name == name or pkg.name.endswith(f"/{name}"):
                return PackageDetails(
                    name=pkg.name,
                    version=pkg.version,
                    location=str(self._get_gobin() / name.split("/")[-1]),
                    binaries=[name.split("/")[-1]],
                )
        return None

    def update(self, packages: Optional[list[str]] = None, dry_run: bool = False) -> CommandResult:
        if packages:
            for pkg in packages:
                pkg_spec = pkg if "@" in pkg else f"{pkg}@latest"
                result = self._run_command(["go", "install", pkg_spec], dry_run)
                if not result.success:
                    return result
            return CommandResult(success=True)
        else:
            installed = self.get_installed_packages()
            for pkg in installed:
                if pkg.name != "unknown":
                    result = self._run_command(["go", "install", f"{pkg.name}@latest"], dry_run)
                    if not result.success:
                        console.print(f"  [yellow]Failed to update {pkg.name}[/]")
            return CommandResult(success=True)


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
            shell = detect_shell()
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
                    version = parts[-1]
                    packages.append(PackageInfo(name=name, version=version))
            return packages
        except subprocess.CalledProcessError:
            return []

    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get detailed info about a brew package"""
        try:
            shell = detect_shell()
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

            first_line = lines[0]
            match = re.match(r"^==> (\S+): .*?(\d+\.\d+[\.\d]*)", first_line)
            if match:
                pkg_name, version = match.group(1), match.group(2)
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

    def update(self, packages: Optional[list[str]] = None, dry_run: bool = False) -> CommandResult:
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
            shell = detect_shell()
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
            shell = detect_shell()
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

    def update(self, packages: Optional[list[str]] = None, dry_run: bool = False) -> CommandResult:
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
        for app_id in packages:
            result = self._run_command(["mas", "install", str(app_id)], dry_run)
            if not result.success:
                return result
        return CommandResult(success=True)

    def remove(self, packages: list[str], dry_run: bool = False) -> CommandResult:
        console.print(
            "  [yellow]Warning:[/] mas cannot uninstall apps. Remove via Finder or Launchpad."
        )
        return CommandResult(success=True, message="Manual removal required")

    def get_installed_packages(self) -> list[PackageInfo]:
        """Get installed Mac App Store apps"""
        try:
            shell = detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", "mas list"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            packages = []
            for line in result.stdout.splitlines():
                match = re.match(r"^(\d+)\s+(.+?)\s+\(([^)]+)\)$", line.strip())
                if match:
                    app_id, app_name, version = match.groups()
                    packages.append(
                        PackageInfo(
                            name=app_id,
                            version=version,
                            display_name=app_name,
                        )
                    )
            return packages
        except subprocess.CalledProcessError:
            return []

    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get details about a Mac App Store app (by ID)"""
        try:
            shell = detect_shell()
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

    def update(self, packages: Optional[list[str]] = None, dry_run: bool = False) -> CommandResult:
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
            shell = detect_shell()
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
                    packages.append(PackageInfo(name=pkg_id, version=version, display_name=name))
            return packages
        except subprocess.CalledProcessError:
            return []

    def get_package_details(self, name: str) -> Optional[PackageDetails]:
        """Get detailed info about a winget package"""
        try:
            shell = detect_shell()
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

    def update(self, packages: Optional[list[str]] = None, dry_run: bool = False) -> CommandResult:
        if packages:
            results = []
            for pkg in packages:
                pkg_escaped = shlex.quote(pkg)
                results.append(self._run_command(["winget.exe", "upgrade", pkg_escaped], dry_run))
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
            shell = detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", "bun pm ls -g"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            )
            packages = []
            for line in result.stdout.splitlines():
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

            shell = detect_shell()
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

    def update(self, packages: Optional[list[str]] = None, dry_run: bool = False) -> CommandResult:
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
        return detect_shell()

    def _run_script(self, script: str, shell: str, dry_run: bool = False) -> CommandResult:
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
            return False

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

    def install(self, pkg_config: CustomPackageConfig, dry_run: bool = False) -> CommandResult:
        """Install a custom package"""
        shell = self._get_shell(pkg_config)
        console.print(f"  [dim]Shell:[/] {shell}")
        return self._run_script(pkg_config.install, shell, dry_run)

    def remove(self, pkg_config: CustomPackageConfig, dry_run: bool = False) -> CommandResult:
        """Remove a custom package"""
        if not pkg_config.remove:
            return CommandResult(
                success=False, message="No remove command specified for this package"
            )
        shell = self._get_shell(pkg_config)
        return self._run_script(pkg_config.remove, shell, dry_run)

    def get_installed_packages(self, custom_configs: dict[str, dict]) -> list[PackageInfo]:
        """Get list of installed custom packages"""
        packages = []
        for name, config in custom_configs.items():
            pkg_config = self.parse_config(name, config)
            if self.is_installed(pkg_config):
                packages.append(PackageInfo(name=name, version="custom"))
        return packages

    def get_package_details(self, name: str, config: dict) -> Optional[PackageDetails]:
        """Get details about a custom package"""
        pkg_config = self.parse_config(name, config)
        if not self.is_installed(pkg_config):
            return None

        return PackageDetails(
            name=name,
            version="custom",
            summary=pkg_config.description
            or f"Custom package ({pkg_config.shell or 'default shell'})",
            binaries=[],
            requires=pkg_config.depends,
        )

    @staticmethod
    def parse_config(name: str, config: dict) -> CustomPackageConfig:
        """Parse a config dict into CustomPackageConfig"""
        if isinstance(config, str):
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


def load_specs() -> dict:
    """Load custom package specs from the bundled specs.yaml"""
    try:
        specs_file = resources.files("onepkg").joinpath("specs.yaml")
        with resources.as_file(specs_file) as path:
            with open(path) as f:
                return yaml.safe_load(f) or {}
    except Exception:
        return {}


# Registry of available package managers
MANAGERS: dict[str, PackageManager] = {
    "conda": CondaManager(),
    "python": PythonManager(),
    "rust": RustManager(),
    "go": GoManager(),
    "brew": BrewManager(),
    "cask": CaskManager(),
    "mas": MasManager(),
    "winget": WingetManager(),
    "bun": BunManager(),
}

# Custom manager instance (separate since it has different interface)
CUSTOM_MANAGER = CustomManager()

# Preferred order for processing
MANAGER_ORDER = ["brew", "cask", "mas", "winget", "conda", "python", "rust", "go", "bun", "custom"]

# Category definitions for grouping package types
CATEGORIES = {
    "mac": {
        "title": "macOS",
        "types": ["brew", "cask", "mas"],
        "platform": "darwin",
    },
    "wsl": {
        "title": "WSL",
        "types": ["winget"],
        "platform": "wsl",
    },
    "general": {
        "title": "General",
        "types": ["conda", "python", "rust", "go", "bun"],
        "platform": None,
    },
    "custom": {
        "title": "Custom",
        "types": ["custom"],
        "platform": None,
    },
}

CATEGORY_ORDER = ["mac", "wsl", "general", "custom"]
