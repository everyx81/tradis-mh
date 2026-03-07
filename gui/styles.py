# JARVIS GUI 스타일시트 상수
"""
JARVIS HUD 스타일 Qt 스타일시트 모음
"""

# --- GLOBAL STYLESHEET ---
GLOBAL_STYLESHEET = """
QMainWindow {
    background-color: rgba(5, 10, 15, 230);
}
#OuterContainer {
    background-color: rgba(5, 15, 25, 100);
    border: 1px solid rgba(0, 255, 255, 150);
    border-radius: 6px;
}
QLabel {
    color: #a9b7c6;
    font-family: 'Malgun Gothic';
    font-size: 10pt;
}
/* Tech Style Input Fields */
QLineEdit {
    background-color: rgba(5, 20, 35, 100) !important;
    border: 1px solid rgba(0, 255, 255, 150);
    border-radius: 4px;
    color: #00ffff !important;
    padding: 8px 10px;
    font-family: 'Consolas', 'Malgun Gothic';
    font-size: 10pt;
    selection-background-color: rgba(0, 255, 255, 80);
}
QLineEdit:focus {
    border: 1px solid #00ffff;
    background-color: rgba(5, 30, 50, 150) !important;
}
QComboBox {
    background-color: rgba(5, 20, 35, 100) !important;
    border: 1px solid rgba(0, 255, 255, 150);
    border-radius: 4px;
    color: #00ffff !important;
    padding: 5px 15px;
}
QComboBox:hover {
    background-color: rgba(0, 255, 255, 20) !important;
}
QComboBox::drop-down {
    border: none;
    background: transparent;
}
QComboBox QAbstractItemView {
    background-color: #050f15;
    color: #00ffff;
    selection-background-color: rgba(0, 255, 255, 50);
    selection-color: #ffffff;
    border: 1px solid #00ffff;
}
QTextEdit {
    background-color: rgba(5, 15, 25, 80) !important;
    border: 1px solid rgba(0, 255, 255, 100);
    border-radius: 4px;
    color: #cceeff !important;
    font-family: 'Consolas';
    font-size: 10pt;
    padding: 10px;
}
QTabWidget::pane {
    border: 2px solid rgba(0, 255, 255, 150);
    background-color: rgba(5, 15, 25, 100);
    border-radius: 12px;
    margin-top: -1px;
}
QTabBar::tab {
    background-color: rgba(10, 20, 30, 180);
    color: rgba(150, 180, 200, 200);
    padding: 8px 12px;
    border: 1px solid rgba(0, 255, 255, 80);
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 3px;
}
QTabBar::tab:selected {
    background-color: rgba(0, 60, 80, 200);
    color: #00ffff;
    border-color: rgba(0, 255, 255, 200);
}
QTabBar::tab:hover:!selected {
    background-color: rgba(0, 80, 100, 150);
    color: #aaffff;
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
        background-color: rgba(2, 11, 20, 30);
        border: 2px solid #335566;
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
    QListWidget::item:hover {
        background-color: rgba(255, 255, 255, 10);
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

# FileManagerWidget list_target 스타일시트
TARGET_LIST_STYLESHEET = """
    QListWidget {
        background-color: rgba(2, 11, 20, 80);
        border: 2px solid #335566;
        border-radius: 10px;
        color: #ffffff;
        font-size: 9pt;
        padding: 5px;
        outline: none;
    }
    QListWidget:focus {
        border: 2px solid #00ffff;
    }
    QListWidget::item {
        padding: 5px;
        border-radius: 3px;
    }
    QListWidget::item:selected {
        background-color: rgba(0, 255, 255, 40);
        color: #00ffff;
    }
"""
