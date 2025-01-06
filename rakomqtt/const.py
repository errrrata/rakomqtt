"""Constants used by rakomqtt components."""
from typing import Final, Tuple

MAJOR_VERSION: Final[int] = 0
MINOR_VERSION: Final[int] = 2
PATCH_VERSION: Final[str] = "0"
__short_version__: Final[str] = f"{MAJOR_VERSION}.{MINOR_VERSION}"
__version__: Final[str] = f"{__short_version__}.{PATCH_VERSION}"
REQUIRED_PYTHON_VER: Final[Tuple[int, int, int]] = (3, 12, 0)
