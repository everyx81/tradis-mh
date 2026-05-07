# JARVIS GUI 커스텀 위젯
"""
공통 커스텀 위젯 모음:
- DropListWidget: 드래그앤드롭 리스트
- JarvisPanel: SEARCH 패널 배경
- DraggableSearchResultList: Everything 검색 결과 리스트
- DraggableTreeView: 파일 탐색기 트리뷰
- GlassFrame: HUD 스타일 컨테이너
- NeonButton: 네온 버튼
"""

import os
import sys
import shutil
import subprocess
import ctypes
import datetime

from PyQt6.QtWidgets import (QWidget, QPushButton, QFrame, QListWidget, QTreeView,
                              QAbstractItemView, QMenu, QInputDialog, QApplication)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QMimeData, QUrl, pyqtProperty
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QDrag, QFileSystemModel, QCursor

from .styles import (DROP_LIST_STYLESHEET, DROP_LIST_HIGHLIGHT_STYLESHEET,
                     SEARCH_RESULT_STYLESHEET, TREE_VIEW_STYLESHEET, MENU_STYLESHEET)

# get_unique_filename 함수는 auto_rename에서 import
from auto_rename import get_unique_filename

# 순환 import 방지를 위해 지연 import 사용
def _get_jarvis_msgbox():
    from .dialogs import JarvisMessageBox
    return JarvisMessageBox


def create_windows_file_drop_data(paths):
    """Windows CF_HDROP 형식의 바이트 데이터 생성 (카카오톡 등 외부 프로그램 호환)"""
    import struct
    
    # DROPFILES 구조체: 20바이트 헤더 + 파일 경로들 (NULL 구분) + 이중 NULL 종료
    header_size = 20
    fWide = 1  # 유니코드 사용
    
    # 파일 경로들을 유니코드로 인코딩 (NULL 구분)
    file_data = b""
    for path in paths:
        # Windows 경로는 역슬래시 사용
        path = path.replace("/", "\\")
        file_data += path.encode("utf-16-le") + b"\x00\x00"
    file_data += b"\x00\x00"  # 이중 NULL 종료
    
    # DROPFILES 헤더 생성
    header = struct.pack("IIIII", header_size, 0, 0, 0, fWide)
    
    return header + file_data


