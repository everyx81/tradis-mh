"""
JARVIS 커스텀 알림 팝업 (시그널 기반)
한비로 스타일 밝은 배경의 알림 팝업
"""

from PyQt6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout, 
                              QApplication, QGraphicsDropShadowEffect, QFrame)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QColor, QPixmap


class JarvisToast(QWidget):
    """JARVIS 커스텀 토스트 알림 (한비로 스타일)"""

    _active_toasts = []
    MAX_TOASTS = 5  # 화면에 동시 표시 가능한 최대 토스트 수

    def __init__(self, title: str, message: str, duration: int = 10, position: str = "bottom-center",
                 is_sticky: bool = False, snooze_callback=None, complete_callback=None, parent=None):
        super().__init__(parent)
        self.title_text = title
        self.message_text = message
        self.duration = duration
        self.position = position
        self.is_sticky = is_sticky
        self.snooze_callback = snooze_callback
        self.complete_callback = complete_callback
        self._closing = False

        self.init_ui()
        self.setup_animation()
    
    def init_ui(self):
        # 윈도우 설정
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        self.setFixedWidth(380)
        self.setMinimumHeight(90)
        
        # 메인 컨테이너 (한비로 스타일 - 밝은 배경)
        self.container = QFrame(self)
        self.container.setObjectName("toast_container")
        self.container.setStyleSheet("""
            #toast_container {
                background-color: #ffffff;
                border: 1px solid #f2f2f2;
                border-radius: 18px;
            }
        """)
        
        # 그림자 효과 (더 부드럽게)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setXOffset(0)
        shadow.setYOffset(8)
        shadow.setColor(QColor(0, 0, 0, 30))
        self.container.setGraphicsEffect(shadow)
        
        # 메인 레이아웃
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.addWidget(self.container)
        
        # 컨테이너 내부 레이아웃
        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(15, 12, 15, 12)
        container_layout.setSpacing(12)
        
        # 왼쪽: 아이콘 영역 (원형 + 그라데이션)
        icon_frame = QFrame()
        icon_frame.setFixedSize(46, 46)
        icon_frame.setStyleSheet("""
            QFrame {
                background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, stop:0 #11c0ff, stop:1 #0078ff);
                border-radius: 23px;
                border: 1px solid rgba(255, 255, 255, 100);
            }
        """)
        icon_layout = QVBoxLayout(icon_frame)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_label = QLabel("📢")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("font-size: 18pt; background: transparent;")
        icon_layout.addWidget(icon_label)
        container_layout.addWidget(icon_frame)
        
        # 중앙: 텍스트 영역
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        
        # 앱 이름 + 시간
        header_layout = QHBoxLayout()
        app_label = QLabel("TRADIS MH")
        app_label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        app_label.setStyleSheet("color: #00aaff; background: transparent;")
        header_layout.addWidget(app_label)
        
        dot_label = QLabel("•")
        dot_label.setStyleSheet("color: #999; background: transparent; margin: 0 4px;")
        header_layout.addWidget(dot_label)
        
        from datetime import datetime
        time_label = QLabel(datetime.now().strftime("%H:%M"))
        time_label.setFont(QFont("Segoe UI", 8))
        time_label.setStyleSheet("color: #999; background: transparent;")
        header_layout.addWidget(time_label)
        
        header_layout.addStretch()
        
        # 닫기 버튼
        close_btn = QLabel("✕")
        close_btn.setFont(QFont("Segoe UI", 10))
        close_btn.setStyleSheet("color: #bbb; background: transparent;")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.mousePressEvent = lambda e: self.close_toast()
        header_layout.addWidget(close_btn)
        
        text_layout.addLayout(header_layout)
        
        # 제목
        title_label = QLabel(self.title_text)
        title_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #333; background: transparent;")
        title_label.setWordWrap(True)
        text_layout.addWidget(title_label)
        
        # 메시지
        msg_label = QLabel(self.message_text)
        msg_label.setFont(QFont("Segoe UI", 9))
        msg_label.setStyleSheet("color: #666; background: transparent;")
        msg_label.setWordWrap(True)
        text_layout.addWidget(msg_label)
        
        # [NEW] Sticky 모드일 경우 하단 액션 버튼 추가
        if self.is_sticky:
            action_layout = QHBoxLayout()
            action_layout.setSpacing(8)
            
            btn_style = """
                QPushButton {
                    background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 4px;
                    color: #555; font-size: 8pt; font-weight: bold; padding: 4px 12px;
                }
                QPushButton:hover { background-color: #e9ecef; color: #333; border: 1px solid #ccc; }
                QPushButton::menu-indicator { image: none; }
            """
            btn_primary_style = """
                QPushButton {
                    background-color: #e3f2fd; border: 1px solid #bbdefb; border-radius: 4px;
                    color: #1976d2; font-size: 8pt; font-weight: bold; padding: 4px 12px;
                }
                QPushButton:hover { background-color: #bbdefb; color: #1565c0; border: 1px solid #90caf9;}
            """
            
            from PyQt6.QtWidgets import QPushButton, QMenu
            
            # 스누즈 메뉴 버튼
            btn_snooze = QPushButton("⏰ 스누즈 ▾")
            btn_snooze.setStyleSheet(btn_style)
            btn_snooze.setCursor(Qt.CursorShape.PointingHandCursor)
            
            snooze_menu = QMenu(btn_snooze)
            snooze_menu.setStyleSheet("QMenu { background-color: #fff; border: 1px solid #ccc; font-size: 9pt; } QMenu::item:selected { background-color: #e3f2fd; color: #1976d2; }")
            snooze_menu.addAction("15분 뒤", lambda: self._on_snooze_clicked(15))
            snooze_menu.addAction("1시간 뒤", lambda: self._on_snooze_clicked(60))
            snooze_menu.addAction("내일 이 시간", lambda: self._on_snooze_clicked(1440))
            btn_snooze.setMenu(snooze_menu)
            action_layout.addWidget(btn_snooze)
            
            # 확인 (현재 팝업만 끄기)
            btn_ok = QPushButton("확인")
            btn_ok.setStyleSheet(btn_style)
            btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_ok.clicked.connect(self.close_toast)
            action_layout.addWidget(btn_ok)
            
            # 완료 (일정 자체를 완료 처리)
            btn_done = QPushButton("✔ 완료")
            btn_done.setStyleSheet(btn_primary_style)
            btn_done.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_done.clicked.connect(self._on_complete_clicked)
            action_layout.addWidget(btn_done)
            
            action_layout.addStretch()
            text_layout.addLayout(action_layout)
        
        container_layout.addLayout(text_layout, stretch=1)
        
        self.adjustSize()
    
    def _on_snooze_clicked(self, minutes=15):
        if self.snooze_callback:
            try:
                self.snooze_callback(minutes)
            except Exception as e:
                print(f"[Toast Snooze Error] {e}")
        self.close_toast()
        
    def _on_complete_clicked(self):
        if self.complete_callback:
            try:
                self.complete_callback()
            except Exception as e:
                print(f"[Toast Complete Error] {e}")
        self.close_toast()
    
    def setup_animation(self):
        self.slide_in_anim = QPropertyAnimation(self, b"pos")
        self.slide_in_anim.setDuration(500) # 조금 더 천천히 부드럽게
        self.slide_in_anim.setEasingCurve(QEasingCurve.Type.OutQuint) # 매우 부드러운 감속
        
        self.fade_out_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_out_anim.setDuration(400)
        self.fade_out_anim.setStartValue(1.0)
        self.fade_out_anim.setEndValue(0.0)
        self.fade_out_anim.finished.connect(self._on_fade_finished)
    
    def show_toast(self):
        # 최대 개수 초과 시 가장 오래된 토스트 제거
        while len(JarvisToast._active_toasts) >= self.MAX_TOASTS:
            oldest = JarvisToast._active_toasts[0]
            oldest.close_toast()

        screen = QApplication.primaryScreen().availableGeometry()

        y_offset = 10
        for toast in JarvisToast._active_toasts:
            if toast.isVisible():
                y_offset += toast.height() + 10

        if self.position == "bottom-center":
            start_x = (screen.width() - self.width()) // 2 + screen.x()
            end_x = start_x
            start_y = screen.bottom() + 10
            end_y = screen.bottom() - self.height() - y_offset
        else:
            start_x = screen.right() + 10
            end_x = screen.right() - self.width() - 10
            start_y = screen.bottom() - self.height() - y_offset
            end_y = start_y

        # 초기 위치를 화면 밖(시작점)으로 설정하여 깜빡임 방지
        self.move(int(start_x), int(start_y))
        self.show()

        JarvisToast._active_toasts.append(self)

        self.slide_in_anim.setStartValue(QPoint(int(start_x), int(start_y)))
        self.slide_in_anim.setEndValue(QPoint(int(end_x), int(end_y)))
        self.slide_in_anim.start()

        if not self.is_sticky:
            QTimer.singleShot(self.duration * 1000, self.close_toast)
    
    def close_toast(self):
        if self._closing:
            return
        self._closing = True
        if self.fade_out_anim.state() != QPropertyAnimation.State.Running:
            self.fade_out_anim.start()

    def _on_fade_finished(self):
        if self in JarvisToast._active_toasts:
            JarvisToast._active_toasts.remove(self)
            self._reposition_toasts()
        self.deleteLater()

    @staticmethod
    def _reposition_toasts():
        """남은 토스트들을 빈 공간 없이 재배치"""
        screen = QApplication.primaryScreen().availableGeometry()
        y_offset = 10
        for toast in JarvisToast._active_toasts:
            if not toast.isVisible():
                continue
            end_x = toast.pos().x()
            end_y = screen.bottom() - toast.height() - y_offset

            anim = QPropertyAnimation(toast, b"pos")
            anim.setDuration(200)
            anim.setEndValue(QPoint(end_x, int(end_y)))
            anim.setEasingCurve(QEasingCurve.Type.OutQuad)
            anim.start()
            # anim을 toast에 보관하여 GC 방지
            toast._reposition_anim = anim

            y_offset += toast.height() + 10

    def mousePressEvent(self, event):
        # Sticky 모드에서는 배경 클릭으로 닫히지 않음 (버튼으로만 닫기)
        if not self.is_sticky:
            self.close_toast()


