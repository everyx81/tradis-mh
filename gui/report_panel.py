# -*- coding: utf-8 -*-
"""
REPORT 탭 - 일일 보고서 생성 패널 (실시간 미리보기 + 메일 발송)
왼쪽: 데이터 입력 | 오른쪽: 실시간 서류 미리보기
"""

import os
import sys
import tempfile
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QFrame, QSpinBox, QDateEdit, QMessageBox, QAbstractItemView,
    QTextEdit, QSplitter, QScrollArea, QLineEdit, QFormLayout,
    QCheckBox
)
import json
from PyQt6.QtCore import Qt, QDate, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QTextDocument

from .widgets import NeonButton
from .dialogs import JarvisMessageBox


class ReportPanel(QWidget):
    """일일 보고서 생성 패널 - 실시간 미리보기 + 메일 발송"""
    
    log_signal = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self._delayed_update)
        
        # exe에서도 올바르게 동작하도록 get_run_dir() 사용
        from gui.utils import get_run_dir
        data_dir = os.path.join(get_run_dir(), 'data')
        os.makedirs(data_dir, exist_ok=True)
        self.data_file = os.path.join(data_dir, 'report_data.json')
        
        # 메일 발송 주소 기억
        self.last_mail_to = ""
        self.last_mail_cc = ""
        self._date_checked = False
        
        self.init_ui()
        self._load_data()  # 저장된 데이터 로드
    
    def showEvent(self, event):
        """패널이 표시될 때 저장된 날짜가 과거이면 현재 날짜로 갱신"""
        super().showEvent(event)
        
        current_date = QDate.currentDate()
        saved_date = self.date_edit.date()
        
        # 최초 표시 시, 저장된 날짜가 오늘과 다르면 오늘 날짜로 갱신 (미래 날짜 포함)
        if not self._date_checked:
            if self.date_edit.date() != QDate.currentDate():
                self.date_edit.setDate(QDate.currentDate())
            self._date_checked = True
    
    def init_ui(self):
        """UI 초기화 - 2분할 레이아웃"""
        self.setStyleSheet("background-color: transparent;")
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)
        
        # 타이틀
        title_layout = QHBoxLayout()
        title_label = QLabel("📊 일일 업무 보고서")
        title_label.setStyleSheet("color: #00ffff; font-size: 16pt; font-weight: bold;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        main_layout.addLayout(title_layout)
        
        # === 메인 분할 영역 (입력 | 미리보기) ===
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #00aaaa;
                width: 3px;
            }
        """)
        
        # ========== 왼쪽: 입력 패널 ==========
        left_panel = QWidget()
        left_panel.setStyleSheet("background-color: rgba(5, 15, 30, 100); border-radius: 10px;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(15, 15, 15, 15)
        left_layout.setSpacing(10)
        
        # 헤더
        left_header = QLabel("📝 데이터 입력")
        left_header.setStyleSheet("color: #00cccc; font-weight: bold; font-size: 11pt;")
        left_layout.addWidget(left_header)
        
        # 스크롤 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(12)
        
        # 날짜 + Excel 로드
        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("보고 날짜:"))
        self.date_edit = QDateEdit()
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setStyleSheet(self._get_input_style())
        self.date_edit.dateChanged.connect(self._schedule_update)
        date_row.addWidget(self.date_edit)
        
        self.btn_load_excel = NeonButton("📂 Excel", color="cyan")
        self.btn_load_excel.setFixedSize(70, 28)
        self.btn_load_excel.clicked.connect(self._load_excel)
        date_row.addWidget(self.btn_load_excel)
        date_row.addStretch()
        scroll_layout.addLayout(date_row)
        
        # --- 통관 실적 (2열 레이아웃으로 컴팩트하게) ---
        self._add_section_header(scroll_layout, "📈 통관 실적")
        
        from PyQt6.QtWidgets import QGridLayout
        stats_grid = QGridLayout()
        stats_grid.setSpacing(8)
        
        # 1행: 당일 건수, 당일 수수료
        lbl_daily_count = QLabel("당일 건수:")
        lbl_daily_count.setStyleSheet("color: #aaaaaa;")
        stats_grid.addWidget(lbl_daily_count, 0, 0)
        self.spin_daily_count = self._create_spinbox(0, 9999)
        stats_grid.addWidget(self.spin_daily_count, 0, 1)
        
        lbl_daily_fee = QLabel("당일 수수료(공급가):")
        lbl_daily_fee.setStyleSheet("color: #aaaaaa;")
        stats_grid.addWidget(lbl_daily_fee, 0, 2)
        self.spin_daily_fee = self._create_spinbox(0, 999999999, step=10000)
        stats_grid.addWidget(self.spin_daily_fee, 0, 3)
        
        # 2행: 월 누계 건수, 월 누계 수수료
        lbl_monthly_count = QLabel("월 누계 건수:")
        lbl_monthly_count.setStyleSheet("color: #aaaaaa;")
        stats_grid.addWidget(lbl_monthly_count, 1, 0)
        self.spin_monthly_count = self._create_spinbox(0, 99999)
        stats_grid.addWidget(self.spin_monthly_count, 1, 1)
        
        lbl_monthly_fee = QLabel("월 누계 수수료(공급가):")
        lbl_monthly_fee.setStyleSheet("color: #aaaaaa;")
        stats_grid.addWidget(lbl_monthly_fee, 1, 2)
        self.spin_monthly_fee = self._create_spinbox(0, 999999999, step=100000)
        stats_grid.addWidget(self.spin_monthly_fee, 1, 3)
        
        scroll_layout.addLayout(stats_grid)
        
        # --- 미수금 (헤더 + 버튼 같은 행) ---
        recv_header_row = QHBoxLayout()
        recv_label = QLabel("💰 미수금")
        recv_label.setStyleSheet("color: #00aaaa; font-weight: bold; font-size: 10pt; margin-top: 5px;")
        recv_header_row.addWidget(recv_label)
        recv_header_row.addStretch()
        btn_add_r = NeonButton("+", color="cyan")
        btn_add_r.setFixedSize(28, 22)
        btn_add_r.clicked.connect(lambda: self._add_row(self.table_receivables))
        recv_header_row.addWidget(btn_add_r)
        btn_del_r = NeonButton("-", color="orange")
        btn_del_r.setFixedSize(28, 22)
        btn_del_r.clicked.connect(lambda: self._del_row(self.table_receivables))
        recv_header_row.addWidget(btn_del_r)
        scroll_layout.addLayout(recv_header_row)
        
        self.table_receivables = self._create_data_table(["업체명", "금액", "입금예정일", "확인"])
        scroll_layout.addWidget(self.table_receivables)
        
        # --- 대납금 (헤더 + 버튼 같은 행) ---
        adv_header_row = QHBoxLayout()
        adv_label = QLabel("🏦 대납금")
        adv_label.setStyleSheet("color: #00aaaa; font-weight: bold; font-size: 10pt; margin-top: 5px;")
        adv_header_row.addWidget(adv_label)
        adv_header_row.addStretch()
        
        # Google Sheets에서 가져오기 버튼
        btn_sheets = NeonButton("가져오기", color="green")
        btn_sheets.setFixedSize(80, 22)
        btn_sheets.clicked.connect(self._load_advances_from_sheets)
        adv_header_row.addWidget(btn_sheets)
        
        btn_add_a = NeonButton("+", color="cyan")
        btn_add_a.setFixedSize(28, 22)
        btn_add_a.clicked.connect(lambda: self._add_row(self.table_advances))
        adv_header_row.addWidget(btn_add_a)
        btn_del_a = NeonButton("-", color="orange")
        btn_del_a.setFixedSize(28, 22)
        btn_del_a.clicked.connect(lambda: self._del_row(self.table_advances))
        adv_header_row.addWidget(btn_del_a)
        scroll_layout.addLayout(adv_header_row)
        
        # [MODIFIED] BL 번호 열 추가
        self.table_advances = self._create_data_table(["업체명", "BL 번호", "금액", "입금예정일", "확인"])
        scroll_layout.addWidget(self.table_advances)
        
        # 3. 통관, 인사, 영업 특이사항
        scroll_layout.addWidget(QLabel("📝 통관, 인사, 영업 특이사항"))
        self.text_issues = QTextEdit()
        self.text_issues.setPlaceholderText("특이사항을 입력하세요...")
        self.text_issues.setMinimumHeight(100)
        self.text_issues.setStyleSheet(self._get_input_style())
        self.text_issues.textChanged.connect(self._schedule_update)
        scroll_layout.addWidget(self.text_issues)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        left_layout.addWidget(scroll)
        
        # ========== 오른쪽: 미리보기 패널 ==========
        right_panel = QWidget()
        right_panel.setStyleSheet("background-color: rgba(255, 255, 255, 5); border-radius: 10px;")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(15, 15, 15, 15)
        right_layout.setSpacing(10)
        
        # 헤더
        right_header = QLabel("📄 서류 미리보기")
        right_header.setStyleSheet("color: #00cccc; font-weight: bold; font-size: 11pt;")
        right_layout.addWidget(right_header)
        
        # 미리보기 영역 (HTML 렌더링)
        self.preview_display = QTextEdit()
        self.preview_display.setReadOnly(True)
        self.preview_display.setStyleSheet("""
            QTextEdit {
                background-color: #ffffff;
                border: 2px solid #00aaaa;
                border-radius: 8px;
                color: #333333;
                padding: 15px;
                font-family: 'Malgun Gothic', sans-serif;
                font-size: 10pt;
            }
        """)
        right_layout.addWidget(self.preview_display)
        
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([400, 500])
        
        main_layout.addWidget(splitter, stretch=1)
        
        # ========== 하단 버튼 ==========
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.btn_generate_pdf = NeonButton("📄 PDF 저장", color="cyan")
        self.btn_generate_pdf.setFixedHeight(40)
        self.btn_generate_pdf.clicked.connect(self._generate_pdf)
        btn_layout.addWidget(self.btn_generate_pdf)
        
        self.btn_send_mail = NeonButton("📧 메일 발송", color="cyan")
        self.btn_send_mail.setFixedHeight(40)
        self.btn_send_mail.clicked.connect(self._send_mail)
        btn_layout.addWidget(self.btn_send_mail)
        
        self.btn_clear = NeonButton("🗑️ 초기화", color="orange")
        self.btn_clear.setFixedHeight(40)
        self.btn_clear.clicked.connect(self._clear_all)
        btn_layout.addWidget(self.btn_clear)
        
        main_layout.addLayout(btn_layout)
        
        # 초기 미리보기
        self._update_preview()
    
    def _get_input_style(self) -> str:
        return """
            background-color: rgba(5, 15, 30, 200);
            border: 1px solid #00aaaa;
            border-radius: 5px;
            color: #ffffff;
            padding: 5px;
        """
    
    def _create_spinbox(self, min_val, max_val, step=1) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(min_val, max_val)
        spin.setSingleStep(step)
        spin.setStyleSheet("""
            QSpinBox {
                background-color: rgba(5, 15, 30, 200);
                border: 1px solid #00aaaa;
                border-radius: 5px;
                color: #ffffff;
                padding: 5px;
                min-width: 120px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #00aaaa;
                border: none;
                width: 18px;
            }
        """)
        spin.valueChanged.connect(self._schedule_update)
        return spin
    
    def _add_section_header(self, layout, text: str):
        header = QLabel(text)
        header.setStyleSheet("color: #00aaaa; font-weight: bold; font-size: 10pt; margin-top: 5px;")
        layout.addWidget(header)
    
    def _create_data_table(self, headers) -> QTableWidget:
        table = QTableWidget()
        n_cols = len(headers)
        table.setColumnCount(n_cols)
        table.setHorizontalHeaderLabels(headers)
        table.setMaximumHeight(150)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setStyleSheet("""
            QTableWidget {
                background-color: rgba(5, 15, 30, 200);
                border: 1px solid #555;
                border-radius: 5px;
                color: #ffffff;
                gridline-color: #333;
                font-size: 9pt;
            }
            QTableWidget::item { padding: 3px; }
            QTableWidget::item:selected { background-color: rgba(0, 255, 255, 50); }
            QTableWidget QLineEdit {
                background-color: #0a1929;
                color: #ffffff;
                border: 1px solid #00aaaa;
                padding: 2px;
            }
            QHeaderView::section {
                background-color: #1a2332;
                color: #00ffff;
                padding: 4px;
                border: 1px solid #333;
                font-size: 9pt;
            }
        """)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # 나머지 컬럼은 Fixed
        for i in range(1, n_cols):
            table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            
        if n_cols == 5: # BL 번호 포함 (대납금)
            # 업체명, BL, 금액, 날짜, 확인
            table.setColumnWidth(1, 100) # BL 번호
            table.setColumnWidth(2, 80)  # 금액
            table.setColumnWidth(3, 90)  # 날짜
            table.setColumnWidth(4, 40)  # 확인
            
        else: # 기본 (미수금)
            # 업체명, 금액, 날짜, 확인
            table.setColumnWidth(1, 80)
            table.setColumnWidth(2, 90)
            table.setColumnWidth(3, 40)
            
        table.cellChanged.connect(self._schedule_update)
        return table
    
    def _add_row(self, table: QTableWidget, company="", bl_no="", amount="0", date="", confirmed=False, row_index=None):
        row = table.rowCount()
        table.insertRow(row)
        
        has_bl = (table.columnCount() == 5)
        
        # 0: 업체명
        company_item = QTableWidgetItem(company)
        if row_index is not None:
            company_item.setData(Qt.ItemDataRole.UserRole, row_index)
        table.setItem(row, 0, company_item)
        
        # BL 번호 처리에 따른 인덱스 오프셋
        col_offset = 0
        
        if has_bl:
            # 1: BL 번호
            table.setItem(row, 1, QTableWidgetItem(bl_no))
            col_offset = 1
        
        # 금액
        table.setItem(row, 1 + col_offset, QTableWidgetItem(str(amount)))
        
        # 입금예정일
        date_item = QTableWidgetItem(date)
        table.setItem(row, 2 + col_offset, date_item)
        
        # 확인/상태 (CheckBox)
        chk_widget = QWidget()
        chk_layout = QHBoxLayout(chk_widget)
        chk_layout.setContentsMargins(0, 0, 0, 0)
        chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        chk = QCheckBox()
        chk.setChecked(confirmed)
        chk.setStyleSheet("QCheckBox::indicator { width: 16px; height: 16px; }")
        chk.stateChanged.connect(self._schedule_update)
        
        chk_layout.addWidget(chk)
        table.setCellWidget(row, 3 + col_offset, chk_widget)
        
        self._schedule_update()
    
    def _del_row(self, table: QTableWidget):
        rows = set(item.row() for item in table.selectedItems())
        for row in sorted(rows, reverse=True):
            table.removeRow(row)
        self._schedule_update()
    
    def _schedule_update(self):
        """입력 변경 시 디바운스로 저장 및 미리보기 업데이트"""
        self.update_timer.start(300)
        
    def _delayed_update(self):
        """실제 업데이트 및 저장"""
        self._save_data()
        self._update_preview()
        
    def _save_data(self):
        """데이터 저장 (persist)"""
        data = self._get_report_data()
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Data save failed: {e}")
            
    def _load_data(self):
        """데이터 로드"""
        if not os.path.exists(self.data_file):
            return
            
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # 기본 필드
            if 'daily_count' in data: self.spin_daily_count.setValue(data['daily_count'])
            if 'daily_fee' in data: self.spin_daily_fee.setValue(data['daily_fee'])
            if 'monthly_count' in data: self.spin_monthly_count.setValue(data['monthly_count'])
            if 'monthly_fee' in data: self.spin_monthly_fee.setValue(data['monthly_fee'])
            if 'date' in data:
                try:
                    d = QDate.fromString(data['date'], "yyyy-MM-dd")
                    if d.isValid(): self.date_edit.setDate(d)
                except: pass
            
            # 메일 주소 로드
            self.last_mail_to = data.get('last_mail_to', "")
            self.last_mail_cc = data.get('last_mail_cc', "")
            
            # 특이사항 로드
            if 'issues' in data:
                self.text_issues.setPlainText(data['issues'])
                
            # 테이블 데이터 로드
            self.table_receivables.setRowCount(0)
            for item in data.get('receivables', []):
                self._add_row(
                    self.table_receivables, 
                    company=item.get('company', ''), 
                    amount=item.get('amount', 0),
                    date=item.get('expected_date', ''),
                    confirmed=item.get('is_confirmed', False)
                )
                
            self.table_advances.setRowCount(0)
            for item in data.get('advances', []):
                self._add_row(
                    self.table_advances, 
                    item.get('company', ''), 
                    bl_no=item.get('bl_no', ''), # 저장된 BL 번호 로드
                    amount=item.get('amount', 0),
                    date=item.get('expected_date', ''),
                    confirmed=item.get('is_confirmed', False),
                    row_index=item.get('row_index')  # 행 번호 전달
                )
                
            self._update_preview()
        except Exception as e:
            print(f"Data load failed: {e}")
    
    def _get_report_data(self) -> dict:
        """현재 입력된 데이터 수집"""
        qdate = self.date_edit.date()
        
        receivables = []
        for row in range(self.table_receivables.rowCount()):
            company_item = self.table_receivables.item(row, 0)
            amount_item = self.table_receivables.item(row, 1)
            date_item = self.table_receivables.item(row, 2)
            
            if company_item:
                company = company_item.text().strip()
                try:
                    amount = int(amount_item.text().replace(',', '').replace(' ', '') or '0') if amount_item else 0
                except ValueError:
                    amount = 0
                
                expected_date = date_item.text().strip() if date_item else ""
                
                # CheckBox 상태
                is_confirmed = False
                widget = self.table_receivables.cellWidget(row, 3)
                if widget:
                    chk = widget.findChild(QCheckBox)
                    if chk:
                        is_confirmed = chk.isChecked()
                
                if company:
                    receivables.append({
                        'company': company, 
                        'amount': amount,
                        'expected_date': expected_date,
                        'is_confirmed': is_confirmed
                    })
        
        advances = []
        for row in range(self.table_advances.rowCount()):
            company_item = self.table_advances.item(row, 0)
            amount_item = self.table_advances.item(row, 1)
            date_item = self.table_advances.item(row, 2)
            
            if company_item:
                company = company_item.text().strip()
                
                # BL 번호 (5열인 경우 1번 인덱스)
                current_col = 1
                bl_no = ""
                if self.table_advances.columnCount() == 5:
                    bl_item = self.table_advances.item(row, current_col)
                    bl_no = bl_item.text().strip() if bl_item else ""
                    current_col += 1
                
                amount_item = self.table_advances.item(row, current_col)
                current_col += 1
                date_item = self.table_advances.item(row, current_col)
                current_col += 1 # 확인 체크박스 인덱스로 이동
                
                try:
                    amount = int(amount_item.text().replace(',', '').replace(' ', '') or '0') if amount_item else 0
                except ValueError:
                    amount = 0
                    
                expected_date = date_item.text().strip() if date_item else ""
                
                # CheckBox 상태
                is_confirmed = False
                widget = self.table_advances.cellWidget(row, current_col)
                if widget:
                    chk = widget.findChild(QCheckBox)
                    if chk:
                        is_confirmed = chk.isChecked()
                
                if company:
                    advances.append({
                        'company': company, 
                        'bl_no': bl_no,
                        'amount': amount,
                        'expected_date': expected_date,
                        'is_confirmed': is_confirmed
                    })
        
        return {
            'date': f"{qdate.year()}-{qdate.month():02d}-{qdate.day():02d}",
            'daily_count': self.spin_daily_count.value(),
            'daily_fee': self.spin_daily_fee.value(),
            'monthly_count': self.spin_monthly_count.value(),
            'monthly_fee': self.spin_monthly_fee.value(),
            'receivables': receivables,
            'advances': advances,
            'last_mail_to': self.last_mail_to,
            'last_mail_cc': self.last_mail_cc,
            'issues': self.text_issues.toPlainText()
        }
    
    def _generate_html(self, data: dict) -> str:
        """보고서 HTML 생성 (PDF 스타일 일치)"""
        def fmt(n): return f"{n:,}"
        
        # PDF 색상 및 스타일 상수
        COLOR_PRIMARY = "#1f3a58"
        COLOR_BORDER = "#d0d0d0"
        COLOR_TEXT = "#333333"
        COLOR_HEADER_TEXT = "#ffffff"
        
        STYLE_HEADER_TEXT = "color: #ffffff; font-weight: bold; font-size: 11pt;"
        
        STYLE_SECTION_TITLE = "font-size: 14pt; font-weight: bold; color: #1f3a58; margin-top: 20px; margin-bottom: 10px; border-bottom: 2px solid #1f3a58; padding-bottom: 5px;"
        STYLE_ISSUES = "background-color: #f7fafc; padding: 15px; border: 1px solid #ddd; border-radius: 5px; white-space: pre-wrap; font-size: 10pt; line-height: 1.6; text-align: left;"
        STYLE_SQUARE = "display: inline-block; width: 12px; height: 12px; background-color: #1f3a58; margin-right: 8px;"

        
        # Inline CSS (PDF와 일치)
        STYLE_BODY = "font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; padding: 20px; color: #333; line-height: 1.4; background-color: #ffffff;"
        STYLE_CONTAINER = "max-width: 800px; margin: 0 auto;"
        
        STYLE_H1 = f"color: {COLOR_PRIMARY}; text-align: center; font-size: 22pt; font-weight: normal; margin: 0 0 5px 0;"
        STYLE_DATE = "text-align: right; color: #888888; font-size: 11pt; margin-bottom: 10px;"
        
        # 섹션 헤더 (사각형 블릿 포함) - PDF와 일치
        STYLE_SECTION_TITLE = f"color: {COLOR_PRIMARY}; font-size: 12pt; margin-top: 12px; margin-bottom: 6px; display: flex; align-items: center;"
        STYLE_SQUARE = f"display: inline-block; width: 10px; height: 10px; background-color: {COLOR_PRIMARY}; margin-right: 8px;"
        
        # 굵은 구분선
        STYLE_DIVIDER = f"border-top: 2px solid {COLOR_PRIMARY}; margin-bottom: 10px;"
        
        # 테이블 스타일 - PDF와 일치 (컴팩트)
        STYLE_TABLE = f"width: calc(100% - 4px); border-collapse: collapse; border: 2px solid {COLOR_PRIMARY}; margin-right: 2px;"
        STYLE_TH = f"background-color: {COLOR_PRIMARY}; color: {COLOR_HEADER_TEXT}; padding: 6px; text-align: center; font-size: 10pt; border-right: 1px solid {COLOR_HEADER_TEXT};"
        STYLE_TH_LAST = f"background-color: {COLOR_PRIMARY}; color: {COLOR_HEADER_TEXT}; padding: 6px; text-align: center; font-size: 10pt; border-right: 2px solid {COLOR_PRIMARY};"
        
        STYLE_TD = f"padding: 5px; font-size: 10pt; border-bottom: 1px solid {COLOR_BORDER}; border-right: 1px solid {COLOR_BORDER}; color: {COLOR_TEXT};"
        STYLE_TD_LAST = f"padding: 5px; font-size: 10pt; border-bottom: 1px solid {COLOR_BORDER}; border-right: 2px solid {COLOR_PRIMARY}; color: {COLOR_TEXT};"
        STYLE_TD_CENTER = f"{STYLE_TD} text-align: center;"
        STYLE_TD_CENTER_LAST = f"{STYLE_TD_LAST} text-align: center;"
        # Fix: Use STYLE_TD (has right border) and align right
        STYLE_TD_RIGHT = f"{STYLE_TD} text-align: right;" 
        # For the last column if it needs right alignment (likely not used, but good to have)
        STYLE_TD_RIGHT_LAST = f"{STYLE_TD_LAST} text-align: right;" 
        
        # 테이블이 없는 경우 (텍스트 표시)
        STYLE_NO_DATA = "color: #555; font-size: 11pt; margin-left: 5px;"
        
        # 1. 통관 실적 테이블
        table_stats = f"""
        <table cellspacing="0" cellpadding="0" style="{STYLE_TABLE}">
            <thead>
                <tr>
                    <th width="33%" style="{STYLE_TH}">구분</th>
                    <th width="33%" style="{STYLE_TH}">건수</th>
                    <th width="34%" style="{STYLE_TH_LAST}">수수료(공급가)</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td style="{STYLE_TD_CENTER}">당일 실적</td>
                    <td style="{STYLE_TD_CENTER}">{fmt(data['daily_count'])}건</td>
                    <td style="{STYLE_TD_CENTER_LAST}">{fmt(data['daily_fee'])}원</td>
                </tr>
                <tr>
                    <td style="{STYLE_TD_CENTER} border-bottom: none;">월 누계</td>
                    <td style="{STYLE_TD_CENTER} border-bottom: none;">{fmt(data['monthly_count'])}건</td>
                    <td style="{STYLE_TD_CENTER_LAST} border-bottom: none;">{fmt(data['monthly_fee'])}원</td>
                </tr>
            </tbody>
        </table>
        """
        
        # 2. 미수금 현황
        if data['receivables']:
            rows = ""
            for i, item in enumerate(data['receivables']):
                is_last = (i == len(data['receivables']) - 1)
                border_style = "border-bottom: none;" if is_last else ""
                
                status_char = "■" if item.get('is_confirmed', False) else "□"
                
                rows += f"""
                <tr>
                    <td style="{STYLE_TD_CENTER} {border_style}">{i+1}</td>
                    <td style="{STYLE_TD} {border_style}">{item['company']}</td>
                    <td style="{STYLE_TD_RIGHT} {border_style}">{fmt(item['amount'])}원</td>
                    <td style="{STYLE_TD_CENTER} {border_style}">{item.get('expected_date', '')}</td>
                    <td style="{STYLE_TD_CENTER_LAST} {border_style}">{status_char}</td>
                </tr>"""
                
            # 합계 행 추가
            total_amount = sum(int(item.get('amount', 0)) for item in data['receivables'])
            rows += f"""
            <tr style="background-color: #f7fafc; font-weight: bold;">
                <td style="{STYLE_TD_CENTER} border-bottom: none;"></td>
                <td style="{STYLE_TD_CENTER} border-bottom: none;">합계</td>
                <td style="{STYLE_TD_RIGHT} border-bottom: none;">{fmt(total_amount)}원</td>
                <td style="{STYLE_TD_CENTER} border-bottom: none;"></td>
                <td style="{STYLE_TD_CENTER_LAST} border-bottom: none;"></td>
            </tr>"""
                
            content_receivables = f"""
            <table cellspacing="0" cellpadding="0" style="{STYLE_TABLE}">
                <thead>
                    <tr>
                        <th width="8%" style="{STYLE_TH}">No</th>
                        <th width="37%" style="{STYLE_TH}">업체명</th>
                        <th width="25%" style="{STYLE_TH}">금액</th>
                        <th width="20%" style="{STYLE_TH}">입금예정일</th>
                        <th width="10%" style="{STYLE_TH_LAST}">확인</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>"""
        else:
            content_receivables = f"<div style='{STYLE_NO_DATA}'>해당 항목 없음</div>"
            
        # 3. 대납금 현황
        if data['advances']:
            rows = ""
            for i, item in enumerate(data['advances']):
                is_last = (i == len(data['advances']) - 1)
                border_style = "border-bottom: none;" if is_last else ""
                
                status_char = "■" if item.get('is_confirmed', False) else "□"
                
                # BL 번호 확인
                bl_no_td = ""
                if 'bl_no' in item:
                    bl_no_td = f'<td style="{STYLE_TD} {border_style}">{item["bl_no"]}</td>'
                
                rows += f"""
                <tr>
                    <td style="{STYLE_TD_CENTER} {border_style}">{i+1}</td>
                    <td style="{STYLE_TD} {border_style}">{item['company']}</td>
                    {bl_no_td}
                    <td style="{STYLE_TD_RIGHT} {border_style}">{fmt(item['amount'])}원</td>
                    <td style="{STYLE_TD_CENTER} {border_style}">{item.get('expected_date', '')}</td>
                    <td style="{STYLE_TD_CENTER_LAST} {border_style}">{status_char}</td>
                </tr>"""

            # 합계 행 추가
            total_amount = sum(int(item.get('amount', 0)) for item in data['advances'])
            
            # BL 번호 있으면 빈 셀 하나 더 추가
            bl_empty_td = '<td style="{STYLE_TD_CENTER} border-bottom: none;"></td>' if any('bl_no' in item for item in data['advances']) else ''
            
            rows += f"""
            <tr style="background-color: #f7fafc; font-weight: bold;">
                <td style="{STYLE_TD_CENTER} border-bottom: none;"></td>
                <td style="{STYLE_TD_CENTER} border-bottom: none;">합계</td>
                {bl_empty_td}
                <td style="{STYLE_TD_RIGHT} border-bottom: none;">{fmt(total_amount)}원</td>
                <td style="{STYLE_TD_CENTER} border-bottom: none;"></td>
                <td style="{STYLE_TD_CENTER_LAST} border-bottom: none;"></td>
            </tr>"""
            
            # 헤더 구성 (BL 포함 시 5열)
            if any('bl_no' in item for item in data['advances']):
                adv_headers = f"""
                        <th width="8%" style="{STYLE_TH}">No</th>
                        <th width="27%" style="{STYLE_TH}">업체명</th>
                        <th width="20%" style="{STYLE_TH}">BL 번호</th>
                        <th width="20%" style="{STYLE_TH}">금액</th>
                        <th width="15%" style="{STYLE_TH}">입금예정일</th>
                        <th width="10%" style="{STYLE_TH_LAST}">확인</th>
                """
            else:
                adv_headers = f"""
                        <th width="8%" style="{STYLE_TH}">No</th>
                        <th width="37%" style="{STYLE_TH}">업체명</th>
                        <th width="25%" style="{STYLE_TH}">금액</th>
                        <th width="20%" style="{STYLE_TH}">입금예정일</th>
                        <th width="10%" style="{STYLE_TH_LAST}">확인</th>
                """
                
            content_advances = f"""
            <table cellspacing="0" cellpadding="0" style="{STYLE_TABLE}">
                <thead>
                    <tr>
                        {adv_headers}
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>"""
        else:
            content_advances = f"<div style='{STYLE_NO_DATA}'>해당 항목 없음</div>"
            
        
        # 최종 HTML 조립
        html = f"""
        <html>
        <head>
            <meta charset="utf-8">
        </head>
        <body style="{STYLE_BODY}">
            <div style="{STYLE_CONTAINER}">
                
                <h1 style="{STYLE_H1}">일일 업무 보고서</h1>
                <p style="{STYLE_DATE}">보고일자: {data['date']}</p>
                
                <div style="{STYLE_DIVIDER}"></div>
                
                <div style="{STYLE_SECTION_TITLE}">
                    <span style="{STYLE_SQUARE}"></span>통관 실적
                </div>
                {table_stats}
                
                <div style="{STYLE_SECTION_TITLE}">
                    <span style="{STYLE_SQUARE}"></span>미수금 현황
                </div>
                {content_receivables}
                
                <div style="{STYLE_SECTION_TITLE}">
                    <span style="{STYLE_SQUARE}"></span>대납금 현황
                </div>
                {content_advances}
                
                <div style="{STYLE_SECTION_TITLE}">
                    <span style="{STYLE_SQUARE}"></span>통관, 인사, 영업 특이사항
                </div>
                <div style="{STYLE_ISSUES}" align="left">{data.get('issues', '특이사항 없음').strip() or '특이사항 없음'}</div>
                
                <div style="margin-top: 60px; border-top: 1px solid #aaa; padding-top: 10px; text-align: right; color: #888; font-size: 9pt;">
                    생성일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Daily Report
                </div>
                
            </div>
        </body>
        </html>
        """
        return html
    
    def _update_preview(self):
        """미리보기 업데이트"""
        data = self._get_report_data()
        html = self._generate_html(data)
        self.preview_display.setHtml(html)
        
    def _get_report_dir(self):
        """일일보고 폴더 경로 반환 (실행 파일 기준)"""
        # exe 실행 시 frozen, 아니면 __file__ 기준
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.dirname(__file__))
            
        report_dir = os.path.join(base_dir, '일일보고')
        if not os.path.exists(report_dir):
            os.makedirs(report_dir)
        return report_dir
        
    def _get_pdf_path(self, date_str):
        """날짜 기준 PDF 파일 경로 반환"""
        filename = f"일일보고서_{date_str}.pdf"
        return os.path.join(self._get_report_dir(), filename)

    def _create_pdf(self, data, save_path):
        """PDF 파일 생성 로직 (공통)"""
        
        try:
            from core.report_generator import DailyReportGenerator, DailyReportData
            
            report_data = DailyReportData()
            report_data.report_date = data['date']
            report_data.daily_count = data['daily_count']
            report_data.daily_fee = data['daily_fee']
            report_data.monthly_count = data['monthly_count']
            report_data.monthly_fee = data['monthly_fee']
            report_data.issues = data.get('issues', '')
            
            for item in data['receivables']:
                report_data.add_receivable(item['company'], int(item.get('amount', 0)), item.get('expected_date', ''), item.get('is_confirmed', False))
            for item in data['advances']:
                report_data.add_advance(item['company'], item.get('bl_no', ''), int(item.get('amount', 0)), item.get('expected_date', ''), item.get('is_confirmed', False))
            
            generator = DailyReportGenerator()
            return generator.generate_pdf(report_data, save_path)
        except Exception as e:
            raise e

    def _generate_pdf(self):
        """PDF 저장 (표준 경로)"""
        data = self._get_report_data()
        save_path = self._get_pdf_path(data['date'])
        
        try:
            output_path = self._create_pdf(data, save_path)
            self.log_signal.emit(f"[REPORT] PDF 생성: {output_path}")
            JarvisMessageBox.information(self, "PDF 생성 완료", f"파일이 생성되었습니다:\n{output_path}")
        except Exception as e:
            JarvisMessageBox.critical(self, "오류", f"PDF 생성 실패: {str(e)}")
            self.log_signal.emit(f"[REPORT] PDF 생성 실패: {e}")
    
    def _send_mail(self):
        """메일 발송 (표준 경로 PDF 자동 첨부)"""
        data = self._get_report_data()
        pdf_path = self._get_pdf_path(data['date'])
        
        # 최신 데이터로 PDF 무조건 재생성 (덮어쓰기)
        try:
            self._create_pdf(data, pdf_path)
            self.log_signal.emit(f"[REPORT] PDF 생성 완료: {pdf_path}")
        except Exception as e:
            JarvisMessageBox.critical(self, "오류", f"PDF 생성 실패: {str(e)}")
            return
            
        # 메일 본문 (HTML)
        html_body = self._generate_html(data)
        
        # 텍스트 본문 (간략 버전)
        plain_body = self._generate_plain_text(data)
        
        # 메일 발송 다이얼로그 호출
        from .dialogs import SendMailDialog
        dialog = SendMailDialog(
            parent=self,
            subject=f"일일 업무 보고서 - {data['date']}",
            body=plain_body,
            html_body=html_body,
            attachments=[pdf_path],
            to=self.last_mail_to,
            cc=self.last_mail_cc
        )
        
        if dialog.exec():
            # 성공 시 사용한 주소 저장
            self.last_mail_to = dialog.input_to.text().strip()
            self.last_mail_cc = dialog.input_cc.text().strip()
            self._save_data()
            
            # Google Sheets 보고일자 업데이트
            self._update_sheets_report_date(data['date'])
            
            self.log_signal.emit(f"[REPORT] 메일 발송 완료")
            JarvisMessageBox.information(self, "완료", "메일이 발송되었습니다.")

    def _load_excel(self):
        """Excel 파일 불러오기"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Excel 파일 선택", "", "Excel Files (*.xlsx *.xls)")
        if not file_path:
            return
        
        try:
            from core.report_generator import load_from_excel
            data = load_from_excel(file_path)
            
            self.spin_daily_count.setValue(data.daily_count)
            self.spin_daily_fee.setValue(data.daily_fee)
            self.spin_monthly_count.setValue(data.monthly_count)
            self.spin_monthly_fee.setValue(data.monthly_fee)
            
            self.table_receivables.setRowCount(0)
            for item in data.receivables:
                self._add_row(
                    self.table_receivables, 
                    company=item['company'], 
                    amount=item['amount'],
                    date=item.get('expected_date', ''),
                    confirmed=item.get('is_confirmed', False)
                )
            
            self.table_advances.setRowCount(0)
            for item in data.advances:
                self._add_row(
                    self.table_advances, 
                    company=item['company'], 
                    bl_no=item.get('bl_no', ''),
                    amount=item['amount'],
                    date=item.get('expected_date', ''),
                    confirmed=item.get('is_confirmed', False)
                )
            
            try:
                date_parts = data.report_date.split('-')
                if len(date_parts) == 3:
                    self.date_edit.setDate(QDate(int(date_parts[0]), int(date_parts[1]), int(date_parts[2])))
            except:
                pass
            
            self._schedule_update()
            self.log_signal.emit(f"[REPORT] Excel 로드 완료: {file_path}")
            
        except Exception as e:
            JarvisMessageBox.warning(self, "오류", f"Excel 로드 실패: {str(e)}")
            self.log_signal.emit(f"[REPORT] Excel 로드 실패: {e}")
    
    def _load_advances_from_sheets(self):
        """Google Sheets에서 대납금 데이터 가져오기"""
        try:
            from core.google_sheets import fetch_advances_from_sheet
            
            # 데이터 가져오기
            advances = fetch_advances_from_sheet()
            
            if not advances:
                JarvisMessageBox.information(self, "알림", "Google Sheets에서 가져온 대납금 데이터가 없습니다.")
                return
                
            # 디버그: 첫 번째 항목 확인 (터미널)
            if advances:
                print(f"[DEBUG] First advance item with BL: {advances[0].get('bl_no', 'N/A')}")
            
            # 기존 데이터 덮어쓰기 확인
            if self.table_advances.rowCount() > 0:
                if not JarvisMessageBox.question(
                    self, "확인", 
                    f"기존 대납금 데이터를 Google Sheets 데이터({len(advances)}건)로 교체하시겠습니까?"
                ):
                    return
            
            # 테이블 초기화 및 데이터 추가
            self.table_advances.setRowCount(0)
            for item in advances:
                self._add_row(
                    self.table_advances, 
                    item.get('company', ''), 
                    bl_no=item.get('bl_no', ''), # Google Sheets에서 가져온 BL 번호
                    amount=item.get('amount', 0),
                    date=item.get('expected_date', ''),
                    confirmed=item.get('is_confirmed', False),
                    row_index=item.get('row_index')  # 행 번호 전달
                )
            self._schedule_update()
            self.log_signal.emit(f"[REPORT] Google Sheets에서 대납금 {len(advances)}건 로드 완료")
            JarvisMessageBox.information(self, "완료", f"대납금 {len(advances)}건을 가져왔습니다.")
            
        except FileNotFoundError as e:
            JarvisMessageBox.warning(self, "인증 파일 없음", str(e))
            self.log_signal.emit(f"[REPORT] Sheets 로드 실패: 인증 파일 없음")
        except Exception as e:
            JarvisMessageBox.critical(self, "오류", f"Google Sheets 로드 실패:\n{str(e)}")
            self.log_signal.emit(f"[REPORT] Sheets 로드 실패: {e}")
    
    def _update_sheets_report_date(self, report_date: str):
        """메일 발송 후 Google Sheets의 보고일자 열 업데이트
        
        확인(입금완료) 체크된 항목만 보고일자를 기록함.
        미확인 항목은 다음 보고에도 포함되어야 하므로 보고일자 기록 안 함.
        """
        try:
            from core.google_sheets import update_report_dates
            
            # 대납금 테이블에서 row_index 수집 (확인된 항목만)
            row_indices = []
            for row in range(self.table_advances.rowCount()):
                company_item = self.table_advances.item(row, 0)
                if not company_item:
                    continue
                    
                # 확인 체크박스 상태 확인 (대납금 테이블은 5열, 마지막 열이 확인)
                chk_col = self.table_advances.columnCount() - 1  # 마지막 열
                widget = self.table_advances.cellWidget(row, chk_col)
                is_confirmed = False
                if widget:
                    chk = widget.findChild(QCheckBox)
                    if chk:
                        is_confirmed = chk.isChecked()
                
                # 확인된 항목만 보고일자 업데이트
                if is_confirmed:
                    row_index = company_item.data(Qt.ItemDataRole.UserRole)
                    if row_index is not None:
                        row_indices.append(row_index)
            
            if not row_indices:
                self.log_signal.emit("[REPORT] 업데이트할 Sheets 행 없음 (로컬 데이터만 사용됨)")
                return
            
            # 날짜 포맷 변환 (2026-01-30 -> 1/30)
            try:
                from datetime import datetime
                dt = datetime.strptime(report_date, '%Y-%m-%d')
                formatted_date = f"{dt.month}/{dt.day}"
            except:
                formatted_date = report_date
            
            # 스프레드시트 업데이트
            updated = update_report_dates(row_indices, formatted_date)
            self.log_signal.emit(f"[REPORT] Sheets 보고일자 업데이트: {updated}건 (행: {row_indices})")
            
        except FileNotFoundError:
            # 인증 파일 없으면 무시 (로컬 전용 모드)
            self.log_signal.emit("[REPORT] Sheets 업데이트 생략 (인증 파일 없음)")
        except Exception as e:
            # 업데이트 실패해도 메일 발송은 성공한 것이므로 경고만
            self.log_signal.emit(f"[REPORT] Sheets 보고일자 업데이트 실패: {e}")


    
    def _generate_plain_text(self, data: dict) -> str:
        """텍스트 형식 보고서"""
        def fmt(n): return f"{n:,}"
        
        lines = [
            "=" * 50,
            "           📊 일일 업무 보고서",
            "=" * 50,
            f"보고일자: {data['date']}",
            "",
            "📈 통관 실적",
            "-" * 30,
            f"  당일 건수: {fmt(data['daily_count'])}건",
            f"  당일 수수료(공급가): {fmt(data['daily_fee'])}원",
            f"  월 누계 건수: {fmt(data['monthly_count'])}건",
            f"  월 누계 수수료(공급가): {fmt(data['monthly_fee'])}원",
            "",
            "💰 미수금 현황",
            "-" * 30,
        ]
        
        total_recv = 0
        for item in data['receivables']:
            status = "[확인]" if item.get('is_confirmed') else "[미수]"
            date_str = f" ({item.get('expected_date')})" if item.get('expected_date') else ""
            lines.append(f"  • {item['company']}: {fmt(item['amount'])}원 {date_str} {status}")
            total_recv += item['amount']
        if not data['receivables']:
            lines.append("  (항목 없음)")
        lines.append(f"  합계: {fmt(total_recv)}원")
        
        lines.extend([
            "",
            "🏦 대납금 현황",
            "-" * 30,
        ])
        
        total_adv = 0
        for item in data['advances']:
            status = "[확인]" if item.get('is_confirmed') else "[미확인]"
            date_str = f" ({item.get('expected_date')})" if item.get('expected_date') else ""
            lines.append(f"  • {item['company']}: {fmt(item['amount'])}원 {date_str} {status}")
            total_adv += item['amount']
        if not data['advances']:
            lines.append("  (항목 없음)")
        lines.append(f"  합계: {fmt(total_adv)}원")
        
        lines.extend([
            "",
            "📝 통관, 인사, 영업 특이사항",
            "-" * 30,
            data.get('issues', '특이사항 없음') or '특이사항 없음'
        ])
        
        lines.extend([
            "",
            "=" * 50,
            f"생성: {datetime.now().strftime('%Y-%m-%d %H:%M')} | TRADIS MH",
        ])
        
        return "\n".join(lines)
    
    def _remove_confirmed_items(self) -> int:
        """체크된(입금 확인된) 항목 삭제 후 삭제된 개수 반환"""
        removed_count = 0
        
        # 미수금 테이블에서 체크된 항목 삭제 (역순으로 삭제)
        for row in range(self.table_receivables.rowCount() - 1, -1, -1):
            widget = self.table_receivables.cellWidget(row, 3)
            if widget:
                chk = widget.findChild(QCheckBox)
                if chk and chk.isChecked():
                    self.table_receivables.removeRow(row)
                    removed_count += 1
        
        # 대납금 테이블에서 체크된 항목 삭제 (역순으로 삭제)
        for row in range(self.table_advances.rowCount() - 1, -1, -1):
            widget = self.table_advances.cellWidget(row, 3)
            if widget:
                chk = widget.findChild(QCheckBox)
                if chk and chk.isChecked():
                    self.table_advances.removeRow(row)
                    removed_count += 1
        
        return removed_count
    
    def _clear_all(self):
        """통계 정보만 초기화 (테이블 및 날짜 유지) - 사용자 옵션에 따라 달라질 수 있음"""
        # self.date_edit.setDate(QDate.currentDate()) # 날짜 유지
        self.spin_daily_count.setValue(0)
        self.spin_daily_fee.setValue(0)
        self.spin_monthly_count.setValue(0)
        self.spin_monthly_fee.setValue(0)
        # 테이블은 유지
        self._schedule_update()
