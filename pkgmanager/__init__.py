from pkgmanager.cli import __version__
from pkgmanager.managers import CUSTOM_MANAGER, MANAGERS
from pkgmanager.models import CommandResult, PackageDetails, PackageInfo

__all__ = [
    "__version__",
    "CUSTOM_MANAGER",
    "CommandResult",
    "MANAGERS",
    "PackageDetails",
    "PackageInfo",
]
