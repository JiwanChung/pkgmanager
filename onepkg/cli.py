"""CLI commands for onepkg."""

import os
import subprocess
from typing import Annotated, Optional

import yaml
from cyclopts import App, Parameter
from rich.panel import Panel
from rich.table import Table

from .managers import (
    CATEGORIES,
    CUSTOM_MANAGER,
    MANAGERS,
    load_specs,
)
from .manifest import (
    find_custom_entry,
    find_package_manifest_type,
    get_active_categories,
    get_installed_names,
    load_manifest,
    reorder_types,
    resolve_all_packages,
    save_manifest,
    update_raw_manifest,
)
from .models import PackageInfo
from .utils import (
    console,
    detect_shell,
    platform_matches,
    print_error,
    print_header,
    print_success,
)

__version__ = "0.6.0"

# Application setup
app = App(
    name="onepkg",
    help_format="rich",
    help="""
[bold cyan]onepkg[/] - Unified package manager for your dotfiles

Manage packages across [bright_yellow]brew[/], [bright_blue]cask[/],
[bright_cyan]mas[/], [green]conda[/], [yellow]python (uv)[/], [red]rust (cargo)[/],
[cyan]go[/], [bright_magenta]bun[/], and [cyan]winget (WSL)[/] with a single YAML manifest file.

[dim]Examples:[/]
  onepkg init                    Install all packages from manifest
  onepkg install brew ripgrep    Install a brew formula
  onepkg install go github.com/jesseduffield/lazygit  Install a Go binary
  onepkg list                    List all installed packages
  onepkg diff                    Show manifest vs system differences
  onepkg sync                    Sync packages from manifest
""",
    version=__version__,
)


def _print_header(action: str, pkg_type: str, packages: Optional[list[str]] = None):
    """Print a styled header for an action"""
    if pkg_type == "custom":
        color = CUSTOM_MANAGER.color
    else:
        manager = MANAGERS.get(pkg_type)
        color = manager.color if manager else "white"
    print_header(action, pkg_type, packages, color)


def _print_success(message: str = "Done"):
    print_success(message)


def _print_error(message: str):
    print_error(message)


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
    quiet: Annotated[
        bool,
        Parameter(
            name=["--quiet", "-q"],
            help="Suppress non-essential output",
        ),
    ] = False,
    continue_on_error: Annotated[
        bool,
        Parameter(
            name=["--continue-on-error", "-c"],
            help="Continue installing other packages if one fails",
        ),
    ] = False,
    locked: Annotated[
        bool,
        Parameter(
            name=["--locked"],
            help="Install exact versions from lock file",
        ),
    ] = False,
    lock_file: Annotated[
        Optional[str],
        Parameter(
            name=["--lock-file"],
            help="Path to lock file (default: packages.lock.yaml)",
        ),
    ] = None,
):
    """
    Install all packages from the YAML manifest.

    Reads the manifest file and installs all listed packages for each
    configured package manager.

    [dim]Examples:[/]
      onepkg init
      onepkg init --env ~/packages.yaml
      onepkg init --types conda,python
      onepkg init --dry-run
      onepkg init --locked        Install exact versions from lock file
    """
    from pathlib import Path

    data, raw_data, path = load_manifest(env)

    # Load lock file if --locked is specified
    lock_data: dict[str, dict[str, str]] = {}
    if locked:
        if lock_file:
            lock_path = Path(lock_file)
        else:
            lock_path = path.parent / "packages.lock.yaml"

        if not lock_path.exists():
            console.print(f"[red]Error:[/] Lock file not found: {lock_path}")
            console.print("[dim]Run 'onepkg lock' to create one[/]")
            raise SystemExit(1)

        with open(lock_path) as f:
            lock_data = yaml.safe_load(f) or {}
        console.print(f"[dim]Lock file:[/] {lock_path}")
    data = resolve_all_packages(data)

    if dry_run:
        console.print(Panel("[yellow]DRY RUN[/] - No changes will be made", style="yellow"))

    all_types = list(data.keys())
    if types:
        all_types = [t.strip() for t in types.split(",")]

    all_types = reorder_types(all_types)

    if not quiet:
        console.print(f"[dim]Manifest:[/] {path}")
        console.print(f"[dim]Package types:[/] {', '.join(all_types)}")

    success_count = 0
    error_count = 0

    for pkg_type in all_types:
        packages = data.get(pkg_type, [])
        if not packages:
            continue

        if pkg_type == "custom":
            specs = load_specs()
            pkg_names = [p for p in packages if p in specs]
            missing = []

            for name in pkg_names:
                pkg_config = CUSTOM_MANAGER.parse_config(name, specs[name])
                if not CUSTOM_MANAGER.is_installed(pkg_config):
                    missing.append(name)

            if not missing:
                if not quiet:
                    console.print(
                        f"\n[{CUSTOM_MANAGER.color}]{pkg_type}[/]: all {len(pkg_names)} packages installed"
                    )
                continue

            if not quiet:
                _print_header("Installing", pkg_type, missing)
                console.print(
                    f"  [dim]Skipping {len(pkg_names) - len(missing)} already installed[/]"
                )

            for name in missing:
                pkg_config = CUSTOM_MANAGER.parse_config(name, specs[name])
                if not quiet:
                    console.print(f"\n  [magenta]{name}[/]")
                    if pkg_config.depends:
                        console.print(f"  [dim]Depends:[/] {', '.join(pkg_config.depends)}")

                result = CUSTOM_MANAGER.install(pkg_config, dry_run=dry_run)
                if result.success:
                    if not quiet:
                        _print_success(f"{name} installed")
                else:
                    error_count += 1
                    _print_error(result.message or f"{name} installation failed")
        else:
            manager = MANAGERS.get(pkg_type)
            if not manager or not manager.is_available():
                if not quiet:
                    console.print(
                        f"\n[yellow]Skipping {pkg_type}:[/] {manager.tool if manager else pkg_type} not available"
                    )
                continue

            installed = get_installed_names(manager)
            if manager.name == "winget":
                missing = [p for p in packages if p not in installed and p.lower() not in installed]
            else:
                missing = [p for p in packages if p not in installed]

            if not missing:
                if not quiet:
                    console.print(
                        f"\n[{manager.color}]{pkg_type}[/]: all {len(packages)} packages installed"
                    )
                continue

            if not quiet:
                _print_header("Installing", pkg_type, missing)
                console.print(
                    f"  [dim]Skipping {len(packages) - len(missing)} already installed[/]"
                )

            # Apply locked versions if available
            install_list = missing
            if locked and pkg_type in lock_data:
                locked_versions = lock_data[pkg_type]
                install_list = []
                for pkg in missing:
                    if pkg in locked_versions:
                        version = locked_versions[pkg]
                        # Format version spec based on manager type
                        if pkg_type in ("python", "rust", "go", "bun"):
                            install_list.append(f"{pkg}@{version}")
                        elif pkg_type == "brew":
                            # Brew doesn't support version pinning in install
                            install_list.append(pkg)
                        else:
                            install_list.append(pkg)
                    else:
                        install_list.append(pkg)
                if not quiet and any("@" in p for p in install_list):
                    console.print("  [dim]Using locked versions[/]")

            result = manager.install(install_list, dry_run=dry_run)

            if result.success:
                success_count += 1
                if not quiet:
                    _print_success()
            else:
                error_count += 1
                _print_error(result.message or "Installation failed")

    if not quiet:
        console.print()
    if error_count == 0:
        if not quiet:
            console.print(Panel("[green]All packages installed successfully![/]", style="green"))
    else:
        console.print(Panel(f"[yellow]Completed with {error_count} error(s)[/]", style="yellow"))


