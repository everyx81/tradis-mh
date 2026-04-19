# JARVIS GUI 스타일시트 상수
"""
JARVIS HUD 스타일 Qt 스타일시트 모음
"""

# --- GLOBAL STYLESHEET ---
GLOBAL_STYLESHEET = """
/* 툴팁 — 카드 아이콘 버튼 설명 표시 */
QToolTip {
    background-color: rgba(30, 50, 75, 240);
    color: #e8f0fa;
    border: 1px solid rgba(100, 200, 255, 120);
    border-radius: 6px;
    padding: 6px 10px;
    font-family: 'Malgun Gothic';
    font-size: 10pt;
    font-weight: 500;
}
QMainWindow {
    background-color: transparent;
}
/* #OuterContainer는 gui_jarvis.py init_ui에서 Claude warm dark로 오버라이드됨 */
#OuterContainer {
    background-color: rgba(13, 15, 21, 255);
    border: none;
    border-radius: 14px;
}
QLabel {
    color: #c1c4c9;
    font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
    font-size: 10pt;
}
/* Claude Design warm dark (oklch 정확 변환) - 입력/콤보/텍스트 위젯 */
QLineEdit {
    background-color: rgba(27, 30, 36, 255);
    border: 1px solid rgba(45, 48, 56, 150);
    border-radius: 8px;
    color: #f3f5f9;
    padding: 7px 10px;
    font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
    font-size: 10pt;
    selection-background-color: rgba(75, 163, 247, 80);
}
QLineEdit:focus {
    border: 1px solid rgba(75, 163, 247, 150);
    background-color: rgba(35, 38, 45, 255);
}
QComboBox {
    background-color: rgba(27, 30, 36, 255);
    border: 1px solid rgba(45, 48, 56, 150);
    border-radius: 8px;
    color: #f3f5f9;
    padding: 6px 12px;
}
QComboBox:hover {
    border: 1px solid rgba(75, 163, 247, 150);
}
QComboBox::drop-down {
    border: none;
    background: transparent;
}
QComboBox QAbstractItemView {
    background-color: rgba(35, 38, 45, 250);
    color: #f3f5f9;
    selection-background-color: rgba(75, 163, 247, 60);
    selection-color: #ffffff;
    border: 1px solid rgba(63, 66, 75, 180);
    border-radius: 6px;
    padding: 4px;
}
QTextEdit {
    background-color: rgba(27, 30, 36, 255);
    border: 1px solid rgba(45, 48, 56, 150);
    border-radius: 10px;
    color: #c1c4c9;
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 10pt;
    padding: 10px;
}
QTabWidget::pane {
    border: none;
    background-color: transparent;
    border-radius: 0px;
    margin-top: 0px;
}
QTabBar::tab {
    background-color: transparent;
    color: #8f9298;
    padding: 8px 12px;
    border: 1px solid transparent;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 3px;
}
QTabBar::tab:selected {
    background-color: rgba(35, 38, 45, 180);
    color: #f3f5f9;
    border-color: rgba(63, 66, 75, 180);
}
QTabBar::tab:hover:!selected {
    background-color: rgba(27, 30, 36, 150);
    color: #c1c4c9;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
/* 수직 스크롤바 - 평소 투명, 호버 시 표시 */
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: rgba(0, 136, 136, 0);  /* 평소 투명 */
    min-height: 30px;
    border-radius: 4px;
}
QScrollBar:vertical:hover {
    background: rgba(0, 20, 40, 100);
}
QScrollBar::handle:vertical:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #006666, stop:0.5 #00aaaa, stop:1 #006666);
}
QScrollBar::handle:vertical:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #008888, stop:0.5 #00ffff, stop:1 #008888);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
/* 수평 스크롤바 - 평소 투명, 호버 시 표시 */
QScrollBar:horizontal {
    border: none;
    background: transparent;
    height: 8px;
    margin: 0px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: rgba(0, 136, 136, 0);  /* 평소 투명 */
    min-width: 30px;
    border-radius: 4px;
}
QScrollBar:horizontal:hover {
    background: rgba(0, 20, 40, 100);
}
QScrollBar::handle:horizontal:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #006666, stop:0.5 #00aaaa, stop:1 #006666);
}
QScrollBar::handle:horizontal:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #008888, stop:0.5 #00ffff, stop:1 #008888);
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}
/* JARVIS 홀로그램 스타일 알림창 */
QMessageBox, QDialog {
    background-color: rgba(5, 15, 25, 120);
    border: 2px solid rgba(0, 255, 255, 220);
    border-radius: 8px;
}
QMessageBox QLabel, QDialog QLabel {
    color: #ffffff;
    font-size: 11pt;
    padding: 10px;
    background: transparent;
}
QMessageBox QLabel#qt_msgbox_label {
    color: #ffffff;
    font-size: 13pt;
    font-weight: bold;
}
QMessageBox QLabel#qt_msgboxex_icon_label {
    background: transparent;
}
QMessageBox QPushButton, QDialog QPushButton {
    background-color: rgba(0, 40, 60, 150);
    border: 2px solid rgba(0, 255, 255, 180);
    border-radius: 6px;
    color: #ffffff;
    padding: 10px 25px;
    min-width: 90px;
    font-weight: bold;
    font-size: 10pt;
}
QMessageBox QPushButton:hover, QDialog QPushButton:hover {
    background-color: rgba(0, 255, 255, 80);
    border: 2px solid #00ffff;
    color: #ffffff;
}
QMessageBox QPushButton:pressed, QDialog QPushButton:pressed {
    background-color: rgba(0, 255, 255, 140);
    border: 3px solid #00ffff;
}
QMessageBox QPushButton:focus, QDialog QPushButton:focus {
    outline: none;
    border: 2px solid #00aaff;
}
/* QFileDialog 내의 툴바 버튼(뒤로가기, 앞으로가기, 상위폴더 등) 스타일 개선 */
QFileDialog QToolButton {
    background-color: #1a2332;
    border: 1px solid #00ffff;
    border-radius: 4px;
    margin: 2px;
    padding: 2px;
}
QFileDialog QToolButton:hover {
    background-color: #005555;
}
QFileDialog QToolButton:pressed {
    background-color: #00aaaa;
}
/* 파일 리스트 및 트리 뷰 배경색 명시 */
QFileDialog QTreeView, QFileDialog QListView {
    background-color: #0d1117;
    color: #ffffff;
    border: 1px solid #335566;
}
QFileDialog QHeaderView::section {
    background-color: #1a2332;
    color: #00ffff;
    border: 1px solid #335566;
}
"""

