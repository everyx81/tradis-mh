# JARVIS GUI 다이얼로그 및 카드 위젯
"""
다이얼로그 및 카드 위젯:
- IntroWindow: 인트로 애니메이션 창
- GroupCard: 병합 그룹 카드
"""

import os
import sys
import random
import threading

from PyQt6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout, QApplication,
                              QPushButton, QComboBox, QDialog, QMessageBox, QLineEdit, QTextEdit,
                              QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
                              QFormLayout, QHeaderView)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve, QPoint, QParallelAnimationGroup
from PyQt6.QtGui import QPixmap, QImage, QCursor, QColor

from .widgets import GlassFrame, NeonButton
from .utils import resource_path, generate_pdf_thumbnail
from core.config import get_config_path


class IntroWindow(QWidget):
    finished = pyqtSignal()
    
    def __init__(self):
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(0, 0, screen.width(), screen.height())
        
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.lbl_img = QLabel(self)
        self.lbl_img.setStyleSheet("background-color: transparent;")
        path = resource_path("intro_jarvis.jpg")
        if os.path.exists(path):
            pix = QPixmap(path)
            pix = pix.scaled(280, 280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            
            img = pix.toImage()
            img = img.convertToFormat(QImage.Format.Format_ARGB32)
            
            width = img.width()
            height = img.height()
            
            if width > 0 and height > 0:
                bg = img.pixelColor(0, 0)
                bg_r, bg_g, bg_b = bg.red(), bg.green(), bg.blue()
                threshold = 30
                
                ptr = img.bits()
                ptr.setsize(img.sizeInBytes())
                arr = memoryview(ptr).cast('B')
                
                bytes_per_line = img.bytesPerLine()
                
                for y in range(height):
                    row_start = y * bytes_per_line
                    for x in range(width):
                        idx = row_start + x * 4
                        b, g, r, a = arr[idx], arr[idx+1], arr[idx+2], arr[idx+3]
                        
                        diff = abs(r - bg_r) + abs(g - bg_g) + abs(b - bg_b)
                        
                        if diff < threshold:
                            arr[idx+3] = 0
            
            pix = QPixmap.fromImage(img)
            self.lbl_img.setPixmap(pix)
            self.lbl_img.setFixedSize(280, 280)
        else:
            self.lbl_img.setText("TRADIS MH LOADING...")
            self.lbl_img.setStyleSheet("color: cyan; font-size: 30pt; font-weight: bold;")
        
        self.layout.addWidget(self.lbl_img, 0, Qt.AlignmentFlag.AlignCenter)
        
        self.opacity_effect = QGraphicsOpacityEffect(self.lbl_img)
        self.opacity_effect.setOpacity(0.0)
        self.lbl_img.setGraphicsEffect(self.opacity_effect)
        
        QTimer.singleShot(500, self.start_appear)
        
    def start_appear(self):
        self.anim_appear = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim_appear.setDuration(6000)
        self.anim_appear.setStartValue(0.0)
        self.anim_appear.setEndValue(1.0)
        self.anim_appear.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.anim_appear.finished.connect(self.explode)
        self.anim_appear.start()

    def explode(self):
        rect = self.lbl_img.geometry()
        root_x = rect.x()
        root_y = rect.y()
        
        pix = self.lbl_img.pixmap()
        if not pix:
            self.on_finished()
            return
            
        w = pix.width()
        h = pix.height()
        
        self.lbl_img.hide()
        
        rows = 10
        cols = 10
        chunk_w = w // cols
        chunk_h = h // rows
        
        self.anim_group = QParallelAnimationGroup()
        
        self.pieces = []
        
        center_x = root_x + w // 2
        center_y = root_y + h // 2
        
        for r in range(rows):
            for c in range(cols):
                piece_pix = pix.copy(c * chunk_w, r * chunk_h, chunk_w, chunk_h)
                lbl_piece = QLabel(self)
                lbl_piece.setPixmap(piece_pix)
                lbl_piece.setFixedSize(chunk_w, chunk_h)
                
                start_x = root_x + c * chunk_w
                start_y = root_y + r * chunk_h
                lbl_piece.move(start_x, start_y)
                lbl_piece.show()
                
                vec_x = (start_x + chunk_w//2) - center_x
                vec_y = (start_y + chunk_h//2) - center_y
                
                if vec_x == 0 and vec_y == 0:
                    vec_x = random.choice([-1, 1])
                    vec_y = random.choice([-1, 1])
                
                dist = (vec_x**2 + vec_y**2)**0.5
                if dist == 0: dist = 1
                
                target_x = start_x + (vec_x / dist) * 1000 * random.uniform(0.8, 1.2)
                target_y = start_y + (vec_y / dist) * 1000 * random.uniform(0.8, 1.2)
                
                anim_pos = QPropertyAnimation(lbl_piece, b"pos")
                anim_pos.setDuration(1200)
                anim_pos.setStartValue(QPoint(start_x, start_y))
                anim_pos.setEndValue(QPoint(int(target_x), int(target_y)))
                anim_pos.setEasingCurve(QEasingCurve.Type.OutExpo)
                
                self.anim_group.addAnimation(anim_pos)
                self.pieces.append(lbl_piece)
        
        self.anim_group.finished.connect(self.on_finished)
        self.anim_group.start()

    def on_finished(self):
        self.finished.emit()
        self.close()


class GroupCard(GlassFrame):
    def __init__(self, parent_widget, renamer, directory, text_id, data, unclassified, parent=None):
        super().__init__(parent)
        self.renamer = renamer
        self.directory = directory
        self.text_id = text_id
        self.data = data
        self.unclassified = unclassified
        self.parent_widget = parent_widget
        self.mapping = []
        self.marked_files = []  # 마킹된 관련 파일 목록
        
        self.available_pdfs = ['(선택 안 함)'] + sorted(list(self.data['docs'].values())) + sorted(self.unclassified)
        
        # 마킹 데이터 로드 (팝업에서 마킹한 파일)
        if hasattr(parent_widget, 'marked_data') and text_id in parent_widget.marked_data:
            self.marked_files = list(parent_widget.marked_data[text_id])
        
        self.init_ui()
        
    def init_ui(self):
        self.layout = QVBoxLayout(self)
        
        header = QHBoxLayout()
        lbl_header = QLabel(f"ID: {self.text_id} ({self.data['company']})")
        lbl_header.setStyleSheet("color: #00ffff; font-weight: bold; font-size: 10pt;")
        lbl_header.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header.addWidget(lbl_header)
        
        docs = self.data['docs']
        has_statement = "자금정산서" in docs or "정산서" in docs
        is_export_only = not has_statement and any('수출신고필증' in v for v in docs.values())
        is_import_no_settlement = not has_statement and not is_export_only and any('수입신고필증' in v for v in docs.values())
        self.is_export_only = is_export_only
        self.is_archive_only = is_export_only or is_import_no_settlement

        if self.is_archive_only:
            btn_text = "폴더 정리"
        elif has_statement:
            btn_text = "AI ANALYZE"
        else:
            btn_text = "MATCH"

        self.btn_toggle = NeonButton(btn_text, color="cyan")
        self.btn_toggle.setFixedSize(100, 30)
        if self.is_archive_only:
            self.btn_toggle.clicked.connect(self._archive_export_only)
        else:
            self.btn_toggle.clicked.connect(self.start_analysis)
        header.addWidget(self.btn_toggle)
        
        self.layout.addLayout(header)
        
        # 필요 서류 체크리스트 표시
        self.lbl_checklist = QLabel()
        self.lbl_checklist.setStyleSheet("color: #ccc; font-size: 9pt; background: transparent;")
        self.lbl_checklist.setWordWrap(True)
        self.layout.addWidget(self.lbl_checklist)
        
        if is_export_only:
            self.lbl_checklist.setText("✅ 수출신고필증 (정산서 없음 → 바로 폴더 정리)")
        elif is_import_no_settlement:
            doc_list = "\n".join(f"  ✅ {v}" for v in docs.values())
            self.lbl_checklist.setText(f"수입신고필증 (정산서 없음 → 바로 폴더 정리)\n{doc_list}")
        elif has_statement:
            self._update_checklist_basic()
        else:
            summary_text = ", ".join(docs.values())
            self.lbl_checklist.setText(summary_text[:80] + "..." if len(summary_text) > 80 else summary_text)
            
        # [NEW] 금액 100% 매칭 검증 상태 라벨
        self.lbl_amount_check = QLabel()
        self.lbl_amount_check.setStyleSheet("color: #ffaa00; font-size: 9pt; font-weight: bold;")
        self.lbl_amount_check.setWordWrap(True)
        self.lbl_amount_check.hide()
        self.layout.addWidget(self.lbl_amount_check)
        
        # ── 마킹 파일 표시 섹션 ──
        self.marking_widget = QWidget()
        self.marking_layout = QVBoxLayout(self.marking_widget)
        self.marking_layout.setContentsMargins(4, 2, 4, 2)
        self.marking_layout.setSpacing(2)
        self.layout.addWidget(self.marking_widget)
        self._refresh_marking_display()
        
        self.mapping_widget = QWidget()
        self.mapping_layout = QVBoxLayout(self.mapping_widget)
        self.mapping_widget.setVisible(False)
        self.layout.addWidget(self.mapping_widget)
        
        # UI 구성 직후 초기 1회 검증 실행 (마킹된 파일 등 확인)
        self._run_amount_validation()

    def start_analysis(self):
        # Import gemini_ocr at runtime to avoid circular imports
        from auto_rename import gemini_ocr
        
        self.btn_toggle.setText("Running...")
        self.btn_toggle.setEnabled(False)
        self.parent_widget.emit_log(f"Starting Analysis for ID: {self.text_id}")
        
        def run():
            try:
                mode = "수입"
                if "수출신고필증" in self.data['docs']: mode = "수출"
                
                statement_file = self.data['docs'].get("자금정산서") or self.data['docs'].get("정산서")
                
                if statement_file:
                    path = os.path.join(self.directory, statement_file)
                    analysis = gemini_ocr.analyze_statement_for_merge(path)
                    mapping = self.renamer._determine_merge_order(
                        self.directory, statement_file, self.data['docs'], mode, analysis, self.text_id
                    )
                else:
                    mapping = self.renamer._determine_merge_order(
                        self.directory, None, self.data['docs'], mode, None, self.text_id
                    )
                
                self.mapping = mapping
                
                QTimer.singleShot(0, self.refresh_mapping_ui)
                self.parent_widget.log_signal.emit(f"Analysis Complete for {self.text_id}")
            except Exception as e:
                self.parent_widget.log_signal.emit(f"Analysis Error: {e}")
                import traceback
                print(traceback.format_exc())
                
        threading.Thread(target=run, daemon=True).start()

    def _update_checklist_basic(self):
        """캐시된 정산서 분석 결과를 활용하여 비용 항목까지 포함한 체크리스트 표시"""
        docs = self.data['docs']
        is_export = "수출신고필증" in docs
        
        # 기본 필수 서류
        if is_export:
            required = [
                {"name": "자금정산서", "found": "자금정산서" in docs or "정산서" in docs},
                {"name": "수출신고필증", "found": True},
            ]
        else:
            required = [
                {"name": "자금정산서", "found": "자금정산서" in docs or "정산서" in docs},
                {"name": "수입신고필증", "found": "수입신고필증" in docs},
                {"name": "납부고지서", "found": "납부고지서" in docs or any("납부영수증" in v for v in docs.values())},
                {"name": "수입세금계산서", "found": "수입세금계산서" in docs},
            ]
        
        # 캐시에서 정산서 분석 결과 조회 → 비용 항목 추가
        statement_file = docs.get("자금정산서") or docs.get("정산서")
        if statement_file:
            try:
                from auto_rename import gemini_ocr
                statement_path = os.path.join(self.directory, statement_file)
                cached = gemini_ocr._get_cached_result(statement_path)
                if cached:
                    merge_info = cached.get("merge_info", {})
                    expense_list = merge_info.get("expense_items", [])
                    if not expense_list:
                        expense_list = cached.get("expense_items", [])
                    
                    # 비용 항목별로 해당하는 파일이 폴더에 있는지 확인
                    # 같은 키워드의 파일 사용 횟수 추적 (N:N 매칭 지원)
                    from core.constants import EXPENSE_SYNONYMS, FEE_INVOICE_ITEMS, FIXED_SLOT_KEYS
                    from core.validator import parse_amount, build_search_kws
                    used_files = []  # 이미 매칭에 사용된 파일 추적

                    for item_data in expense_list:
                        if not item_data:
                            continue

                        if isinstance(item_data, str):
                            item_name = item_data
                        else:
                            item_name = item_data.get("name", "")

                        if not item_name or any(k in item_name for k in ["관세", "부가세"]):
                            continue

                        # 통관수수료 항목 체크
                        item_clean = item_name.replace(" ", "")
                        is_fee = (item_clean in FEE_INVOICE_ITEMS or
                                 item_name in FEE_INVOICE_ITEMS or
                                 any(fee in item_clean or item_clean in fee
                                     for fee in FEE_INVOICE_ITEMS))
                        if is_fee:
                            found = any(
                                "수수료계산서" in v or "수수료" in v
                                for v in docs.values()
                            )
                            required.append({'name': item_name, 'found': found})
                            continue

                        # 동의어 사전으로 검색 키워드 확장 (양방향)
                        search_kws = build_search_kws(item_name)

                        # 아직 사용 안 된 파일 중에서 키워드 매칭 (1개씩 소비)
                        found = False
                        matched_by_amount = False
                        for v in docs.values():
                            if v in used_files:
                                continue
                            v_upper = v.upper().replace(" ", "")
                            if any(kw in v_upper for kw in search_kws):
                                found = True
                                used_files.append(v)
                                break

                        # billing_items 기반 콘텐츠 매칭 (파일명 키워드 실패 시)
                        if not found:
                            for v in docs.values():
                                fp = os.path.join(self.directory, v)
                                f_cached = gemini_ocr._get_cached_result(fp)
                                if f_cached:
                                    for bi in f_cached.get('billing_items', []):
                                        bi_upper = bi.get('name', '').upper().replace(' ', '')
                                        if any(kw in bi_upper or bi_upper in kw for kw in search_kws):
                                            found = True
                                            break
                                if found:
                                    break

                        # 금액 기반 보정 매칭 (위에서 못 찾은 경우)
                        if not found:
                            item_amt = parse_amount(item_data.get("amount", 0) if isinstance(item_data, dict) else 0)

                            # 고정 슬롯 파일만 제외 (비용 계산서 파일은 금액 매칭 후보에 포함)
                            fixed_slot_files = {docs[key] for key in FIXED_SLOT_KEYS if key in docs}

                            if item_amt > 0:
                                uncl_amounts = {}
                                if os.path.exists(self.directory):
                                    for f in os.listdir(self.directory):
                                        if not f.lower().endswith('.pdf'):
                                            continue
                                        if f in fixed_slot_files or f in used_files:
                                            continue
                                        if "청구서" in f and "계산서" not in f:
                                            continue
                                        fp = os.path.join(self.directory, f)
                                        f_cached = gemini_ocr._get_cached_result(fp)
                                        if f_cached:
                                            f_amt = parse_amount(f_cached.get('total_amount', 0))
                                            if f_amt > 0:
                                                uncl_amounts[f] = f_amt

                                matching_files = [f for f, amt in uncl_amounts.items() if amt == item_amt]
                                if len(matching_files) == 1:
                                    found = True
                                    matched_by_amount = True
                                    used_files.append(matching_files[0])

                        required.append({
                            'name': item_name,
                            'found': found,
                            'matched_by_amount': matched_by_amount
                        })
            except Exception as e:
                print(f"캐시 조회 오류: {e}")
        
        parts = []
        for req in required:
            is_found = req['found']
            if is_found:
                icon = "🔵" if req.get('matched_by_amount') else "✅"
            else:
                icon = "❌"
            parts.append(f"{icon} {req['name']}")
            
        total = len(required)
        checked = sum(1 for req in required if req['found'])
        missing = total - checked
        if missing == 0:
            summary = f"  🎉 전체 {total}개 항목 완료"
        else:
            summary = f"  ⚠️ {total}개 중 {missing}개 미확인"
        self.lbl_checklist.setText("  ".join(parts) + summary)
    
    def _update_checklist_from_mapping(self):
        """AI 분석 후 mapping 기반으로 전체 체크리스트 갱신 (비용 항목 포함)"""
        parts = []
        for item in self.mapping:
            label = item.get('label', '')
            filename = item.get('filename', '')
            # 라벨에서 표시 이름 추출
            if ']' in label:
                name = label.split(']')[-1].strip()
            elif ':' in label:
                name = label.split(':')[-1].strip()
            else:
                name = label
            
            # [NEW] 금액 보정 기반 매칭 아이콘 시각적 차별화 (파랑 = 금액 매칭만)
            is_matched_by_amount = item.get('matched_by_amount', False)
            if filename:
                icon = "🔵" if is_matched_by_amount else "✅"
            else:
                icon = "❌"
                
            # 수수료계산서 포함 항목은 파일이 없어도 ✅ 처리
            if not filename and "포함" in label:
                icon = "✅"
            parts.append(f"{icon} {name}")
        total = len(parts)
        checked = sum(1 for item in self.mapping if item.get('filename', '') or '포함' in item.get('label', ''))
        missing = total - checked
        if missing == 0:
            summary = f"  🎉 전체 {total}개 항목 완료"
        else:
            summary = f"  ⚠️ {total}개 중 {missing}개 미확인"
        self.lbl_checklist.setText("  ".join(parts) + summary)

    def refresh_mapping_ui(self):
        self.mapping_widget.setVisible(True)
        self.btn_toggle.setText("COLLAPSE")
        self.btn_toggle.setEnabled(True)
        try: self.btn_toggle.clicked.disconnect()
        except (RuntimeError, TypeError): pass
        self.btn_toggle.clicked.connect(self.toggle_view)
        
        # AI 분석 결과로 체크리스트 갱신 (비용 항목 포함)
        self._update_checklist_from_mapping()
        
        # 기존 레이아웃 정리
        while self.mapping_layout.count():
            child = self.mapping_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        
        # 파일 매핑 리스트 (▲/▼ 버튼으로 파일 교환)
        self.combo_list = []  # 콤보박스 참조 저장
        
        arrow_btn_style = """
            QPushButton { 
                background: #002233; border: 1px solid #005555; border-radius: 4px; 
                color: #00aaaa; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { background: #003344; border: 1px solid #00aaaa; color: #00ffff; }
            QPushButton:disabled { color: #333; border: 1px solid #222; }
        """
        
        for idx, item in enumerate(self.mapping):
            row_widget = QWidget()
            row_widget.setMinimumHeight(36)
            row_widget.setStyleSheet("""
                QWidget { 
                    background-color: rgba(0, 30, 50, 150); 
                    border: 1px solid #004444; 
                    border-radius: 4px; 
                }
            """)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(8, 4, 8, 4)
            row_layout.setSpacing(6)
            
            # ▲/▼ 버튼
            btn_up = QPushButton("▲")
            btn_up.setFixedSize(22, 22)
            btn_up.setStyleSheet(arrow_btn_style)
            btn_up.setToolTip("파일을 위로 이동")
            btn_up.setEnabled(idx > 0)
            btn_up.clicked.connect(lambda _, i=idx: self._swap_files(i, i - 1))
            row_layout.addWidget(btn_up)
            
            btn_down = QPushButton("▼")
            btn_down.setFixedSize(22, 22)
            btn_down.setStyleSheet(arrow_btn_style)
            btn_down.setToolTip("파일을 아래로 이동")
            btn_down.setEnabled(idx < len(self.mapping) - 1)
            btn_down.clicked.connect(lambda _, i=idx: self._swap_files(i, i + 1))
            row_layout.addWidget(btn_down)
            
            # 콤보박스 (파일 선택)
            combo = QComboBox()
            combo.addItems(self.available_pdfs)
            combo.setMinimumWidth(200)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            combo.wheelEvent = lambda event: event.ignore()
            
            current_file = item.get('filename', '')
            if current_file and current_file in self.available_pdfs:
                combo.setCurrentText(current_file)
            elif current_file:
                combo.addItem(current_file)
                combo.setCurrentText(current_file)
            else:
                combo.setCurrentText('(선택 안 함)')
            
            combo.setToolTip(combo.currentText())
            combo.currentIndexChanged.connect(lambda _, i=idx, c=combo: self.update_mapping(i, c))
            combo.currentTextChanged.connect(lambda text, c=combo: c.setToolTip(text))
            combo.setStyleSheet("""
                QComboBox {
                    background-color: #001122;
                    color: #00ffff;
                    border: 1px solid #00aaaa;
                    border-radius: 4px;
                    padding: 4px 8px;
                    min-width: 180px;
                    font-size: 10pt;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 20px;
                }
                QComboBox::down-arrow {
                    image: none;
                    border-left: 5px solid transparent;
                    border-right: 5px solid transparent;
                    border-top: 6px solid #00aaaa;
                    margin-right: 5px;
                }
                QComboBox QAbstractItemView {
                    background-color: #001122;
                    color: #00ffff;
                    selection-background-color: #00aaaa;
                    selection-color: #ffffff;
                    border: 1px solid #00aaaa;
                }
                QToolTip {
                    background-color: #001122;
                    color: #00ffff;
                    border: 1px solid #00aaaa;
                    padding: 5px;
                    font-size: 9pt;
                }
            """)
            row_layout.addWidget(combo, stretch=1)
            self.combo_list.append(combo)
            
            btn_preview = QPushButton("🔍")
            btn_preview.setFixedSize(26, 26)
            btn_preview.setStyleSheet("""
                QPushButton { background: #002233; border: 1px solid #005555; border-radius: 4px; }
                QPushButton:hover { background: #003344; border: 1px solid #00aaaa; }
            """)
            btn_preview.setToolTip("📄 파일 미리보기")
            btn_preview.clicked.connect(lambda _, c=combo: self._show_thumbnail_popup(c.currentText()))
            row_layout.addWidget(btn_preview)
            
            lbl = QLabel(f"➡ {item['label']}")
            
            # 매칭 상태에 따른 라벨 색상 분기
            has_file = bool(item.get('filename', ''))
            is_included = '포함' in item['label']
            if item.get('matched_by_amount', False):
                lbl.setStyleSheet("color: #00BFFF; background: transparent; font-weight: bold;")
                lbl.setToolTip("총금액 비교로 매칭되었습니다.")
            elif not has_file and not is_included:
                lbl.setStyleSheet("color: #ff4444; background: transparent; font-weight: bold;")
                lbl.setToolTip("계산서 매칭 안 됨")
            elif is_included:
                lbl.setStyleSheet("color: #00aaaa; background: transparent;")
            else:
                lbl.setStyleSheet("color: #00ffff; background: transparent;")
                
            lbl.setMinimumWidth(120)
            row_layout.addWidget(lbl)
            
            self.mapping_layout.addWidget(row_widget)
        
        self.mapping_layout.setSpacing(2)
        self.mapping_layout.setContentsMargins(0, 0, 0, 0)
        
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_add_row = NeonButton("+ ADD ROW", color="cyan")
        btn_add_row.clicked.connect(self.add_unclassified_row)
        btn_row.addWidget(btn_add_row)
            
        btn_exec = NeonButton("MERGE EXECUTE", color="cyan", is_primary=True)
        btn_exec.clicked.connect(self.execute_merge)
        btn_row.addWidget(btn_exec)
        self.mapping_layout.addLayout(btn_row)
        
        # 맵핑 UI 새로고침(또는 AI 분석) 후 자동 검증 실행
        self._run_amount_validation()
    
    def _swap_files(self, idx_a, idx_b):
        """두 행의 파일명(콤보박스 값)만 교환, 라벨은 고정"""
        if 0 <= idx_a < len(self.mapping) and 0 <= idx_b < len(self.mapping):
            # mapping 데이터 교환
            self.mapping[idx_a]['filename'], self.mapping[idx_b]['filename'] = \
                self.mapping[idx_b]['filename'], self.mapping[idx_a]['filename']
            
            # 콤보박스 UI 업데이트 (UI 전체 갱신 없이 빠르게)
            combo_a = self.combo_list[idx_a]
            combo_b = self.combo_list[idx_b]
            
            file_a = self.mapping[idx_a]['filename'] or '(선택 안 함)'
            file_b = self.mapping[idx_b]['filename'] or '(선택 안 함)'
            
            # 시그널 임시 차단
            combo_a.blockSignals(True)
            combo_b.blockSignals(True)
            
            combo_a.setCurrentText(file_a)
            combo_b.setCurrentText(file_b)
            
            combo_a.blockSignals(False)
            combo_b.blockSignals(False)
            
            # 체크리스트 및 검증 갱신
            self._update_checklist_from_mapping()
            self._run_amount_validation()

    def move_row(self, idx, direction):
        new_idx = idx + direction
        if 0 <= new_idx < len(self.mapping):
            self.mapping[idx], self.mapping[new_idx] = self.mapping[new_idx], self.mapping[idx]
            self.refresh_mapping_ui()

    def update_mapping(self, idx, combo):
        val = combo.currentText()
        if val == '(선택 안 함)': val = ""
        self.mapping[idx]['filename'] = val
        self._update_checklist_from_mapping()
        self._run_amount_validation()

    def add_unclassified_row(self):
        self.mapping.append({'label': '[추가] 미분류 서류', 'filename': ''})
        self.refresh_mapping_ui()

    def toggle_view(self):
        is_visible = self.mapping_widget.isVisible()
        self.mapping_widget.setVisible(not is_visible)
        self.btn_toggle.setText("EXPAND" if is_visible else "COLLAPSE")
    
    def _refresh_marking_display(self):
        """마킹된 파일 목록을 카드에 표시/갱신"""
        # 기존 위젯 정리
        while self.marking_layout.count():
            child = self.marking_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        if not self.marked_files:
            # 마킹 없으면 빈 위젯 유지하되 파일 추가 버튼은 표시
            self.marking_widget.setVisible(True)
            # 폴더 정리 버튼 텍스트 원복
            if self.is_export_only and hasattr(self, 'btn_toggle'):
                self.btn_toggle.setText("폴더 정리")
            
            # 기존과 동일한 파일 추가 버튼 표시
            btn_add = NeonButton("📂 파일 추가", color="orange")
            btn_add.setFixedHeight(26)
            btn_add.setFixedWidth(110)
            btn_add.clicked.connect(self._add_marking_files)
            self.marking_layout.addWidget(btn_add)
            return
        
        self.marking_widget.setVisible(True)
        
        # 폴더 정리 버튼에 파일 수 표시
        if self.is_export_only and hasattr(self, 'btn_toggle'):
            self.btn_toggle.setText(f"폴더 정리 ({len(self.marked_files)})")
        
        # 헤더
        lbl = QLabel(f"📎 관련 파일 ({len(self.marked_files)}):")
        lbl.setStyleSheet("color: #ffaa44; font-size: 9pt; font-weight: bold; background: transparent;")
        self.marking_layout.addWidget(lbl)
        
        # 각 마킹 파일
        for idx, finfo in enumerate(self.marked_files):
            row = QHBoxLayout()
            row.setSpacing(4)
            
            file_lbl = QLabel(f"  ✅ {finfo.get('icon', '📄')} {finfo['name']}")
            file_lbl.setStyleSheet("color: #00cc66; font-size: 9pt; background: transparent;")
            file_lbl.setToolTip(finfo.get('path', ''))
            row.addWidget(file_lbl, stretch=1)
            
            btn_remove = QPushButton("❌")
            btn_remove.setFixedSize(22, 22)
            btn_remove.setStyleSheet("""
                QPushButton { background: transparent; border: none; font-size: 10px; }
                QPushButton:hover { background: rgba(255, 50, 50, 80); border-radius: 4px; }
            """)
            btn_remove.setToolTip("마킹 제거")
            btn_remove.clicked.connect(lambda _, i=idx: self._remove_marking_file(i))
            row.addWidget(btn_remove)
            
            row_widget = QWidget()
            row_widget.setLayout(row)
            row_widget.setStyleSheet("background: transparent;")
            self.marking_layout.addWidget(row_widget)
        
        # 파일 추가 버튼
        btn_add = NeonButton("📂 파일 추가", color="orange")
        btn_add.setFixedHeight(26)
        btn_add.setFixedWidth(110)
        btn_add.clicked.connect(self._add_marking_files)
        self.marking_layout.addWidget(btn_add)
    
    def _add_marking_files(self):
        """파일 대화상자로 마킹 파일 추가"""
        from PyQt6.QtWidgets import QFileDialog
        
        export_docs_root = ''
        if hasattr(self.parent_widget, 'archiver'):
            export_docs_root = getattr(self.parent_widget.archiver, 'export_docs_root', '')
        
        start_dir = export_docs_root if export_docs_root and os.path.exists(export_docs_root) else ""
        
        files, _ = QFileDialog.getOpenFileNames(
            self, "관련 파일 선택", start_dir,
            "All Files (*.*);;PDF (*.pdf);;Excel (*.xlsx *.xls);;Images (*.jpg *.png *.bmp)"
        )
        
        if files:
            from core.open_file_detector import get_file_type_icon
            for f in files:
                name = os.path.basename(f)
                # 중복 확인
                if any(mf['name'] == name for mf in self.marked_files):
                    continue
                self.marked_files.append({'name': name, 'path': f, 'icon': get_file_type_icon(name)})
            self._refresh_marking_display()
            self._run_amount_validation()
    
    def _remove_marking_file(self, index):
        """마킹 파일 제거"""
        if 0 <= index < len(self.marked_files):
            removed = self.marked_files.pop(index)
            self.parent_widget.emit_log(f"[마킹 제거] {removed['name']}")
            self._refresh_marking_display()
            self._run_amount_validation()

    
    def _show_thumbnail_popup(self, filename):
        if not filename or filename == '(선택 안 함)':
            JarvisMessageBox.information(self, "미리보기", "파일을 먼저 선택해주세요.")
            return
        
        pdf_path = os.path.join(self.directory, filename)
        if not os.path.exists(pdf_path):
            JarvisMessageBox.warning(self, "오류", f"파일을 찾을 수 없습니다:\n{filename}")
            return
        
        pixmap = generate_pdf_thumbnail(pdf_path, 600, 840)  # 크기 확대
        if not pixmap:
            JarvisMessageBox.warning(self, "오류", "썸네일 생성에 실패했습니다.")
            return
        
        popup = QDialog(self)
        popup.setWindowTitle(f"미리보기: {filename}")
        popup.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        popup.setStyleSheet("background-color: #0d1117; border: 2px solid #00ffff; border-radius: 10px;")
        
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(10, 10, 10, 10)
        
        lbl_img = QLabel()
        lbl_img.setPixmap(pixmap)
        lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_img)
        
        lbl_name = QLabel(filename)
        lbl_name.setStyleSheet("color: #00ffff; font-size: 9pt; padding: 5px;")
        lbl_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_name)
        
        btn_close = NeonButton("닫기", color="cyan")
        btn_close.clicked.connect(popup.close)
        layout.addWidget(btn_close)
        
        popup.adjustSize()
        cursor_pos = QCursor.pos()
        popup.move(cursor_pos.x() - popup.width() // 2, cursor_pos.y() - popup.height() // 2)
        popup.exec()
        
    def _archive_export_only(self):
        """정산서 없는 수출/수입건: 신고필증 아카이빙 + 관련 파일 수집"""
        docs = self.data['docs']
        archive_files = [v for v in docs.values()]
        if not archive_files:
            return

        parent = self.parent_widget
        # 수입/수출 자동 구분
        if any('수입신고필증' in v for v in docs.values()):
            doc_label = "수입신고필증"
            log_prefix = "수입"
        else:
            doc_label = "수출신고필증"
            log_prefix = "수출"
        output_name = f"{self.data['company']}({self.text_id}){doc_label}.pdf"
        marked = list(self.marked_files)  # 마킹된 파일 복사

        # 마킹 파일 경로 재검증
        if marked:
            export_docs_root = getattr(parent.archiver, 'export_docs_root', '') if hasattr(parent, 'archiver') else ''
            search_dirs = [sd for sd in [export_docs_root, self.directory] if sd and os.path.exists(sd)]

            missing_files = []
            for mf in marked:
                src_path = mf.get('path', '')
                if src_path and os.path.exists(src_path):
                    continue
                # 경로가 유효하지 않으면 자동 검색 시도
                file_name = mf.get('name', '')
                if file_name:
                    from core.open_file_detector import find_file_path
                    found = find_file_path(file_name, search_dirs)
                    if found:
                        mf['path'] = found
                        parent.emit_log(f"[마킹 경로 갱신] {file_name} → {found}")
                    else:
                        missing_files.append(mf)

            # 경로를 찾을 수 없는 파일이 있으면 경고 다이얼로그
            if missing_files:
                resolved = self._show_missing_files_dialog(missing_files, export_docs_root)
                if not resolved:
                    return  # 사용자가 취소

        def run_archive():
            export_docs_root = getattr(parent.archiver, 'export_docs_root', '') if hasattr(parent, 'archiver') else ''
            self.renamer.execute_merge_task(self.directory, output_name, archive_files,
                                           export_docs_root=export_docs_root, marked_files=marked)
            parent.merge_complete_signal.emit()

        threading.Thread(target=run_archive, daemon=True).start()
        parent.emit_log(f"[{log_prefix}] {self.text_id} 폴더 정리 + 관련 파일 수집 중... (마킹 {len(marked)}개)")
        # 마킹 데이터 정리
        if hasattr(parent, 'marked_data') and self.text_id in parent.marked_data:
            del parent.marked_data[self.text_id]
        self.deleteLater()

    def _show_missing_files_dialog(self, missing_files, export_docs_root=""):
        """마킹 파일 경로를 찾을 수 없을 때 경고 다이얼로그 표시

        Returns:
            True: 모든 파일 해결됨 또는 사용자가 무시하고 진행
            False: 사용자가 취소
        """
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog
        from PyQt6.QtCore import Qt
        from core.open_file_detector import get_file_type_icon

        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        from PyQt6.QtGui import QFont

        dlg = QDialog(self)
        dlg.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dlg.setMinimumWidth(480)

        # 메인 컨테이너 (JarvisMessageBox와 동일한 Frosted Glass 스타일)
        container = QWidget(dlg)
        container.setObjectName("missing_files_container")
        container.setStyleSheet("""
            #missing_files_container {
                background-color: rgba(45, 50, 60, 230);
                border: 1px solid rgba(100, 110, 120, 0.5);
                border-radius: 20px;
            }
        """)

        shadow = QGraphicsDropShadowEffect(dlg)
        shadow.setBlurRadius(30)
        shadow.setXOffset(0)
        shadow.setYOffset(5)
        shadow.setColor(Qt.GlobalColor.black)
        container.setGraphicsEffect(shadow)

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 28, 24, 20)
        layout.setSpacing(12)

        # 경고 헤더
        lbl_warn = QLabel(f"파일 경로를 찾을 수 없습니다")
        lbl_warn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_warn.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        lbl_warn.setStyleSheet("color: #ffffff; background: transparent;")
        lbl_warn.setWordWrap(True)
        layout.addWidget(lbl_warn)

        lbl_sub = QLabel(f"{len(missing_files)}개 마킹 파일의 위치를 확인해 주세요")
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_sub.setFont(QFont("Segoe UI", 10))
        lbl_sub.setStyleSheet("color: rgba(255, 255, 255, 0.7); background: transparent;")
        lbl_sub.setWordWrap(True)
        layout.addWidget(lbl_sub)

        layout.addSpacing(6)

        # 파일 목록 + 개별 찾기 버튼
        file_rows = {}
        for mf in missing_files:
            row = QHBoxLayout()
            row.setSpacing(10)

            icon = mf.get('icon', '📁')
            name = mf.get('name', '?')
            lbl_name = QLabel(f"{icon} {name}")
            lbl_name.setFont(QFont("Segoe UI", 10))
            lbl_name.setStyleSheet("color: #ff8888; background: transparent;")
            lbl_name.setWordWrap(True)
            row.addWidget(lbl_name, 1)

            lbl_status = QLabel("❌")
            lbl_status.setFont(QFont("Segoe UI", 10))
            lbl_status.setStyleSheet("color: #ff6666; background: transparent;")
            lbl_status.setFixedWidth(28)
            row.addWidget(lbl_status)

            btn_find = QPushButton("찾기")
            btn_find.setFixedHeight(34)
            btn_find.setMinimumWidth(70)
            btn_find.setFont(QFont("Segoe UI", 10))
            btn_find.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_find.setStyleSheet("""
                QPushButton {
                    background-color: rgba(30, 35, 45, 200);
                    border: 2px solid #00d4ff;
                    border-radius: 12px;
                    color: #00d4ff;
                    padding: 4px 14px;
                }
                QPushButton:hover {
                    background-color: rgba(0, 212, 255, 40);
                    border: 2px solid #00ffff;
                    color: #00ffff;
                }
            """)
            row.addWidget(btn_find)

            file_rows[mf['name']] = (lbl_status, lbl_name, mf)

            def make_find_handler(target_mf, status_lbl, name_lbl):
                def handler():
                    start = export_docs_root if export_docs_root and os.path.exists(export_docs_root) else ""
                    path, _ = QFileDialog.getOpenFileName(dlg, f"'{target_mf['name']}' 파일 선택", start)
                    if path:
                        target_mf['path'] = path
                        status_lbl.setText("✅")
                        status_lbl.setStyleSheet("color: #44ff44; background: transparent;")
                        name_lbl.setStyleSheet("color: #44ff44; background: transparent;")
                return handler

            btn_find.clicked.connect(make_find_handler(mf, lbl_status, lbl_name))
            layout.addLayout(row)

        layout.addSpacing(10)

        # 버튼 영역
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        btn_cancel = QPushButton("취소")
        btn_cancel.setFixedHeight(42)
        btn_cancel.setMinimumWidth(100)
        btn_cancel.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: rgba(100, 105, 115, 180);
                border: 1px solid rgba(150, 155, 165, 0.5);
                border-radius: 12px;
                color: #ffffff;
                padding: 8px 20px;
            }
            QPushButton:hover { background-color: rgba(120, 125, 135, 200); }
            QPushButton:pressed { background-color: rgba(80, 85, 95, 200); }
        """)
        btn_cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_cancel)

        btn_ok = QPushButton("진행")
        btn_ok.setFixedHeight(42)
        btn_ok.setMinimumWidth(120)
        btn_ok.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: rgba(30, 35, 45, 200);
                border: 2px solid #00d4ff;
                border-radius: 12px;
                color: #00d4ff;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: rgba(0, 212, 255, 40);
                border: 2px solid #00ffff;
                color: #00ffff;
            }
            QPushButton:pressed { background-color: rgba(0, 212, 255, 80); }
        """)

        def on_ok():
            # 경로가 여전히 없는 파일은 marked_files에서 제거
            for name_key, (_, _, mf_ref) in file_rows.items():
                p = mf_ref.get('path', '')
                if not p or not os.path.exists(p):
                    if mf_ref in self.marked_files:
                        self.marked_files.remove(mf_ref)
            dlg.accept()

        btn_ok.clicked.connect(on_ok)
        btn_row.addWidget(btn_ok)

        layout.addLayout(btn_row)

        result = dlg.exec()
        return result == QDialog.DialogCode.Accepted

    def execute_merge(self):
        final_files = list(dict.fromkeys(m['filename'] for m in self.mapping if m['filename']))
        if not final_files: return
        output_name = f"{self.data['company']}({self.text_id})정산서.pdf"

        parent = self.parent_widget
        marked = list(self.marked_files) if self.marked_files else None

        # 마킹 파일 경로 재검증
        if marked:
            export_docs_root = getattr(parent.archiver, 'export_docs_root', '') if hasattr(parent, 'archiver') else ''
            search_dirs = [sd for sd in [export_docs_root, self.directory] if sd and os.path.exists(sd)]

            missing_files = []
            for mf in marked:
                src_path = mf.get('path', '')
                if src_path and os.path.exists(src_path):
                    continue
                file_name = mf.get('name', '')
                if file_name:
                    from core.open_file_detector import find_file_path
                    found = find_file_path(file_name, search_dirs)
                    if found:
                        mf['path'] = found
                        parent.emit_log(f"[마킹 경로 갱신] {file_name} → {found}")
                    else:
                        missing_files.append(mf)

            if missing_files:
                resolved = self._show_missing_files_dialog(missing_files, export_docs_root)
                if not resolved:
                    return

        def run_merge():
            export_docs_root = getattr(parent.archiver, 'export_docs_root', '') if hasattr(parent, 'archiver') else ''
            self.renamer.execute_merge_task(self.directory, output_name, final_files,
                                           export_docs_root=export_docs_root, marked_files=marked)
            parent.merge_complete_signal.emit()

        threading.Thread(target=run_merge, daemon=True).start()

        parent.emit_log(f"Merging {len(final_files)} files...")
        # 마킹 데이터 정리
        if marked and hasattr(parent, 'marked_data') and self.text_id in parent.marked_data:
            del parent.marked_data[self.text_id]
        self.deleteLater()

    def _run_amount_validation(self):
        """항목별 1:1 금액 비교 + 전체 합산 비교 2단계 검증"""
        if not self.mapping:
            # 매핑 없으면 비용 항목이 있는 항목이 있는지만 간단 체크
            has_expense = any('비용: ' in item.get('label', '') for item in self.mapping) if self.mapping else False
            if not has_expense:
                self.lbl_amount_check.hide()
                return

        # 비용 항목이 하나라도 있는지 확인
        has_expense_items = any('비용: ' in item.get('label', '') for item in self.mapping)
        if not has_expense_items:
            self.lbl_amount_check.hide()
            return

        self.lbl_amount_check.setText("⏳ 금액 검증 중...")
        self.lbl_amount_check.setStyleSheet("color: #aaaaaa; font-size: 9pt;")
        self.lbl_amount_check.show()

        if hasattr(self, '_validator_worker'):
            try:
                self._validator_worker.finished.disconnect()
            except (RuntimeError, TypeError):
                pass

        from PyQt6.QtCore import QThread, pyqtSignal

        class ValidatorWorker(QThread):
            finished = pyqtSignal(dict)
            def __init__(self, mapping, directory):
                super().__init__()
                self.mapping = mapping
                self.directory = directory

            def run(self):
                import sys
                core_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
                if core_path not in sys.path:
                    sys.path.insert(0, core_path)
                try:
                    from core.validator import validate_mapping_amounts
                    res = validate_mapping_amounts(self.mapping, self.directory)
                except Exception as e:
                    print("validator error:", e)
                    res = {}
                self.finished.emit(res)

        self._validator_worker = ValidatorWorker(list(self.mapping), self.directory)

        def _on_validated(res):
            try:
                item_all = res.get('item_all_matched', True)
                sum_matched = res.get('sum_matched', True)
                details = res.get('item_details', [])
                sum_items = res.get('sum_items', 0)
                sum_files = res.get('sum_files', 0)

                if item_all and sum_matched:
                    self.lbl_amount_check.setText("🟢 항목별/합산 금액 검증 완료")
                    self.lbl_amount_check.setStyleSheet("color: #00ff00; font-size: 9pt; font-weight: bold;")
                elif not item_all and sum_matched:
                    # 항목별 불일치이나 합산은 맞음 → OCR 오류 가능성
                    mismatched = [d for d in details if not d.get('matched') and not d.get('no_file')]
                    names = [d['label'].split('비용: ')[-1] for d in mismatched[:3]]
                    names_str = ", ".join(names)
                    if len(mismatched) > 3:
                        names_str += f" 외 {len(mismatched)-3}건"
                    self.lbl_amount_check.setText(f"🟡 {names_str} 금액 불일치 (합산은 일치)")
                    self.lbl_amount_check.setStyleSheet("color: #ffaa00; font-size: 9pt; font-weight: bold;")
                elif item_all and not sum_matched:
                    diff = abs(sum_items - sum_files)
                    self.lbl_amount_check.setText(f"🟡 합산 불일치 (차이: {diff:,}원)")
                    self.lbl_amount_check.setStyleSheet("color: #ffaa00; font-size: 9pt; font-weight: bold;")
                else:
                    mismatched = [d for d in details if not d.get('matched') and not d.get('no_file')]
                    diff = abs(sum_items - sum_files)
                    names = [d['label'].split('비용: ')[-1] for d in mismatched[:2]]
                    names_str = ", ".join(names)
                    if len(mismatched) > 2:
                        names_str += f" 외 {len(mismatched)-2}건"
                    self.lbl_amount_check.setText(f"🔴 {names_str} 금액 불일치, 합산 차이 {diff:,}원")
                    self.lbl_amount_check.setStyleSheet("color: #ff4444; font-size: 9pt; font-weight: bold;")
            except Exception:
                pass

        self._validator_worker.finished.connect(_on_validated)
        self._validator_worker.start()


