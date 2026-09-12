# JARVIS GUI 커스텀 위젯
"""
공통 커스텀 위젯 모음:
- DropListWidget: 드래그앤드롭 리스트
- DraggableSearchResultList: Everything 검색 결과 리스트
- DraggableTreeView: 파일 탐색기 트리뷰
- GlassFrame: HUD 스타일 컨테이너
- NeonButton: 네온 버튼
"""

import os
import shutil
import subprocess
import ctypes
import datetime

from PyQt6.QtWidgets import (QPushButton, QFrame, QListWidget, QTreeView,
                              QAbstractItemView, QMenu, QApplication)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QMimeData, QUrl
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QDrag, QFileSystemModel

from .styles import (DROP_LIST_STYLESHEET, DROP_LIST_HIGHLIGHT_STYLESHEET,
                     MENU_STYLESHEET)

from core.utils import get_unique_filename

# 순환 import 방지를 위해 지연 import 사용
def _get_jarvis_msgbox():
    from .dialogs import JarvisMessageBox
    return JarvisMessageBox


class DropListWidget(QListWidget):
    """드래그 앤 드롭 및 탐색기 기능을 지원하는 커스텀 QListWidget"""
    items_dropped = pyqtSignal(list)       # 드롭 발생 시
    refresh_needed = pyqtSignal()          # 새로고침 필요 시
    mail_send_requested = pyqtSignal(str)  # 정산서 메일 발송 요청 (파일 경로)
    mail_preconnect_requested = pyqtSignal()  # IMAP 사전 연결 요청
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        
        self.current_folder = None
        self._clipboard_path = None
        self._clipboard_mode = "copy"
        
        # 더블클릭 이벤트 연결
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
    
    def _on_item_double_clicked(self, item):
        """아이템 더블클릭 시 파일 실행"""
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path or not os.path.exists(path):
            return
        
        try:
            if os.path.isfile(path):
                os.startfile(path)
            elif os.path.isdir(path):
                subprocess.run(['explorer', path], creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as e:
            print(f"파일 실행 오류: {e}")
        
    def startDrag(self, supportedActions):
        """선택된 항목들을 드래그 시작"""
        items = self.selectedItems()
        if not items:
            return
        
        paths = []
        for item in items:
            path = item.data(Qt.ItemDataRole.UserRole)
            if not path:
                text = item.text()
                if os.path.exists(text):
                    path = text
            
            if path and os.path.exists(path):
                paths.append(path)
        
        if not paths:
            return
        
        # 2. 실패 시 PyQt 기본 드래그 폴백
        mime_data = QMimeData()
        urls = [QUrl.fromLocalFile(p) for p in paths]
        mime_data.setUrls(urls)
        
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)

    def _show_context_menu(self, position):
        """컨텍스트 메뉴 표시"""
        item = self.itemAt(position)
        if not item:
            return
            
        menu = QMenu()
        menu.setStyleSheet(MENU_STYLESHEET)
        
        # 액션 정의
        action_copy = menu.addAction("📄 복사")
        action_cut = menu.addAction("✂️ 잘라내기")
        action_paste = menu.addAction("📋 붙여넣기")
        menu.addSeparator()
        action_rename = menu.addAction("✏️ 이름 변경")
        action_delete = menu.addAction("🗑️ 삭제")
        menu.addSeparator()
        action_open_explorer = menu.addAction("📂 탐색기에서 열기")

        # 메일 보내기 (정산서 PDF만)
        menu.addSeparator()
        action_mail = menu.addAction("📧 메일 보내기")
        path_for_check = item.data(Qt.ItemDataRole.UserRole) or ""
        basename = os.path.basename(path_for_check) if path_for_check else ""
        is_settlement_pdf = path_for_check and path_for_check.lower().endswith('.pdf') and '정산서' in basename
        if not is_settlement_pdf:
            action_mail.setEnabled(False)
        else:
            # 정산서 PDF 우클릭 시 IMAP 사전 연결 시작
            self.mail_preconnect_requested.emit()

        # 붙여넣기 가능 여부 확인
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        if not mime_data.hasUrls():
            action_paste.setEnabled(False)
            
        # 메뉴 실행
        action = menu.exec(self.mapToGlobal(position))
        
        path = item.data(Qt.ItemDataRole.UserRole)
        
        if action == action_copy:
            if path:
                self._copy_to_clipboard([path], is_cut=False)
        elif action == action_cut:
            if path:
                self._copy_to_clipboard([path], is_cut=True)
                item.setHidden(True)  # 잘라내기 시각적 효과
        elif action == action_paste:
            self._paste_from_clipboard()
        elif action == action_rename:
            if path:
                self._rename_item(item, path)
        elif action == action_delete:
            if path:
                self._delete_item(item, path)
        elif action == action_open_explorer:
            if path:
                subprocess.run(f'explorer /select,"{path}"', creationflags=subprocess.CREATE_NO_WINDOW)
        elif action == action_mail:
            if path:
                print(f"[메일 보내기] 시그널 emit: {path}")
                self.mail_send_requested.emit(path)

    def _copy_to_clipboard(self, paths, is_cut=False):
        """파일을 클립보드에 복사/잘라내기"""
        mime_data = QMimeData()
        urls = [QUrl.fromLocalFile(p) for p in paths]
        mime_data.setUrls(urls)
        
        clipboard = QApplication.clipboard()
        clipboard.setMimeData(mime_data)
        
        self._clipboard_path = paths[0] if paths else None
        self._clipboard_mode = "cut" if is_cut else "copy"
        
    def _paste_from_clipboard(self):
        """클립보드 내용을 현재 폴더에 붙여넣기"""
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        
        if mime_data.hasUrls():
            urls = mime_data.urls()
            # 잘라내기 모드는 우리가 잘라낸 그 파일에만 적용 — 그 뒤 탐색기에서 복사한 파일이
            # 클립보드에 있으면 "cut" 상태가 남아 남의 파일을 이동시키던 결함 (v1.1.77)
            _local = [u.toLocalFile() for u in urls]
            _is_our_cut = (self._clipboard_mode == "cut" and self._clipboard_path
                           and os.path.normcase(self._clipboard_path) in {os.path.normcase(p) for p in _local})
            if not _is_our_cut:
                self._clipboard_mode = "copy"
            for url in urls:
                src_path = url.toLocalFile()
                if os.path.exists(src_path):
                    file_name = os.path.basename(src_path)
                    dest_path = os.path.join(self.current_folder, file_name) if self.current_folder else src_path
                    if os.path.normcase(os.path.abspath(dest_path)) == os.path.normcase(os.path.abspath(src_path)):
                        continue
                    if os.path.exists(dest_path):
                        dest_path = get_unique_filename(dest_path)  # 같은 이름 덮어쓰기 방지

                    try:
                        if self._clipboard_mode == "cut":
                            shutil.move(src_path, dest_path)
                        else:
                            if os.path.isdir(src_path):
                                shutil.copytree(src_path, dest_path)
                            else:
                                shutil.copy2(src_path, dest_path)
                        
                        # 리스트 갱신 (부모 위젯의 refresh 메서드 호출 필요)
                        self.refresh_needed.emit()
                        
                    except Exception as e:
                        _get_jarvis_msgbox().critical(self, "오류", f"파일 붙여넣기 실패: {e}")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_highlight_style(True)
        else:
            event.ignore()
    
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
            
    def dragLeaveEvent(self, event):
        self._set_highlight_style(False)
        event.accept()

    def dropEvent(self, event):
        self._set_highlight_style(False)
        
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        # 내부 이동인지 외부 드롭인지 확인
        if event.source() == self:
            event.ignore()  # 내부 드래그는 무시 (탐색기 역할만 수행)
            return

        urls = event.mimeData().urls()
        paths = [url.toLocalFile() for url in urls if url.isValid()]
        
        if paths:
            self.items_dropped.emit(paths)
            event.acceptProposedAction()

    def _rename_item(self, item, path):
        """아이템 이름 변경 (파일은 확장자 자동 보존)"""
        old_name = os.path.basename(path)
        # 파일이면 확장자 분리, 폴더면 그대로
        if os.path.isfile(path):
            base_name, ext = os.path.splitext(old_name)
        else:
            base_name, ext = old_name, ""
        from .dialogs import JarvisInputDialog
        new_base, ok = JarvisInputDialog.get_text(self, "이름 변경", "새 이름을 입력하세요:", text=base_name)
        if ok and new_base:
            new_name = new_base + ext
            new_path = os.path.join(os.path.dirname(path), new_name)
            try:
                os.rename(path, new_path)
                item.setText(new_name)
                item.setData(Qt.ItemDataRole.UserRole, new_path)
            except Exception as e:
                _get_jarvis_msgbox().critical(self, "오류", f"이름 변경 실패: {e}")

    def _delete_item(self, item, path):
        """아이템 삭제"""
        msg_box = _get_jarvis_msgbox()
        if msg_box.question(self, "삭제 확인", "휴지통으로 이동하시겠습니까?"):
            try:
                from .file_browser import move_to_recycle_bin
                if not move_to_recycle_bin([path]):   # 영구 삭제(os.remove/rmtree) 대신 휴지통
                    if move_to_recycle_bin.aborted:
                        return   # 사용자가 취소 — 오류 아님
                    raise OSError("휴지통 이동 실패")
                self.takeItem(self.row(item))
            except Exception as e:
                msg_box.critical(self, "오류", f"삭제 실패: {e}")

    def keyPressEvent(self, event):
        """키보드 단축키: Delete(삭제), F2(이름변경)"""
        items = self.selectedItems()
        if event.key() == Qt.Key.Key_Delete and items:
            # 선택된 모든 항목 삭제
            count = len(items)
            msg_box = _get_jarvis_msgbox()
            if msg_box.question(self, "삭제 확인", f"선택한 {count}개 항목을 휴지통으로 이동하시겠습니까?"):
                from .file_browser import move_to_recycle_bin
                paths = [item.data(Qt.ItemDataRole.UserRole) for item in items]
                paths = [p for p in paths if p and os.path.exists(p)]
                if paths and not move_to_recycle_bin(paths):   # 영구 삭제 대신 휴지통
                    if not move_to_recycle_bin.aborted:      # 사용자 취소는 오류 아님
                        msg_box.warning(self, "오류", "휴지통 이동에 실패했습니다.")
                    return
                for item in items:
                    row = self.row(item)
                    if row >= 0:
                        self.takeItem(row)
                self.refresh_needed.emit()
        elif event.key() == Qt.Key.Key_F2 and items:
            item = items[0]
            path = item.data(Qt.ItemDataRole.UserRole)
            if path and os.path.exists(path):
                self._rename_item(item, path)
                self.refresh_needed.emit()
        else:
            super().keyPressEvent(event)

    def _set_highlight_style(self, highlight=True):
        """드래그 진입 시 스타일 변경"""
        if highlight:
            self.setStyleSheet(DROP_LIST_HIGHLIGHT_STYLESHEET)
        else:
            self.setStyleSheet(DROP_LIST_STYLESHEET)
            
    def _restore_style(self):
        """기본 스타일 복원"""
        self.setStyleSheet(DROP_LIST_STYLESHEET)