def start_windows_shell_drag(paths, hwnd=None):
    """Windows Shell OLE 드래그 앤 드롭 실행 (카카오톡 호환)
    
    PyQt 드래그 대신 Windows 네이티브 OLE DoDragDrop을 사용합니다.
    마우스 버튼이 눌린 상태에서 호출되어야 합니다.
    """
    try:
        import ctypes
        from ctypes import wintypes, POINTER, byref, c_void_p, c_int
        import struct
        
        # ============ COM 인터페이스 정의 ============
        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32
        
        # CF_HDROP 형식 ID
        CF_HDROP = 15
        
        # DROPEFFECT 상수
        DROPEFFECT_NONE = 0
        DROPEFFECT_COPY = 1
        DROPEFFECT_MOVE = 2
        DROPEFFECT_LINK = 4
        
        # GMEM 상수
        GMEM_MOVEABLE = 0x0002
        GMEM_ZEROINIT = 0x0040
        
        # OLE 초기화
        ole32.OleInitialize(None)
        
        # CF_HDROP 데이터 생성
        header_size = 20
        file_data = b""
        for path in paths:
            path = path.replace("/", "\\")
            file_data += path.encode("utf-16-le") + b"\x00\x00"
        file_data += b"\x00\x00"  # 이중 NULL 종료
        
        header = struct.pack("IIIII", header_size, 0, 0, 0, 1)  # fWide=1 (유니코드)
        hdrop_data = header + file_data
        
        # HGLOBAL 메모리 할당
        hglobal = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(hdrop_data))
        if not hglobal:
            print("[Shell Drag] GlobalAlloc failed")
            return False
        
        ptr = kernel32.GlobalLock(hglobal)
        if ptr:
            ctypes.memmove(ptr, hdrop_data, len(hdrop_data))
            kernel32.GlobalUnlock(hglobal)
        else:
            kernel32.GlobalFree(hglobal)
            return False
        
        # 클립보드에 HDROP 설정 (Ctrl+V 지원)
        import win32clipboard
        try:
            win32clipboard.OpenClipboard(0)
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(CF_HDROP, hdrop_data)
            win32clipboard.CloseClipboard()
        except OSError:
            pass

        return True
        
    except Exception as e:
        print(f"[Shell Drag Error] {e}")
        import traceback
        traceback.print_exc()
        return False




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
        
        # 1. Windows 네이티브 OLE 드래그 시도 (카카오톡 등 외부 호환성용)
        try:
            from .ole_drag_drop import do_file_drag_drop
            # 별도 스레드에서 실행하지 않고 메인 스레드에서 실행 (DoDragDrop은 블로킹 함수)
            # 드래그 앤 드롭이 완료될 때까지 대기함
            if do_file_drag_drop(paths):
                return
        except Exception as e:
            print(f"OLE Drag failed: {e}")

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
            for url in urls:
                src_path = url.toLocalFile()
                if os.path.exists(src_path):
                    file_name = os.path.basename(src_path)
                    dest_path = os.path.join(self.current_folder, file_name) if self.current_folder else src_path
                    
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
        new_base, ok = QInputDialog.getText(self, "이름 변경", "새 이름을 입력하세요:", text=base_name)
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
        if msg_box.question(self, "삭제 확인", "정말 삭제하시겠습니까?"):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
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
            if msg_box.question(self, "삭제 확인", f"선택한 {count}개 항목을 삭제하시겠습니까?"):
                for item in items:
                    path = item.data(Qt.ItemDataRole.UserRole)
                    if path and os.path.exists(path):
                        try:
                            if os.path.isdir(path):
                                shutil.rmtree(path)
                            else:
                                os.remove(path)
                        except Exception as e:
                            print(f"삭제 실패: {e}")
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


# ... (중간 생략: DropListWidget의 나머지 메서드들) ...