class JarvisMessageBox(QDialog):
    """iOS 스타일 커스텀 메시지 박스 (Frosted Glass)"""
    
    # 아이콘 타입 상수
    Information = "info"
    Warning = "warning"
    Critical = "critical"
    Question = "question"
    
    def __init__(self, parent=None, title="Notification", message="", icon_type="info"):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(340)

        self.result_value = None
        self.icon_type = icon_type
        self.title_text = title
        self.message_text = message
        self.buttons = []
        
        self.init_ui()
        
    def init_ui(self):
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        from PyQt6.QtGui import QFont
        
        # 메인 컨테이너 (iOS Frosted Glass 스타일)
        self.container = QWidget(self)
        self.container.setObjectName("ios_alert_container")
        self.container.setStyleSheet("""
            #ios_alert_container {
                background-color: rgba(45, 50, 60, 230);
                border: 1px solid rgba(100, 110, 120, 0.5);
                border-radius: 20px;
            }
        """)
        
        # 그림자 효과
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setXOffset(0)
        shadow.setYOffset(5)
        shadow.setColor(Qt.GlobalColor.black)
        self.container.setGraphicsEffect(shadow)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self.container)
        
        inner_layout = QVBoxLayout(self.container)
        inner_layout.setContentsMargins(24, 28, 24, 20)
        inner_layout.setSpacing(12)
        
        # 타이틀 (중앙 정렬, 굵은 흰색)
        lbl_title = QLabel(self.title_text)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        lbl_title.setStyleSheet("""
            color: #ffffff;
            background: transparent;
        """)
        inner_layout.addWidget(lbl_title)
        
        # 메시지 (중앙 정렬, 연한 회색)
        lbl_message = QLabel(self.message_text)
        lbl_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_message.setWordWrap(True)
        lbl_message.setFont(QFont("Segoe UI", 10))
        lbl_message.setStyleSheet("""
            color: rgba(255, 255, 255, 0.7);
            background: transparent;
            padding: 0 10px;
        """)
        inner_layout.addWidget(lbl_message)
        
        inner_layout.addSpacing(10)
        
        # 버튼 영역
        self.btn_widget = QWidget()
        self.btn_widget.setStyleSheet("background: transparent;")
        self.btn_layout = QHBoxLayout(self.btn_widget)
        self.btn_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_layout.setSpacing(12)
        
        inner_layout.addWidget(self.btn_widget)
        
    def add_button(self, text, role="accept", color="cyan"):
        """iOS 스타일 버튼 추가"""
        from PyQt6.QtGui import QFont
        
        btn = QPushButton(text)
        btn.setFixedHeight(42)
        btn.setMinimumWidth(120)
        btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        if color == "cyan":
            # OK 버튼 - 시안 글로우 효과
            btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(30, 35, 45, 200);
                    border: 2px solid #00d4ff;
                    border-radius: 12px;
                    color: #00d4ff;
                    padding: 8px 20px;
                }
                QPushButton:hover {
                    background-color: rgba(0, 212, 255, 40);
                    border: 2px solid #00ffff;
                    color: #00ffff;
                }
                QPushButton:pressed {
                    background-color: rgba(0, 212, 255, 80);
                }
            """)
        else:
            # Cancel 버튼 - 회색
            btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(100, 105, 115, 180);
                    border: 1px solid rgba(150, 155, 165, 0.5);
                    border-radius: 12px;
                    color: #ffffff;
                    padding: 8px 20px;
                }
                QPushButton:hover {
                    background-color: rgba(120, 125, 135, 200);
                }
                QPushButton:pressed {
                    background-color: rgba(80, 85, 95, 200);
                }
            """)
        
        if role == "accept":
            btn.clicked.connect(self.accept)
        elif role == "reject":
            btn.clicked.connect(self.reject)
        else:
            btn.clicked.connect(lambda: self._set_result_and_close(role))
        
        self.btn_layout.addWidget(btn)
        self.buttons.append(btn)
        return btn
        
    def _set_result_and_close(self, value):
        self.result_value = value
        self.accept()
        
    @staticmethod
    def information(parent, title, message):
        """정보 메시지 표시"""
        dlg = JarvisMessageBox(parent, title, message, JarvisMessageBox.Information)
        dlg.add_button("OK", "accept", "cyan")
        dlg.exec()
        
    @staticmethod
    def warning(parent, title, message):
        """경고 메시지 표시"""
        dlg = JarvisMessageBox(parent, title, message, JarvisMessageBox.Warning)
        dlg.add_button("OK", "accept", "cyan")
        dlg.exec()
        
    @staticmethod
    def critical(parent, title, message):
        """오류 메시지 표시"""
        dlg = JarvisMessageBox(parent, title, message, JarvisMessageBox.Critical)
        dlg.add_button("OK", "accept", "cyan")
        dlg.exec()
        
    @staticmethod
    def question(parent, title, message):
        """예/아니오 질문 (True/False 반환)"""
        dlg = JarvisMessageBox(parent, title, message, JarvisMessageBox.Question)
        dlg.add_button("Cancel", "reject", "gray")
        dlg.add_button("OK", "accept", "cyan")
        result = dlg.exec()
        return result == QDialog.DialogCode.Accepted


