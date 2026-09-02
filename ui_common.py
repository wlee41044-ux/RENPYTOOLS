import tkinter as tk
from tkinter import ttk

BG = "#F7F9FD"
CARD = "#FFFFFF"
TEXT = "#10213F"
MUTED = "#6B778C"
BORDER = "#DCE5F2"
BLUE = "#2F7AF8"
GREEN = "#34B45A"
GREEN_DARK = "#249548"
RED = "#D84A4A"


def setup_styles(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
    style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=("Segoe UI", 10))
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 20))
    style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
    style.configure("Section.TLabel", background=CARD, foreground=TEXT, font=("Segoe UI Semibold", 12))
    style.configure("Muted.Card.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 9))
    style.configure("Step.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
    style.configure("StepActive.TLabel", background=BG, foreground=BLUE, font=("Segoe UI Semibold", 9))
    style.configure("Primary.TButton", font=("Segoe UI Semibold", 11), padding=(16, 11))
    style.configure("Secondary.TButton", font=("Segoe UI Semibold", 10), padding=(14, 10))
    style.configure("Flat.TButton", font=("Segoe UI", 10), padding=(10, 8))
    style.configure("TCheckbutton", background=CARD, foreground=TEXT, font=("Segoe UI", 10))
    style.configure("TRadiobutton", background=CARD, foreground=TEXT, font=("Segoe UI", 10))
    style.configure("TCombobox", padding=7)
    style.configure("TEntry", padding=8)
    style.configure("Horizontal.TProgressbar", troughcolor="#EAF0FB", background=BLUE, thickness=12)


def card(parent, padding=18):
    outer = tk.Frame(parent, bg=BORDER)
    inner = ttk.Frame(outer, style="Card.TFrame", padding=padding)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    return outer, inner


def stepper(parent, active, labels):
    wrap = ttk.Frame(parent)
    wrap.pack(fill="x", pady=(0, 18))
    for i, label in enumerate(labels, 1):
        cell = ttk.Frame(wrap)
        cell.grid(row=0, column=i - 1, sticky="ew")
        wrap.columnconfigure(i - 1, weight=1)
        bubble = tk.Label(
            cell,
            text=("✓" if i < active else str(i)),
            width=2,
            height=1,
            bg=(BLUE if i <= active else "#EEF3FA"),
            fg=("white" if i <= active else MUTED),
            font=("Segoe UI Semibold", 10),
        )
        bubble.pack()
        ttk.Label(
            cell,
            text=label,
            style=("StepActive.TLabel" if i == active else "Step.TLabel"),
        ).pack(pady=(4, 0))