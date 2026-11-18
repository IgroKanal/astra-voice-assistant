"""Astra Glass — minimal autonomous-interface theme for Qt."""
BG = "#030509"
SURFACE = "#080D16"
SURFACE_RAISED = "#0B1220"
FIELD = "#050A12"
BORDER = "#182538"
TEXT = "#F4F8FF"
MUTED = "#8794AA"
ACCENT = "#4FE8D6"
ACCENT_HOT = "#B7FFF6"
CYAN = "#4FE8D6"
DANGER = "#FF7189"

STYLE = f"""
* {{
    font-family: 'Segoe UI';
    font-size: 14px;
    color: {TEXT};
}}
QWidget {{ background: transparent; }}
QMainWindow, QDialog, QWidget#root {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #020408, stop:0.55 #050A12, stop:1 #07101A);
}}
QScrollArea, QScrollArea > QWidget#qt_scrollarea_viewport, QWidget#page {{
    background: transparent;
    border: none;
}}
QFrame#nav {{
    background: rgba(3, 6, 11, 170);
    border-bottom: 1px solid rgba(24, 37, 56, 110);
}}
QFrame#card, QFrame#voiceCard {{
    background: rgba(8, 13, 22, 190);
    border: 1px solid rgba(24, 37, 56, 150);
    border-radius: 22px;
}}
QFrame#voiceCard {{ border-color: rgba(79, 232, 214, 45); }}
QLabel#brand {{
    font-size: 25px;
    font-weight: 760;
    letter-spacing: 0.4px;
}}
QLabel#eyebrow {{
    color: {ACCENT};
    font-size: 10px;
    font-weight: 760;
    letter-spacing: 2.4px;
}}
QLabel#title {{
    font-size: 32px;
    font-weight: 740;
    letter-spacing: -0.3px;
}}
QLabel#subtitle, QLabel#muted {{ color: {MUTED}; }}
QLabel#section {{ font-size: 18px; font-weight: 660; }}
QLabel#status {{
    color: {ACCENT};
    font-size: 13px;
    font-weight: 680;
}}
QPushButton {{
    background: rgba(11, 18, 32, 190);
    border: 1px solid rgba(24, 37, 56, 140);
    border-radius: 13px;
    padding: 10px 15px;
    text-align: left;
}}
QPushButton:hover {{
    background: rgba(16, 27, 45, 220);
    border-color: rgba(79, 232, 214, 95);
}}
QPushButton:pressed {{ background: #08101C; }}
QPushButton:focus {{ border: 1px solid {ACCENT}; }}
QPushButton:disabled {{ color: #59677A; background: #080D16; }}
QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #35D9C8, stop:1 #A8FFF3);
    color: #02100E;
    border: none;
    border-radius: 15px;
    font-weight: 820;
    text-align: center;
    padding: 13px 22px;
}}
QPushButton#primary:hover {{ background: #C7FFF8; }}
QPushButton#voice {{
    background: rgba(8, 17, 21, 220);
    border: 1px solid rgba(79, 232, 214, 90);
    border-radius: 17px;
    font-size: 14px;
    font-weight: 720;
    text-align: center;
    padding: 13px 18px;
}}
QPushButton#voice[active="true"] {{
    background: rgba(15, 58, 55, 225);
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton#navButton {{
    background: transparent;
    border: none;
    border-radius: 11px;
    color: {MUTED};
    padding: 9px 13px;
    font-weight: 640;
}}
QPushButton#navButton:hover {{
    color: {TEXT};
    background: rgba(15, 25, 40, 110);
}}
QPushButton#navButton:checked {{
    color: {TEXT};
    background: rgba(79, 232, 214, 34);
    border-bottom: 2px solid {ACCENT};
    border-radius: 11px 11px 4px 4px;
}}
QLineEdit, QTextEdit, QPlainTextEdit, QTextBrowser, QListWidget, QTableWidget, QComboBox, QDateTimeEdit {{
    background: rgba(5, 10, 18, 230);
    border: 1px solid rgba(24, 37, 56, 160);
    border-radius: 14px;
    padding: 11px;
    selection-background-color: #184D48;
    selection-color: white;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QTextBrowser:focus,
QListWidget:focus, QTableWidget:focus, QComboBox:focus, QDateTimeEdit:focus {{
    border: 1px solid {ACCENT};
}}
QTableWidget {{ gridline-color: rgba(24, 37, 56, 140); }}
QHeaderView::section {{
    background: rgba(11, 18, 32, 210);
    color: {MUTED};
    border: none;
    border-bottom: 1px solid #182538;
    padding: 10px;
}}
QMenu {{
    background: rgba(8, 14, 24, 245);
    border: 1px solid #20304A;
    border-radius: 14px;
    padding: 7px;
}}
QMenu::item {{ padding: 10px 26px; border-radius: 8px; }}
QMenu::item:selected {{ background: #123B38; }}
QComboBox::drop-down {{ border: none; width: 32px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {MUTED};
    margin-right: 11px;
}}
QComboBox QAbstractItemView {{
    background: #0B1220;
    border: 1px solid #20304A;
    selection-background-color: #123B38;
    padding: 6px;
}}
QTextBrowser {{ padding: 18px; }}
QScrollBar:vertical {{
    background: transparent;
    width: 7px;
    margin: 5px;
}}
QScrollBar::handle:vertical {{
    background: #26364C;
    border-radius: 4px;
    min-height: 34px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 7px;
    margin: 5px;
}}
QScrollBar::handle:horizontal {{
    background: #26364C;
    border-radius: 4px;
    min-width: 34px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QCheckBox {{ spacing: 10px; padding: 7px; }}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid #42536A;
    border-radius: 6px;
    background: {FIELD};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QSlider::groove:horizontal {{
    height: 5px;
    background: #1B283A;
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    width: 18px;
    margin: -7px 0;
    border-radius: 9px;
    background: {ACCENT};
}}
QProgressBar {{
    background: {FIELD};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 4px;
}}
QToolTip {{
    background: #0B1220;
    color: {TEXT};
    border: 1px solid #20304A;
    border-radius: 10px;
    padding: 7px;
}}
"""
