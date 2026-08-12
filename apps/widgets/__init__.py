"""Custom widgets dùng chung cho các trang.

Re-export các ký hiệu công khai để giữ tương thích với imports cũ:

    from apps.widgets import StyledButton, StatusBar, make_header, make_section, DatePicker
    from apps.widgets import ScrollableFrame, show_info, show_warning, show_error
    from apps.widgets import ensure_sftp_backend, get_sftp_uploader, run_upload_batch
"""

from .buttons import StyledButton
from .status import StatusBar
from .header import make_header, make_section
from .date_picker import DatePicker
from .scrollable import ScrollableFrame, make_scrollable_listbox
from .dialogs import show_message, show_report, show_info, show_warning, show_error
from .sftp import ensure_sftp_backend, get_sftp_uploader
from .upload_batch import run_upload_batch

__all__ = [
    "StyledButton",
    "StatusBar",
    "make_header",
    "make_section",
    "DatePicker",
    "ScrollableFrame",
    "make_scrollable_listbox",
    "show_message",
    "show_report",
    "show_info",
    "show_warning",
    "show_error",
    "ensure_sftp_backend",
    "get_sftp_uploader",
    "run_upload_batch",
]