@app.command
def sync(
    *,
    env: Annotated[
        Optional[str], Parameter(name=["--env", "-e"], help="Path to manifest file")
    ] = None,
    types: Annotated[
        Optional[str], Parameter(name=["--types", "-t"], help="Package types to sync")
    ] = None,
    dry_run: Annotated[bool, Parameter(name=["--dry-run", "-n"], help="Dry run mode")] = False,
    quiet: Annotated[bool, Parameter(name=["--quiet", "-q"], help="Quiet mode")] = False,
    continue_on_error: Annotated[
        bool, Parameter(name=["--continue-on-error", "-c"], help="Continue on error")
    ] = False,
    locked: Annotated[
        bool, Parameter(name=["--locked"], help="Install exact versions from lock file")
    ] = False,
    lock_file: Annotated[
        Optional[str], Parameter(name=["--lock-file"], help="Path to lock file")
    ] = None,
):
    """Sync packages from the YAML manifest (alias for init)."""
    init(
        env=env,
        types=types,
        dry_run=dry_run,
        quiet=quiet,
        continue_on_error=continue_on_error,
        locked=locked,
        lock_file=lock_file,
    )


@app.command
def install(
    pkg_type: Annotated[
        str,
        Parameter(
            help="Package type (brew, cask, mas, winget, conda, python, rust, go, bun, custom)"
        ),
    ],
    name: Annotated[str, Parameter(help="Package name (or app ID for mas)")],
    *,
    env: Annotated[
        Optional[str], Parameter(name=["--env", "-e"], help="Path to manifest file")
    ] = None,
    dry_run: Annotated[bool, Parameter(name=["--dry-run", "-n"], help="Dry run mode")] = False,
    force: Annotated[bool, Parameter(name=["--force", "-f"], help="Force reinstall")] = False,
):
    """
    Install a package and add it to the manifest.

    [dim]Examples:[/]
      onepkg install brew ripgrep
      onepkg install python ruff
      onepkg install go github.com/jesseduffield/lazygit
    """
    data, raw_data, path = load_manifest(env)

    if dry_run:
        console.print(Panel("[yellow]DRY RUN[/] - No changes will be made", style="yellow"))

    if pkg_type == "custom":
        specs = load_specs()
        if name not in specs:
            console.print(f"[red]Error:[/] No spec found for custom package '{name}'")
            raise SystemExit(1)

        platforms = find_custom_entry(raw_data, name)
        if platforms and not platform_matches(platforms):
            console.print(
                f"[red]Error:[/] Custom package '{name}' is not supported on this platform."
            )
            raise SystemExit(1)

        pkg_config = CUSTOM_MANAGER.parse_config(name, specs[name])

        if not force and CUSTOM_MANAGER.is_installed(pkg_config):
            console.print(f"[green]✓[/] {name} is already installed (use --force to reinstall)")
            if not dry_run:
                custom_list = data.get("custom", [])
                if name not in custom_list:
                    if "custom" not in raw_data:
                        raw_data["custom"] = []
                    raw_data["custom"].append(name)
                    save_manifest(raw_data, path)
                    console.print(f"[dim]Added to manifest:[/] {path}")
            return

        _print_header("Installing", pkg_type, [name])
        if pkg_config.depends:
            console.print(f"  [dim]Depends:[/] {', '.join(pkg_config.depends)}")

        result = CUSTOM_MANAGER.install(pkg_config, dry_run=dry_run)

        if result.success:
            _print_success()
            if not dry_run:
                custom_list = data.get("custom", [])
                if name not in custom_list:
                    if "custom" not in raw_data:
                        raw_data["custom"] = []
                    raw_data["custom"].append(name)
                    save_manifest(raw_data, path)
                    console.print(f"[dim]Added to manifest:[/] {path}")
        else:
            _print_error(result.message or "Installation failed")
            raise SystemExit(1)
    else:
        manager = MANAGERS.get(pkg_type)
        if not manager:
            console.print(f"[red]Error:[/] Unknown package type: {pkg_type}")
            raise SystemExit(1)

        if not force:
            installed = get_installed_names(manager)
            is_installed = name in installed or (
                manager.name == "winget" and name.lower() in installed
            )
            if is_installed:
                console.print(f"[green]✓[/] {name} is already installed (use --force to reinstall)")
                if not dry_run:
                    if name not in data.get(pkg_type, []):
                        update_raw_manifest(raw_data, pkg_type, name, "add")
                        save_manifest(raw_data, path)
                        console.print(f"[dim]Added to manifest:[/] {path}")
                return

        _print_header("Installing", pkg_type, [name])
        result = manager.install([name], dry_run=dry_run)

        if result.success:
            _print_success()
            if not dry_run:
                if name not in data.get(pkg_type, []):
                    update_raw_manifest(raw_data, pkg_type, name, "add")
                    save_manifest(raw_data, path)
                    console.print(f"[dim]Added to manifest:[/] {path}")
        else:
            _print_error(result.message or "Installation failed")
            raise SystemExit(1)


