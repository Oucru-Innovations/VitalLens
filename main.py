"""VitalLens - Entry point.

Environment setup is centralized in `apps/logging_setup.py` to keep this
file minimal. Call `setup_logging()` and `patch_paddlex_when_frozen()`
BEFORE importing any Paddle modules.
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
