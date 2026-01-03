<div align="center">

# pkgmanager

**One manifest to rule them all.**

A unified CLI that manages packages across Homebrew, Cargo, uv, Bun, and more — all from a single YAML file.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

</div>

---

## Why pkgmanager?

Setting up a new machine means running `brew install`, `cargo install`, `uv tool install`, and more — each with their own syntax and state. **pkgmanager** consolidates everything into one manifest:

```yaml
general:
  brew:
    - ripgrep
    - fzf
  python:
    - ruff
    - pyright
  rust:
    - miniserve
```

Then sync everywhere with one command:

```bash
pkgmanager sync
```

---

## Features

- **Single manifest** — Track all packages in `~/.config/packages.yaml`
- **Cross-platform** — macOS, Linux, and WSL support with platform-specific sections
- **Smart syncing** — Only installs what's missing, skips what's already there
- **Fallback syntax** — Define preferred managers with automatic fallbacks (`tmux:brew`)
- **Custom packages** — Shell script-based installs for anything else
- **Beautiful output** — Rich terminal UI with progress and status

---

## Supported Package Managers

| Type | Tool | Platform | Description |
|:-----|:-----|:---------|:------------|
| `brew` | Homebrew | macOS | CLI tools and formulae |
| `cask` | Homebrew Cask | macOS | GUI applications |
| `mas` | Mac App Store | macOS | App Store apps (by ID) |
| `conda` | micromamba | All | Conda packages |
| `python` | uv | All | Python CLI tools |
| `rust` | cargo | All | Rust binaries |
| `bun` | bun | All | JavaScript/TypeScript tools |
| `winget` | winget.exe | WSL | Windows packages from WSL |
| `custom` | shell scripts | All | Custom installation scripts |

---

## Installation

```bash
# Using uv (recommended)
uv tool install pkgmanager

# Or from source
git clone https://github.com/JiwanChung/pkgmanager
cd pkgmanager
uv tool install .
```

---

## Quick Start

### 1. Create a manifest

```bash
mkdir -p ~/.config
cat > ~/.config/packages.yaml << 'EOF'
general:
  brew:
    - ripgrep
    - fzf
    - jq
  python:
    - ruff
    - black
  rust:
    - bat
    - eza
EOF
```

### 2. Sync packages

```bash
pkgmanager sync
```

### 3. Add more packages

```bash
pkgmanager install brew fd
pkgmanager install python poetry
pkgmanager install cask raycast
```

---

## Usage

### Sync from manifest

```bash
pkgmanager sync                    # Install all packages
pkgmanager sync --types brew,rust  # Install specific types only
pkgmanager sync --dry-run          # Preview what would be installed
```

### Install packages

```bash
pkgmanager install brew ripgrep    # Homebrew formula
pkgmanager install cask raycast    # Homebrew cask (GUI app)
pkgmanager install mas 937984704   # Mac App Store (by ID)
pkgmanager install python ruff     # Python tool via uv
pkgmanager install rust miniserve  # Rust binary via cargo
pkgmanager install bun typescript  # Bun global package
```

### Remove packages

```bash
pkgmanager remove ripgrep          # Auto-detects type
pkgmanager remove ruff --type python
```

### Update packages

```bash
pkgmanager update                  # Update all
pkgmanager update ruff             # Update specific package
```

### List & status

```bash
pkgmanager list                    # Show tracked packages
pkgmanager list -v                 # Include untracked installed packages
pkgmanager status                  # Show manager availability
pkgmanager show ruff               # Detailed package info
```

### Bootstrap managers

```bash
pkgmanager bootstrap               # Install all missing managers
pkgmanager bootstrap bun           # Install just bun
pkgmanager bootstrap rust          # Install rustup
```

---

## Manifest Format

The manifest lives at `~/.config/packages.yaml` (override with `$PACKAGE_CONFIG`):

```yaml
# macOS-specific packages
mac:
  brew:
    - infisical
    - mackup
  cask:
    - raycast
    - ghostty
  mas:
    - '937984704'  # Amphetamine

# Cross-platform packages
general:
  conda:
    - python
    - nodejs
  python:
    - ruff
    - pyright
    - poetry
  rust:
    - miniserve
    - bat
    - eza
  bun:
    - typescript
    - prettier

# WSL-specific packages (Windows from Linux)
wsl:
  winget:
    - Microsoft.PowerToys

# Custom script-based packages
custom:
  - fisher
  - my-custom-tool
```

### Platform-specific packages

Restrict packages to specific platforms:

```yaml
general:
  python:
    - ruff
    - { name: "linux-only-tool", platform: "linux" }
    - { name: "mac-only-tool", platform: "darwin" }
```

### Fallback syntax

Prefer one manager but fall back to another:

```yaml
general:
  conda:
    - python
    - tmux:brew    # Use brew on macOS, conda elsewhere
```

---

## Custom Packages

Define custom packages in a `specs.yaml` bundled with pkgmanager:

```yaml
fisher:
  description: Fish plugin manager
  shell: fish
  check: type -q fisher
  install: curl -sL https://git.io/fisher | source && fisher install jorgebucaran/fisher
  remove: fisher self-uninstall

my-tool:
  check: command -v my-tool
  install: |
    curl -L https://example.com/install.sh | bash
  depends:
    - curl
```

---

## Environment Variables

| Variable | Description | Default |
|:---------|:------------|:--------|
| `PACKAGE_CONFIG` | Path to manifest file | `~/.config/packages.yaml` |
| `EDITOR` | Editor for `pkgmanager edit` | `vim` |

---

## License

MIT