@app.command
def remove(
    name: Annotated[str, Parameter(help="Package name to remove")],
    *,
    pkg_type: Annotated[
        Optional[str], Parameter(name=["--type", "-t"], help="Package type")
    ] = None,
    env: Annotated[
        Optional[str], Parameter(name=["--env", "-e"], help="Path to manifest file")
    ] = None,
    dry_run: Annotated[bool, Parameter(name=["--dry-run", "-n"], help="Dry run mode")] = False,
    keep: Annotated[bool, Parameter(name=["--keep", "-k"], help="Keep in manifest")] = False,
):
    """
    Remove a package and update the manifest.

    [dim]Examples:[/]
      onepkg remove ripgrep
      onepkg remove raycast --type cask
    """
    data, raw_data, path = load_manifest(env)

    if dry_run:
        console.print(Panel("[yellow]DRY RUN[/] - No changes will be made", style="yellow"))

    # Auto-detect type if not provided
    if not pkg_type:
        pkg_type = find_package_manifest_type(name, data)
        if not pkg_type:
            console.print(f"[red]Error:[/] Package '{name}' not found in manifest")
            console.print("[dim]Specify --type to remove an untracked package[/]")
            raise SystemExit(1)

    if pkg_type == "custom":
        specs = load_specs()
        if name not in specs:
            console.print(f"[red]Error:[/] No spec found for '{name}'")
            raise SystemExit(1)

        pkg_config = CUSTOM_MANAGER.parse_config(name, specs[name])
        _print_header("Removing", pkg_type, [name])

        result = CUSTOM_MANAGER.remove(pkg_config, dry_run=dry_run)
        if result.success:
            _print_success()
            if not dry_run and not keep:
                update_raw_manifest(raw_data, "custom", name, "remove")
                save_manifest(raw_data, path)
                console.print(f"[dim]Removed from manifest:[/] {path}")
        else:
            _print_error(result.message or "Removal failed")
            raise SystemExit(1)
    else:
        manager = MANAGERS.get(pkg_type)
        if not manager:
            console.print(f"[red]Error:[/] Unknown package type: {pkg_type}")
            raise SystemExit(1)

        _print_header("Removing", pkg_type, [name])
        result = manager.remove([name], dry_run=dry_run)

        if result.success:
            _print_success()
            if not dry_run and not keep:
                update_raw_manifest(raw_data, pkg_type, name, "remove")
                save_manifest(raw_data, path)
                console.print(f"[dim]Removed from manifest:[/] {path}")
        else:
            _print_error(result.message or "Removal failed")
            raise SystemExit(1)


