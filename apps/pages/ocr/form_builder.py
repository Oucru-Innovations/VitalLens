"""Form builder cho trang OCR: dựng widgets theo loại hồ sơ (lab/monitor).

Tách khỏi page chính để giữ file view ngắn gọn và dễ sửa layout.
"""

from __future__ import annotations

import tkinter as tk
from typing import Dict, List

from apps.config import (
    ACCENT_BLUE,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_RED,
    BG_CARD,
    BG_INPUT,
    BORDER_COLOR,
    FG_DIM,
    FG_TEXT,
    FG_TITLE,
)

LAB_INFO_KEYS = [
    "patient_name",
    "patient_dob",
    "patient_id",
    "collection_date",
    "lab_name",
    "report_type",
]

EXCLUDED_EXTRA_KEYS = {
    *LAB_INFO_KEYS,
    "results",
    "raw_text",
    "provider",
    "model",
    "source",
    "notification",
    "error",
    "extraction_status",
}


class LabFormState:
    """Giữ tham chiếu các widget/var dựng ra trong form lab để page đọc lại."""

    def __init__(self) -> None:
        self.form_vars: Dict[str, tk.StringVar] = {}
        self.result_vars: List[Dict[str, tk.StringVar]] = []
        self.results_container: tk.Frame | None = None
        self.result_count_label: tk.Label | None = None


def build_monitor_form(form_inner: tk.Frame, data: dict) -> Dict[str, tk.StringVar]:
    """Dựng form đơn giản cho OCR BEDSIDE MONITOR."""

    form_vars: Dict[str, tk.StringVar] = {}
    for key, val_obj in data.items():
        row = tk.Frame(form_inner, bg=BG_CARD)
        row.pack(fill="x", padx=8, pady=3)

        tk.Label(
            row,
            text=key.upper(),
            font=("Helvetica", 11, "bold"),
            bg=BG_CARD,
            fg=FG_TEXT,
            width=12,
            anchor="e",
        ).pack(side="left", padx=(0, 8))

        if isinstance(val_obj, dict):
            value = str(val_obj.get("value", ""))
        elif isinstance(val_obj, list) and val_obj:
            value = str(val_obj[0].get("value", ""))
        else:
            value = str(val_obj) if val_obj else ""

        var = tk.StringVar(value=value)
        form_vars[key] = var
        tk.Entry(
            row,
            textvariable=var,
            font=("Helvetica", 12),
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            borderwidth=0,
            highlightthickness=1,
            highlightcolor=ACCENT_BLUE,
        ).pack(side="left", fill="x", expand=True, ipady=4)
    return form_vars


