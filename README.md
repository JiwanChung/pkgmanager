<div align="center">

# onepkg

**One manifest to rule them all.**

A unified CLI that manages packages across Homebrew, Cargo, uv, Go, Bun, and more — all from a single YAML file.

[![CI](https://github.com/JiwanChung/pkgmanager/actions/workflows/ci.yml/badge.svg)](https://github.com/JiwanChung/pkgmanager/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

</div>

---

## Why onepkg?

Setting up a new machine means running `brew install`, `cargo install`, `go install`, `uv tool install`, and more — each with their own syntax and state. **onepkg** consolidates everything into one manifest:

```yaml
general:
  brew:
    - ripgrep
    - fzf
  python:
    - ruff
    - pyright
  rust:
    - bat
    - eza
  go:
    - github.com/jesseduffield/lazygit
```

Then sync everywhere with one command:

```bash
onepkg sync
```

---

## Features

- **Single manifest** — Track all packages in `~/.config/packages.yaml`
- **10 package managers** — brew, cask, mas, conda, python, rust, go, bun, winget, custom
- **Cross-platform** — macOS, Linux, and WSL support with platform-specific sections
- **Smart syncing** — Only installs what's missing, skips what's already there
- **Lock file support** — Pin exact versions for reproducible deployments
- **Diff & export** — Compare manifest vs system, export installed packages
- **Diagnostics** — Built-in doctor, outdated, and clean commands
- **Fallback syntax** — Define preferred managers with automatic fallbacks (`tmux:brew`)
- **Custom packages** — Shell script-based installs for anything else
- **Shell completions** — Tab completion for bash, zsh, and fish
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
| `go` | go install | All | Go binaries |
| `bun` | bun | All | JavaScript/TypeScript tools |
| `winget` | winget.exe | WSL | Windows packages from WSL |
| `custom` | shell scripts | All | Custom installation scripts |

---

## Installation

```bash
# Using uv (recommended)
uv tool install onepkg

# Or from source
git clone https://github.com/JiwanChung/pkgmanager
cd onepkg
uv tool install .
```

### Shell Completions

```bash
# Bash
onepkg completions bash >> ~/.bashrc

# Zsh
onepkg completions zsh >> ~/.zshrc

# Fish
onepkg completions fish > ~/.config/fish/completions/onepkg.fish
```

---

## Quick Start

### 1. Create a manifest

```bash
mkdir -p ~/.config
cat > ~/.config/packages.yaml << 'EOF'
general:
  python:
    - ruff
    - black
  rust:
    - bat
    - eza
  go:
    - github.com/jesseduffield/lazygit
EOF
```

### 2. Sync packages

```bash
onepkg sync
```

### 3. Add more packages

```bash
onepkg install brew ripgrep
onepkg install python poetry
onepkg install go github.com/charmbracelet/glow
```

---

## Commands

### Core Commands

| Command | Description |
|:--------|:------------|
| `sync` / `init` | Install all packages from manifest |
| `install <type> <name>` | Install a package and add to manifest |
| `remove <name>` | Remove a package and update manifest |
| `update [name]` | Update packages (all or specific) |
| `list` | List tracked packages by category |
| `lock` | Create lock file with exact versions |

### Inspection Commands

| Command | Description |
|:--------|:------------|
| `diff` | Show differences between manifest and system |
| `status` | Show package manager availability |
| `show <name>` | Display detailed package info |
| `search <query>` | Search for packages across managers |
| `outdated` | Show packages with available updates |

### Maintenance Commands

| Command | Description |
|:--------|:------------|
| `doctor` | Diagnose issues with setup |
| `clean` | Remove untracked packages |
| `export` | Export installed packages to YAML |
| `bootstrap` | Install package managers themselves |
| `edit` | Open manifest in editor |
| `completions` | Generate shell completions |

---

## Usage Examples

### Sync from manifest

```bash
onepkg sync                    # Install all packages
onepkg sync --types brew,rust  # Install specific types only
onepkg sync --dry-run          # Preview what would be installed
onepkg sync --quiet            # Suppress non-essential output
onepkg sync --locked           # Install exact versions from lock file
```

### Lock versions

```bash
onepkg lock                    # Create packages.lock.yaml
onepkg lock --types python     # Lock only specific types
onepkg lock -o deploy.lock.yaml  # Custom output file

# Then install with locked versions on another machine:
onepkg sync --locked
```

### Install packages

```bash
onepkg install brew ripgrep              # Homebrew formula
onepkg install cask raycast              # Homebrew cask (GUI app)
onepkg install mas 937984704             # Mac App Store (by ID)
onepkg install python ruff               # Python tool via uv
onepkg install rust miniserve            # Rust binary via cargo
onepkg install go github.com/junegunn/fzf  # Go binary
onepkg install bun typescript            # Bun global package
onepkg install custom fisher             # Custom script package
```

### Check differences

```bash
onepkg diff                    # Show manifest vs installed
# Output:
# brew
#   + ripgrep (not installed)
#   - unused-tool (untracked)
```

### Export current setup

```bash
onepkg export > packages.yaml  # Export all to YAML
onepkg export --types brew     # Export only brew packages
onepkg export --format list    # Simple list format
```

### Diagnose issues

```bash
onepkg doctor
# Output:
# ✓ Manifest file exists
# ✓ brew: brew is available
# ✓ python: uv is available
# ! rust: 2 packages not installed
# ✗ go: go not found but manifest has 3 packages
```

### Clean up untracked packages

```bash
onepkg clean --dry-run         # Preview what would be removed
onepkg clean --types python    # Clean only python packages
```

### Check for updates

```bash
onepkg outdated                # Show all outdated packages
onepkg outdated --types brew   # Check only brew
```

---

## Manifest Format

The manifest lives at `~/.config/packages.yaml` (override with `$PACKAGE_CONFIG`):

```yaml
# macOS-specific packages
mac:
  brew:
    - ripgrep
    - fzf
    - jq
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
    - bat
    - eza
    - miniserve
  go:
    - github.com/jesseduffield/lazygit
    - github.com/charmbracelet/glow
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

Define custom packages in a `specs.yaml` bundled with onepkg:

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

## Command-Line Flags

### Global flags

| Flag | Description |
|:-----|:------------|
| `--env, -e` | Path to manifest file |
| `--dry-run, -n` | Preview without executing |
| `--help, -h` | Show help |

### Install/Sync flags

| Flag | Description |
|:-----|:------------|
| `--types, -t` | Filter by package types |
| `--quiet, -q` | Suppress non-essential output |
| `--force, -f` | Force reinstall |
| `--continue-on-error, -c` | Continue if a package fails |
| `--locked` | Install exact versions from lock file |
| `--lock-file` | Path to lock file (default: packages.lock.yaml) |

---

## Environment Variables

| Variable | Description | Default |
|:---------|:------------|:--------|
| `PACKAGE_CONFIG` | Path to manifest file | `~/.config/packages.yaml` |
| `EDITOR` | Editor for `onepkg edit` | `vim` |

---

## Development

```bash
# Clone and install with dev dependencies
git clone https://github.com/JiwanChung/pkgmanager
cd onepkg
uv pip install -e ".[dev]"

# Run tests
uv run pytest tests/ -v

# Check types
uv run mypy onepkg/
```

---

## Project Structure

```
onepkg/
├── cli.py        # CLI commands (1,279 lines)
├── managers.py   # Package manager implementations (1,129 lines)
├── manifest.py   # Manifest handling (344 lines)
├── models.py     # Data classes (57 lines)
├── utils.py      # Utilities (100 lines)
└── specs.yaml    # Custom package specs
```

---

## License

MIT