@app.command
def list(
    *,
    env: Annotated[
        Optional[str], Parameter(name=["--env", "-e"], help="Path to manifest file")
    ] = None,
    verbose: Annotated[
        bool, Parameter(name=["--verbose", "-v"], help="Show untracked packages")
    ] = False,
    types: Annotated[
        Optional[str], Parameter(name=["--types", "-t"], help="Package types to list")
    ] = None,
):
    """
    List tracked packages grouped by category.

    [dim]Examples:[/]
      onepkg list
      onepkg list --verbose
      onepkg list --types brew,python
    """
    data, raw_data, path = load_manifest(env)
    data = resolve_all_packages(data)

    console.print(f"[dim]Manifest:[/] {path}\n")

    filter_types = None
    if types:
        filter_types = set(t.strip() for t in types.split(","))

    for cat_name in get_active_categories():
        cat = CATEGORIES[cat_name]
        cat_types = cat["types"]

        if filter_types:
            cat_types = [t for t in cat_types if t in filter_types]

        if not cat_types:
            continue

        has_content = False
        for pkg_type in cat_types:
            manifest_pkgs = data.get(pkg_type, [])
            if pkg_type == "custom":
                if manifest_pkgs:
                    has_content = True
                    break
            else:
                manager = MANAGERS.get(pkg_type)
                if manager and (manager.is_available() or manifest_pkgs):
                    has_content = True
                    break

        if not has_content:
            continue

        console.print(f"[bold]{cat['title']}[/]")

        for pkg_type in cat_types:
            if pkg_type == "custom":
                custom_list = data.get("custom", [])
                if not custom_list:
                    continue

                specs = load_specs()
                console.print(f"  [{CUSTOM_MANAGER.color}]{pkg_type}[/]")

                for name in custom_list:
                    if name in specs:
                        pkg_config = CUSTOM_MANAGER.parse_config(name, specs[name])
                        if CUSTOM_MANAGER.is_installed(pkg_config):
                            console.print(f"    [green]●[/] {name}")
                        else:
                            console.print(f"    [red]○[/] {name}")
                    else:
                        console.print(f"    [dim]?[/] {name} [dim](no spec)[/]")
            else:
                manager = MANAGERS.get(pkg_type)
                if not manager:
                    continue

                manifest_pkgs = set(data.get(pkg_type, []))
                if manager.is_available():
                    installed = manager.get_installed_packages()
                    installed_names = {p.name for p in installed}
                else:
                    installed_names = set()

                if not manifest_pkgs and not (verbose and installed_names):
                    continue

                status = "[green]✓[/]" if manager.is_available() else "[red]✗[/]"
                console.print(f"  [{manager.color}]{pkg_type}[/] {status}")

                # Show tracked packages
                for name in sorted(manifest_pkgs):
                    if name in installed_names:
                        console.print(f"    [green]●[/] {name}")
                    else:
                        console.print(f"    [red]○[/] {name}")

                # Show untracked if verbose
                if verbose:
                    untracked = installed_names - manifest_pkgs
                    for name in sorted(untracked):
                        console.print(f"    [dim]○ {name}[/]")

        console.print()


@app.command
def update(
    name: Annotated[Optional[str], Parameter(help="Package name (omit to update all)")] = None,
    *,
    pkg_type: Annotated[
        Optional[str], Parameter(name=["--type", "-t"], help="Package type")
    ] = None,
    env: Annotated[
        Optional[str], Parameter(name=["--env", "-e"], help="Path to manifest file")
    ] = None,
    dry_run: Annotated[bool, Parameter(name=["--dry-run", "-n"], help="Dry run mode")] = False,
):
    """
    Update packages.

    [dim]Examples:[/]
      onepkg update           Update all packages
      onepkg update ruff      Update specific package
      onepkg update --type brew  Update all brew packages
    """
    data, raw_data, path = load_manifest(env)

    if dry_run:
        console.print(Panel("[yellow]DRY RUN[/] - No changes will be made", style="yellow"))

    if name:
        # Update specific package
        if not pkg_type:
            pkg_type = find_package_manifest_type(name, data)

        if pkg_type == "custom":
            console.print("[yellow]Custom packages cannot be updated automatically[/]")
            return

        if pkg_type:
            manager = MANAGERS.get(pkg_type)
        else:
            # Search all managers
            for mgr_type, mgr in MANAGERS.items():
                if not mgr.is_available():
                    continue
                installed = get_installed_names(mgr)
                if name in installed:
                    manager = mgr
                    pkg_type = mgr_type
                    break
            else:
                console.print(f"[red]Error:[/] Package '{name}' not found")
                raise SystemExit(1)

        _print_header("Updating", pkg_type, [name])
        result = manager.update([name], dry_run=dry_run)
        if result.success:
            _print_success()
        else:
            _print_error(result.message or "Update failed")
    else:
        # Update all
        for pkg_type in reorder_types(list(MANAGERS.keys())):
            manager = MANAGERS[pkg_type]
            if not manager.is_available():
                continue

            _print_header("Updating", pkg_type)
            result = manager.update(dry_run=dry_run)
            if result.success:
                _print_success()
            else:
                _print_error(result.message or "Update failed")


@app.command
def status(
    *,
    env: Annotated[
        Optional[str], Parameter(name=["--env", "-e"], help="Path to manifest file")
    ] = None,
):
    """Show status of package managers and manifest."""
    data, raw_data, path = load_manifest(env)
    data = resolve_all_packages(data)

    console.print(f"[dim]Manifest:[/] {path}\n")

    for cat_name in get_active_categories():
        cat = CATEGORIES[cat_name]

        table = Table(title=cat["title"], show_header=True)
        table.add_column("Type", style="cyan")
        table.add_column("Tool")
        table.add_column("Status")
        table.add_column("Tracked")
        table.add_column("Installed")

        for pkg_type in cat["types"]:
            if pkg_type == "custom":
                custom_list = data.get("custom", [])
                specs = load_specs()
                installed_count = sum(
                    1
                    for name in custom_list
                    if name in specs
                    and CUSTOM_MANAGER.is_installed(CUSTOM_MANAGER.parse_config(name, specs[name]))
                )
                table.add_row(
                    pkg_type,
                    "scripts",
                    "[green]✓[/]",
                    str(len(custom_list)),
                    str(installed_count),
                )
            else:
                manager = MANAGERS.get(pkg_type)
                if not manager:
                    continue

                is_avail = manager.is_available()
                status = "[green]✓[/]" if is_avail else "[red]✗[/]"
                tracked = len(data.get(pkg_type, []))
                installed = len(manager.get_installed_packages()) if is_avail else 0

                table.add_row(
                    pkg_type,
                    manager.tool,
                    status,
                    str(tracked),
                    str(installed),
                )

        console.print(table)
        console.print()


