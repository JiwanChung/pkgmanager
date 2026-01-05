"""Manifest file handling for onepkg."""

import os
import sys
from pathlib import Path
from typing import Optional

import yaml

from .managers import CATEGORIES, CATEGORY_ORDER, MANAGERS
from .utils import console, is_macos, is_wsl


def get_default_manifest_path() -> Path:
    """Get the default manifest file path"""
    env_path = os.environ.get("PACKAGE_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    return Path.home() / ".config" / "packages.yaml"


def load_manifest(env: Optional[str] = None) -> tuple[dict, dict, Path]:
    """
    Load the package manifest file.

    Returns:
        (flattened_data, raw_data, path)
        - flattened_data: packages grouped by type (platform-filtered)
        - raw_data: original nested structure for round-trip saving
        - path: path to the manifest file
    """
    if env:
        path = Path(env).expanduser()
    else:
        path = get_default_manifest_path()

    if not path.exists():
        console.print(f"[red]Error:[/] Manifest file not found: {path}")
        console.print("[dim]Create one with your package definitions[/]")
        raise SystemExit(1)

    with open(path) as f:
        raw_data = yaml.safe_load(f) or {}

    # Flatten nested structure based on platform
    data = flatten_manifest(raw_data)

    return data, raw_data, path


def save_manifest(data: dict, path: Path):
    """Save manifest data to file"""
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def flatten_manifest(raw_data: dict) -> dict:
    """
    Flatten nested manifest structure based on current platform.

    Converts:
        mac:
          brew: [...]
        general:
          python: [...]

    To:
        brew: [...]
        python: [...]

    Only includes packages for the current platform.
    """
    flattened = {}
    active_categories = get_active_categories()

    for cat_name in active_categories:
        # Check if this category has a section in raw_data
        if cat_name in raw_data:
            section = raw_data[cat_name]
            if isinstance(section, dict):
                for pkg_type, packages in section.items():
                    if packages:
                        # Filter by platform constraints in package entries
                        filtered = filter_packages_by_platform(packages)
                        if filtered:
                            flattened[pkg_type] = filtered

    # Handle custom packages at top level
    if "custom" in raw_data:
        custom_list = raw_data["custom"]
        if isinstance(custom_list, list):
            filtered = filter_packages_by_platform(custom_list)
            if filtered:
                flattened["custom"] = filtered

    return flattened


def filter_packages_by_platform(packages: list) -> list:
    """Filter package list by platform constraints"""
    filtered = []
    for entry in packages:
        if isinstance(entry, dict):
            # Check for platform constraint
            platform = entry.get("platform") or entry.get("platforms")
            if platform:
                from .utils import platform_matches

                if not platform_matches(platform):
                    continue
            # Extract name for the flattened list
            name = entry.get("name")
            if name:
                filtered.append(name)
        else:
            # Simple string entry
            filtered.append(entry)
    return filtered


def get_active_categories() -> list[str]:
    """Get list of active category names for current platform"""
    active = []
    for cat_name in CATEGORY_ORDER:
        cat = CATEGORIES[cat_name]
        platform = cat.get("platform")

        if platform is None:
            active.append(cat_name)
        elif platform == "darwin" and is_macos():
            active.append(cat_name)
        elif platform == "wsl" and is_wsl():
            active.append(cat_name)
        elif platform == "linux" and sys.platform == "linux":
            active.append(cat_name)

    return active


def get_category_for_type(pkg_type: str) -> Optional[str]:
    """Get the category name for a package type"""
    for cat_name, cat in CATEGORIES.items():
        if pkg_type in cat["types"]:
            return cat_name
    return None


def update_raw_manifest(raw_data: dict, pkg_type: str, name: str, action: str):
    """
    Update the raw manifest data structure.

    Args:
        raw_data: The raw nested manifest data
        pkg_type: Package type (brew, python, etc.)
        name: Package name
        action: "add" or "remove"
    """
    if pkg_type == "custom":
        # Custom packages are at the top level
        if "custom" not in raw_data:
            raw_data["custom"] = []
        if action == "add":
            if name not in raw_data["custom"]:
                raw_data["custom"].append(name)
        elif action == "remove":
            if name in raw_data["custom"]:
                raw_data["custom"].remove(name)
    else:
        # Find the category for this type
        category = get_category_for_type(pkg_type)
        if not category:
            # Default to general
            category = "general"

        if category not in raw_data:
            raw_data[category] = {}
        if pkg_type not in raw_data[category]:
            raw_data[category][pkg_type] = []

        if action == "add":
            if name not in raw_data[category][pkg_type]:
                raw_data[category][pkg_type].append(name)
        elif action == "remove":
            # Handle both simple names and dict entries
            pkg_list = raw_data[category][pkg_type]
            for i, entry in enumerate(pkg_list):
                entry_name = entry.get("name") if isinstance(entry, dict) else entry
                if entry_name == name:
                    pkg_list.pop(i)
                    break


def parse_package_entry(entry: str) -> tuple[str, Optional[str]]:
    """
    Parse a package entry that may have fallback syntax.

    "tmux:brew" -> ("tmux", "brew")
    "ripgrep" -> ("ripgrep", None)
    """
    if ":" in entry:
        parts = entry.split(":", 1)
        return parts[0], parts[1]
    return entry, None


def parse_custom_entry(entry) -> tuple[Optional[str], Optional[object]]:
    """
    Parse a custom package entry.

    Can be:
        - "fisher" -> ("fisher", None)
        - {"name": "tool", "platform": "linux"} -> ("tool", "linux")
    """
    if isinstance(entry, str):
        return entry, None
    elif isinstance(entry, dict):
        name = entry.get("name")
        platforms = entry.get("platform") or entry.get("platforms")
        return name, platforms
    return None, None


def package_in_list(name: str, pkg_list: list) -> bool:
    """Check if a package name is in the list (handling fallback syntax)"""
    for entry in pkg_list:
        if isinstance(entry, str):
            entry_name, _ = parse_package_entry(entry)
            if entry_name == name:
                return True
        elif isinstance(entry, dict):
            if entry.get("name") == name:
                return True
    return False


def find_package_manifest_type(name: str, data: dict) -> Optional[str]:
    """Find which package type a package belongs to in the manifest"""
    # Check custom first
    if "custom" in data and name in data["custom"]:
        return "custom"

    # Check standard types
    for pkg_type in MANAGERS.keys():
        packages = data.get(pkg_type, [])
        if package_in_list(name, packages):
            return pkg_type

    return None


def resolve_package_manager(
    pkg_name: str, preferred_manager: Optional[str], default_manager: str
) -> str:
    """
    Resolve which package manager to use for a package.

    Args:
        pkg_name: Package name
        preferred_manager: Preferred manager from fallback syntax (e.g., "brew" from "pkg:brew")
        default_manager: Default manager this package is listed under

    Returns:
        The resolved manager name to use
    """
    if not preferred_manager:
        return default_manager

    # Check if preferred manager exists and is available
    manager = MANAGERS.get(preferred_manager)
    if not manager:
        return default_manager

    if not manager.is_available():
        return default_manager

    # Check if this manager type is active on current platform
    active_cats = get_active_categories()
    for cat_name in active_cats:
        if preferred_manager in CATEGORIES[cat_name]["types"]:
            return preferred_manager

    return default_manager


def resolve_all_packages(data: dict) -> dict:
    """
    Resolve all packages to their actual managers based on fallback syntax.

    For example, if "tmux:brew" is under conda, on macOS it moves to brew,
    on Linux it stays under conda.
    """
    resolved = {}

    for pkg_type, packages in data.items():
        if pkg_type == "custom":
            resolved["custom"] = packages
            continue

        for entry in packages:
            if isinstance(entry, str):
                pkg_name, preferred = parse_package_entry(entry)
                target_manager = resolve_package_manager(pkg_name, preferred, pkg_type)
            else:
                # Dict entry with platform constraint
                pkg_name = entry.get("name", entry)
                target_manager = pkg_type

            if target_manager not in resolved:
                resolved[target_manager] = []
            if pkg_name not in resolved[target_manager]:
                resolved[target_manager].append(pkg_name)

    return resolved


def find_custom_entry(raw_data: dict, name: str) -> Optional[object]:
    """Find a custom package entry in raw data and return its platforms"""
    custom_list = raw_data.get("custom", [])
    for entry in custom_list:
        if isinstance(entry, str) and entry == name:
            return None
        elif isinstance(entry, dict) and entry.get("name") == name:
            return entry.get("platform") or entry.get("platforms")
    return None


def reorder_types(types: list[str]) -> list[str]:
    """Reorder package types according to MANAGER_ORDER"""
    from .managers import MANAGER_ORDER

    ordered = []
    for t in MANAGER_ORDER:
        if t in types:
            ordered.append(t)
    # Add any remaining types not in MANAGER_ORDER
    for t in types:
        if t not in ordered:
            ordered.append(t)
    return ordered


def get_installed_names(manager) -> set[str]:
    """Get set of installed package names for a manager"""
    return {p.name for p in manager.get_installed_packages()}