class DraggableSearchResultList(QListWidget):
    """Everything 검색 결과를 표시하고 드래그를 지원하는 리스트"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        
        self.setStyleSheet(SEARCH_RESULT_STYLESHEET)
    
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
        
        # 1. Windows 네이티브 OLE 드래그 시도
        try:
            from .ole_drag_drop import do_file_drag_drop
            if do_file_drag_drop(paths):
                return
        except Exception as e:
            print(f"OLE Drag failed: {e}")
        
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

# ... (중간 생략) ...

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
        
        self.setStyleSheet(TREE_VIEW_STYLESHEET)
        
        self._clipboard_path = None
        self._clipboard_mode = "copy"
    
    # ... (중간 생략: keyPressEvent 등) ...
    
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
        
        # 1. Windows 네이티브 OLE 드래그 시도
        try:
            from .ole_drag_drop import do_file_drag_drop
            if do_file_drag_drop(list(paths)):
                return
        except Exception as e:
            print(f"OLE Drag failed: {e}")
        
        # 2. PyQt 기본 드래그
        mime_data = QMimeData()
        urls = [QUrl.fromLocalFile(p) for p in paths]
        mime_data.setUrls(urls)
        
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        result = drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction, Qt.DropAction.MoveAction)
        
        # 이동 완료 시 파일 목록 새로고침
        if result == Qt.DropAction.MoveAction:
            self.refresh_needed.emit()

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
        self._restore_style()
        event.accept()
    
    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = []
            for url in event.mimeData().urls():
                local_path = url.toLocalFile()
                if local_path and os.path.exists(local_path):
                    paths.append(local_path)
            
            if paths:
                self.items_dropped.emit(paths)
            
            event.acceptProposedAction()
        else:
            event.ignore()
        
        self._restore_style()
    
    def _set_highlight_style(self, highlight):
        if highlight:
            self.setStyleSheet(DROP_LIST_HIGHLIGHT_STYLESHEET)
        else:
            self._restore_style()

    def _restore_style(self):
        """원래 스타일로 복원"""
        self.setStyleSheet(DROP_LIST_STYLESHEET)

    def keyPressEvent(self, event):
        """키보드 단축키 처리"""
        items = self.selectedItems()
        path = items[0].data(Qt.ItemDataRole.UserRole) if items else None
        
        if event.key() == Qt.Key.Key_F2 and items:
            self._rename_item(items[0])
        elif event.key() == Qt.Key.Key_Delete and items:
            self._delete_selected_items()
        elif event.key() == Qt.Key.Key_F5:
            self.refresh_needed.emit()
        elif event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_C and path:
                self._copy_item(path)
            elif event.key() == Qt.Key.Key_X and path:
                self._cut_item(path)
            elif event.key() == Qt.Key.Key_V:
                self._paste_item()
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def _show_context_menu(self, position):
        item = self.itemAt(position)
        path = item.data(Qt.ItemDataRole.UserRole) if item else None
        
        menu = QMenu()
        menu.setStyleSheet(self.styleSheet())
        
        is_file = path and os.path.isfile(path)
        
        if path:
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
        
        if item:
            action_rename = menu.addAction("✏️ 이름 변경 (F2)")
            action_rename.triggered.connect(lambda: self._rename_item(item))
            
            action_delete = menu.addAction("🗑️ 삭제 (Delete)")
            action_delete.triggered.connect(self._delete_selected_items)
            
            menu.addSeparator()
        
        new_menu = menu.addMenu("➕ 새로 만들기")
        action_new_folder = new_menu.addAction("📁 폴더")
        action_new_folder.triggered.connect(self._create_new_folder)
        action_new_text = new_menu.addAction("📄 텍스트 문서")
        action_new_text.triggered.connect(lambda: self._create_new_file(".txt"))
        
        menu.addSeparator()
        
        if path:
            action_prop = menu.addAction("ℹ️ 속성")
            action_prop.triggered.connect(lambda: self._show_properties(path))
        
        action_refresh = menu.addAction("🔄 새로고침 (F5)")
        action_refresh.triggered.connect(lambda: self.refresh_needed.emit())
        
        menu.exec(self.mapToGlobal(position))

    def _open_item(self, path):
        if os.path.isfile(path):
            try:
                os.startfile(path)
            except Exception as e:
                pass
        elif os.path.isdir(path):
            subprocess.run(['explorer', path], creationflags=subprocess.CREATE_NO_WINDOW)

    def _rename_item(self, item):
        """아이템 이름 변경 (파일은 확장자 자동 보존)"""
        path = item.data(Qt.ItemDataRole.UserRole)
        basename = os.path.basename(path)
        # 파일이면 확장자 분리, 폴더면 그대로
        if os.path.isfile(path):
            base_name, ext = os.path.splitext(basename)
        else:
            base_name, ext = basename, ""
        new_base, ok = QInputDialog.getText(self, "이름 변경", "새 이름:", text=base_name)
        if ok and new_base:
            new_name = new_base + ext
            new_path = os.path.join(os.path.dirname(path), new_name)
            try:
                os.rename(path, new_path)
                self.refresh_needed.emit()
            except Exception as e:
                _get_jarvis_msgbox().warning(self, "오류", f"이름 변경 실패:\n{e}")

    def _delete_selected_items(self):
        items = self.selectedItems()
        if not items: return
        
        count = len(items)
        if _get_jarvis_msgbox().question(self, "삭제 확인", f"선택한 {count}개 항목을 삭제하시겠습니까?"):
            for item in items:
                path = item.data(Qt.ItemDataRole.UserRole)
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                    else:
                        shutil.rmtree(path)
                except Exception as e:
                    print(f"삭제 실패: {e}")
            self.refresh_needed.emit()

    def _copy_item(self, path):
        self._clipboard_path = path
        self._clipboard_mode = "copy"

    def _cut_item(self, path):
        self._clipboard_path = path
        self._clipboard_mode = "cut"

    def _paste_item(self):
        if not self._clipboard_path or not self.current_folder: return
        
        src = self._clipboard_path
        dst = os.path.join(self.current_folder, os.path.basename(src))
        
        try:
            if os.path.exists(dst):
                dst = get_unique_filename(dst)
            
            if self._clipboard_mode == "cut":
                shutil.move(src, dst)
                self._clipboard_path = None
            else:
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            self.refresh_needed.emit()
        except Exception as e:
            _get_jarvis_msgbox().warning(self, "오류", f"붙여넣기 실패:\n{e}")

    def _create_new_folder(self):
        if not self.current_folder: return
        new_path = os.path.join(self.current_folder, "새 폴더")
        counter = 1
        while os.path.exists(new_path):
            new_path = os.path.join(self.current_folder, f"새 폴더 ({counter})")
            counter += 1
        try:
            os.makedirs(new_path)
            self.refresh_needed.emit()
        except Exception as e:
            _get_jarvis_msgbox().warning(self, "오류", f"폴더 생성 실패:\n{e}")

    def _create_new_file(self, ext):
        if not self.current_folder: return
        new_path = os.path.join(self.current_folder, f"새 파일{ext}")
        counter = 1
        while os.path.exists(new_path):
            new_path = os.path.join(self.current_folder, f"새 파일 ({counter}){ext}")
            counter += 1
        try:
            with open(new_path, 'w') as f: pass
            self.refresh_needed.emit()
        except Exception as e:
            _get_jarvis_msgbox().warning(self, "오류", f"파일 생성 실패:\n{e}")

    def _show_properties(self, path):
        try:
            ctypes.windll.shell32.ShellExecuteW(None, "properties", path, None, None, 1)
        except OSError:
            _get_jarvis_msgbox().information(self, "정보", f"경로: {path}")

    def _has_clipboard_files(self):
        return bool(self._clipboard_path and os.path.exists(self._clipboard_path))


class JarvisPanel(QWidget):
    """JARVIS SEARCH 패널의 배경을 담당하는 단순 패널"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._core_opacity = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._glow_cache = None
        self._glow_cache_size = None

    def resizeEvent(self, event):
        self._glow_cache = None
        super().resizeEvent(event)

    def paintEvent(self, event):
        size = self.size()
        if self._glow_cache is None or self._glow_cache_size != size:
            from PyQt6.QtGui import QPixmap
            pixmap = QPixmap(size)
            pixmap.fill(Qt.GlobalColor.transparent)
            p = QPainter(pixmap)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            glow_color = QColor(128, 240, 255)
            rect = self.rect().adjusted(10, 10, -10, -10)
            for i in range(10):
                glow_color.setAlpha(100 - i * 10)
                p.setPen(QPen(glow_color, 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                r = rect.adjusted(-i, -i, i, i)
                p.drawRoundedRect(r, 8+i, 8+i)
            p.setPen(QPen(QColor("#80f0ff"), 1.5))
            p.setBrush(QColor(5, 15, 30, 210))
            p.drawRoundedRect(rect, 8, 8)
            p.end()
            self._glow_cache = pixmap
            self._glow_cache_size = size

        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._glow_cache)

    def get_core_opacity(self):
        return self._core_opacity

    def set_core_opacity(self, v):
        self._core_opacity = v

    core_opacity_prop = pyqtProperty(float, get_core_opacity, set_core_opacity)


class DraggableSearchResultList(QListWidget):
    """Everything 검색 결과를 표시하고 드래그를 지원하는 리스트"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        
        self.setStyleSheet(SEARCH_RESULT_STYLESHEET)
    
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
        
        # 1. Windows 네이티브 OLE 드래그 시도
        try:
            from .ole_drag_drop import do_file_drag_drop
            if do_file_drag_drop(paths):
                return
        except Exception as e:
            print(f"OLE Drag failed: {e}")
        
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
        
        self.setStyleSheet(TREE_VIEW_STYLESHEET)
        
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
            confirm_msg = f"'{name}'을(를) 삭제하시겠습니까?\n\n이 작업은 되돌릴 수 없습니다."
        else:
            preview = "\n".join(f"  • {os.path.basename(p)}" for p in paths[:5])
            if len(paths) > 5:
                preview += f"\n  ... 외 {len(paths) - 5}개"
            confirm_msg = (f"선택한 {len(paths)}개 항목을 삭제하시겠습니까?\n\n"
                          f"{preview}\n\n이 작업은 되돌릴 수 없습니다.")

        if not msg_box.question(self, "삭제 확인", confirm_msg):
            return

        failed = []
        for path in paths:
            try:
                if os.path.isfile(path):
                    os.remove(path)
                else:
                    shutil.rmtree(path)
            except Exception as e:
                failed.append((os.path.basename(path), str(e)))

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
        
        # 1. Windows 네이티브 OLE 드래그 시도
        try:
            from .ole_drag_drop import do_file_drag_drop
            if do_file_drag_drop(list(paths)):
                return
        except Exception as e:
            print(f"OLE Drag failed: {e}")
        
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
            moved_count = 0
            for src in paths:
                try:
                    dest = os.path.join(target_folder, os.path.basename(src))
                    if os.path.exists(dest):
                        dest = get_unique_filename(dest)
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
        # 버튼은 drop shadow 없이 색상 보간만 (클릭 시 흔들림 방지)
        self._hover_shadow = None

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
        from PyQt6.QtGui import QColor
        self._hover_progress = float(value)
        t = max(0.0, min(1.0, float(value)))
        def lerp(a, b):
            return int(a + (b - a) * t)

        if self._is_primary:
            # 프라이머리: 차분한 블루, 살짝만 밝아짐
            bg1_r = lerp(40, 50); bg1_g = lerp(108, 125); bg1_b = lerp(180, 200)
            bg2_r = lerp(28, 38); bg2_g = lerp(88, 105);  bg2_b = lerp(150, 170)
            br_r = lerp(90, 115); br_g = lerp(165, 195); br_b = lerp(220, 245); br_a = lerp(110, 175)
            self.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba({bg1_r}, {bg1_g}, {bg1_b}, 190),
                        stop:1 rgba({bg2_r}, {bg2_g}, {bg2_b}, 170));
                    border: 1px solid rgba({br_r}, {br_g}, {br_b}, {br_a});
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
                    border: 1px solid rgba({br_r}, {br_g}, {br_b}, {br_a});
                }}
                QPushButton:disabled {{
                    background: rgba(40, 55, 75, 90);
                    border: 1px solid rgba(100, 130, 160, 40);
                    color: #556070;
                    padding: 0 18px;
                    margin: 0;
                }}
            """)
            glow_alpha = lerp(0, 120)
        else:
            # 일반: base rgba(20,35,55,150) → hover 약간 밝아짐
            bg_r = lerp(20, 30);  bg_g = lerp(35, 52);  bg_b = lerp(55, 80);  bg_a = lerp(150, 190)
            br_r = lerp(120, 130); br_g = lerp(200, 225); br_b = lerp(245, 255); br_a = lerp(95, 170)
            self.setStyleSheet(f"""
                QPushButton {{
                    background: rgba({bg_r}, {bg_g}, {bg_b}, {bg_a});
                    border: 1px solid rgba({br_r}, {br_g}, {br_b}, {br_a});
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
                    border: 1px solid rgba({br_r}, {br_g}, {br_b}, {br_a});
                }}
                QPushButton:disabled {{
                    background: rgba(30, 40, 55, 80);
                    border: 1px solid rgba(80, 100, 130, 40);
                    color: #556070;
                    padding: 0 16px;
                    margin: 0;
                }}
            """)
            glow_alpha = lerp(0, 100)

        if hasattr(self, '_hover_shadow') and self._hover_shadow is not None:
            self._hover_shadow.setColor(QColor(0, 180, 230, glow_alpha))