@app.command
def diff(
    *,
    env: Annotated[
        Optional[str], Parameter(name=["--env", "-e"], help="Path to manifest file")
    ] = None,
    types: Annotated[
        Optional[str], Parameter(name=["--types", "-t"], help="Package types to check")
    ] = None,
):
    """
    Show differences between manifest and installed packages.

    [dim]Examples:[/]
      onepkg diff
      onepkg diff --types brew,cask
    """
    data, raw_data, path = load_manifest(env)
    data = resolve_all_packages(data)

    console.print(f"[dim]Manifest:[/] {path}\n")

    filter_types = None
    if types:
        filter_types = set(t.strip() for t in types.split(","))

    total_missing = 0
    total_untracked = 0

    for cat_name in get_active_categories():
        cat = CATEGORIES[cat_name]
        cat_types = cat["types"]

        if filter_types:
            cat_types = [t for t in cat_types if t in filter_types]

        for pkg_type in cat_types:
            if pkg_type == "custom":
                custom_list = data.get("custom", [])
                if not custom_list:
                    continue

                specs = load_specs()
                manifest_pkgs = set(custom_list)
                custom_configs = {name: specs[name] for name in specs if name in manifest_pkgs}
                installed_packages = CUSTOM_MANAGER.get_installed_packages(custom_configs)
                installed_names = {p.name for p in installed_packages}

                missing = manifest_pkgs - installed_names

                if missing:
                    console.print(f"[bold {CUSTOM_MANAGER.color}]{pkg_type}[/]")
                    for name in sorted(missing):
                        console.print(f"  [red]+ {name}[/] [dim](not installed)[/]")
                        total_missing += 1
                    console.print()
            else:
                manager = MANAGERS.get(pkg_type)
                if not manager or not manager.is_available():
                    continue

                manifest_pkgs = set(data.get(pkg_type, []))
                installed_packages = manager.get_installed_packages()
                installed_names = {p.name for p in installed_packages}

                missing = manifest_pkgs - installed_names
                untracked = installed_names - manifest_pkgs

                if not missing and not untracked:
                    continue

                console.print(f"[bold {manager.color}]{pkg_type}[/]")

                for name in sorted(missing):
                    console.print(f"  [red]+ {name}[/] [dim](not installed)[/]")
                    total_missing += 1

                for name in sorted(untracked):
                    console.print(f"  [yellow]- {name}[/] [dim](untracked)[/]")
                    total_untracked += 1

                console.print()

    if total_missing == 0 and total_untracked == 0:
        console.print(Panel("[green]Everything is in sync![/]", style="green"))
    else:
        summary_parts = []
        if total_missing > 0:
            summary_parts.append(f"[red]{total_missing} missing[/]")
        if total_untracked > 0:
            summary_parts.append(f"[yellow]{total_untracked} untracked[/]")
        console.print(
            Panel(
                " | ".join(summary_parts)
                + "\n[dim]Run 'onepkg init' to install missing packages[/]",
                style="cyan",
            )
        )


@app.command
def export(
    *,
    types: Annotated[
        Optional[str], Parameter(name=["--types", "-t"], help="Package types to export")
    ] = None,
    format: Annotated[
        str, Parameter(name=["--format", "-f"], help="Output format: yaml or list")
    ] = "yaml",
):
    """
    Export installed packages to manifest format.

    [dim]Examples:[/]
      onepkg export > packages.yaml
      onepkg export --types brew,cask
      onepkg export --format list
    """
    filter_types = None
    if types:
        filter_types = set(t.strip() for t in types.split(","))

    export_data: dict[str, dict[str, list[str]]] = {}

    for cat_name in get_active_categories():
        cat = CATEGORIES[cat_name]
        cat_types = cat["types"]

        if filter_types:
            cat_types = [t for t in cat_types if t in filter_types]

        for pkg_type in cat_types:
            if pkg_type == "custom":
                continue

            manager = MANAGERS.get(pkg_type)
            if not manager or not manager.is_available():
                continue

            installed = manager.get_installed_packages()
            if not installed:
                continue

            pkg_names = sorted([p.name for p in installed])

            if format == "list":
                console.print(f"[bold cyan]{pkg_type}[/]")
                for name in pkg_names:
                    console.print(f"  {name}")
                console.print()
            else:
                if cat_name not in export_data:
                    export_data[cat_name] = {}
                export_data[cat_name][pkg_type] = pkg_names

    if format == "yaml":
        yaml_output = yaml.dump(export_data, default_flow_style=False, sort_keys=False)
        print(yaml_output)


