"""Custom widgets dùng chung cho các trang.

Re-export các ký hiệu công khai để giữ tương thích với imports cũ:

    from apps.widgets import StyledButton, StatusBar, make_header, make_section, DatePicker
    from apps.widgets import ScrollableFrame, show_info, show_warning, show_error
"""

from .buttons import StyledButton
from .status import StatusBar
from .header import make_header, make_section
from .date_picker import DatePicker
from .scrollable import ScrollableFrame
from .dialogs import show_message, show_report, show_info, show_warning, show_error

__all__ = [
    "StyledButton",
    "StatusBar",
    "make_header",
    "make_section",
    "DatePicker",
    "ScrollableFrame",
    "show_message",
    "show_report",
    "show_info",
    "show_warning",
    "show_error",
]
