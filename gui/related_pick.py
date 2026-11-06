# 같은 ID 관련 파일 선택 팝업 (수출·반송건 폴더 정리 전/후) — JarvisMessageBox 표준
import os

from PyQt6.QtWidgets import QCheckBox, QLabel, QScrollArea, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt

from .claude_theme import C as CT


def pick_related(parent, title, message, candidates, ok_text="포함하고 진행"):
    """후보 체크 목록을 띄운다.

    반환: (accepted, selected, declined) — 취소면 (False, [], []).
    exact 후보는 기본 체크, 포함만 된 후보는 '별건 의심'으로 기본 해제.
    """
    from .dialogs import JarvisMessageBox

    dlg = JarvisMessageBox(parent, title, message, JarvisMessageBox.Question)
    dlg.setMinimumWidth(460)

    body = QWidget()
    body.setStyleSheet("background: transparent;")
    lay = QVBoxLayout(body)
    lay.setContentsMargins(4, 0, 4, 0)
    lay.setSpacing(6)

    boxes = []
    for c in candidates:
        if c['kind'] == 'folder':
            text = f"📁 {c['name']}  ({c['count']}개)"
        else:
            text = c['name']
        cb = QCheckBox(text)
        cb.setChecked(bool(c['exact']))
        cb.setToolTip(c['path'])
        cb.setCursor(Qt.CursorShape.PointingHandCursor)
        cb.setStyleSheet(f"QCheckBox {{ color: {CT['fg_0']}; font-size: 9.5pt; background: transparent; spacing: 8px; }}"
                         "QCheckBox::indicator { width: 15px; height: 15px; }")
        lay.addWidget(cb)
        if not c['exact']:
            note = QLabel("      별건 의심 — ID 뒤에 다른 글자가 이어짐")
            note.setStyleSheet(f"color: {CT['amber']}; font-size: 8.5pt; background: transparent;")
            lay.addWidget(note)
        else:
            where = QLabel(f"      {os.path.dirname(c['path'])}")
            where.setStyleSheet(f"color: {CT['fg_2']}; font-size: 8pt; background: transparent;")
            lay.addWidget(where)
        boxes.append((cb, c))
    lay.addStretch(1)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")
    scroll.setWidget(body)
    scroll.setMaximumHeight(min(360, 52 * len(candidates) + 8))
    scroll.setMinimumHeight(min(360, 52 * len(candidates) + 8))

    inner = dlg.container.layout()
    inner.insertWidget(inner.indexOf(dlg.btn_widget), scroll)

    dlg.add_button("취소", "reject", "gray")
    dlg.add_button(ok_text, "accept", "cyan")
    accepted = bool(dlg.exec())
    selected = [c for cb, c in boxes if cb.isChecked()] if accepted else []
    declined = [c for cb, c in boxes if not cb.isChecked()] if accepted else []
    dlg.deleteLater()
    return accepted, selected, declined