@app.command
def bootstrap(
    name: Annotated[Optional[str], Parameter(help="Manager to install (omit for all)")] = None,
    *,
    dry_run: Annotated[bool, Parameter(name=["--dry-run", "-n"], help="Dry run mode")] = False,
):
    """
    Install package managers themselves.

    [dim]Examples:[/]
      onepkg bootstrap
      onepkg bootstrap rust
    """
    if dry_run:
        console.print(Panel("[yellow]DRY RUN[/] - No changes will be made", style="yellow"))

    managers_to_install = []

    if name:
        if name not in MANAGERS:
            console.print(f"[red]Error:[/] Unknown manager: {name}")
            raise SystemExit(1)
        managers_to_install = [name]
    else:
        for mgr_name, manager in MANAGERS.items():
            if not manager.is_available() and manager.install_cmds:
                managers_to_install.append(mgr_name)

    if not managers_to_install:
        console.print("[green]All package managers are already installed![/]")
        return

    for mgr_name in managers_to_install:
        manager = MANAGERS[mgr_name]
        console.print(f"\n[bold {manager.color}]Installing {mgr_name}...[/]")
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
        Optional[str], Parameter(name=["--type", "-t"], help="Package type")
    ] = None,
    env: Annotated[
        Optional[str], Parameter(name=["--env", "-e"], help="Path to manifest file")
    ] = None,
):
    """
    Show detailed information about a package.

    [dim]Examples:[/]
      onepkg show ruff
      onepkg show miniserve --type rust
    """
    data, raw_data, path = load_manifest(env)

    found_details = None
    found_type = None

    # Check custom packages first
    if pkg_type == "custom" or pkg_type is None:
        specs = load_specs()
        if name in specs:
            details = CUSTOM_MANAGER.get_package_details(name, specs[name])
            if details:
                found_details = details
                found_type = "custom"

    if not found_details:
        if pkg_type and pkg_type != "custom":
            managers_to_check = [(pkg_type, MANAGERS.get(pkg_type))]
        elif pkg_type is None:
            managers_to_check = list(MANAGERS.items())
        else:
            managers_to_check = []

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
        raise SystemExit(1)

    # Display
    if found_type == "custom":
        color = CUSTOM_MANAGER.color
    else:
        color = MANAGERS[found_type].color

    console.print(f"[bold {color}]{found_details.name}[/] [dim]v{found_details.version}[/]")
    console.print(f"[dim]Type:[/] {found_type}")

    if found_details.summary:
        console.print(f"\n{found_details.summary}")
    if found_details.homepage:
        console.print(f"\n[dim]Homepage:[/] {found_details.homepage}")
    if found_details.license:
        console.print(f"[dim]License:[/] {found_details.license}")
    if found_details.location:
        console.print(f"[dim]Location:[/] {found_details.location}")
    if found_details.requires:
        console.print(f"[dim]Requires:[/] {', '.join(found_details.requires)}")
    if found_details.binaries:
        console.print(f"[dim]Binaries:[/] {', '.join(found_details.binaries)}")


@app.command
def edit(
    *,
    env: Annotated[
        Optional[str], Parameter(name=["--env", "-e"], help="Path to manifest file")
    ] = None,
):
    """Open the manifest file in your editor."""
    _, _, path = load_manifest(env)
    editor = os.environ.get("EDITOR", "vim")
    console.print(f"[dim]Opening:[/] {path}")

    try:
        subprocess.run([editor, str(path)], check=True)
    except FileNotFoundError:
        console.print(f"[red]Error:[/] Editor '{editor}' not found")
        raise SystemExit(1)


