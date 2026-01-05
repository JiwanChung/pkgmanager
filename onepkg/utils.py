"""Utility functions for onepkg."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()


def detect_shell() -> str:
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


def is_macos() -> bool:
    """Check if running on macOS"""
    return sys.platform == "darwin"


def is_wsl() -> bool:
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


def platform_matches(platforms: Optional[object]) -> bool:
    """Check if current platform matches any of the provided platform tags."""
    if not platforms:
        return True
    if isinstance(platforms, str):
        platforms = [platforms]
    for platform in platforms:
        if platform == "wsl" and is_wsl():
            return True
        if platform == "darwin" and is_macos():
            return True
        if platform == "linux" and sys.platform == "linux":
            return True
        if platform in {"windows", "win32"} and sys.platform == "win32":
            return True
        if platform == sys.platform:
            return True
    return False


def print_header(
    action: str, pkg_type: str, packages: Optional[list[str]] = None, color: str = "white"
):
    """Print a styled header for an action"""
    if packages:
        pkg_list = ", ".join(packages) if len(packages) <= 3 else f"{len(packages)} packages"
        console.print(
            f"\n[bold {color}]▶ {action.capitalize()}[/] [{color}]{pkg_type}[/]: {pkg_list}"
        )
    else:
        console.print(f"\n[bold {color}]▶ {action.capitalize()}[/] [{color}]{pkg_type}[/]")


def print_success(message: str = "Done"):
    """Print a success message"""
    console.print(f"[green]✓[/] {message}")


def print_error(message: str):
    """Print an error message"""
    console.print(f"[red]✗[/] {message}")
