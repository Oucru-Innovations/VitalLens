"""Custom widgets dùng chung cho các trang.

Re-export các ký hiệu công khai để giữ tương thích với imports cũ:

    from apps.widgets import StyledButton, StatusBar, make_header, make_section, DatePicker
    from apps.widgets import ScrollableFrame, show_info, show_warning, show_error
    from apps.widgets import ensure_sftp_backend, get_sftp_uploader, run_upload_batch
"""

from .buttons import StyledButton
from .status import StatusBar
from .header import make_header, make_section
from .date_picker import DatePicker, clipboard_date
from .scrollable import ScrollableFrame, make_scrollable_listbox
from .dialogs import (
    ask_owner, ask_yes_no,
    show_message, show_report, show_info, show_warning, show_error,
)
from .sftp import ensure_sftp_backend, get_sftp_uploader
from .upload_batch import run_upload_batch
from .settings_dialog import show_settings_dialog

__all__ = [
    "StyledButton",
    "StatusBar",
    "make_header",
    "make_section",
    "DatePicker",
    "clipboard_date",
    "ScrollableFrame",
    "make_scrollable_listbox",
    "ask_owner",
    "ask_yes_no",
    "show_message",
    "show_report",
    "show_info",
    "show_warning",
    "show_error",
    "ensure_sftp_backend",
    "get_sftp_uploader",
    "run_upload_batch",
    "show_settings_dialog",
]