@app.command
def search(
    query: Annotated[str, Parameter(help="Package name to search for")],
    *,
    types: Annotated[
        Optional[str], Parameter(name=["--types", "-t"], help="Package types to search")
    ] = None,
):
    """
    Search for packages across package managers.

    [dim]Examples:[/]
      onepkg search ripgrep
      onepkg search python --types brew,conda
    """
    filter_types = None
    if types:
        filter_types = set(t.strip() for t in types.split(","))

    console.print(f"[dim]Searching for:[/] {query}\n")

    found_in = []

    for pkg_type, manager in MANAGERS.items():
        if filter_types and pkg_type not in filter_types:
            continue
        if not manager.is_available():
            continue

        installed = manager.get_installed_packages()
        matches = [p for p in installed if query.lower() in p.name.lower()]

        if matches:
            found_in.append((pkg_type, manager.color, matches, True))

    # Also search brew
    if not filter_types or "brew" in filter_types or "cask" in filter_types:
        brew_manager = MANAGERS.get("brew")
        if brew_manager and brew_manager.is_available():
            try:
                shell = detect_shell()
                result = subprocess.run(
                    [shell, "-l", "-c", f"brew search {query}"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and result.stdout.strip():
                    lines = result.stdout.strip().split("\n")
                    formulae, casks = [], []
                    current_section = None
                    for line in lines:
                        if "==> Formulae" in line:
                            current_section = "formulae"
                        elif "==> Casks" in line:
                            current_section = "casks"
                        elif line.strip() and not line.startswith("==>"):
                            pkgs = line.split()
                            if current_section == "formulae":
                                formulae.extend(pkgs)
                            elif current_section == "casks":
                                casks.extend(pkgs)
                            elif current_section is None:
                                formulae.extend(pkgs)

                    if formulae and (not filter_types or "brew" in filter_types):
                        if not any(f[0] == "brew" for f in found_in):
                            found_in.append(
                                (
                                    "brew",
                                    "bright_yellow",
                                    [PackageInfo(name=f, version="") for f in formulae[:10]],
                                    False,
                                )
                            )

                    if casks and (not filter_types or "cask" in filter_types):
                        if not any(f[0] == "cask" for f in found_in):
                            found_in.append(
                                (
                                    "cask",
                                    "bright_blue",
                                    [PackageInfo(name=c, version="") for c in casks[:10]],
                                    False,
                                )
                            )
            except Exception:
                pass

    if not found_in:
        console.print(f"[yellow]No packages found matching '{query}'[/]")
        return

    for pkg_type, color, matches, is_installed in found_in:
        status = "[green](installed)[/]" if is_installed else "[dim](available)[/]"
        console.print(f"[bold {color}]{pkg_type}[/] {status}")
        for pkg in matches[:5]:
            version_str = f" [dim]v{pkg.version}[/]" if pkg.version else ""
            console.print(f"  {pkg.name}{version_str}")
        if len(matches) > 5:
            console.print(f"  [dim]... and {len(matches) - 5} more[/]")
        console.print()


@app.command
def doctor(
    *,
    env: Annotated[
        Optional[str], Parameter(name=["--env", "-e"], help="Path to manifest file")
    ] = None,
):
    """Diagnose issues with package managers and manifest."""
    data, raw_data, path = load_manifest(env)
    data = resolve_all_packages(data)

    console.print(Panel("[bold]Package Manager Doctor[/]", style="cyan"))
    console.print()

    issues, warnings, ok_items = [], [], []

    if path.exists():
        ok_items.append(f"Manifest file exists: {path}")
    else:
        issues.append(f"Manifest file not found: {path}")

    for pkg_type, manager in MANAGERS.items():
        if manager.is_available():
            ok_items.append(f"{pkg_type}: {manager.tool} is available")
        else:
            if data.get(pkg_type):
                issues.append(
                    f"{pkg_type}: {manager.tool} not found but manifest has {len(data[pkg_type])} packages"
                )
            else:
                warnings.append(f"{pkg_type}: {manager.tool} not installed")

    missing_count = 0
    for pkg_type in data:
        if pkg_type == "custom":
            continue
        manager = MANAGERS.get(pkg_type)
        if not manager or not manager.is_available():
            continue

        installed = get_installed_names(manager)
        manifest_pkgs = set(data.get(pkg_type, []))
        missing = manifest_pkgs - installed
        if missing:
            missing_count += len(missing)
            warnings.append(f"{pkg_type}: {len(missing)} packages not installed")

    if missing_count == 0:
        ok_items.append("All manifest packages are installed")

    for item in ok_items:
        console.print(f"[green]✓[/] {item}")
    if warnings:
        console.print()
        for item in warnings:
            console.print(f"[yellow]![/] {item}")
    if issues:
        console.print()
        for item in issues:
            console.print(f"[red]✗[/] {item}")

    console.print()
    if issues:
        console.print(Panel(f"[red]Found {len(issues)} issue(s)[/]", style="red"))
    elif warnings:
        console.print(Panel(f"[yellow]Found {len(warnings)} warning(s)[/]", style="yellow"))
    else:
        console.print(Panel("[green]Everything looks good![/]", style="green"))


@app.command
def outdated(
    *,
    types: Annotated[
        Optional[str], Parameter(name=["--types", "-t"], help="Package types to check")
    ] = None,
):
    """Show packages with available updates."""
    filter_types = None
    if types:
        filter_types = set(t.strip() for t in types.split(","))

    console.print("[dim]Checking for outdated packages...[/]\n")
    total_outdated = 0

    if (not filter_types or "brew" in filter_types) and MANAGERS["brew"].is_available():
        try:
            shell = detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", "brew outdated --formula"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split("\n")
                console.print(f"[bold bright_yellow]brew[/] ({len(lines)} outdated)")
                for line in lines[:10]:
                    console.print(f"  {line}")
                if len(lines) > 10:
                    console.print(f"  [dim]... and {len(lines) - 10} more[/]")
                console.print()
                total_outdated += len(lines)
        except Exception:
            pass

    if (not filter_types or "cask" in filter_types) and MANAGERS["cask"].is_available():
        try:
            shell = detect_shell()
            result = subprocess.run(
                [shell, "-l", "-c", "brew outdated --cask"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split("\n")
                console.print(f"[bold bright_blue]cask[/] ({len(lines)} outdated)")
                for line in lines[:10]:
                    console.print(f"  {line}")
                console.print()
                total_outdated += len(lines)
        except Exception:
            pass

    if total_outdated == 0:
        console.print(Panel("[green]All packages are up to date![/]", style="green"))
    else:
        console.print(
            Panel(f"[yellow]{total_outdated} package(s) can be updated[/]", style="yellow")
        )


@app.command
def clean(
    *,
    env: Annotated[
        Optional[str], Parameter(name=["--env", "-e"], help="Path to manifest file")
    ] = None,
    types: Annotated[
        Optional[str], Parameter(name=["--types", "-t"], help="Package types to clean")
    ] = None,
    dry_run: Annotated[bool, Parameter(name=["--dry-run", "-n"], help="Dry run mode")] = False,
):
    """
    Remove packages not in the manifest (untracked packages).

    [dim]Examples:[/]
      onepkg clean --dry-run
      onepkg clean --types python
    """
    data, raw_data, path = load_manifest(env)
    data = resolve_all_packages(data)

    console.print(f"[dim]Manifest:[/] {path}\n")

    if dry_run:
        console.print(Panel("[yellow]DRY RUN[/] - No changes will be made", style="yellow"))
        console.print()

    filter_types = None
    if types:
        filter_types = set(t.strip() for t in types.split(","))

    total_untracked = 0
    to_remove: dict[str, list[str]] = {}

    for pkg_type, manager in MANAGERS.items():
        if filter_types and pkg_type not in filter_types:
            continue
        if not manager.is_available():
            continue

        manifest_pkgs = set(data.get(pkg_type, []))
        installed_names = {p.name for p in manager.get_installed_packages()}
        untracked = installed_names - manifest_pkgs

        if untracked:
            to_remove[pkg_type] = sorted(untracked)
            total_untracked += len(untracked)

    if total_untracked == 0:
        console.print(Panel("[green]No untracked packages found![/]", style="green"))
        return

    console.print(f"[bold]Found {total_untracked} untracked package(s):[/]\n")

    for pkg_type, packages in to_remove.items():
        manager = MANAGERS[pkg_type]
        console.print(f"[bold {manager.color}]{pkg_type}[/]")
        for pkg in packages[:20]:
            console.print(f"  [red]- {pkg}[/]")
        if len(packages) > 20:
            console.print(f"  [dim]... and {len(packages) - 20} more[/]")
        console.print()

    if dry_run:
        console.print("[dim]Run without --dry-run to remove these packages[/]")
        return

    console.print("[yellow]Warning:[/] This will remove these packages from your system.")
    try:
        response = input("Continue? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]Cancelled[/]")
        return

    if response != "y":
        console.print("[dim]Cancelled[/]")
        return

    for pkg_type, packages in to_remove.items():
        manager = MANAGERS[pkg_type]
        _print_header("Removing", pkg_type, packages)
        result = manager.remove(packages, dry_run=False)
        if result.success:
            _print_success()
        else:
            _print_error(result.message or "Removal failed")

    console.print(Panel("[green]Cleaned up untracked packages![/]", style="green"))


@app.command
def lock(
    *,
    env: Annotated[
        Optional[str], Parameter(name=["--env", "-e"], help="Path to manifest file")
    ] = None,
    output: Annotated[
        Optional[str],
        Parameter(name=["--output", "-o"], help="Output lock file path"),
    ] = None,
    types: Annotated[
        Optional[str], Parameter(name=["--types", "-t"], help="Package types to lock")
    ] = None,
):
    """
    Create a lock file with exact package versions.

    Captures the current versions of all installed packages that are in
    your manifest, creating a reproducible snapshot for deployment.

    [dim]Examples:[/]
      onepkg lock                     Create packages.lock.yaml
      onepkg lock -o my.lock.yaml     Custom output file
      onepkg lock --types python,rust Lock only specific types
    """
    from pathlib import Path

    data, raw_data, manifest_path = load_manifest(env)
    data = resolve_all_packages(data)

    # Determine lock file path
    if output:
        lock_path = Path(output)
    else:
        lock_path = manifest_path.parent / "packages.lock.yaml"

    console.print(f"[dim]Manifest:[/] {manifest_path}")
    console.print(f"[dim]Lock file:[/] {lock_path}\n")

    filter_types = None
    if types:
        filter_types = set(t.strip() for t in types.split(","))

    lock_data: dict[str, dict[str, str]] = {}
    total_locked = 0

    for pkg_type, manager in MANAGERS.items():
        if filter_types and pkg_type not in filter_types:
            continue
        if not manager.is_available():
            continue

        manifest_pkgs = set(data.get(pkg_type, []))
        if not manifest_pkgs:
            continue

        installed = manager.get_installed_packages()
        installed_map = {p.name: p.version for p in installed}

        locked_versions = {}
        for pkg in manifest_pkgs:
            if pkg in installed_map:
                version = installed_map[pkg]
                if version:
                    locked_versions[pkg] = version
                    total_locked += 1

        if locked_versions:
            lock_data[pkg_type] = dict(sorted(locked_versions.items()))

    if total_locked == 0:
        console.print(
            Panel("[yellow]No packages to lock (none installed from manifest)[/]", style="yellow")
        )
        return

    # Write lock file
    with open(lock_path, "w") as f:
        f.write("# onepkg lock file - DO NOT EDIT\n")
        f.write(f"# Generated from: {manifest_path}\n")
        f.write(f"# Packages: {total_locked}\n\n")
        yaml.dump(lock_data, f, default_flow_style=False, sort_keys=False)

    console.print(f"[bold]Locked {total_locked} package(s):[/]\n")
    for pkg_type, versions in lock_data.items():
        manager = MANAGERS[pkg_type]
        console.print(f"[bold {manager.color}]{pkg_type}[/] ({len(versions)})")
        items = [*versions.items()][:5]
        for name, version in items:
            console.print(f"  {name} [dim]@ {version}[/]")
        if len(versions) > 5:
            console.print(f"  [dim]... and {len(versions) - 5} more[/]")
        console.print()

    console.print(Panel(f"[green]Lock file created: {lock_path}[/]", style="green"))


@app.command
def completions(
    shell_type: Annotated[str, Parameter(help="Shell type: bash, zsh, or fish")],
):
    """Generate shell completion script."""
    commands = [
        "init",
        "sync",
        "install",
        "remove",
        "list",
        "update",
        "status",
        "diff",
        "export",
        "lock",
        "bootstrap",
        "show",
        "edit",
        "search",
        "doctor",
        "outdated",
        "clean",
        "completions",
    ]
    pkg_types = list(MANAGERS.keys()) + ["custom"]

    if shell_type == "bash":
        script = f'''# onepkg bash completion
_onepkg() {{
    local cur prev
    COMPREPLY=()
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"
    case "${{prev}}" in
        onepkg) COMPREPLY=( $(compgen -W "{" ".join(commands)}" -- "${{cur}}") );;
        install) COMPREPLY=( $(compgen -W "{" ".join(pkg_types)}" -- "${{cur}}") );;
    esac
}}
complete -F _onepkg onepkg
'''
    elif shell_type == "zsh":
        script = """#compdef onepkg
_onepkg() {
    local -a commands
    commands=(init sync install remove list update status diff export lock bootstrap show edit search doctor outdated clean completions)
    _arguments '1: :->cmd' '*: :->args'
    case $state in cmd) _describe 'command' commands;; esac
}
_onepkg "$@"
"""
    elif shell_type == "fish":
        script = f"""# onepkg fish completion
set -l commands {" ".join(commands)}
set -l types {" ".join(pkg_types)}
complete -c onepkg -f
complete -c onepkg -n "not __fish_seen_subcommand_from $commands" -a "$commands"
complete -c onepkg -n "__fish_seen_subcommand_from install" -a "$types"
"""
    else:
        console.print(f"[red]Error:[/] Unknown shell: {shell_type}")
        raise SystemExit(1)

    print(script)


def main():
    """Entry point for the CLI"""
    app()


if __name__ == "__main__":
    main()