class SendMailDialog(QDialog):
    """메일 발송 다이얼로그"""
    
    def __init__(self, parent=None, subject="", body="", html_body="", attachments=None,
                 to="", cc="", in_reply_to="", references="",
                 recipient_name="", recipient_title=""):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.subject = subject
        self.body = body
        self.html_body = html_body
        self.attachments = attachments or []
        self.default_to = to
        self.default_cc = cc
        self.in_reply_to = in_reply_to
        self.references = references
        self.recipient_name = recipient_name
        self.recipient_title = recipient_title

        self.init_ui()
        self._load_mail_settings()
    
    def init_ui(self):
        from PyQt6.QtWidgets import QFormLayout, QGraphicsDropShadowEffect
        from PyQt6.QtGui import QFont

        # Frosted Glass 컨테이너
        self.container = QWidget(self)
        self.container.setObjectName("send_mail_container")
        self.container.setStyleSheet("""
            #send_mail_container {
                background-color: rgba(25, 32, 48, 235);
                border: 1px solid rgba(0, 255, 255, 0.3);
                border-radius: 16px;
            }
            #send_mail_container QLabel {
                color: #e0e0e0;
                font-size: 10pt;
                background: transparent;
            }
            #send_mail_container QLineEdit, #send_mail_container QTextEdit {
                background-color: rgba(15, 22, 40, 200);
                border: 1px solid rgba(0, 200, 220, 0.25);
                border-radius: 6px;
                color: #ffffff;
                padding: 8px;
                font-size: 10pt;
            }
            #send_mail_container QLineEdit:focus, #send_mail_container QTextEdit:focus {
                border: 1px solid rgba(0, 255, 255, 0.6);
            }
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setXOffset(0)
        shadow.setYOffset(8)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.container.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(12)

        # 헤더
        header = QLabel("메일 발송")
        header.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        header.setStyleSheet("color: #00ffff; background: transparent;")
        layout.addWidget(header)
        
        # 폼
        form = QFormLayout()
        form.setSpacing(10)
        
        # 받는 사람
        self.input_to = QLineEdit()
        self.input_to.setPlaceholderText("example@email.com")
        self.input_to.setText(self.default_to)
        form.addRow("받는 사람:", self.input_to)
        
        # 참조 (CC)
        self.input_cc = QLineEdit()
        self.input_cc.setPlaceholderText("cc1@email.com, cc2@email.com")
        self.input_cc.setText(self.default_cc)
        form.addRow("참조:", self.input_cc)

        # 이름/직책 (정산서 메일용)
        name_title_layout = QHBoxLayout()
        self.input_name = QLineEdit()
        self.input_name.setPlaceholderText("이름")
        self.input_name.setText(self.recipient_name)
        self.input_name.setMaximumWidth(150)
        name_title_layout.addWidget(self.input_name)

        self.input_title = QLineEdit()
        self.input_title.setPlaceholderText("직책")
        self.input_title.setText(self.recipient_title)
        self.input_title.setMaximumWidth(150)
        name_title_layout.addWidget(self.input_title)
        name_title_layout.addStretch()

        form.addRow("이름/직책:", name_title_layout)

        # 이름/직책 변경 시 본문 첫 줄 업데이트
        self.input_name.textChanged.connect(self._update_greeting_line)
        self.input_title.textChanged.connect(self._update_greeting_line)

        # 제목
        self.input_subject = QLineEdit()
        self.input_subject.setText(self.subject)
        form.addRow("제목:", self.input_subject)
        
        layout.addLayout(form)
        
        # 본문
        layout.addWidget(QLabel("내용:"))
        self.text_body = QTextEdit()
        self.text_body.setText(self.body)
        self.text_body.setMaximumHeight(180)
        layout.addWidget(self.text_body)
        
        # 첨부 파일 영역
        attach_header = QHBoxLayout()
        attach_label = QLabel("📎 첨부파일:")
        attach_label.setStyleSheet("color: #00ff88; font-size: 10pt; font-weight: bold; background: transparent;")
        attach_header.addWidget(attach_label)
        attach_header.addStretch()
        
        from .widgets import NeonButton
        
        btn_add_file = NeonButton("+ 파일 추가", color="cyan")
        btn_add_file.setFixedSize(110, 28)
        btn_add_file.clicked.connect(self._add_attachment)
        attach_header.addWidget(btn_add_file)
        
        layout.addLayout(attach_header)
        
        # 첨부파일 목록 (드래그 앤 드롭 지원)
        from PyQt6.QtWidgets import QListWidget
        self.attach_list = QListWidget()
        self.attach_list.setMaximumHeight(120)
        self.attach_list.setAcceptDrops(True)
        self.attach_list.setStyleSheet("""
            QListWidget {
                background-color: rgba(15, 22, 40, 200);
                border: 1px solid rgba(0, 200, 220, 0.2);
                border-radius: 6px;
                color: #00ff88;
                font-size: 9pt;
            }
            QListWidget::item { padding: 4px 8px; }
            QListWidget::item:selected { background-color: rgba(0, 255, 255, 50); color: #ffffff; }
        """)
        self.attach_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.attach_list.customContextMenuRequested.connect(self._show_attach_context_menu)
        
        # 드래그 앤 드롭 이벤트 핸들러 설정
        self.attach_list.dragEnterEvent = self._attach_drag_enter
        self.attach_list.dragMoveEvent = self._attach_drag_move
        self.attach_list.dropEvent = self._attach_drop
        
        layout.addWidget(self.attach_list)
        
        # 드래그 앤 드롭 힌트
        drop_hint = QLabel("💡 파일을 끌어다 놓거나 버튼으로 추가")
        drop_hint.setStyleSheet("color: rgba(255,255,255,0.35); font-size: 8pt; background: transparent;")
        layout.addWidget(drop_hint)
        
        # 기존 첨부파일 추가
        for f in self.attachments:
            self.attach_list.addItem(f"📄 {os.path.basename(f)}")
        
        # 버튼
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_cancel = NeonButton("취소", color="orange")
        btn_cancel.setFixedSize(80, 35)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_send = NeonButton("📧 발송", color="cyan")
        btn_send.setFixedSize(100, 35)
        btn_send.clicked.connect(self._send_mail)
        btn_layout.addWidget(btn_send)
        
        layout.addLayout(btn_layout)
        
        # 상태
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #888; font-size: 9pt;")
        layout.addWidget(self.lbl_status)
    
    def _add_attachment(self):
        """파일 선택하여 첨부파일 추가"""
        from PyQt6.QtWidgets import QFileDialog
        files, _ = QFileDialog.getOpenFileNames(self, "첨부할 파일 선택", "", "All Files (*)")
        if files:
            for f in files:
                if f not in self.attachments:
                    self.attachments.append(f)
                    self.attach_list.addItem(f"📄 {os.path.basename(f)}")
    
    def _show_attach_context_menu(self, pos):
        """첨부파일 우클릭 메뉴"""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        
        item = self.attach_list.itemAt(pos)
        if not item:
            return
        
        idx = self.attach_list.row(item)
        
        menu = QMenu(self)
        delete_action = QAction("❌ 첨부 취소", self)
        delete_action.triggered.connect(lambda: self._remove_attachment(idx))
        menu.addAction(delete_action)
        menu.exec(self.attach_list.mapToGlobal(pos))
    
    def _remove_attachment(self, idx):
        """첨부파일 삭제"""
        if 0 <= idx < len(self.attachments):
            self.attachments.pop(idx)
            self.attach_list.takeItem(idx)
    
    def _attach_drag_enter(self, event):
        """드래그 진입 이벤트"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def _attach_drag_move(self, event):
        """드래그 이동 이벤트"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def _attach_drop(self, event):
        """드롭 이벤트 - 파일 첨부"""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if file_path and os.path.isfile(file_path):
                    if file_path not in self.attachments:
                        self.attachments.append(file_path)
                        self.attach_list.addItem(f"📄 {os.path.basename(file_path)}")
            event.acceptProposedAction()
        else:
            event.ignore()


    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, '_drag_pos'):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)

    def _update_greeting_line(self):
        """이름/직책 변경 시 본문 첫 줄 업데이트"""
        name = self.input_name.text().strip()
        title = self.input_title.text().strip()

        current_text = self.text_body.toPlainText()
        lines = current_text.split('\n')

        # 첫 줄이 "안녕하세요"로 시작하면 업데이트
        if lines and lines[0].startswith("안녕하세요"):
            if name and title:
                lines[0] = f"안녕하세요 {name} {title}님!!"
            elif name:
                lines[0] = f"안녕하세요 {name}님!!"
            else:
                lines[0] = "안녕하세요"
            self.text_body.setText('\n'.join(lines))

    def _load_mail_settings(self):
        """저장된 메일 설정 로드"""
        import json
        from .utils import get_run_dir
        
        config_path = get_config_path()
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # hanbiro_mail 중첩 객체에서 읽기
                    hanbiro = config.get('hanbiro_mail', {})
                    self.smtp_server = hanbiro.get('imap_server', 'raeon.hanbiro.net')  # SMTP도 같은 서버
                    self.smtp_port = 465  # SSL 포트
                    self.smtp_user = hanbiro.get('email', '')
                    # 비밀번호는 keyring에서 로드
                    import keyring
                    self.smtp_password = keyring.get_password("TRADIS_MH", "email_password") or ''
        except Exception:
            self.smtp_server = 'raeon.hanbiro.net'
            self.smtp_port = 465
            self.smtp_user = ''
            self.smtp_password = ''
    
    def _get_signature_html(self) -> str:
        """HAEDO 메일 서명 HTML 반환"""
        return """
<br>
<div>
  <img src="cid:haedo_logo" width="260" style="display:block; margin-bottom:4px;">
  <div style="font-size: 9pt; color: #555; line-height: 1.6; font-family: '맑은 고딕', sans-serif;">
    <b style="color:#333;">해도관세사무소 / 최명헌 / 차장</b><br>
    서울특별시 강서구 공항대로 194, 11층 1118호(마곡동, 문영 퀸즈파크 12차)(07807)<br>
    Tel 02-2664-3692&nbsp;&nbsp;Fax 02-2665-3693&nbsp;&nbsp;<b>Mobile</b>&nbsp;&nbsp;010-7441-1104<br>
    <b>Messenger</b>&nbsp;&nbsp;n97397737@nate.com<br>
    <b>Email</b>&nbsp;&nbsp;mhchoi@ihaedo.com
  </div>
</div>"""

    def _append_signature_to_html(self, html_body: str) -> str:
        """전달받은 HTML 본문에 HAEDO 서명 추가"""
        signature_html = self._get_signature_html()
        # </body> 태그가 있으면 그 앞에 서명 삽입, 없으면 뒤에 추가
        if '</body>' in html_body.lower():
            import re
            return re.sub(r'(</body>)', f'{signature_html}\\1', html_body, count=1, flags=re.IGNORECASE)
        return html_body + signature_html

    def _build_html_with_signature(self, plain_text: str) -> str:
        """텍스트 본문을 HTML로 변환하고 HAEDO 서명 추가"""
        # 텍스트를 HTML 단락으로 변환
        paragraphs = plain_text.split('\n\n')
        html_body_parts = []
        for p in paragraphs:
            lines = p.strip().replace('\n', '<br>')
            if lines:
                html_body_parts.append(f'<p style="margin:0 0 10px 0;">{lines}</p>')

        body_html = '\n'.join(html_body_parts)
        signature_html = self._get_signature_html()

        return f"""<div style="font-family: '맑은 고딕', sans-serif; font-size: 10pt; color: #333;">
{body_html}
{signature_html}
</div>"""

    def _send_mail(self):
        """메일 발송"""
        import smtplib
        import imaplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email.mime.image import MIMEImage
        from email import encoders

        to_addr = self.input_to.text().strip()
        cc_addr = self.input_cc.text().strip()
        subject = self.input_subject.text().strip()
        body = self.text_body.toPlainText()

        if not to_addr:
            self.lbl_status.setText("❌ 받는 사람을 입력하세요")
            self.lbl_status.setStyleSheet("color: #ff6666; font-size: 9pt;")
            return

        if not self.smtp_user or not self.smtp_password:
            self.lbl_status.setText("❌ SETTINGS 탭에서 메일 설정을 먼저 해주세요")
            self.lbl_status.setStyleSheet("color: #ff6666; font-size: 9pt;")
            return

        try:
            self.lbl_status.setText("📤 발송 중...")
            self.lbl_status.setStyleSheet("color: #00ffff; font-size: 9pt;")
            QApplication.processEvents()

            # 메일 구성
            msg = MIMEMultipart('mixed')

            # 사용자 요청: ID + @ihaedo.com 자동 변환
            user_id = self.smtp_user.split('@')[0] if '@' in self.smtp_user else self.smtp_user
            sender_address = f"{user_id}@ihaedo.com"

            msg['From'] = f'"최명헌" <{sender_address}>'
            msg['To'] = to_addr
            if cc_addr:
                msg['Cc'] = cc_addr
            msg['Subject'] = subject

            # In-Reply-To / References 헤더 (스레드 연결)
            if self.in_reply_to:
                msg['In-Reply-To'] = self.in_reply_to
                msg['References'] = self.references or self.in_reply_to

            # 본문 컨테이너
            msg_related = MIMEMultipart('related')
            msg.attach(msg_related)

            msg_alt = MIMEMultipart('alternative')
            msg_related.attach(msg_alt)

            # 텍스트 본문
            part_text = MIMEText(body, 'plain', 'utf-8')
            msg_alt.attach(part_text)

            # HTML 본문 (서명 포함)
            if self.html_body:
                # 전달받은 HTML 본문이 있으면 그대로 사용 + 서명 추가
                html_content = self._append_signature_to_html(self.html_body)
            else:
                # 없으면 텍스트를 HTML로 변환 + 서명 추가
                html_content = self._build_html_with_signature(body)
            part_html = MIMEText(html_content, 'html', 'utf-8')
            msg_alt.attach(part_html)

            # HAEDO 로고 인라인 이미지
            from .utils import resource_path
            logo_path = resource_path("haedo_logo.png")
            if os.path.exists(logo_path):
                with open(logo_path, 'rb') as f:
                    logo_img = MIMEImage(f.read(), _subtype='png')
                    logo_img.add_header('Content-ID', '<haedo_logo>')
                    logo_img.add_header('Content-Disposition', 'inline', filename='haedo_logo.png')
                    msg_related.attach(logo_img)
            
            # 첨부파일
            from email.header import Header
            for filepath in self.attachments:
                if os.path.exists(filepath):
                    with open(filepath, 'rb') as f:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        
                        filename = os.path.basename(filepath)
                        # 한글 파일명 인코딩 처리
                        encoded_filename = Header(filename, 'utf-8').encode()
                        part.add_header('Content-Disposition', 'attachment', filename=encoded_filename)
                        
                        msg.attach(part)
                else:
                    self.lbl_status.setText(f"⚠️ 파일 없음: {os.path.basename(filepath)}")
            
            # SMTP SSL 발송 (포트 465)
            # 받는 사람 목록 (To + CC)
            recipients = [addr.strip() for addr in to_addr.split(',') if addr.strip()]
            if cc_addr:
                recipients.extend([addr.strip() for addr in cc_addr.split(',') if addr.strip()])
            
            with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port) as server:
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_user, recipients, msg.as_string())

            # 보낸메일함에 IMAP 저장
            try:
                imap = imaplib.IMAP4_SSL(self.smtp_server, 993)
                imap.login(self.smtp_user, self.smtp_password)
                # Sent 폴더 찾기 (\Sent 플래그 기반)
                _, folders = imap.list()
                sent_folder = None
                for folder_info in folders:
                    decoded = folder_info.decode() if folder_info else ""
                    if '\\Sent' in decoded:
                        parts = decoded.split('"')
                        if len(parts) >= 4:
                            sent_folder = parts[-2]
                        break
                if sent_folder:
                    imap.append(sent_folder, "\\Seen", None, msg.as_bytes())
                    print(f"[메일] 보낸메일함 저장 완료: {sent_folder}")
                else:
                    print("[메일] 보낸메일함 폴더를 찾지 못함")
                imap.logout()
            except Exception as e:
                print(f"[메일] 보낸메일함 저장 실패: {e}")  # 발송은 성공

            self.lbl_status.setText("✅ 발송 완료!")
            self.lbl_status.setStyleSheet("color: #00ff88; font-size: 9pt;")
            QTimer.singleShot(1000, self.accept)

        except Exception as e:
            self.lbl_status.setText(f"❌ 발송 실패: {str(e)}")
            self.lbl_status.setStyleSheet("color: #ff6666; font-size: 9pt;")


class MailThreadSelectDialog(QDialog):
    """B/L 검색 결과에서 답장할 메일을 선택하는 다이얼로그 (Frosted Glass)"""

    def __init__(self, parent=None, threads=None, bl_number=""):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.threads = threads or []
        self.bl_number = bl_number
        self.selected_thread = None

        self._init_ui()

    def _init_ui(self):
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        from PyQt6.QtGui import QFont
        from .widgets import NeonButton

        # 메인 컨테이너 (Frosted Glass)
        self.container = QWidget(self)
        self.container.setObjectName("mail_thread_container")
        self.container.setStyleSheet("""
            #mail_thread_container {
                background-color: rgba(25, 32, 48, 235);
                border: 1px solid rgba(0, 255, 255, 0.3);
                border-radius: 16px;
            }
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setXOffset(0)
        shadow.setYOffset(8)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.container.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(12)

        # 헤더
        header = QLabel(f"B/L: {self.bl_number}")
        header.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        header.setStyleSheet("color: #00ffff; background: transparent;")
        layout.addWidget(header)

        sub = QLabel(f"관련 메일 {len(self.threads)}건  ·  답장할 메일을 선택하세요")
        sub.setFont(QFont("Segoe UI", 9))
        sub.setStyleSheet("color: rgba(255,255,255,0.55); background: transparent;")
        layout.addWidget(sub)

        layout.addSpacing(4)

        if self.threads:
            # 테이블
            self.table = QTableWidget(len(self.threads), 4)
            self.table.setHorizontalHeaderLabels(["날짜", "구분", "보낸사람", "제목"])
            self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
            self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.table.verticalHeader().setVisible(False)
            self.table.setAlternatingRowColors(True)
            self.table.setShowGrid(False)
            self.table.setFont(QFont("Segoe UI", 9))
            self.table.setMinimumHeight(250)
            self.table.setStyleSheet("""
                QTableWidget {
                    background-color: rgba(15, 22, 40, 200);
                    alternate-background-color: rgba(25, 35, 55, 200);
                    border: 1px solid rgba(0, 200, 220, 0.2);
                    border-radius: 8px;
                    color: #e0e0e0;
                    selection-background-color: rgba(0, 255, 255, 50);
                    selection-color: #ffffff;
                }
                QTableWidget::item {
                    padding: 6px 10px;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
                }
                QTableWidget::item:hover {
                    background-color: rgba(0, 255, 255, 15);
                }
                QHeaderView::section {
                    background-color: rgba(0, 50, 65, 220);
                    color: #00ddee;
                    border: none;
                    border-bottom: 2px solid rgba(0, 200, 220, 0.3);
                    padding: 7px 10px;
                    font-weight: bold;
                    font-size: 9pt;
                }
                QScrollBar:vertical {
                    background: rgba(15, 22, 40, 100);
                    width: 8px;
                    border-radius: 4px;
                }
                QScrollBar::handle:vertical {
                    background: rgba(0, 200, 220, 0.3);
                    border-radius: 4px;
                    min-height: 30px;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            """)

            def extract_name(raw: str) -> str:
                if '"' in raw:
                    return raw.split('"')[1].strip()
                if '<' in raw:
                    return raw.split('<')[0].strip().strip('"')
                return raw.split('@')[0] if '@' in raw else raw

            for row, thread in enumerate(self.threads):
                date_item = QTableWidgetItem(thread.date)
                date_item.setData(Qt.ItemDataRole.UserRole, thread)
                self.table.setItem(row, 0, date_item)

                folder_item = QTableWidgetItem(thread.folder)
                if thread.folder == "보낸메일":
                    folder_item.setForeground(QColor("#5bc0de"))
                else:
                    folder_item.setForeground(QColor("#f0ad4e"))
                self.table.setItem(row, 1, folder_item)

                if thread.folder == "보낸메일":
                    sender_name = "최명헌"
                else:
                    sender_name = extract_name(thread.sender)
                self.table.setItem(row, 2, QTableWidgetItem(sender_name))

                self.table.setItem(row, 3, QTableWidgetItem(thread.subject))

            # 컬럼 너비: 내용에 맞게 자동 조절 후 제목은 확장
            self.table.resizeColumnsToContents()
            # 최소 너비 보장
            if self.table.columnWidth(0) < 120:
                self.table.setColumnWidth(0, 120)
            if self.table.columnWidth(1) < 65:
                self.table.setColumnWidth(1, 65)
            if self.table.columnWidth(2) < 80:
                self.table.setColumnWidth(2, 80)
            self.table.horizontalHeader().setStretchLastSection(True)
            self.table.setRowHeight(0, 36)
            for r in range(len(self.threads)):
                self.table.setRowHeight(r, 36)

            # 전체 다이얼로그 너비 계산 (테이블 내용 기반)
            total_w = sum(self.table.columnWidth(c) for c in range(3)) + 300  # 제목 여유
            self.setMinimumWidth(max(700, min(total_w, 950)))

            self.table.selectRow(0)
            self.table.cellDoubleClicked.connect(lambda r, c: self._select_row(r))
            layout.addWidget(self.table)
        else:
            no_result = QLabel("검색 결과가 없습니다.\n새 메일을 작성하시겠습니까?")
            no_result.setFont(QFont("Segoe UI", 11))
            no_result.setStyleSheet("color: rgba(255,150,150,0.9); background: transparent;")
            no_result.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(no_result)
            layout.addStretch()
            self.setMinimumWidth(400)

        layout.addSpacing(4)

        # 버튼
        btn_layout = QHBoxLayout()

        btn_new = NeonButton("새 메일 작성", color="green")
        btn_new.setFixedSize(120, 34)
        btn_new.clicked.connect(lambda: self._finish(None))
        btn_layout.addWidget(btn_new)

        btn_layout.addStretch()

        btn_cancel = NeonButton("취소", color="orange")
        btn_cancel.setFixedSize(80, 34)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        if self.threads:
            btn_select = NeonButton("답장", color="cyan")
            btn_select.setFixedSize(80, 34)
            btn_select.clicked.connect(self._on_select)
            btn_layout.addWidget(btn_select)

        layout.addLayout(btn_layout)

    def _select_row(self, row):
        item = self.table.item(row, 0)
        if item:
            self._finish(item.data(Qt.ItemDataRole.UserRole))

    def _on_select(self):
        if hasattr(self, 'table'):
            row = self.table.currentRow()
            if row >= 0:
                self._select_row(row)

    def _finish(self, thread):
        self.selected_thread = thread
        self.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, '_drag_pos'):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)