def _render_notifications(form_inner: tk.Frame, data: dict) -> bool:
    """Render banner error/warning/metadata. Trả True nếu form nên có trạng thái blank."""

    extraction_status = data.get("extraction_status")
    notification = data.get("notification")
    error_info = data.get("error")
    results = data.get("results", [])
    is_error = extraction_status == "failed"
    is_warning = notification is not None and not is_error
    is_blank = is_error or (not results)

    if is_error and notification:
        banner = tk.Frame(form_inner, bg="#fef2f2")
        banner.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(
            banner,
            text="✗  " + notification.get("type", "error").upper().replace("_", " "),
            font=("Helvetica", 12, "bold"),
            bg="#fef2f2",
            fg=ACCENT_RED,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(
            banner,
            text=notification.get("message", ""),
            font=("Helvetica", 11),
            bg="#fef2f2",
            fg="#7f1d1d",
            anchor="w",
            wraplength=500,
            justify="left",
        ).pack(fill="x", padx=10, pady=(2, 6))
        if error_info and error_info.get("details", {}).get("recommendation"):
            tk.Label(
                banner,
                text="💡 " + error_info["details"]["recommendation"],
                font=("Helvetica", 10, "italic"),
                bg="#fef2f2",
                fg="#92400e",
                anchor="w",
                wraplength=500,
                justify="left",
            ).pack(fill="x", padx=10, pady=(0, 6))
    elif is_warning and notification:
        warn_bg = (
            "#fffbeb" if notification.get("type") != "partial_extraction" else "#fff7ed"
        )
        banner = tk.Frame(form_inner, bg=warn_bg)
        banner.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(
            banner,
            text="⚠  " + notification.get("type", "warning").upper().replace("_", " "),
            font=("Helvetica", 12, "bold"),
            bg=warn_bg,
            fg=ACCENT_ORANGE,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(
            banner,
            text=notification.get("message", ""),
            font=("Helvetica", 11),
            bg=warn_bg,
            fg="#78350f",
            anchor="w",
            wraplength=500,
            justify="left",
        ).pack(fill="x", padx=10, pady=(2, 6))

    provider = data.get("provider")
    model = data.get("model")
    source = data.get("source")
    if provider or model:
        meta_frame = tk.Frame(form_inner, bg="#f0f9ff")
        meta_frame.pack(fill="x", padx=8, pady=(4, 4))
        parts = []
        if provider:
            parts.append(provider)
        if model and model not in (provider or ""):
            parts.append(f"model: {model}")
        if source:
            parts.append(f"({source})")
        tk.Label(
            meta_frame,
            text="ℹ  " + "  |  ".join(parts),
            font=("Helvetica", 10),
            bg="#f0f9ff",
            fg="#1e40af",
            anchor="w",
        ).pack(fill="x", padx=10, pady=4)

    if is_blank:
        hint_bg = "#f0fdf4" if is_error else "#fefce8"
        hint_fg = ACCENT_GREEN if is_error else "#854d0e"
        hint = tk.Frame(form_inner, bg=hint_bg)
        hint.pack(fill="x", padx=8, pady=(4, 8))
        tk.Label(
            hint,
            text="✎  Kết quả trích xuất bị lỗi / trống. Bạn có thể nhập thủ công bên dưới.",
            font=("Helvetica", 11),
            bg=hint_bg,
            fg=hint_fg,
            anchor="w",
            wraplength=500,
            justify="left",
        ).pack(fill="x", padx=10, pady=6)

    return is_blank


def _render_entry_row(
    form_inner: tk.Frame,
    label_text: str,
    var: tk.StringVar,
) -> None:
    row = tk.Frame(form_inner, bg=BG_CARD)
    row.pack(fill="x", padx=10, pady=3)
    tk.Label(
        row,
        text=label_text,
        font=("Helvetica", 12),
        bg=BG_CARD,
        fg=FG_DIM,
        width=16,
        anchor="e",
    ).pack(side="left", padx=(0, 8))
    tk.Entry(
        row,
        textvariable=var,
        font=("Helvetica", 12),
        bg=BG_INPUT,
        fg=FG_TEXT,
        insertbackground=FG_TEXT,
        borderwidth=0,
        highlightthickness=1,
        highlightcolor=ACCENT_BLUE,
    ).pack(side="left", fill="x", expand=True, ipady=5)


def build_lab_form(
    form_inner: tk.Frame,
    data: dict,
    on_add_row,
    on_remove_row,
) -> LabFormState:
    state = LabFormState()

    is_blank = _render_notifications(form_inner, data)

    tk.Label(
        form_inner,
        text="Thông tin bệnh nhân",
        font=("Helvetica", 13, "bold"),
        bg=BG_CARD,
        fg=FG_TITLE,
    ).pack(anchor="w", padx=10, pady=(8, 5))

    for key in LAB_INFO_KEYS:
        var = tk.StringVar(value=str(data.get(key) or ""))
        state.form_vars[key] = var
        _render_entry_row(form_inner, key.replace("_", " ").title(), var)

    extra_keys = [
        key
        for key in data.keys()
        if key not in EXCLUDED_EXTRA_KEYS
        and not isinstance(data.get(key), (dict, list))
    ]
    if extra_keys:
        tk.Label(
            form_inner,
            text="Thông tin theo loại",
            font=("Helvetica", 13, "bold"),
            bg=BG_CARD,
            fg=FG_TITLE,
        ).pack(anchor="w", padx=10, pady=(10, 5))
        for key in extra_keys:
            var = tk.StringVar(value=str(data.get(key) or ""))
            state.form_vars[key] = var
            _render_entry_row(form_inner, key.replace("_", " ").title(), var)

    tk.Frame(form_inner, bg=BORDER_COLOR, height=1).pack(fill="x", padx=10, pady=10)

    results = data.get("results", [])

    result_hdr = tk.Frame(form_inner, bg=BG_CARD)
    result_hdr.pack(fill="x", padx=10, pady=(5, 5))

    state.result_count_label = tk.Label(
        result_hdr,
        text=f"Kết quả ({len(results)} mục)",
        font=("Helvetica", 13, "bold"),
        bg=BG_CARD,
        fg=FG_TITLE,
    )
    state.result_count_label.pack(side="left")

    rm_btn = tk.Label(
        result_hdr,
        text="  − Xóa dòng  ",
        font=("Helvetica", 10, "bold"),
        bg=ACCENT_RED,
        fg="#ffffff",
        cursor="hand2",
        padx=4,
        pady=2,
    )
    rm_btn.pack(side="right", padx=(4, 0))
    rm_btn.bind("<Button-1>", lambda e: on_remove_row())
    rm_btn.bind("<Enter>", lambda e: rm_btn.config(bg="#b91c1c"))
    rm_btn.bind("<Leave>", lambda e: rm_btn.config(bg=ACCENT_RED))

    add_btn = tk.Label(
        result_hdr,
        text="  + Thêm dòng  ",
        font=("Helvetica", 10, "bold"),
        bg=ACCENT_GREEN,
        fg="#ffffff",
        cursor="hand2",
        padx=4,
        pady=2,
    )
    add_btn.pack(side="right", padx=(4, 0))
    add_btn.bind("<Button-1>", lambda e: on_add_row())
    add_btn.bind("<Enter>", lambda e: add_btn.config(bg="#15803d"))
    add_btn.bind("<Leave>", lambda e: add_btn.config(bg=ACCENT_GREEN))

    hdr = tk.Frame(form_inner, bg=BG_CARD)
    hdr.pack(fill="x", padx=10, pady=(0, 3))
    for col_text, col_w in [
        ("Tên xét nghiệm", 0),
        ("Giá trị", 10),
        ("Đơn vị", 8),
        ("Ref", 6),
        ("Flag", 5),
    ]:
        if col_w == 0:
            tk.Label(
                hdr,
                text=col_text,
                font=("Helvetica", 10, "bold"),
                bg=BG_CARD,
                fg=FG_DIM,
            ).pack(side="left", fill="x", expand=True, anchor="w")
        else:
            tk.Label(
                hdr,
                text=col_text,
                font=("Helvetica", 10, "bold"),
                bg=BG_CARD,
                fg=FG_DIM,
                width=col_w,
            ).pack(side="left", padx=2)

    state.results_container = tk.Frame(form_inner, bg=BG_CARD)
    state.results_container.pack(fill="x", padx=10)

    return state


def add_result_row(state: LabFormState, result: dict | None = None) -> None:
    assert state.results_container is not None
    i = len(state.result_vars)
    bg = BG_INPUT if i % 2 == 0 else "#e8e8e8"
    rf = tk.Frame(state.results_container, bg=bg)
    rf.pack(fill="x", pady=1)
    row_vars: Dict[str, tk.StringVar] = {"_frame": rf}  # type: ignore[dict-item]

    var_name = tk.StringVar(value=str((result or {}).get("test_name") or ""))
    row_vars["test_name"] = var_name
    tk.Entry(
        rf,
        textvariable=var_name,
        font=("Helvetica", 11),
        bg=bg,
        fg=FG_TEXT,
        borderwidth=0,
        highlightthickness=0,
        readonlybackground=bg,
    ).pack(side="left", fill="x", expand=True, ipady=4, padx=(4, 2))

    for col_key, col_w in [("value", 10), ("unit", 8), ("reference_range", 6), ("flag", 5)]:
        var = tk.StringVar(value=str((result or {}).get(col_key) or ""))
        row_vars[col_key] = var
        tk.Entry(
            rf,
            textvariable=var,
            font=("Helvetica", 11),
            width=col_w,
            bg="#ffffff",
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            borderwidth=1,
            relief="solid",
            highlightthickness=0,
        ).pack(side="left", ipady=4, padx=2)

    state.result_vars.append(row_vars)
    _update_result_count(state)


def remove_result_row(state: LabFormState) -> None:
    if not state.result_vars:
        return
    row = state.result_vars.pop()
    frame = row.get("_frame")
    if frame is not None:
        frame.destroy()  # type: ignore[union-attr]
    _update_result_count(state)


def _update_result_count(state: LabFormState) -> None:
    if state.result_count_label is not None:
        state.result_count_label.config(
            text=f"Kết quả ({len(state.result_vars)} mục)"
        )


__all__ = [
    "LabFormState",
    "build_monitor_form",
    "build_lab_form",
    "add_result_row",
    "remove_result_row",
]
