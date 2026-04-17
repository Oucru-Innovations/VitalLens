"""VitalLens - Entry point.

Logic setup environment được gom vào `apps/logging_setup.py` để file entry
gọn và dễ nhìn. Gọi `setup_logging()` và `patch_paddlex_when_frozen()`
TRƯỚC khi import bất kỳ module Paddle nào khác.
"""

from apps.logging_setup import patch_paddlex_when_frozen, setup_logging

setup_logging()
patch_paddlex_when_frozen()

from apps.app import App  # noqa: E402 - must happen after setup_logging()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
