"""nat20-bridge — localhost HTTP host for the dnd5e-engine (SillyTavern sidecar)."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# The installed distribution is the one source of the version, so the value
# ``/v1/health`` reports can never drift from the released package again.
try:  # pragma: no cover - trivial packaging fallback
    __version__ = _pkg_version("nat20-bridge")
except PackageNotFoundError:  # pragma: no cover - source tree without install
    __version__ = "0.0.0+unknown"