# 컨텍스트 메뉴 공통 스타일시트
MENU_STYLESHEET = """
    QMenu {
        background-color: #0d1117;
        border: 2px solid #00ffff;
        border-radius: 8px;
        color: #ffffff;
        padding: 5px;
    }
    QMenu::item {
        padding: 8px 20px;
        border-radius: 4px;
    }
    QMenu::item:selected {
        background-color: rgba(0, 255, 255, 40);
        color: #00ffff;
    }
    QMenu::item:disabled {
        color: #666666;
    }
    QMenu::separator {
        height: 1px;
        background-color: #335566;
        margin: 5px 10px;
    }
"""

# DropListWidget 기본 스타일시트
DROP_LIST_STYLESHEET = """
    QListWidget {
        background: rgba(10, 20, 32, 100);
        border: 1px solid rgba(100, 160, 200, 35);
        border-radius: 12px;
        color: #c0d0e0;
        font-size: 10pt;
        padding: 6px;
        outline: none;
    }
    QListWidget::item {
        padding: 8px 10px;
        border-radius: 6px;
        margin: 1px 0;
    }
    QListWidget::item:selected {
        background: rgba(100, 200, 240, 60);
        color: #ffffff;
    }
    QListWidget::item:hover {
        background: rgba(100, 180, 240, 25);
    }
"""

# DropListWidget 하이라이트(드래그 오버) 스타일시트
DROP_LIST_HIGHLIGHT_STYLESHEET = """
    QListWidget {
        background-color: rgba(0, 255, 255, 30);
        border: 3px solid #00ffff;
        border-radius: 15px;
        color: #ffffff;
        font-size: 10pt;
        padding: 5px;
    }
    QListWidget::item {
        padding: 8px;
        border-bottom: 1px solid rgba(0, 255, 255, 10);
    }
    QListWidget::item:selected {
        background-color: rgba(0, 255, 255, 40);
        color: #00ffff;
        border: 1px solid #00ffff;
        border-radius: 5px;
    }
"""

# DraggableSearchResultList 스타일시트
SEARCH_RESULT_STYLESHEET = """
    QListWidget {
        background-color: rgba(2, 11, 20, 30);
        border: 2px solid #335566;
        border-radius: 10px;
        color: #ffffff;
        font-size: 9pt;
        padding: 5px;
        outline: none;
    }
    QListWidget:focus {
        border: 2px solid #335566;
        outline: none;
    }
    QListWidget::item {
        padding: 4px;
        border-radius: 3px;
        outline: none;
    }
    QListWidget::item:selected {
        background-color: rgba(0, 255, 255, 40);
        color: #00ffff;
    }
    QListWidget::item:hover {
        background-color: rgba(255, 255, 255, 20);
    }
    QListWidget::item:focus {
        outline: none;
        border: none;
    }
"""

# DraggableTreeView 스타일시트
TREE_VIEW_STYLESHEET = """
    QTreeView {
        background-color: rgba(2, 11, 20, 30);
        border: 2px solid #335566;
        border-radius: 10px;
        color: #ffffff;
        font-size: 10pt;
        padding: 5px;
        outline: none;
    }
    QTreeView:focus {
        border: 2px solid #335566;
        outline: none;
    }
    QTreeView::item {
        padding: 4px;
        border-radius: 3px;
        outline: none;
    }
    QTreeView::item:selected {
        background-color: rgba(0, 255, 255, 40);
        color: #00ffff;
    }
    QTreeView::item:hover {
        background-color: rgba(255, 255, 255, 20);
    }
    QTreeView::item:focus {
        outline: none;
        border: none;
    }
    QTreeView::branch {
        background-color: transparent;
    }
    QTreeView QLineEdit {
        background-color: #1a2332;
        border: 2px solid #00ffff;
        border-radius: 3px;
        color: #ffffff;
        padding: 2px 5px;
        selection-background-color: #00ffff;
        selection-color: #000000;
}
"""

# FileManagerWidget list_target 스타일시트 (Claude Design warm dark)
TARGET_LIST_STYLESHEET = """
    QListWidget {
        background: transparent;
        border: none;
        color: #c1c4c9;
        font-family: 'JetBrains Mono', 'Consolas', monospace;
        font-size: 9pt;
        padding: 2px;
        outline: none;
    }
    QListWidget::item {
        padding: 7px 10px;
        border-radius: 8px;
        margin: 1px 0;
        border: 1px solid transparent;
    }
    QListWidget::item:hover {
        background: rgba(45, 48, 56, 130);
        border: 1px solid rgba(63, 66, 75, 180);
        color: #f3f5f9;
    }
    QListWidget::item:selected {
        background: rgba(75, 163, 247, 40);
        border: 1px solid rgba(75, 163, 247, 90);
        color: #f3f5f9;
    }
"""