class TargetListWidget(QListWidget):
    """MOVE TARGET 폴더 리스트를 위한 커스텀 위젯 (단축키 + 다중 선택 지원)"""
    delete_requested = pyqtSignal(list)  # 다중 선택 지원: 폴더 이름 리스트
    rename_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 다중 선택 활성화 (Ctrl/Shift 클릭으로 여러 폴더 동시 선택 가능)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            # 선택된 모든 항목의 폴더 이름 수집
            folder_names = []
            for item in self.selectedItems():
                fn = item.data(Qt.ItemDataRole.UserRole)
                if fn and fn != "(No Folders)":
                    folder_names.append(fn)
            if folder_names:
                self.delete_requested.emit(folder_names)
            return

        if event.key() == Qt.Key.Key_F2:
            # 이름 변경은 단일 항목만 허용
            item = self.currentItem()
            if not item:
                super().keyPressEvent(event)
                return
            folder_name = item.data(Qt.ItemDataRole.UserRole)
            if not folder_name or folder_name == "(No Folders)":
                super().keyPressEvent(event)
                return
            self.rename_requested.emit(folder_name)
            return

        super().keyPressEvent(event)


class DraggableSearchResultList(QListWidget):
    """Everything 검색 결과를 표시하고 드래그를 지원하는 리스트"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        
    def startDrag(self, supportedActions):
        """선택된 항목들을 드래그"""
        items = self.selectedItems()
        if not items:
            return
        
        paths = []
        for item in items:
            path = item.data(Qt.ItemDataRole.UserRole)
            if path and os.path.exists(path):
                paths.append(path)
        
        if not paths:
            return
        
        # 2. PyQt 기본 드래그
        mime_data = QMimeData()
        urls = [QUrl.fromLocalFile(p) for p in paths]
        mime_data.setUrls(urls)
        
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        result = drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction, Qt.DropAction.MoveAction)
        
        # 이동 완료 시 목록에서 해당 항목 제거
        if result == Qt.DropAction.MoveAction:
            for item in items:
                row = self.row(item)
                if row >= 0:
                    self.takeItem(row)
    
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            item = self.itemAt(event.position().toPoint())
            if item:
                path = item.data(Qt.ItemDataRole.UserRole)
                if path and os.path.exists(path) and os.path.isdir(path):
                    self.setCurrentItem(item)
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            item = self.itemAt(event.position().toPoint())
            if item:
                target_folder = item.data(Qt.ItemDataRole.UserRole)
                if target_folder and os.path.exists(target_folder) and os.path.isdir(target_folder):
                    paths = []
                    for url in event.mimeData().urls():
                        local_path = url.toLocalFile()
                        if local_path and os.path.exists(local_path):
                            if os.path.dirname(local_path) != target_folder:
                                paths.append(local_path)
                    
                    if paths:
                        moved_count = 0
                        for src in paths:
                            try:
                                dest = os.path.join(target_folder, os.path.basename(src))
                                if os.path.exists(dest):
                                    dest = get_unique_filename(dest)
                                shutil.move(src, dest)
                                moved_count += 1
                            except Exception as e:
                                print(f"Move failed: {e}")
                    
                    event.acceptProposedAction()
                    return
        event.ignore()


class DraggableTreeView(QTreeView):
    """드래그 및 드롭을 지원하는 파일 탐색기 트리뷰"""
    items_dropped = pyqtSignal(list, str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        self.file_model = QFileSystemModel()
        self.file_model.setRootPath(desktop_path)
        self.file_model.setReadOnly(False)
        self.setModel(self.file_model)
        
        self.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed | QAbstractItemView.EditTrigger.SelectedClicked)
        
        self.setRootIndex(self.file_model.index(desktop_path))
        self.current_path = desktop_path
        
        self.setHeaderHidden(True)
        self.hideColumn(1)
        self.hideColumn(2)
        self.hideColumn(3)
        
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        from PyQt6.QtWidgets import QHeaderView
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        
        self.doubleClicked.connect(self._on_double_click)
        
        
        self._clipboard_path = None
        self._clipboard_mode = "copy"
    
    def keyPressEvent(self, event):
        """키보드 단축키 처리"""
        modifiers = event.modifiers()
        key = event.key()
        
        if key == Qt.Key.Key_F2:
            current_index = self.currentIndex()
            if current_index.isValid():
                self.edit(current_index)
            event.accept()
            return
        
        elif key == Qt.Key.Key_Delete:
            # 선택된 모든 항목 수집 (다중 선택 지원)
            selected_indexes = self.selectionModel().selectedIndexes()
            paths = []
            seen = set()
            for idx in selected_indexes:
                if idx.column() != 0:
                    continue
                p = self.file_model.filePath(idx)
                if p and p not in seen:
                    seen.add(p)
                    paths.append(p)
            if paths:
                self._delete_paths(paths)
            event.accept()
            return
        
        elif key == Qt.Key.Key_F5:
            self._refresh()
            event.accept()
            return
        
        elif modifiers == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_C:
            current_index = self.currentIndex()
            if current_index.isValid():
                path = self.file_model.filePath(current_index)
                self._copy_item(path)
            event.accept()
            return
        
        elif modifiers == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_X:
            current_index = self.currentIndex()
            if current_index.isValid():
                path = self.file_model.filePath(current_index)
                self._cut_item(path)
            event.accept()
            return
        
        elif modifiers == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_V:
            self._paste_item()
            event.accept()
            return
        
        super().keyPressEvent(event)
    
    def _on_double_click(self, index):
        """더블클릭 시 파일 실행 또는 폴더 열기"""
        path = self.file_model.filePath(index)
        if not path:
            return
        
        if os.path.isfile(path):
            try:
                os.startfile(path)
            except Exception as e:
                print(f"파일 실행 오류: {e}")
        elif os.path.isdir(path):
            self.navigate_to(path)
    
    def _show_context_menu(self, position):
        """컨텍스트 메뉴 표시"""
        index = self.indexAt(position)
        
        if index.isValid():
            path = self.file_model.filePath(index)
            if path and os.path.exists(path):
                self._show_fallback_menu(path, position)
                return
        
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLESHEET)
        
        action_new_folder = menu.addAction("➕ 새 폴더")
        action_new_folder.triggered.connect(self._create_new_folder)
        
        action_refresh = menu.addAction("🔄 새로고침")
        action_refresh.triggered.connect(self._refresh)
        
        menu.exec(self.viewport().mapToGlobal(position))
    
    def _show_fallback_menu(self, path, position):
        """Windows 탐색기와 유사한 전체 컨텍스트 메뉴"""
        index = self.indexAt(position)
        is_file = os.path.isfile(path)
        
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLESHEET)
        
        action_open = menu.addAction("📂 열기" if not is_file else "▶ 실행")
        action_open.triggered.connect(lambda: self._open_item(path))
        
        menu.addSeparator()
        
        action_cut = menu.addAction("✂️ 잘라내기 (Ctrl+X)")
        action_cut.triggered.connect(lambda: self._cut_item(path))
        
        action_copy = menu.addAction("📋 복사 (Ctrl+C)")
        action_copy.triggered.connect(lambda: self._copy_item(path))
        
        action_paste = menu.addAction("📥 붙여넣기 (Ctrl+V)")
        action_paste.triggered.connect(self._paste_item)
        action_paste.setEnabled(self._has_clipboard_files())
        
        menu.addSeparator()
        
        action_rename = menu.addAction("✏️ 이름 변경 (F2)")
        action_rename.triggered.connect(lambda: self._rename_item(index))
        
        action_delete = menu.addAction("🗑️ 삭제 (Delete)")
        action_delete.triggered.connect(lambda: self._delete_item(path))
        
        menu.addSeparator()
        
        new_menu = menu.addMenu("➕ 새로 만들기")
        new_menu.setStyleSheet(menu.styleSheet())
        
        action_new_folder = new_menu.addAction("📁 폴더")
        action_new_folder.triggered.connect(self._create_new_folder)
        
        action_new_txt = new_menu.addAction("📄 텍스트 문서")
        action_new_txt.triggered.connect(lambda: self._create_new_file(".txt"))
        
        menu.addSeparator()
        
        action_explorer = menu.addAction("📁 탐색기에서 열기")
        action_explorer.triggered.connect(lambda: self._open_in_explorer(path))
        
        action_properties = menu.addAction("ℹ️ 속성")
        action_properties.triggered.connect(lambda: self._show_properties(path))
        
        menu.addSeparator()
        
        action_refresh = menu.addAction("🔄 새로고침 (F5)")
        action_refresh.triggered.connect(self._refresh)
        
        menu.exec(self.viewport().mapToGlobal(position))
    
    def _cut_item(self, path):
        self._clipboard_path = path
        self._clipboard_mode = "cut"
        
    def _copy_item(self, path):
        self._clipboard_path = path
        self._clipboard_mode = "copy"
    
    def _rename_item(self, index):
        if not index.isValid():
            return
        self.setCurrentIndex(index)
        self.scrollTo(index)
        QTimer.singleShot(100, lambda: self.edit(index))
    
    def _paste_item(self):
        if not self._clipboard_path:
            return
        
        src = self._clipboard_path
        dst_folder = self.current_path
        dst = os.path.join(dst_folder, os.path.basename(src))
        
        if os.path.exists(dst):
            dst = get_unique_filename(dst)
        
        try:
            if self._clipboard_mode == "cut":
                shutil.move(src, dst)
                self._clipboard_path = None
            else:
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            self._refresh()
        except Exception as e:
            _get_jarvis_msgbox().warning(self, "오류", f"붙여넣기 실패:\n{e}")
    
    def _has_clipboard_files(self):
        return bool(self._clipboard_path and os.path.exists(self._clipboard_path))
    
    def _create_new_file(self, extension):
        new_file_path = os.path.join(self.current_path, f"새 파일{extension}")
        
        counter = 1
        while os.path.exists(new_file_path):
            new_file_path = os.path.join(self.current_path, f"새 파일 ({counter}){extension}")
            counter += 1
        
        try:
            with open(new_file_path, 'w', encoding='utf-8') as f:
                pass
            new_index = self.file_model.index(new_file_path)
            self.setCurrentIndex(new_index)
            self.edit(new_index)
        except Exception as e:
            _get_jarvis_msgbox().warning(self, "오류", f"파일을 생성할 수 없습니다:\n{e}")
    
    def _show_properties(self, path):
        try:
            ctypes.windll.shell32.ShellExecuteW(None, "properties", path, None, None, 1)
        except Exception as e:
            info = []
            info.append(f"이름: {os.path.basename(path)}")
            info.append(f"위치: {os.path.dirname(path)}")
            
            if os.path.isfile(path):
                size = os.path.getsize(path)
                info.append(f"크기: {size:,} 바이트")
            else:
                info.append("유형: 폴더")
            
            mtime = os.path.getmtime(path)
            info.append(f"수정 날짜: {datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')}")
            
            _get_jarvis_msgbox().information(self, "속성", "\n".join(info))
    
    def _open_item(self, path):
        if os.path.isfile(path):
            try:
                os.startfile(path)
            except Exception as e:
                _get_jarvis_msgbox().warning(self, "오류", f"파일을 실행할 수 없습니다:\n{e}")
        elif os.path.isdir(path):
            self.navigate_to(path)
    
    def _delete_item(self, path):
        """단일 경로 삭제 (컨텍스트 메뉴용)"""
        self._delete_paths([path])

    def _delete_paths(self, paths):
        """여러 파일/폴더 동시 삭제"""
        if not paths:
            return
        msg_box = _get_jarvis_msgbox()

        if len(paths) == 1:
            name = os.path.basename(paths[0])
            confirm_msg = f"'{name}'을(를) 휴지통으로 이동하시겠습니까?"
        else:
            preview = "\n".join(f"  • {os.path.basename(p)}" for p in paths[:5])
            if len(paths) > 5:
                preview += f"\n  ... 외 {len(paths) - 5}개"
            confirm_msg = (f"선택한 {len(paths)}개 항목을 휴지통으로 이동하시겠습니까?\n\n{preview}")

        if not msg_box.question(self, "삭제 확인", confirm_msg):
            return

        # 영구 삭제(os.remove/rmtree) 대신 휴지통 — 복구 가능 (v1.1.77)
        from .file_browser import move_to_recycle_bin
        failed = []
        if not move_to_recycle_bin(paths):
            if move_to_recycle_bin.aborted:
                return   # 사용자가 경고창에서 취소 — 오류 아님
            failed = [(os.path.basename(p), "휴지통 이동 실패") for p in paths if os.path.exists(p)]

        if failed:
            msg = f"일부 삭제 실패 ({len(failed)}개):\n"
            for name, err in failed[:5]:
                msg += f"  • {name}: {err}\n"
            msg_box.warning(self, "오류", msg)
    
    def _open_in_explorer(self, path):
        try:
            if os.path.isfile(path):
                subprocess.run(['explorer', '/select,', path], creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.startfile(path)
        except Exception as e:
            _get_jarvis_msgbox().warning(self, "오류", f"탐색기를 열 수 없습니다:\n{e}")
    
    def _create_new_folder(self):
        new_folder_path = os.path.join(self.current_path, "새 폴더")
        
        counter = 1
        while os.path.exists(new_folder_path):
            new_folder_path = os.path.join(self.current_path, f"새 폴더 ({counter})")
            counter += 1
        
        try:
            os.makedirs(new_folder_path)
            new_index = self.file_model.index(new_folder_path)
            self.setCurrentIndex(new_index)
            self.edit(new_index)
        except Exception as e:
            _get_jarvis_msgbox().warning(self, "오류", f"폴더를 생성할 수 없습니다:\n{e}")
    
    def _refresh(self):
        self.file_model.setRootPath("")
        self.setRootIndex(self.file_model.index(self.current_path))
    
    def navigate_to(self, path):
        if os.path.exists(path) and os.path.isdir(path):
            self.setRootIndex(self.file_model.index(path))
            self.current_path = path
    
    def go_up(self):
        parent_path = os.path.dirname(self.current_path)
        if parent_path and os.path.exists(parent_path):
            self.navigate_to(parent_path)
    
    def startDrag(self, supportedActions):
        indexes = self.selectedIndexes()
        if not indexes:
            return
        
        paths = set()
        for index in indexes:
            if index.column() == 0:
                path = self.file_model.filePath(index)
                if path:
                    paths.add(path)
        
        if not paths:
            return
        
        # 2. PyQt 기본 드래그
        mime_data = QMimeData()
        urls = [QUrl.fromLocalFile(p) for p in paths]
        mime_data.setUrls(urls)
        
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)
    
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        
        drop_index = self.indexAt(event.position().toPoint())
        
        if drop_index.isValid():
            drop_path = self.file_model.filePath(drop_index)
            if os.path.isdir(drop_path):
                target_folder = drop_path
            else:
                target_folder = os.path.dirname(drop_path)
        else:
            target_folder = self.current_path
        
        paths = []
        for url in event.mimeData().urls():
            local_path = url.toLocalFile()
            if local_path and os.path.exists(local_path):
                if os.path.dirname(local_path) != target_folder:
                    paths.append(local_path)
        
        if paths:
            # 기존 동작(끌어다 놓기 = 이동)은 그대로 두고, Ctrl 을 누른 채 놓을 때만 복사.
            # proposedAction 으로 판정하면 탐색기가 다른 드라이브에서 끌 때 기본 제안이 '복사'라
            # 평소 하던 이동이 복사로 바뀌므로, 사용자의 명시적 의도(Ctrl)만 본다.
            _copy = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            moved_count = 0
            for src in paths:
                try:
                    dest = os.path.join(target_folder, os.path.basename(src))
                    if os.path.exists(dest):
                        dest = get_unique_filename(dest)
                    if _copy:
                        if os.path.isdir(src):
                            shutil.copytree(src, dest)
                        else:
                            shutil.copy2(src, dest)
                    else:
                        shutil.move(src, dest)
                    moved_count += 1
                except Exception as e:
                    print(f"이동 실패: {src} -> {e}")
            
            if moved_count > 0:
                self._refresh()
                self.items_dropped.emit(paths, target_folder)
        
        event.acceptProposedAction()


class GlassFrame(QFrame):
    """Semi-transparent container for panels with Jarvis HUD style (Custom Paint)"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(5, 5, 5, 5)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._glow_cache = None  # 글로우 픽스맵 캐시
        self._glow_cache_size = None

    def resizeEvent(self, event):
        self._glow_cache = None  # 크기 변경 시 캐시 무효화
        super().resizeEvent(event)

    def paintEvent(self, event):
        size = self.size()
        # 캐시된 글로우 픽스맵 재사용 (매 paint마다 10회 반복 드로우 방지)
        if self._glow_cache is None or self._glow_cache_size != size:
            from PyQt6.QtGui import QPixmap
            pixmap = QPixmap(size)
            pixmap.fill(Qt.GlobalColor.transparent)
            p = QPainter(pixmap)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            glow_color = QColor(128, 240, 255)
            rect = self.rect().adjusted(4, 4, -4, -4)
            for i in range(10):
                glow_color.setAlpha(100 - i * 10)
                p.setPen(QPen(glow_color, 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                r = rect.adjusted(-i, -i, i, i)
                p.drawRoundedRect(r, 5+i, 5+i)
            p.setPen(QPen(QColor("#80f0ff"), 1))
            p.setBrush(QColor(5, 15, 35, 80))
            p.drawRoundedRect(rect, 5, 5)
            p.end()
            self._glow_cache = pixmap
            self._glow_cache_size = size

        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._glow_cache)


class NeonButton(QPushButton):
    """Mac-style button with smooth 420ms hover animation + blue outer glow"""
    def __init__(self, text, parent=None, color="cyan", is_primary=False):
        super().__init__(text, parent)
        self.setFont(QFont("Malgun Gothic", 10, QFont.Weight.DemiBold))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(34)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.color_type = color
        self._is_primary = is_primary
        self._hover_progress = 0.0
        self._hover_anim = None

        self._apply_hover_state(0.0)

    def enterEvent(self, event):
        if self.isEnabled():
            self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def _animate_hover(self, target):
        from PyQt6.QtCore import QVariantAnimation, QEasingCurve
        if self._hover_anim is not None:
            try: self._hover_anim.stop()
            except RuntimeError: pass
        anim = QVariantAnimation(self)
        anim.setStartValue(float(self._hover_progress))
        anim.setEndValue(float(target))
        anim.setDuration(420)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._apply_hover_state)
        anim.start()
        self._hover_anim = anim

    def _apply_hover_state(self, value):
        self._hover_progress = float(value)
        t = max(0.0, min(1.0, float(value)))
        def lerp(a, b):
            return int(a + (b - a) * t)

        # 보더는 배경과 미리 합성해 불투명으로 (반투명이면 둥근 모서리에 점 아티팩트)
        def opaque_border(cr, cg, cb, ca, base):
            a = ca / 255.0
            return (round(cr * a + base[0] * (1 - a)),
                    round(cg * a + base[1] * (1 - a)),
                    round(cb * a + base[2] * (1 - a)))

        if self._is_primary:
            # 프라이머리: 차분한 블루, 살짝만 밝아짐
            bg1_r = lerp(40, 50); bg1_g = lerp(108, 125); bg1_b = lerp(180, 200)
            bg2_r = lerp(28, 38); bg2_g = lerp(88, 105);  bg2_b = lerp(150, 170)
            br_r = lerp(90, 115); br_g = lerp(165, 195); br_b = lerp(220, 245); br_a = lerp(110, 175)
            _eff = ((bg1_r + bg2_r) // 2, (bg1_g + bg2_g) // 2, (bg1_b + bg2_b) // 2)
            obr_r, obr_g, obr_b = opaque_border(br_r, br_g, br_b, br_a, _eff)
            self.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba({bg1_r}, {bg1_g}, {bg1_b}, 190),
                        stop:1 rgba({bg2_r}, {bg2_g}, {bg2_b}, 170));
                    border: 1px solid rgb({obr_r}, {obr_g}, {obr_b});
                    border-radius: 10px;
                    color: #e8f2ff;
                    font-weight: 600;
                    padding: 0 18px;
                    margin: 0;
                    letter-spacing: 0.3px;
                    outline: none;
                }}
                QPushButton:focus {{ outline: none; padding: 0 18px; margin: 0; }}
                QPushButton:pressed {{
                    background: rgba(30, 88, 150, 210);
                    padding: 0 18px;
                    margin: 0;
                    border: 1px solid rgb({obr_r}, {obr_g}, {obr_b});
                }}
                QPushButton:disabled {{
                    background: rgba(40, 55, 75, 90);
                    border: 1px solid #262e37;
                    color: #556070;
                    padding: 0 18px;
                    margin: 0;
                }}
            """)
        else:
            # 일반: base rgba(20,35,55,150) → hover 약간 밝아짐
            bg_r = lerp(20, 30);  bg_g = lerp(35, 52);  bg_b = lerp(55, 80);  bg_a = lerp(150, 190)
            br_r = lerp(120, 130); br_g = lerp(200, 225); br_b = lerp(245, 255); br_a = lerp(95, 170)
            obr_r, obr_g, obr_b = opaque_border(br_r, br_g, br_b, br_a, (bg_r, bg_g, bg_b))
            self.setStyleSheet(f"""
                QPushButton {{
                    background: rgba({bg_r}, {bg_g}, {bg_b}, {bg_a});
                    border: 1px solid rgb({obr_r}, {obr_g}, {obr_b});
                    border-radius: 10px;
                    color: #c0d0e0;
                    font-weight: 600;
                    padding: 0 16px;
                    margin: 0;
                    letter-spacing: 0.3px;
                    outline: none;
                }}
                QPushButton:focus {{ outline: none; padding: 0 16px; margin: 0; }}
                QPushButton:pressed {{
                    background: rgba(30, 55, 80, 220);
                    padding: 0 16px;
                    margin: 0;
                    border: 1px solid rgb({obr_r}, {obr_g}, {obr_b});
                }}
                QPushButton:disabled {{
                    background: rgba(30, 40, 55, 80);
                    border: 1px solid #232933;
                    color: #556070;
                    padding: 0 16px;
                    margin: 0;
                }}
            """)
