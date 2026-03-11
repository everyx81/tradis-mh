# JARVIS MK3 일정/메모 위젯
"""
MK3 일정 관리 시스템 위젯:
- MK3ScheduleOnlyWidget: 일정 관리 전용 위젯 (중앙 패널)
- MK3MemoOnlyWidget: 메모 관리 전용 위젯 (오른쪽 패널)
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QLineEdit, QComboBox, QListWidget, QListWidgetItem,
                              QTextEdit, QFrame, QSpinBox, QMenu, QDialog, QCheckBox,
                              QTabWidget, QCalendarWidget)
from PyQt6.QtCore import Qt, QTimer, QDate, QTime, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QBrush

import sys
import os
# 상위 디렉토리 추가 (gui 폴더에서 실행 시 calendar_manager 찾기 위함)
from calendar_manager import LocalScheduleManager, WindowsNotifier
from core.holidays import is_holiday
from .widgets import NeonButton

class HUDStyleCalendar(QCalendarWidget):
    """JARVIS HUD 스타일 테마가 적용되고 일정이 있는 날짜에 뱃지를 그려주는 커스텀 달력"""
    CELL_WIDTH = 78  # 둥근 직사각형 가로 크기 (72와 83의 중간)
    CELL_HEIGHT = 62 # 둥근 직사각형 세로 크기 (57과 66의 중간)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.event_dates = set()  # 일정이 있는 QDate 집합
        self._cell_rects = {}
        
        # 1. 왼쪽의 주 번호(Week number) 열 제거
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        
        # 2. 기본 네비게이션 바 숨기기 (커스텀 헤더로 대체)
        self.setNavigationBarVisible(False)
        
        # 3. 달력 전체 크기를 셀 크기 기준으로 고정 (네비 바 숨겼으므로 요일헤더+격자만)
        header_height = 25  # 요일 헤더 높이
        total_width = self.CELL_WIDTH * 7
        total_height = self.CELL_HEIGHT * 6 + header_height
        self.setFixedSize(total_width, total_height)
        
        self.init_style()
        
        # 4. 정사각형 셀 비율을 위한 초기 설정
        QTimer.singleShot(0, self._force_square_cells)
        # 5. 월 변경 시에도 정사각형 유지 + 이전 달 셀 위치 데이터 정리
        def _on_page_changed():
            self._cell_rects.clear()
            QTimer.singleShot(0, self._force_square_cells)
        self.currentPageChanged.connect(_on_page_changed)
        
    def init_style(self):
        # 애플 스타일 다크 모드 캘린더 테마 적용
        self.setStyleSheet("""
            /* 전체 달력 배경 (다크 그레이) 및 테두리 제거 */
            QCalendarWidget QWidget { 
                alternate-background-color: transparent; 
                background-color: transparent; 
            }
            
            /* 상단 네비게이션 바 (월/년도, 화살표) 영역 */
            QCalendarWidget QWidget#qt_calendar_navigationbar {
                background-color: #1a1a1c;
                border: none;
                padding: 10px 5px;
            }
            
            /* 이전/다음 달 이동 화살표 버튼 */
            QCalendarWidget QToolButton {
                color: #8e8e93; /* 애플 스타일 회색 */
                font-weight: bold;
                font-size: 14pt;
                background-color: transparent;
                border: none;
                padding: 4px;
            }
            QCalendarWidget QToolButton:hover {
                color: #ffffff;
            }
            
            /* 월/년도 선택 구역 정렬 및 폰트 */
            QCalendarWidget QToolButton#qt_calendar_monthbutton {
                color: #ffffff;
                background-color: transparent;
                font-size: 15pt;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                font-weight: bold;
            }
            QCalendarWidget QToolButton#qt_calendar_yearbutton {
                color: #ffffff;
                background-color: transparent;
                font-size: 15pt;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                font-weight: bold;
            }
            
            /* 날짜 셀 뷰 영역 */
            QCalendarWidget QTableView {
                background-color: #1a1a1c;
                selection-background-color: transparent;
                selection-color: transparent;
                outline: none;
                border: none;
                gridline-color: transparent;
            }
            
            /* 포커스 아웃라인 제거 */
            QCalendarWidget QAbstractItemView:enabled {
                color: #ffffff;
                outline: none;
                border: none;
            }
            
            /* 요일 헤더 폰트 공통 설정 (색상은 setWeekdayTextFormat 사용) */
            QTableView QHeaderView::section {
                background-color: transparent;
                border: none;
                font-family: -apple-system;
                font-size: 9pt;
            }
            
            /* 메뉴 박스 레이아웃 조정 (년/월 선택용 팝업) */
            QCalendarWidget QMenu {
                background-color: #2c2c2e;
                color: #ffffff;
                border-radius: 8px;
            }
            QCalendarWidget QSpinBox {
                background-color: #2c2c2e;
                color: #ffffff;
                selection-background-color: #3a3a3c;
                border-radius: 4px;
            }
        """)
        
        from PyQt6.QtGui import QTextCharFormat
        from PyQt6.QtCore import Qt
        
        fmt_weekday = QTextCharFormat()
        fmt_weekday.setForeground(QColor("#8e8e93"))
        for day in (Qt.DayOfWeek.Monday, Qt.DayOfWeek.Tuesday, Qt.DayOfWeek.Wednesday, Qt.DayOfWeek.Thursday, Qt.DayOfWeek.Friday):
            self.setWeekdayTextFormat(day, fmt_weekday)
            
        fmt_sat = QTextCharFormat()
        fmt_sat.setForeground(QColor("#0a84ff")) # 파란색
        self.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, fmt_sat)
        
        fmt_sun = QTextCharFormat()
        fmt_sun.setForeground(QColor("#ff453a")) # 빨간색
        self.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, fmt_sun)
        
    def _force_square_cells(self):
        """모든 셀을 CELL_WIDTH x CELL_HEIGHT 직사각형으로 강제 (배치 처리)"""
        from PyQt6.QtWidgets import QTableView, QHeaderView
        table = self.findChild(QTableView)
        if not table:
            return

        col_count = table.model().columnCount() if table.model() else 7
        row_count = table.model().rowCount() if table.model() else 6

        # 시그널 차단으로 레이아웃 재계산 1회로 축소
        table.horizontalHeader().blockSignals(True)
        table.verticalHeader().blockSignals(True)
        for c in range(col_count):
            table.setColumnWidth(c, self.CELL_WIDTH)
        for r in range(row_count):
            table.setRowHeight(r, self.CELL_HEIGHT)
        table.horizontalHeader().blockSignals(False)
        table.verticalHeader().blockSignals(False)
        table.viewport().update()
    
    def resizeEvent(self, event):
        """크기 변경 시 정사각형 셀 비율 유지"""
        super().resizeEvent(event)
        self._force_square_cells()
    
    def set_event_dates(self, dates_set):
        """일정이 존재하는 날짜들의 set(QDate)을 받아 갱신하고 다시 그림"""
        self.event_dates = dates_set
        self.updateCells()
        
    def paintCell(self, painter, rect, date):
        from PyQt6.QtCore import Qt, QRect, QPoint, QDate
        from PyQt6.QtGui import QColor, QPen, QBrush, QFont
        
        painter.save()
        
        # 각 날짜별 렌더링된 사각형 영역을 저장(드래그앤드롭 계산용)
        self._cell_rects[date] = rect
        
        # 기본 배경 투명 (큰 레이아웃 자체 배경)
        painter.fillRect(rect, Qt.GlobalColor.transparent)
        
        is_selected = (date == self.selectedDate())
        is_today = (date == QDate.currentDate())
        has_event = (date in self.event_dates)
        
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        
        # --- 1. 셀 내부에 둥근 직사각형 배경 박스 그리기 ---
        padding_x = max(2, int(rect.width() * 0.03))
        padding_y = max(2, int(rect.height() * 0.03))
        bg_width = rect.width() - (padding_x * 2)
        bg_height = rect.height() - (padding_y * 2)
        
        bg_rect = QRect(0, 0, bg_width, bg_height)
        bg_rect.moveCenter(rect.center())
        
        if date.month() == self.monthShown():
            holiday = is_holiday(date)
            if date.dayOfWeek() == 6:
                base_bg_color = QColor(42, 50, 65)  # 약간 푸른빛 바탕 (토요일)
            elif date.dayOfWeek() == 7 or holiday:
                base_bg_color = QColor(65, 42, 42)  # 약간 붉은빛 바탕 (일요일/공휴일)
            else:
                base_bg_color = QColor(58, 58, 60)  # 기본 짙은 회색 바탕
                
            if has_event:
                # 일정이 있는 날짜는 격자 바탕이 조금 투명해지도록 (알파값 조정)
                base_bg_color.setAlpha(150)
        else:
            base_bg_color = QColor(44, 44, 46, 40)  # 더 투명하게
            
        painter.setBrush(QBrush(base_bg_color))
        painter.setPen(Qt.PenStyle.NoPen)
        radius = max(6, int(min(bg_width, bg_height) * 0.15))  # 셀 크기에 비례한 둥근 모서리
        painter.drawRoundedRect(bg_rect, radius, radius)
        
        # --- 2. 셀 하이라이트/선택 표시 ---
        if is_today:
            # [오늘] 흰색 꽉 찬 원형 배경 (높이 기준 원, 조금 더 큼직하게 80%)
            circle_size = int(min(bg_width, bg_height) * 0.8)
            circle_rect = QRect(0, 0, circle_size, circle_size)
            circle_rect.moveCenter(bg_rect.center())
            
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(circle_rect)
            
        elif is_selected:
            # [선택됨] 얇은 파란색 외곽선 (배경 박스보다 1px 바깥쪽에 여유롭게 그림)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(QColor("#0a84ff"))
            pen.setWidth(2)
            painter.setPen(pen)
            
            sel_rect = bg_rect.adjusted(-1, -1, 1, 1)
            painter.drawRoundedRect(sel_rect, radius, radius)
            
        # --- 3. 날짜 텍스트 렌더링 ---
        font = painter.font()
        font_size = max(9, int(min(bg_width, bg_height) * 0.35))
        font.setPixelSize(font_size)
        font.setFamily("-apple-system")
        font.setWeight(QFont.Weight.Light) # 얇은 폰트 적용
        
        # 이벤트 있는 날짜는 볼드 처리 (이미지처럼)
        if has_event and date.month() == self.monthShown():
            font.setBold(True)
        else:
            font.setBold(False)
        
        painter.setFont(font)
        
        # 글자 색상
        if date.month() != self.monthShown():
            text_color = QColor("#48484a")
        elif is_today:
            text_color = QColor("#000000")
        elif date.dayOfWeek() == 6:
            text_color = QColor("#0a84ff")
        elif date.dayOfWeek() == 7 or is_holiday(date):
            text_color = QColor("#ff453a")
        else:
            text_color = QColor("#f2f2f7")
            
        painter.setPen(text_color)
        
        # 텍스트를 최상단 쪽에 가깝게 배치하여 아래쪽에 여백(점 찍을 공간)을 시원하게 줌
        text_rect = QRect(bg_rect.x(), bg_rect.y() - 2, bg_rect.width(), int(bg_rect.height() * 0.75))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, str(date.day()))
        
        # --- 4. 일정 인디케이터 (작은 점) ---
        if has_event:
            dot_color = QColor("#0a84ff") if is_today else QColor("#8e8e93")
            painter.setBrush(QBrush(dot_color))
            painter.setPen(Qt.PenStyle.NoPen)
            
            dot_size = max(3, int(min(bg_width, bg_height) * 0.08))
            dot_x = int(bg_rect.center().x() - (dot_size / 2))
            dot_y = int(bg_rect.y() + bg_height * 0.78)
            
            painter.drawEllipse(dot_x, dot_y, dot_size, dot_size)
            
        painter.restore()

class ScheduleEditDialog(QDialog):
    """일정 상세 편집 다이얼로그 (갤럭시 리마인더 스타일 팝업)"""
    def __init__(self, schedule: dict, parent=None):
        super().__init__(parent)
        self.schedule = schedule
        self.result_data = None
        self.init_ui()
        
    def init_ui(self):
        from PyQt6.QtWidgets import (QDateEdit, QTimeEdit, QCheckBox, 
                                     QGroupBox, QGridLayout)
        from datetime import datetime
        
        self.setWindowTitle("리마인더 상세 편집")
        self.setFixedSize(380, 520)
        self.setStyleSheet("""
            QDialog { background-color: #0b141e; border: 1px solid #335566; }
            QLabel { color: #ffffff; font-size: 10pt; }
            QGroupBox { border: 1px solid #335566; margin-top: 10px; padding-top: 15px; color: #66aacc; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top center; padding: 0 5px; }
            QLineEdit, QDateEdit, QTimeEdit, QComboBox {
                background-color: rgba(2, 11, 20, 120); border: 1px solid #335566; color: #00ffff;
                padding: 6px; border-radius: 4px;
            }
            QPushButton {
                background-color: #005566; color: white; border: none; padding: 10px; border-radius: 6px; font-weight: bold;
            }
            QPushButton:hover { background-color: #007788; }
            QPushButton#btnCancel { background-color: #444; }
            QPushButton#btnCancel:hover { background-color: #666; }
            QPushButton#btnDelete { background-color: #660000; }
            QPushButton#btnDelete:hover { background-color: #880000; }
            QCheckBox { color: #ddd; }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # 1. 제목
        self.title_edit = QLineEdit(self.schedule.get("title", ""))
        self.title_edit.setPlaceholderText("리마인더 제목")
        self.title_edit.setStyleSheet("font-size: 12pt; font-weight: bold; padding: 10px;")
        layout.addWidget(self.title_edit)
        
        dt_str = self.schedule.get("datetime")
        dt_obj = datetime.fromisoformat(dt_str) if dt_str else datetime.now()
        
        # 2. 날짜/시간 설정 그룹
        time_group = QGroupBox("기한 (목표일시)")
        time_layout = QGridLayout(time_group)
        
        self.date_edit = QDateEdit(QDate(dt_obj.year, dt_obj.month, dt_obj.day))
        self.date_edit.setCalendarPopup(True)
        time_layout.addWidget(QLabel("날짜:"), 0, 0)
        time_layout.addWidget(self.date_edit, 0, 1)
        
        self.time_edit = QTimeEdit(QTime(dt_obj.hour, dt_obj.minute))
        time_layout.addWidget(QLabel("시간:"), 1, 0)
        time_layout.addWidget(self.time_edit, 1, 1)
        
        self.repeat_combo = QComboBox()
        self.repeat_combo.addItems(["반복 없음", "매 30분", "매 1시간", "매 3시간", "매일", "매주", "매월"])
        repeat_map_rev = {
            "None": 0, "Every30Min": 1, "Hourly": 2, "Every3Hours": 3, 
            "Daily": 4, "Weekly": 5, "Monthly": 6
        }
        self.repeat_combo.setCurrentIndex(repeat_map_rev.get(self.schedule.get("repeat", "None"), 0))
        time_layout.addWidget(QLabel("반복:"), 2, 0)
        time_layout.addWidget(self.repeat_combo, 2, 1)
        
        layout.addWidget(time_group)
        
        # 3. 사전 알림(Alerts) 다중 선택 그룹
        alert_group = QGroupBox("사전 알림 (다중 선택 가능)")
        alert_layout = QVBoxLayout(alert_group)
        
        alerts = self.schedule.get("alerts", [0])
        
        self.chk_0 = QCheckBox("정각 (기한 정시)")
        self.chk_15 = QCheckBox("15분 전")
        self.chk_60 = QCheckBox("1시간 전")
        self.chk_1440 = QCheckBox("1일 전")
        self.chk_2880 = QCheckBox("2일 전")
        
        self.chk_0.setChecked(0 in alerts)
        self.chk_15.setChecked(15 in alerts)
        self.chk_60.setChecked(60 in alerts)
        self.chk_1440.setChecked(1440 in alerts)
        self.chk_2880.setChecked(2880 in alerts)
        
        alert_layout.addWidget(self.chk_0)
        alert_layout.addWidget(self.chk_15)
        alert_layout.addWidget(self.chk_60)
        alert_layout.addWidget(self.chk_1440)
        alert_layout.addWidget(self.chk_2880)
        
        layout.addWidget(alert_group)
        
        # 4. 메모
        self.note_edit = QLineEdit(self.schedule.get("note", ""))
        self.note_edit.setPlaceholderText("메모 추가...")
        layout.addWidget(self.note_edit)
        
        layout.addStretch()
        
        # 5. 버튼
        btn_layout = QHBoxLayout()
        self.btn_del = QPushButton("삭제")
        self.btn_del.setObjectName("btnDelete")
        self.btn_del.clicked.connect(self.on_delete)
        
        self.btn_save = QPushButton("저장")
        self.btn_save.clicked.connect(self.on_save)
        
        self.btn_cancel = QPushButton("취소")
        self.btn_cancel.setObjectName("btnCancel")
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.btn_del)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        
        layout.addLayout(btn_layout)
        
    def get_alerts(self):
        res = []
        if self.chk_0.isChecked(): res.append(0)
        if self.chk_15.isChecked(): res.append(15)
        if self.chk_60.isChecked(): res.append(60)
        if self.chk_1440.isChecked(): res.append(1440)
        if self.chk_2880.isChecked(): res.append(2880)
        if not res: res.append(0) # 최소 1개는 있도록 보정
        return res
        
    def on_save(self):
        from datetime import datetime
        qdate = self.date_edit.date()
        qtime = self.time_edit.time()
        new_dt = datetime(qdate.year(), qdate.month(), qdate.day(), qtime.hour(), qtime.minute())
        
        repeat_map = {
            "반복 없음": "None", "매 30분": "Every30Min", "매 1시간": "Hourly",
            "매 3시간": "Every3Hours", "매일": "Daily", "매주": "Weekly", "매월": "Monthly"
        }
        
        self.result_data = {
            "action": "save",
            "title": self.title_edit.text() if self.title_edit.text() else "제목 없음",
            "datetime": new_dt,
            "repeat": repeat_map.get(self.repeat_combo.currentText(), "None"),
            "alerts": self.get_alerts(),
            "note": self.note_edit.text()
        }
        self.accept()
        
    def on_delete(self):
        self.result_data = {"action": "delete"}
        self.accept()


class ScheduleCardWidget(QFrame):
    """개별 일정 카드 위젯 (애플 리마인더 라인 스타일로 리뉴얼)"""
    def __init__(self, schedule: dict, main_widget, parent=None):
        super().__init__(parent)
        self.schedule = schedule
        self.main_widget = main_widget # MK3ScheduleOnlyWidget 참조
        self.init_ui()
        
    def init_ui(self):
        from PyQt6.QtWidgets import QMenu, QSizePolicy
        from datetime import datetime
        
        # 완전 투명 바탕 테마 (부모 리스트의 밑줄로 구분됨)
        is_completed = self.schedule.get("completed", False)
        self.setStyleSheet("""
            QFrame { background-color: transparent; border: none; }
        """)
        
        self.setMinimumHeight(45)  # 한 줄 높이 슬림화
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(15)
        
        # 1. 항목 식별 색상 지정 (애플 캘린더 파스텔톤 적용)
        colors = ["#6CC3F9", "#C695F4", "#80D478", "#FBA35A", "#FC7588", "#70D7CC"]
        title_hash = sum(ord(c) for c in self.schedule.get("title", ""))
        dot_color = colors[title_hash % len(colors)]
        
        # 완료 상태 (플랫한 원형 파스텔 점 느낌)
        self.chk_complete = QCheckBox()
        # 미완료: 꽉 찬 파스텔톤 색상
        chk_style = f"QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 7px; background-color: {dot_color}; border: none; }}"
        if is_completed:
            # 완료: 안쪽 투명(또는 매우 옅음) + 외곽선
            chk_style += f"QCheckBox::indicator:checked {{ background-color: transparent; border: 2px solid {dot_color}; image: url(none); opacity: 0.5; }}"
        self.chk_complete.setStyleSheet(chk_style)
        self.chk_complete.setChecked(is_completed)
        self.chk_complete.clicked.connect(self.toggle_complete)
        layout.addWidget(self.chk_complete)
        
        # 2. 텍스트 컨테이너
        text_layout = QVBoxLayout()
        text_layout.setSpacing(0)
        
        # 제목
        title_text = self.schedule.get("title", "")
        self.lbl_title = QLabel(title_text)
        # 글자 크기 조금 더 키움 (11pt -> 13pt)
        font_str = "font-size: 13pt; font-weight: 500; font-family: -apple-system, BlinkMacSystemFont, sans-serif; color: #ffffff;"
        if is_completed:
            # 너무 어둡지 않게 색상 상향 조정 (#8a8a8e 등)
            font_str += " text-decoration: line-through; color: #8a8a8e;"
        self.lbl_title.setStyleSheet(font_str)
        text_layout.addWidget(self.lbl_title)
        
        # 시간, 설정 요약
        dt_str = self.schedule.get("datetime")
        if dt_str:
            try:
                dt_obj = datetime.fromisoformat(dt_str)
                weekdays = ["월", "화", "수", "목", "금", "토", "일"]
                wd = weekdays[dt_obj.weekday()]
                # "3월 3일 (화) · 11:00 AM" 형식 만들기
                time_str = f"{dt_obj.month}월 {dt_obj.day}일 ({wd}) · {dt_obj.strftime('%I:%M %p')}"
            except ValueError: time_str = dt_str
        else:
            time_str = "하루 종일"
            
        alerts = self.schedule.get("alerts", [])
        alert_str = f"알림 {len(alerts)}개" if (alerts and alerts != [0]) else ""
        repeat = self.schedule.get("repeat", "None")
        repeat_str = "" if repeat == "None" else "반복됨"

        # 스누즈 상태 표시
        snooze_str = ""
        snooze_until = self.schedule.get("snooze_until")
        if snooze_until and not is_completed:
            try:
                snooze_dt = datetime.fromisoformat(snooze_until)
                snooze_str = f"스누즈 {snooze_dt.strftime('%H:%M')}"
            except ValueError:
                pass

        # 기한 경과 확인
        is_overdue = False
        if dt_str and not is_completed:
            try:
                if datetime.fromisoformat(dt_str) < datetime.now():
                    is_overdue = True
            except ValueError:
                pass

        # 디테일 라벨 조합
        parts = [p for p in [time_str, snooze_str, alert_str, repeat_str] if p]
        desc = " · ".join(parts)

        self.lbl_desc = QLabel(desc)
        if is_overdue:
            desc_color = "#ff6b6b"  # 기한 경과: 빨간색
        elif snooze_str:
            desc_color = "#ffa500"  # 스누즈 중: 주황색
        elif is_completed:
            desc_color = "#6e6e73"
        else:
            desc_color = "#8e8e93"
        self.lbl_desc.setStyleSheet(f"font-size: 10pt; color: {desc_color}; font-family: -apple-system;")
        text_layout.addWidget(self.lbl_desc)
        
        layout.addLayout(text_layout, stretch=1)
        
        # 3. 상세 관리 버튼 (ℹ️ 모양 흉내)
        self.btn_edit = QPushButton("i")
        self.btn_edit.setFixedSize(20, 20)
        self.btn_edit.setStyleSheet("""
            QPushButton {
                background-color: transparent; border: 1px solid rgba(10, 132, 255, 120);
                border-radius: 10px; color: #0a84ff; font-size: 10pt; font-family: 'Times New Roman', serif; font-style: italic;
            }
            QPushButton:hover { background-color: rgba(10, 132, 255, 30); }
        """)
        self.btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit.clicked.connect(self.open_edit_dialog)
        layout.addWidget(self.btn_edit)
        
    def toggle_complete(self):
        new_status = self.chk_complete.isChecked()
        self.main_widget.schedule_manager.update_schedule(self.schedule["id"], completed=new_status)
        self.main_widget.refresh_schedules()
        
    def open_edit_dialog(self):
        dialog = ScheduleEditDialog(self.schedule, self.window())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.result_data
            if data["action"] == "delete":
                self.main_widget.schedule_manager.delete_schedule(self.schedule["id"])
            elif data["action"] == "save":
                self.main_widget.schedule_manager.update_schedule(
                    self.schedule["id"], 
                    title=data["title"],
                    datetime=data["datetime"],
                    repeat=data["repeat"],
                    alerts=data["alerts"],
                    note=data["note"]
                )
            self.main_widget.refresh_schedules()


class MK3ScheduleOnlyWidget(QWidget):
    """MK3 - 일정 관리 전용 위젯 (중앙 패널)"""
    
    def __init__(self, schedule_manager=None, notifier=None, parent=None):
        super().__init__(parent)
        self.schedule_manager = schedule_manager if schedule_manager else LocalScheduleManager()
        self.notifier = notifier if notifier else WindowsNotifier()
        self.init_ui()

        # 스누즈/완료/반복 등 데이터 변경 시 UI 자동 갱신 (스레드 안전)
        self.schedule_manager.register_ui_callback(
            lambda: QTimer.singleShot(0, self.refresh_schedules)
        )

        self.schedule_manager.start_reminder_loop(1)
    
    def init_ui(self):
        from PyQt6.QtWidgets import QDateEdit
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        # (SCHEDULE MANAGER 및 하위 타이틀 등 불필요한 헤더는 모두 애플 캘린더 스타일을 위해 제거)
        split_layout = QHBoxLayout()
        split_layout.setSpacing(20)
        
        # --- 좌측 달력 영역 (네비게이션 + 달력) ---
        left_layout = QVBoxLayout()
        left_layout.setSpacing(8)
        
        # === 커스텀 네비게이션 헤더 (Apple Calendar 스타일) ===
        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(5)
        
        # < > 화살표 (Apple 스타일로 왼쪽에 나란히)
        btn_style = """
            QPushButton {
                background-color: transparent; color: #8e8e93;
                font-size: 14pt; font-weight: bold; border: none;
                padding: 2px 8px;
            }
            QPushButton:hover { color: #ffffff; }
        """
        # 1. 왼쪽 그룹 (< > 화살표)
        left_group = QHBoxLayout()
        left_group.setSpacing(5)
        self.btn_prev_month = QPushButton("❮")
        self.btn_prev_month.setStyleSheet(btn_style)
        self.btn_prev_month.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_prev_month.setFixedSize(30, 30)
        left_group.addWidget(self.btn_prev_month)
        
        self.btn_next_month = QPushButton("❯")
        self.btn_next_month.setStyleSheet(btn_style)
        self.btn_next_month.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next_month.setFixedSize(30, 30)
        left_group.addWidget(self.btn_next_month)
        
        # 2. 중앙 타이틀 ("2026년 3월")
        self.lbl_cal_title = QLabel()
        self.lbl_cal_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_cal_title.setStyleSheet("""
            color: #ffffff; font-size: 20pt; font-weight: bold;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        """)
        
        # 3. 양옆 여백으로 중앙 조절
        nav_layout.addLayout(left_group)
        nav_layout.addStretch()
        nav_layout.addWidget(self.lbl_cal_title)
        nav_layout.addStretch()
        
        # + 버튼 (Apple 스타일)
        self.btn_add_schedule = QPushButton("+")
        self.btn_add_schedule.setStyleSheet("""
            QPushButton {
                background-color: transparent; color: #8e8e93;
                font-size: 18pt; font-weight: bold; border: none;
                padding: 2px 8px;
            }
            QPushButton:hover { color: #ffffff; }
        """)
        self.btn_add_schedule.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_schedule.setFixedSize(30, 30)
        nav_layout.addWidget(self.btn_add_schedule)
        
        # 달력 + 헤더를 담을 컨테이너 (좌측 정렬 및 너비 고정용)
        cal_container = QVBoxLayout()
        cal_container.setSpacing(25)  # 네비게이션 헤더와 달력 사이의 여백 추가 (이미지 반영)
        
        # 네비게이션 헤더에 달력과 동일한 고정 너비 적용 (CELL_WIDTH * 7)
        nav_widget = QWidget()
        nav_widget.setLayout(nav_layout)
        nav_widget.setFixedWidth(HUDStyleCalendar.CELL_WIDTH * 7)
        cal_container.addWidget(nav_widget)
        
        self.calendar = HUDStyleCalendar()
        self.calendar.clicked.connect(self._on_calendar_clicked)
        self.calendar.activated.connect(self._on_calendar_activated) # 더블클릭/엔터
        cal_container.addWidget(self.calendar)
        
        # 좌측 레이아웃(달력)에 컨테이너 배치 (위쪽으로 밀착)
        left_layout.addLayout(cal_container, stretch=0)
        left_layout.addStretch(1)

        # 네비게이션 버튼 연결
        self.btn_prev_month.clicked.connect(self.calendar.showPreviousMonth)
        self.btn_next_month.clicked.connect(self.calendar.showNextMonth)
        self.btn_add_schedule.clicked.connect(self._on_add_button_clicked)
        self.calendar.currentPageChanged.connect(self._update_calendar_title)
        self._update_calendar_title()
        
        split_layout.addLayout(left_layout, stretch=1) # 달력 영역 (고정 크기이므로 스레치는 리스트에 양보)
        
        # --- 우측 일정 리스트 영역 ---
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(20, 0, 10, 0)
        
        list_header = QHBoxLayout()
        # 중앙 정렬을 양쪽 스페이서로 구현
        list_header.addStretch(1)
        self.lbl_list_header = QLabel("전체 일정")
        self.lbl_list_header.setStyleSheet("color: #ffffff; font-size: 12pt; font-weight: bold; font-family: -apple-system;")
        self.lbl_list_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        list_header.addWidget(self.lbl_list_header, stretch=0)
        
        list_header.addStretch(1)
        
        self.btn_show_all = QPushButton("모두 보기")
        self.btn_show_all.setStyleSheet("background-color: transparent; color: #0a84ff; font-weight: bold; text-decoration: none;")
        self.btn_show_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_show_all.clicked.connect(self.show_all_schedules)
        self.btn_show_all.hide()  # 평소(전체보기일 때)는 숨김
        # btn_show_all 이 보여질 때를 위해 약간의 트릭
        list_header.addWidget(self.btn_show_all)
        
        right_layout.addLayout(list_header)
        
        # 리스트 위젯 껍데기 투명화 (애플 스타일의 줄바꿈 선만 유지)
        self.schedule_list = QListWidget()
        self.schedule_list.setStyleSheet("""
            QListWidget {
                background-color: transparent;
                border: none;
                color: #ffffff;
                font-size: 10pt;
                outline: none;
            }
            QListWidget::item { 
                padding: 6px 0px; 
                border-bottom: 1px solid #38383a; 
            }
            QListWidget::item:selected { 
                background-color: transparent; 
            }
            QListWidget::item:focus { 
                outline: none; 
            }
        """)
        self.schedule_list.itemDoubleClicked.connect(self._on_schedule_item_clicked)
        self.schedule_list.keyPressEvent = self._on_schedule_key_press
        right_layout.addWidget(self.schedule_list)
        
        split_layout.addLayout(right_layout, stretch=2) # 우측 일정 리스트 영역 비율
        
        layout.addLayout(split_layout, stretch=1)
        
        self.current_filter_date = None # 필터링 날짜 저장용 변수
        
        QTimer.singleShot(100, self.refresh_schedules)
        
        self.refresh_schedules()
    
    def refresh_schedules(self):
        self.schedule_list.clear()
        
        from PyQt6.QtCore import QDate
        from datetime import datetime as dt
        
        schedules = self.schedule_manager.list_schedules(include_completed=True)
        
        active_schedules = []
        completed_schedules = []
        event_dates = set()
        
        for schedule in schedules:
            is_completed = schedule.get("completed", False)
            
            # 시간 파싱하여 달력 뱃지용 Set에 달아두기
            date_obj = None
            if "datetime" in schedule:
                try:
                    s_dt = dt.fromisoformat(schedule["datetime"])
                    date_obj = QDate(s_dt.year, s_dt.month, s_dt.day)
                    if not is_completed:
                        event_dates.add(date_obj)
                except (ValueError, KeyError): pass
                
            # 현재 필터링 상태면 해당 날짜만 리스트업
            if self.current_filter_date and date_obj != self.current_filter_date:
                continue
                
            if is_completed:
                completed_schedules.append(schedule)
            else:
                active_schedules.append(schedule)
                
        # 달력 위젯 갱신 (점 찍기)
        self.calendar.set_event_dates(event_dates)
        
        # 필터 라벨 갱신 (Apple Calendar 스타일: "3월 3일 월요일")
        if self.current_filter_date:
            weekday_names = ["", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
            d = self.current_filter_date
            weekday = weekday_names[d.dayOfWeek()]
            self.lbl_list_header.setText(f"{d.month()}월 {d.day()}일 {weekday}")
            self.btn_show_all.show()
        else:
            self.lbl_list_header.setText("전체 일정")
            self.btn_show_all.hide()
            
        # 리스트 렌더링
        for schedule in active_schedules:
            try:
                item = QListWidgetItem(self.schedule_list)
                card = ScheduleCardWidget(schedule, self)
                item.setSizeHint(card.sizeHint())
                item.setData(Qt.ItemDataRole.UserRole, schedule["id"])
                
                self.schedule_list.addItem(item)
                self.schedule_list.setItemWidget(item, card)
            except Exception as e: pass
                
        for schedule in completed_schedules:
            try:
                item = QListWidgetItem(self.schedule_list)
                card = ScheduleCardWidget(schedule, self)
                item.setSizeHint(card.sizeHint())
                item.setData(Qt.ItemDataRole.UserRole, schedule["id"])
                
                self.schedule_list.addItem(item)
                self.schedule_list.setItemWidget(item, card)
            except Exception as e: pass
            
    def show_all_schedules(self):
        """달력 연동 필터링을 해제하고 전체를 보여줌"""
        self.current_filter_date = None
        self.refresh_schedules()
        
    def _on_calendar_clicked(self, date):
        """달력 특정 날짜 단일 클릭: 해당 일자 필터링"""
        self.current_filter_date = date
        self.refresh_schedules()
        
    def _on_calendar_activated(self, date):
        """달력 특정 날짜 더블클릭/엔터: 빈 해당 일자 일정 추가 팝업 띄우기"""
        from datetime import datetime as dt
        # 새 빈 스케줄 더미 생성
        now = dt.now()
        dummy_dt = dt(date.year(), date.month(), date.day(), now.hour, 0)
        
        dummy_schedule = {
            "title": "",
            "datetime": dummy_dt.isoformat(),
            "repeat": "None",
            "alerts": [0]
        }
        
        dialog = ScheduleEditDialog(dummy_schedule, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.result_data
            if data["action"] == "save":
                self.schedule_manager.add_schedule(
                    title=data["title"],
                    dt=data["datetime"],
                    repeat=data["repeat"],
                    alerts=data["alerts"],
                    note=data.get("note", "")
                )
            self.refresh_schedules()
        
    def _update_calendar_title(self, year=None, month=None):
        """커스텀 네비게이션 헤더의 년월 타이틀 갱신"""
        if year is None or month is None:
            year = self.calendar.yearShown()
            month = self.calendar.monthShown()
        self.lbl_cal_title.setText(f"{year}년 {month}월")
    
    def _on_add_button_clicked(self):
        """+ 버튼 클릭: 현재 선택된 날짜에 일정 추가"""
        date = self.calendar.selectedDate()
        self._on_calendar_activated(date)
        
    def _on_schedule_item_clicked(self, item):
        """더미 핸들러: 카드 내에서 자체 처리하므로 리스트 더블클릭은 Edit을 바로 띄우도록 우회"""
        schedule_id = item.data(Qt.ItemDataRole.UserRole)
        if not schedule_id: return
        
        # 카드를 트리거
        widget = self.schedule_list.itemWidget(item)
        if hasattr(widget, "open_edit_dialog"):
            widget.open_edit_dialog()
            
    def _on_schedule_key_press(self, event):
        """Delete 키로 선택된 일정 삭제"""
        from PyQt6.QtWidgets import QListWidget
        
        if event.key() == Qt.Key.Key_Delete:
            current_item = self.schedule_list.currentItem()
            if current_item:
                schedule_id = current_item.data(Qt.ItemDataRole.UserRole)
                if schedule_id:
                    self.schedule_manager.delete_schedule(schedule_id)
                    self.refresh_schedules()
        else:
            QListWidget.keyPressEvent(self.schedule_list, event)
            
    def test_notification(self):
        self.notifier.show_toast("📅 TRADIS MH 알림 테스트", "일정관리 알림이 정상 작동합니다!", duration=5)


class MK3MemoOnlyWidget(QWidget):
    """MK3 - 메모 관리 전용 위젯 (오른쪽 패널) - Multi-Tab Support"""
    hotkey_settings_clicked = pyqtSignal()  # 단축키 설정 버튼 시그널
    
    def __init__(self, schedule_manager=None, parent=None):
        super().__init__(parent)
        self.schedule_manager = schedule_manager if schedule_manager else LocalScheduleManager()
        
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(1000)
        self.save_timer.timeout.connect(self._save_current_memo)
        
        self.memo_counter = 0  # 새 메모 번호 카운터
        
        self.init_ui()
        self._load_all_memos()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 헤더
        header_container = QWidget()
        header_container.setFixedHeight(40)
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(10, 5, 10, 5)
        
        header = QLabel("📝 MK3 - 메모장")
        header.setStyleSheet("color: #ffa500; font-size: 12pt; font-weight: bold;")
        header_layout.addWidget(header)
        
        header_layout.addStretch()
        
        # 버튼 스타일 (모던 자비스 스타일)
        from .widgets import NeonButton
        
        # AI 정리 버튼
        btn_organize = NeonButton("🔄 정리", color="green")
        btn_organize.setFixedSize(85, 32)
        btn_organize.setToolTip("AI로 메모 내용 정리")
        btn_organize.clicked.connect(self._organize_memo_with_ai)
        header_layout.addWidget(btn_organize)
        
        # 새 메모 추가 버튼
        btn_add = NeonButton("＋", color="cyan")
        btn_add.setFixedSize(38, 32)
        btn_add.setToolTip("새 메모 추가")
        btn_add.clicked.connect(self._add_new_memo)
        header_layout.addWidget(btn_add)
        
        # 단축키 설정 버튼
        btn_settings = NeonButton("⌨", color="purple")
        btn_settings.setFixedSize(38, 32)
        btn_settings.setToolTip("단축키 설정")
        btn_settings.clicked.connect(self.hotkey_settings_clicked.emit)
        header_layout.addWidget(btn_settings)
        
        layout.addWidget(header_container)
        
        # 탭 위젯
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.setUsesScrollButtons(True)  # 스크롤 버튼 활성화
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self.tab_widget.tabBarDoubleClicked.connect(self._rename_tab)
        
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: transparent;
            }
            QTabBar {
                background: transparent;
            }
            QTabBar::tab {
                background-color: rgba(40, 45, 55, 200);
                color: #888888;
                padding: 6px 24px 6px 10px;
                margin-right: 3px;
                border: 1px solid rgba(80, 90, 100, 100);
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                min-width: 60px;
                max-width: 120px;
            }
            QTabBar::tab:selected {
                background-color: rgba(60, 70, 85, 250);
                color: #ffa500;
                border: 1px solid #ffa500;
                border-bottom: 2px solid #ffa500;
            }
            QTabBar::tab:hover:!selected {
                background-color: rgba(55, 65, 75, 220);
                color: #cccccc;
                border: 1px solid rgba(100, 110, 120, 150);
            }
            QTabBar::close-button {
                subcontrol-position: right;
                subcontrol-origin: padding;
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background: transparent;
                margin-right: 2px;
            }
            QTabBar::close-button:hover {
                background-color: #ff5555;
            }
            QTabBar::scroller {
                width: 24px;
            }
            QTabBar QToolButton {
                background-color: rgba(40, 50, 60, 200);
                border: 1px solid #555555;
                border-radius: 4px;
                color: #00d4ff;
            }
            QTabBar QToolButton:hover {
                background-color: rgba(0, 200, 255, 50);
            }
        """)
        
        # 탭 우클릭 메뉴 활성화
        self.tab_widget.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_widget.tabBar().customContextMenuRequested.connect(self._show_tab_context_menu)
        
        layout.addWidget(self.tab_widget)
    
    def focus_current_memo(self):
        """현재 활성 메모에 포커스 설정 (글로벌 단축키용)"""
        index = self.tab_widget.currentIndex()
        if index >= 0:
            editor = self.tab_widget.widget(index)
            if isinstance(editor, QTextEdit):
                editor.setFocus()

    
    def _create_memo_editor(self) -> QTextEdit:
        """메모 편집기 생성"""
        editor = QTextEdit()
        editor.setPlaceholderText("자유롭게 내용을 작성하세요... (자동 저장됨)")
        editor.setFrameShape(QFrame.Shape.NoFrame)
        editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        editor.setAcceptRichText(False)  # Plain text만 허용 (서식 붙여넣기 방지)
        
        editor.setStyleSheet("""
            QTextEdit {
                background-color: transparent;
                color: #ffffff;
                font-size: 11pt;
                line-height: 1.6;
                selection-background-color: rgba(255, 165, 0, 100);
                selection-color: #ffffff;
                padding: 10px;
                border: none;
            }
        """)
        
        editor.textChanged.connect(self._on_text_changed)
        return editor
    
    def _load_all_memos(self):
        """저장된 모든 메모 로드"""
        memos = self.schedule_manager.list_memos()
        
        if not memos:
            # 메모가 없으면 기본 메모 하나 생성
            self._add_new_memo()
            return
        
        for memo in memos:
            title = memo.get("title", "메모")
            # QUICK_MEMO_PAD는 "메모 1"로 표시
            if title == "QUICK_MEMO_PAD":
                title = "메모 1"
            
            content = memo.get("content", "")
            memo_id = memo.get("id")
            is_locked = memo.get("locked", False)
            
            editor = self._create_memo_editor()
            editor.blockSignals(True)
            editor.setPlainText(content)
            editor.blockSignals(False)
            editor.setProperty("memo_id", memo_id)
            editor.setProperty("locked", is_locked)
            
            # 잠금 상태 적용
            if is_locked:
                editor.setReadOnly(True)
                display_title = f"🔒 {title.replace('🔒 ', '')}"
            else:
                display_title = title.replace('🔒 ', '')
            
            self.tab_widget.addTab(editor, display_title)
            
            # 메모 번호 추적
            self.memo_counter = max(self.memo_counter, self._extract_memo_number(title))
    
    def _extract_memo_number(self, title: str) -> int:
        """메모 제목에서 번호 추출"""
        import re
        match = re.search(r'메모\s*(\d+)', title)
        if match:
            return int(match.group(1))
        return 0
    
    def _add_new_memo(self):
        """새 메모 탭 추가"""
        self.memo_counter += 1
        title = f"메모 {self.memo_counter}"
        
        new_memo = self.schedule_manager.add_memo(title=title, content="")
        
        editor = self._create_memo_editor()
        editor.setProperty("memo_id", new_memo["id"])
        
        idx = self.tab_widget.addTab(editor, title)
        self.tab_widget.setCurrentIndex(idx)
        editor.setFocus()
    
    def _close_tab(self, index: int):
        """메모 탭 닫기 (잠금 확인 + 삭제 확인)"""
        if self.tab_widget.count() <= 1:
            # 최소 1개 메모는 유지
            return
        
        editor = self.tab_widget.widget(index)
        memo_id = editor.property("memo_id")
        is_locked = editor.property("locked")
        
        # 잠금된 메모는 삭제 불가
        if is_locked:
            from .dialogs import JarvisMessageBox
            JarvisMessageBox.warning(self, "잠금 메모", "🔒 잠긴 메모는 삭제할 수 없습니다.\n먼저 잠금을 해제해 주세요.")
            return
        
        # 내용이 있는 메모는 확인 다이얼로그 표시
        content = editor.toPlainText().strip()
        if content:
            from .dialogs import JarvisMessageBox
            if not JarvisMessageBox.question(self, "메모 삭제", f"이 메모를 정말 삭제하시겠습니까?\n\n내용 미리보기:\n{content[:80]}{'...' if len(content) > 80 else ''}"):
                return
        
        if memo_id:
            self.schedule_manager.delete_memo(memo_id)
        
        self.tab_widget.removeTab(index)
    
    def _rename_tab(self, index: int):
        """탭 이름 변경 (더블클릭)"""
        from PyQt6.QtWidgets import QInputDialog
        
        current_name = self.tab_widget.tabText(index)
        new_name, ok = QInputDialog.getText(
            self, "메모 이름 변경", "새 이름:", text=current_name
        )
        
        if ok and new_name.strip():
            new_name = new_name.strip()
            self.tab_widget.setTabText(index, new_name)
            
            editor = self.tab_widget.widget(index)
            memo_id = editor.property("memo_id")
            if memo_id:
                self.schedule_manager.update_memo(memo_id, title=new_name)
    
    def _on_tab_changed(self, index: int):
        """탭 변경 시 저장"""
        self._save_current_memo()
    
    def _on_text_changed(self):
        """텍스트 변경 시 저장 타이머 시작"""
        self.save_timer.start()
    
    def _save_current_memo(self):
        """현재 활성 메모 저장"""
        index = self.tab_widget.currentIndex()
        if index < 0:
            return
        
        editor = self.tab_widget.widget(index)
        if not isinstance(editor, QTextEdit):
            return
        
        memo_id = editor.property("memo_id")
        if memo_id:
            content = editor.toPlainText()
            title = self.tab_widget.tabText(index).replace('🔒 ', '')
            self.schedule_manager.update_memo(memo_id, title=title, content=content)
    
    def save_all_memos(self):
        """모든 메모 강제 저장 (앱 종료 시 호출)"""
        for i in range(self.tab_widget.count()):
            editor = self.tab_widget.widget(i)
            if isinstance(editor, QTextEdit):
                memo_id = editor.property("memo_id")
                if memo_id:
                    content = editor.toPlainText()
                    title = self.tab_widget.tabText(i).replace('🔒 ', '')
                    self.schedule_manager.update_memo(memo_id, title=title, content=content)
    
    def _show_tab_context_menu(self, position):
        """탭 우클릭 메뉴 (잠금/해제)"""
        from PyQt6.QtWidgets import QMenu
        
        tab_bar = self.tab_widget.tabBar()
        index = tab_bar.tabAt(position)
        if index < 0:
            return
        
        editor = self.tab_widget.widget(index)
        is_locked = editor.property("locked") or False
        
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #0d1117; color: white; border: 1px solid #ffa500; } QMenu::item:selected { background-color: #ffa500; }")
        
        if is_locked:
            action_lock = menu.addAction("🔓 잠금 해제")
        else:
            action_lock = menu.addAction("🔒 잠금")
        
        action = menu.exec(tab_bar.mapToGlobal(position))
        if action == action_lock:
            self._toggle_lock(index)
    def _toggle_lock(self, index: int):
        """메모 잠금/해제 토글"""
        editor = self.tab_widget.widget(index)
        if not isinstance(editor, QTextEdit):
            return
        
        is_locked = editor.property("locked") or False
        new_locked = not is_locked
        
        editor.setProperty("locked", new_locked)
        editor.setReadOnly(new_locked)
        
        # 탭 제목 업데이트
        current_title = self.tab_widget.tabText(index).replace('🔒 ', '')
        if new_locked:
            self.tab_widget.setTabText(index, f"🔒 {current_title}")
        else:
            self.tab_widget.setTabText(index, current_title)
        
        # 데이터 저장
        memo_id = editor.property("memo_id")
        if memo_id:
            self.schedule_manager.update_memo(memo_id, locked=new_locked)
    
    def _organize_memo_with_ai(self):
        """AI로 현재 메모 내용 정리"""
        index = self.tab_widget.currentIndex()
        if index < 0:
            return
        
        editor = self.tab_widget.widget(index)
        if not isinstance(editor, QTextEdit):
            return
        
        content = editor.toPlainText().strip()
        if not content:
            return
        
        # UI 피드백
        original_text = content
        editor.setPlainText("⏳ AI가 정리 중...")
        editor.setReadOnly(True)
        
        # 백그라운드 스레드에서 AI 호출
        from PyQt6.QtCore import QThread, pyqtSignal
        
        class OrganizeWorker(QThread):
            finished = pyqtSignal(str)
            error = pyqtSignal(str)
            
            def __init__(self, text):
                super().__init__()
                self.text = text
            
            def run(self):
                try:
                    from core.config import client
                    
                    if client is None:
                        self.error.emit("API 키가 설정되지 않았습니다.")
                        return
                    
                    prompt = f"""다음 메모를 깔끔하게 정리해주세요.

규칙:
- 아이콘/이모지 사용 금지
- 간결한 문장으로 정리
- 관련 항목은 그룹화
- 불릿 포인트(-, *) 사용
- 원본의 핵심 내용 유지
- 한국어로 작성

메모 내용:
{self.text}

정리된 결과:"""
                    
                    response = client.models.generate_content(
                        model="models/gemini-2.0-flash",
                        contents=prompt
                    )
                    
                    result = response.text.strip()
                    self.finished.emit(result)
                    
                except Exception as e:
                    self.error.emit(str(e))
        
        def on_finished(result):
            editor.setReadOnly(False)
            editor.setPlainText(result)
            self._save_current_memo()
            self.worker = None
        
        def on_error(error_msg):
            editor.setReadOnly(False)
            editor.setPlainText(original_text)
            from .dialogs import JarvisMessageBox
            JarvisMessageBox.warning(self, "AI 정리 실패", f"오류: {error_msg}")
            self.worker = None
        
        self.worker = OrganizeWorker(content)
        self.worker.finished.connect(on_finished)
        self.worker.error.connect(on_error)
        self.worker.start()