class MarkingPopup(QDialog):
    """수출신고필증 이름변경 시 관련 파일 마킹 팝업"""
    
    def __init__(self, parent=None, company="", invoice_id="", filepath="", export_docs_root=""):
        super().__init__(parent)
        self.company = company
        self.invoice_id = invoice_id
        self.filepath = filepath
        self.export_docs_root = export_docs_root
        self.marked_files = []  # 결과: [{'name': str, 'path': str, 'icon': str}, ...]
        self._skipped = False
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(450)
        self.setMinimumHeight(200)
        
        self.init_ui()
    
    def init_ui(self):
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QScrollArea, QCheckBox, QFileDialog
        from PyQt6.QtGui import QFont
        
        # 메인 컨테이너
        self.container = QWidget(self)
        self.container.setObjectName("marking_container")
        self.container.setStyleSheet("""
            #marking_container {
                background-color: rgba(5, 15, 30, 240);
                border: 2px solid #00ffff;
                border-radius: 12px;
            }
        """)
        
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setXOffset(0)
        shadow.setYOffset(5)
        shadow.setColor(Qt.GlobalColor.black)
        self.container.setGraphicsEffect(shadow)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.container)
        
        inner = QVBoxLayout(self.container)
        inner.setContentsMargins(16, 16, 16, 12)
        inner.setSpacing(10)
        
        # 헤더
        lbl_title = QLabel(f"📎 파일 마킹")
        lbl_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #00ffff; background: transparent;")
        inner.addWidget(lbl_title)
        
        lbl_info = QLabel(f"{self.company}({self.invoice_id}) 수출신고필증")
        lbl_info.setStyleSheet("color: #aaa; font-size: 9pt; background: transparent;")
        lbl_info.setWordWrap(True)
        inner.addWidget(lbl_info)
        
        # 구분선
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #00aaaa;")
        inner.addWidget(line)
        
        # 열린 파일 목록 + 자동 매칭 파일
        lbl_open = QLabel("현재 열린 파일:")
        lbl_open.setStyleSheet("color: #ccc; font-size: 9pt; background: transparent;")
        inner.addWidget(lbl_open)
        
        # 스크롤 영역 (체크박스 리스트)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMaximumHeight(250)
        self.scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollArea > QWidget > QWidget { background: transparent; }
        """)

        self.check_container = QWidget()
        self.check_layout = QVBoxLayout(self.check_container)
        self.check_layout.setContentsMargins(4, 4, 4, 4)
        self.check_layout.setSpacing(4)
        self.scroll.setWidget(self.check_container)
        inner.addWidget(self.scroll)
        
        self.checkboxes = []  # (QCheckBox, file_info_dict)
        
        # 열린 파일 감지
        try:
            from core.open_file_detector import get_open_files
            open_files = get_open_files()
        except Exception:
            open_files = []
        
        # 경로가 비어있는 파일의 실제 경로 찾기
        search_dirs = []
        if self.export_docs_root and os.path.exists(self.export_docs_root):
            search_dirs.append(self.export_docs_root)
        rename_dir = os.path.dirname(self.filepath) if self.filepath else ''
        if rename_dir and os.path.exists(rename_dir):
            search_dirs.append(rename_dir)
        
        for finfo in open_files:
            if not finfo.get('path') and search_dirs:
                finfo['path'] = self._find_file_in_dirs(finfo['name'], search_dirs)
        
        if open_files:
            for finfo in open_files:
                icon = finfo['icon']
                name = finfo['name']
                cb = QCheckBox(f"☐ {icon} {name}")
                cb.setStyleSheet("""
                    QCheckBox { 
                        color: #ddd; font-size: 10pt; background: transparent;
                        padding: 4px 8px;
                    }
                    QCheckBox:hover { color: #00ffff; }
                    QCheckBox::indicator {
                        width: 0px; height: 0px;
                        border: none;
                    }
                """)
                cb.toggled.connect(lambda checked, c=cb, ic=icon, n=name:
                    c.setText(f"✅ {ic} {n}" if checked else f"☐ {ic} {n}"))
                self.check_layout.addWidget(cb)
                self.checkboxes.append((cb, finfo))
        else:
            lbl_none = QLabel("  (열린 파일을 감지하지 못했습니다)")
            lbl_none.setStyleSheet("color: #666; font-size: 9pt; background: transparent;")
            self.check_layout.addWidget(lbl_none)
        
        # 자동 매칭 기능이 제거되었습니다.
        
        self.check_layout.addStretch()
        
        # 버튼 영역
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        # 파일 직접 추가
        btn_add = NeonButton("📂 파일 추가", color="orange")
        btn_add.setFixedHeight(34)
        btn_add.clicked.connect(self._add_files_dialog)
        btn_layout.addWidget(btn_add)
        
        btn_layout.addStretch()
        
        # 건너뛰기
        btn_skip = NeonButton("건너뛰기", color="orange")
        btn_skip.setFixedHeight(34)
        btn_skip.clicked.connect(self._skip)
        btn_layout.addWidget(btn_skip)
        
        # 마킹 완료
        btn_done = NeonButton("✅ 마킹 완료", color="cyan")
        btn_done.setFixedHeight(34)
        btn_done.clicked.connect(self._complete)
        btn_layout.addWidget(btn_done)
        
        inner.addLayout(btn_layout)
        
        # 화면 중앙 상단에 배치 (작업에 방해가 덜 되도록)
        self.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 20, screen.top() + 50)
    
    def _add_files_dialog(self):
        """파일 직접 추가 (export_docs_root 기본 경로)"""
        from PyQt6.QtWidgets import QFileDialog, QCheckBox
        
        start_dir = self.export_docs_root if self.export_docs_root and os.path.exists(self.export_docs_root) else ""
        
        files, _ = QFileDialog.getOpenFileNames(
            self, "관련 파일 선택", start_dir,
            "All Files (*.*);;PDF (*.pdf);;Excel (*.xlsx *.xls);;Images (*.jpg *.png *.bmp);;Word (*.docx *.doc)"
        )
        
        if files:
            from core.open_file_detector import get_file_type_icon
            for f in files:
                name = os.path.basename(f)
                # 중복 확인
                existing = [info['name'] for _, info in self.checkboxes]
                if name in existing:
                    continue
                
                finfo = {'name': name, 'path': f, 'icon': get_file_type_icon(name)}
                icon = finfo['icon']
                cb = QCheckBox(f"✅ {icon} {name}")
                cb.setChecked(True)  # 직접 추가한 파일은 자동 체크
                cb.setStyleSheet("""
                    QCheckBox { 
                        color: #ffaa44; font-size: 10pt; background: transparent;
                        padding: 4px 8px;
                    }
                    QCheckBox:hover { color: #ffcc66; }
                    QCheckBox::indicator {
                        width: 0px; height: 0px;
                        border: none;
                    }
                """)
                cb.toggled.connect(lambda checked, c=cb, ic=icon, n=name:
                    c.setText(f"✅ {ic} {n}" if checked else f"☐ {ic} {n}"))
                # stretch 앞에 삽입
                idx = self.check_layout.count() - 1  # stretch 위치
                self.check_layout.insertWidget(idx, cb)
                self.checkboxes.append((cb, finfo))

            # 추가된 파일이 보이도록 스크롤을 맨 아래로
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(50, lambda: self.scroll.verticalScrollBar().setValue(
                self.scroll.verticalScrollBar().maximum()))
    
    def _find_file_in_dirs(self, filename, search_dirs):
        """파일명으로 여러 디렉토리에서 실제 경로 찾기"""
        base_name = os.path.splitext(filename)[0]
        
        for search_dir in search_dirs:
            if not search_dir or not os.path.exists(search_dir):
                continue
            try:
                for item in os.listdir(search_dir):
                    item_path = os.path.join(search_dir, item)
                    if os.path.isfile(item_path):
                        # 정확 매칭
                        if item == filename:
                            return item_path
                        # base name 매칭 (확장자가 다를 수 있음)
                        if os.path.splitext(item)[0] == base_name:
                            return item_path
                    elif os.path.isdir(item_path):
                        # 하위 1단계도 검색
                        for sub_item in os.listdir(item_path):
                            sub_path = os.path.join(item_path, sub_item)
                            if os.path.isfile(sub_path):
                                if sub_item == filename:
                                    return sub_path
                                if os.path.splitext(sub_item)[0] == base_name:
                                    return sub_path
            except Exception:
                continue
        return ''
    

    
    def _skip(self):

        """건너뛰기 (마킹 없이 닫기)"""
        self._skipped = True
        self.marked_files = []
        self.reject()
    
    def _complete(self):
        """마킹 완료 - 체크된 파일을 결과로 저장하고 해당 파일 창 닫기"""
        self.marked_files = []
        for cb, finfo in self.checkboxes:
            if cb.isChecked():
                self.marked_files.append(finfo)
        
        # 체크된 파일의 창 닫기
        if self.marked_files:
            self._close_marked_file_windows()
        
        self.accept()
    
    def _close_marked_file_windows(self):
        """마킹된 개별 파일만 정확하고 빠르게 종료 (Acrobat 탭 순회 포함)"""
        import win32gui
        import win32con
        import win32api
        import time
        import os
        
        # 1. 종료 대상 목록 정리
        marked_pdfs = []
        marked_others = []
        for f in self.marked_files:
            name = f['name'].lower()
            base = os.path.splitext(name)[0]
            if name.endswith('.pdf'):
                marked_pdfs.append(base)
            else:
                marked_others.append(base)
        
        # 2. 일반 파일 종료 - 엑셀(COM)과 기타(Win32) 분리
        if marked_others:
            # 엑셀과 나머지(이미지/워드 등) 분리
            excel_exts = {'.xls', '.xlsx', '.xlsm', '.csv'}
            excel_targets = []
            generic_targets = []
            
            # 마킹된 파일 리스트를 다시 뒤져서 확장자 확인
            for m_base in marked_others:
                is_excel = False
                for f in self.marked_files:
                    f_name = f['name'].lower()
                    if m_base in f_name and any(ext in f_name for ext in excel_exts):
                        is_excel = True
                        break
                if is_excel:
                    excel_targets.append(m_base)
                else:
                    generic_targets.append(m_base)
            
            # (A) 엑셀: COM API를 이용한 '진짜' 개별 워크북 종료 (근본 해결)
            if excel_targets:
                self._smart_close_excel_via_com(excel_targets)
                
            # (B) 기타(이미지, 워드 등) : 창 제목 매칭 + WM_CLOSE (독립적 창이므로 안전함)
            if generic_targets:
                def enum_generic(hwnd, _):
                    if not win32gui.IsWindowVisible(hwnd): return
                    title = win32gui.GetWindowText(hwnd).lower()
                    if not title: return
                    for m in generic_targets:
                        if m in title:
                            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                            break
                try:
                    win32gui.EnumWindows(enum_generic, None)
                except OSError: pass
            
        # 3. PDF (Acrobat) - 탭 순회 종료 (마킹된 페이지만 닫기)
        if marked_pdfs:
            self._smart_close_acrobat_tabs(marked_pdfs)

    def _smart_close_excel_via_com(self, targets):
        """시스템 전체의 ROT를 스캔하고 IDispatch 바인딩을 통해 마킹된 엑셀 파일만 100% 정밀 종료"""
        import pythoncom
        import win32com.client
        import os
        import win32gui
        import win32con
        
        if not targets: return
        targets = set(targets)
        
        # COM 초기화 (스레드 안전성 확보)
        pythoncom.CoInitialize()
        try:
            context = pythoncom.CreateBindCtx(0)
            rot = pythoncom.GetRunningObjectTable()
            
            for mon in rot.EnumRunning():
                try:
                    name = mon.GetDisplayName(context, mon)
                    low_name = name.lower()
                    # 엑셀 관련 모니커 확인
                    if any(ext in low_name for ext in ['.xls', '.xlsx', '.xlsm', '.csv']):
                        base_name = os.path.splitext(os.path.basename(low_name))[0]
                        
                        matched = None
                        for t in targets:
                            if t == base_name or t in low_name:
                                matched = t
                                break
                        
                        if matched:
                            # [핵심] PyIUnknown 개체를 IDispatch로 쿼리하여 바인딩 (성공 검증된 방식)
                            unk = rot.GetObject(mon)
                            try:
                                # IDispatch 인터페이스 확보 후 Dispatch 래핑
                                disp = unk.QueryInterface(pythoncom.IID_IDispatch)
                                wb = win32com.client.Dispatch(disp)
                                # 저장 없이 닫기
                                wb.Close(False)
                                if matched in targets:
                                    targets.remove(matched)
                            except Exception:
                                # 폴백: 직접 Close 호출 시도
                                try:
                                    getattr(unk, "Close")(False)
                                    if matched in targets:
                                        targets.remove(matched)
                                except Exception: pass
                except Exception: continue
                if not targets: break
        except Exception:
            pass
        finally:
            pythoncom.CoUninitialize()
            
        # Fallback: COM으로 닫히지 않고 남은 타겟들 강제 닫기
        if targets:
            def force_close_excel(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd): return
                title = win32gui.GetWindowText(hwnd).lower()
                if "excel" in title:
                    for t in list(targets):
                        if t in title:
                            # 윈도우 단에서 강제 닫기 신호
                            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                            try: targets.remove(t)
                            except ValueError: pass
                            break
            try:
                win32gui.EnumWindows(force_close_excel, None)
            except Exception:
                pass

    def _smart_close_acrobat_tabs(self, targets):
        """Acrobat 창의 탭을 돌려가며 마킹된 파일만 종료"""
        import win32gui
        import win32con
        import win32api
        import time
        
        # 대상이 없으면 즉시 종료
        if not targets: return
        
        targets = set(targets)
        acro_hwnds = []
        def find_acro(h, _):
            if "AcrobatSDIWindow" in win32gui.GetClassName(h) and win32gui.IsWindowVisible(h):
                acro_hwnds.append(h)
        try:
            win32gui.EnumWindows(find_acro, None)
        except OSError: pass
        
        for hwnd in acro_hwnds:
            # 한 창에서 최대 15번 탭 전환 시도 (무한 루프 방지)
            visited_titles = set()
            for _ in range(15):
                if not targets: break
                
                title = win32gui.GetWindowText(hwnd).lower()
                # 이미 확인한 제목이고 마킹 대상이 아니면 순회 종료
                if title in visited_titles: break
                visited_titles.add(title)
                
                matched = None
                for t in targets:
                    if t in title:
                        matched = t
                        break
                
                if matched:
                    # 마킹된 파일이면 해당 탭 닫기 (Ctrl+W)
                    targets.remove(matched)
                    try:
                        win32gui.SetForegroundWindow(hwnd)
                        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
                        win32api.keybd_event(ord('W'), 0, 0, 0)
                        win32api.keybd_event(ord('W'), 0, win32con.KEYEVENTF_KEYUP, 0)
                        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
                        time.sleep(0.3) # 탭이 닫히고 다음 탭이 로드될 때까지 대기
                    except OSError: break
                else:
                    # 마킹 안 된 파일이면 다음 탭으로 이동 (Ctrl+Tab)
                    try:
                        win32gui.SetForegroundWindow(hwnd)
                        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
                        win32api.keybd_event(win32con.VK_TAB, 0, 0, 0)
                        win32api.keybd_event(win32con.VK_TAB, 0, win32con.KEYEVENTF_KEYUP, 0)
                        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
                        time.sleep(0.1)
                    except OSError: break

    def _smart_close_excel_windows(self, targets):
        """엑셀 창들을 하나씩 확인하며 마킹된 파일만 종료 (Ctrl+W 활용)"""
        import win32gui
        import win32con
        import win32api
        import time
        
        if not targets: return
        targets = set(targets)
        
        excel_hwnds = []
        def find_excel(h, _):
            # 엑셀의 메인 창 클래스 로드
            if "XLMAIN" in win32gui.GetClassName(h) and win32gui.IsWindowVisible(h):
                excel_hwnds.append(h)
        try:
            win32gui.EnumWindows(find_excel, None)
        except OSError: pass
        
        for hwnd in excel_hwnds:
            if not targets: break
            
            title = win32gui.GetWindowText(hwnd).lower()
            matched = None
            for t in targets:
                if t in title:
                    matched = t
                    break
            
            if matched:
                targets.remove(matched)
                try:
                    win32gui.SetForegroundWindow(hwnd)
                    time.sleep(0.1)
                    # Ctrl+W 전송 (엑셀의 현재 통합 문서만 닫기)
                    win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
                    win32api.keybd_event(ord('W'), 0, 0, 0)
                    win32api.keybd_event(ord('W'), 0, win32con.KEYEVENTF_KEYUP, 0)
                    win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
                    time.sleep(0.3)
                except OSError:
                    continue

    @property
    def was_skipped(self):
        return self._skipped