class ToastSignalHandler(QObject):
    """알림 시그널 핸들러 (메인 스레드에서 토스트 생성)"""
    
    # title, message, duration, position, is_sticky, snooze_callback(object), complete_callback(object)
    toast_requested = pyqtSignal(str, str, int, str, bool, object, object)  
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.toast_requested.connect(self._create_toast)
    
    def _create_toast(self, title: str, message: str, duration: int, position: str, is_sticky: bool, snooze_callback: object, complete_callback: object):
        """메인 스레드에서 토스트 생성 (슬롯)"""
        toast = JarvisToast(title, message, duration, position, is_sticky, snooze_callback, complete_callback)
        toast.show_toast()
    
    def request_toast(self, title: str, message: str, duration: int = 10, position: str = "bottom-center", 
                      is_sticky: bool = False, snooze_callback=None, complete_callback=None):
        """토스트 요청 (어떤 스레드에서든 호출 가능)"""
        self.toast_requested.emit(title, message, duration, position, is_sticky, snooze_callback, complete_callback)


# 싱글톤 핸들러 (앱 전체에서 공유)
_toast_handler = None

def get_toast_handler():
    """전역 토스트 핸들러 반환 (lazy 초기화)"""
    global _toast_handler
    if _toast_handler is None:
        app = QApplication.instance()
        if app:
            _toast_handler = ToastSignalHandler()
    return _toast_handler

def show_custom_toast(title: str, message: str, duration: int = 10, position: str = "bottom-center",
                      is_sticky: bool = False, snooze_callback=None, complete_callback=None):
    """커스텀 토스트 표시 (편의 함수)"""
    handler = get_toast_handler()
    if handler:
        handler.request_toast(title, message, duration, position, is_sticky, snooze_callback, complete_callback)
        return True
    return False


# 테스트
if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    
    # 핸들러 테스트
    handler = get_toast_handler()
    handler.request_toast("🔔 테스트 알림", "TRADIS MH 커스텀 알림!", 5)
    
    QTimer.singleShot(2000, lambda: handler.request_toast("⏰ 일정 알림", "15분 후 회의", 5))
    QTimer.singleShot(4000, lambda: handler.request_toast("🚨 수출요청! #123", "📦 경로: ICN/BKK", 5))
    
    QTimer.singleShot(10000, app.quit)
    sys.exit(app.exec())
