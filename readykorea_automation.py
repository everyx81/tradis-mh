"""
JARVIS 수출 자동화 - ReadyKorea 자동 입력 모듈
pywinauto를 사용하여 ReadyKorea 프로그램에 수출 데이터를 자동 입력합니다.

v2.0: AI 기반 신고서 선택 기능 추가
- Gemini Vision으로 화면을 분석하여 적절한 신고서 자동 선택
"""

import time
from dataclasses import dataclass
from typing import Optional, Callable, Any, Dict
from enum import Enum

# pywinauto는 지연 임포트 (PyQt6 COM 충돌 방지)
# connect() 메서드에서 필요할 때만 임포트됨
PYWINAUTO_AVAILABLE = None  # None = 아직 확인 안 함, True/False = 확인됨
_pywinauto_modules = {}  # 지연 임포트된 모듈 저장

# AI 모듈 지연 임포트
SCREEN_AI_AVAILABLE = None
_screen_ai = None

def _lazy_import_screen_ai():
    """screen_ai 지연 임포트"""
    global SCREEN_AI_AVAILABLE, _screen_ai
    
    if SCREEN_AI_AVAILABLE is not None:
        return SCREEN_AI_AVAILABLE
    
    try:
        from core.screen_ai import screen_ai
        _screen_ai = screen_ai
        SCREEN_AI_AVAILABLE = True
        print("[ReadyKorea] AI 모듈 로드 완료")
    except ImportError as e:
        SCREEN_AI_AVAILABLE = False
        print(f"[경고] AI 모듈 로드 실패: {e}")
    
    return SCREEN_AI_AVAILABLE


def _lazy_import_pywinauto():
    """pywinauto 지연 임포트"""
    global PYWINAUTO_AVAILABLE, _pywinauto_modules
    
    if PYWINAUTO_AVAILABLE is not None:
        return PYWINAUTO_AVAILABLE
    
    try:
        from pywinauto import Application, Desktop
        from pywinauto.keyboard import send_keys
        from pywinauto.mouse import click, double_click
        
        _pywinauto_modules['Application'] = Application
        _pywinauto_modules['Desktop'] = Desktop
        _pywinauto_modules['send_keys'] = send_keys
        _pywinauto_modules['click'] = click
        _pywinauto_modules['double_click'] = double_click
        
        PYWINAUTO_AVAILABLE = True
    except ImportError:
        PYWINAUTO_AVAILABLE = False
        print("[경고] pywinauto 패키지가 없습니다. pip install pywinauto")
    
    return PYWINAUTO_AVAILABLE


class AutomationStatus(Enum):
    """자동화 작업 상태"""
    IDLE = "대기"
    CONNECTING = "ReadyKorea 연결 중"
    SEARCHING = "업체 검색 중"
    SELECTING = "신고서 선택 중"
    EDITING_HEADER = "헤더 수정 중"
    EDITING_DETAIL = "란내역 수정 중"
    COMPLETED = "완료"
    ERROR = "오류"


@dataclass
class ReadyKoreaFields:
    """ReadyKorea UI 필드 정의 (AutomationId + 좌표 기반)"""
    # 버튼 (ID, 중심좌표X, 중심좌표Y)
    BTN_EXPORT_DECLARATION: int = 267120  # 수출신고서
    BTN_EXPORT_LIST: int = 72816          # 수출목록 (F1)
    BTN_EXPORT_DETAIL: int = 72814        # 수출상세 (F2)
    BTN_MODIFY: int = 2629810             # 수정
    BTN_RAN_DETAIL: int = 401138          # 란내역 (F3)
    BTN_RAN_MODIFY: int = 401622          # 란수정
    BTN_COPY_APPROVE: int = 467536        # 복사승인
    
    # 검색
    EDIT_SEARCH: int = 1001               # 검색 필드
    
    # 헤더 입력 필드
    EDIT_TOTAL_WEIGHT: int = 466768       # 총중량
    EDIT_TOTAL_PACKAGE: int = 466670      # 총포장갯수
    EDIT_PAYMENT_AMOUNT: int = 925870     # 결제금액
    EDIT_INVOICE: int = 74158             # 송품장
    
    # 란내역 입력 필드
    EDIT_NET_WEIGHT: int = 74194          # 순중량
    EDIT_PACKAGE_COUNT: int = 74204       # 포장갯수
    EDIT_QUANTITY: int = 205146           # 수량
    EDIT_UNIT_PRICE: int = 598144         # 단가
    EDIT_AMOUNT: int = 335868             # 금액
    
    # 그리드
    GRID_DECLARATIONS: int = 72750        # 1번째 신고서 그리드
    
    # 좌표 정보 (AutomationId로 찾지 못할 경우 폴백용)
    # 형식: (left, top, right, bottom)
    COORDS = {
        267120: (112, 990, 222, 1041),    # 수출신고서
        1001: (695, 157, 866, 176),       # 검색
        72816: (7, 80, 102, 107),         # 수출목록
        72814: (106, 80, 201, 107),       # 수출상세
        2629810: (541, 170, 611, 220),    # 수정
        466768: (1097, 495, 1248, 515),   # 총중량
        466670: (1097, 521, 1387, 541),   # 총포장갯수
        925870: (1166, 547, 1387, 567),   # 결제금액
        401138: (515, 150, 625, 177),     # 란내역
        74158: (1206, 347, 1475, 367),    # 송품장
        74194: (1723, 248, 1875, 268),    # 순중량
        74204: (1723, 298, 1875, 318),    # 포장갯수
        401622: (541, 566, 611, 616),     # 란수정
        205146: (1672, 613, 1772, 633),   # 수량
        598144: (1672, 638, 1772, 658),   # 단가
        335868: (1672, 663, 1772, 683),   # 금액
        467536: (663, 542, 960, 582),     # 복사승인
        72750: (4, 185, 1888, 872),       # 1번째 신고서 그리드
    }


@dataclass
class ExportInputData:
    """수출 입력 데이터"""
    company_name: str = "주식회사 와이에스씨"  # 검색할 업체명
    
    # 헤더 정보
    total_weight: float = 0.0      # 총중량
    total_package: int = 0         # 총포장갯수
    payment_amount: float = 0.0    # 결제금액
    
    # 란내역 정보
    net_weight: float = 0.0        # 순중량
    package_count: int = 0         # 포장갯수
    quantity: int = 0              # 수량
    unit_price: float = 0.0        # 단가
    amount: float = 0.0            # 금액
    
    # AI 선택용 추가 정보
    item_name: str = ""            # 품명
    route: str = ""                # 경로 (ICN/BKK 등)
    is_free: bool = False          # 무상 여부 (무상=True, 유상=False)
    
    @classmethod
    def from_export_data(cls, export_data):
        """ExportData 객체에서 변환"""
        qty = int(export_data.수량)
        return cls(
            total_weight=export_data.중량,
            total_package=qty,  # 수량과 동일
            payment_amount=export_data.총액,
            net_weight=export_data.중량,
            package_count=qty,  # 수량과 동일
            quantity=qty,
            unit_price=export_data.단가,
            amount=export_data.총액,
            item_name=getattr(export_data, '품명', ''),
            route=getattr(export_data, 'route', ''),
            is_free=getattr(export_data, 'is_free', False)
        )


class ReadyKoreaAutomation:
    """ReadyKorea 자동 입력 클래스"""
    
    WINDOW_TITLE = "레디코리아"  # ReadyKorea 윈도우 타이틀
    
    def __init__(self, on_status_change: Optional[Callable[[AutomationStatus, str], None]] = None,
                 use_ai_selection: bool = True):
        """
        Args:
            on_status_change: 상태 변경 콜백 (status, message)
            use_ai_selection: AI 기반 신고서 선택 사용 여부 (기본: True)
        """
        self.fields = ReadyKoreaFields()
        self.app: Optional[Application] = None
        self.main_window = None
        self.on_status_change = on_status_change
        self._running = False
        self.use_ai_selection = use_ai_selection
        self._last_ai_result = None  # 마지막 AI 분석 결과 저장
        
    def _update_status(self, status: AutomationStatus, message: str = ""):
        """상태 업데이트 및 콜백 호출"""
        if self.on_status_change:
            self.on_status_change(status, message)
        print(f"[ReadyKorea] {status.value}: {message}")
    
    def connect(self) -> bool:
        """ReadyKorea 프로그램에 연결"""
        # 지연 임포트 실행
        if not _lazy_import_pywinauto():
            self._update_status(AutomationStatus.ERROR, "pywinauto 패키지가 설치되지 않았습니다")
            return False

        self._update_status(AutomationStatus.CONNECTING, "ReadyKorea 프로그램 검색 중...")

        try:
            Application = _pywinauto_modules['Application']

            # win32gui로 ReadyKorea 창 찾기 (Desktop(backend="uia") 사용 금지)
            # Desktop(backend="uia")는 모든 창의 접근성 트리에 접근하여
            # Chrome/Edge 등에 심각한 메모리 누수를 유발하므로 win32gui로 대체
            import win32gui

            target_hwnd = None
            def enum_callback(hwnd, _):
                nonlocal target_hwnd
                if target_hwnd:
                    return
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd)
                if title and ("레디코리아" in title or "ReadyKorea" in title or "READYKOREA" in title):
                    target_hwnd = hwnd

            win32gui.EnumWindows(enum_callback, None)

            if not target_hwnd:
                self._update_status(AutomationStatus.ERROR, "ReadyKorea 프로그램을 찾을 수 없습니다")
                return False

            # 찾은 핸들로 직접 연결 (UIA 전체 스캔 없이 대상 창에만 접근)
            self.app = Application(backend="uia").connect(handle=target_hwnd)
            self.main_window = self.app.window(handle=target_hwnd)
            
            # 포커스
            self.main_window.set_focus()
            time.sleep(0.3)
            
            self._update_status(AutomationStatus.IDLE, "ReadyKorea 연결 완료")
            return True
            
        except Exception as e:
            self._update_status(AutomationStatus.ERROR, f"연결 실패: {e}")
            return False
    
    def _find_element_by_id(self, automation_id: int):
        """AutomationId로 요소 찾기 (descendants 스캔 + child_window 폴백)"""
        str_id = str(automation_id)
        
        # 방법 1: descendants 스캔 (Delphi VCL 컨트롤용)
        try:
            for element in self.main_window.descendants():
                try:
                    if hasattr(element, 'automation_id'):
                        elem_id = element.automation_id()
                    elif hasattr(element, 'element_info'):
                        elem_id = element.element_info.automation_id
                    else:
                        continue
                    
                    if str(elem_id) == str_id:
                        return element
                except Exception:
                    continue
        except Exception:
            pass
        
        # 방법 2: child_window (일반 컨트롤용)
        try:
            element = self.main_window.child_window(auto_id=str_id)
            if element.exists():
                return element
        except Exception:
            pass

        return None
    
    def _click_by_coords(self, automation_id: int, wait: float = 0.15) -> bool:
        """좌표 기반 클릭 (폴백용)"""
        try:
            click = _pywinauto_modules.get('click')
            if not click:
                return False
            
            coords = self.fields.COORDS.get(automation_id)
            if coords:
                left, top, right, bottom = coords
                center_x = (left + right) // 2
                center_y = (top + bottom) // 2
                
                # ReadyKorea 윈도우 위치 보정
                if self.main_window:
                    try:
                        rect = self.main_window.rectangle()
                        # 윈도우가 (0, 0)이 아니면 오프셋 적용
                        # 참고: 좌표가 이미 절대좌표라면 보정 불필요
                    except Exception:
                        pass
                
                click(coords=(center_x, center_y))
                time.sleep(wait)
                print(f"[ReadyKorea] 좌표 클릭 성공 (ID: {automation_id}, 좌표: {center_x}, {center_y})")
                return True
        except Exception as e:
            print(f"[ReadyKorea] 좌표 클릭 실패 (ID: {automation_id}): {e}")
        return False
    
    def _click_element(self, automation_id: int, wait: float = 0.15) -> bool:
        """요소 클릭 (좌표 우선 → AutomationId 폴백)"""
        # 방법 1: 좌표 클릭 (속도 빠름)
        if self._click_by_coords(automation_id, wait):
            return True
            
        # 방법 2: AutomationId로 찾아서 클릭 (느림)
        try:
            print(f"[ReadyKorea] 좌표 클릭 실패, ID 검색 시도 (ID: {automation_id})")
            element = self._find_element_by_id(automation_id)
            if element and element.exists():
                element.click_input()
                time.sleep(wait)
                print(f"[ReadyKorea] AutomationId 클릭 성공 (ID: {automation_id})")
                return True
        except Exception as e:
            print(f"[ReadyKorea] AutomationId 클릭 실패 (ID: {automation_id}): {e}")
        
        return False
    
    def _double_click_element(self, automation_id: int, wait: float = 0.15) -> bool:
        """요소 더블클릭 (좌표 우선 → AutomationId 폴백)"""
        # 방법 1: 좌표로 더블클릭
        try:
            double_click = _pywinauto_modules.get('double_click')
            if double_click:
                coords = self.fields.COORDS.get(automation_id)
                if coords:
                    left, top, right, bottom = coords
                    center_x = (left + right) // 2
                    center_y = (top + bottom) // 2
                    
                    # ReadyKorea 윈도우 위치 보정은 _click_by_coords 참고 (생략 가능하면 생략)
                    
                    double_click(coords=(center_x, center_y))
                    time.sleep(wait)
                    print(f"[ReadyKorea] 좌표 더블클릭 성공 (ID: {automation_id})")
                    return True
        except Exception as e:
            print(f"[ReadyKorea] 좌표 더블클릭 실패 (ID: {automation_id}): {e}")
            
        # 방법 2: AutomationId로 찾아서 더블클릭
        try:
            print(f"[ReadyKorea] 좌표 더블클릭 실패, ID 검색 시도 (ID: {automation_id})")
            element = self._find_element_by_id(automation_id)
            if element and element.exists():
                element.double_click_input()
                time.sleep(wait)
                print(f"[ReadyKorea] AutomationId 더블클릭 성공 (ID: {automation_id})")
                return True
        except Exception as e:
            print(f"[ReadyKorea] AutomationId 더블클릭 실패 (ID: {automation_id}): {e}")
        
        return False
    
    def _set_text(self, automation_id: int, value: str, clear_first: bool = True, wait: float = 0.03) -> bool:
        """텍스트 입력 (좌표 기반 클릭 우선 - 속도 최적화)"""
        send_keys = _pywinauto_modules.get('send_keys')
        click = _pywinauto_modules.get('click')
        if not send_keys:
            return False
        
        clicked = False
        
        # 방법 1: 좌표로 클릭 (빠름 - 우선 사용)
        if click:
            try:
                coords = self.fields.COORDS.get(automation_id)
                if coords:
                    left, top, right, bottom = coords
                    center_x = (left + right) // 2
                    center_y = (top + bottom) // 2
                    click(coords=(center_x, center_y))
                    clicked = True
            except Exception as e:
                print(f"[ReadyKorea] 좌표 클릭 실패 (ID: {automation_id}): {e}")
        
        # 방법 2: AutomationId로 클릭 (폴백 - 느림)
        if not clicked:
            try:
                element = self._find_element_by_id(automation_id)
                if element and element.exists():
                    element.click_input()
                    clicked = True
            except Exception as e:
                print(f"[ReadyKorea] AutomationId 클릭 실패 (ID: {automation_id}): {e}")
        
        if not clicked:
            print(f"[ReadyKorea] 텍스트 필드를 찾을 수 없음 (ID: {automation_id})")
            return False
        
        # Home + Shift+End로 전체 선택 후 붙여넣기 (최소 대기)
        time.sleep(0.02)
        send_keys("{HOME}")  # 맨 앞으로
        time.sleep(0.01)
        send_keys("+{END}")  # Shift+End: 끝까지 선택
        time.sleep(0.02)
        
        try:
            import pyperclip
            pyperclip.copy(value)
            send_keys("^v")  # 붙여넣기
        except ImportError:
            escaped_value = value.replace("{", "{{").replace("}", "}}")
            send_keys(escaped_value, with_spaces=True)
        
        time.sleep(wait)
        return True
    
    def _send_key(self, key: str, wait: float = 0.1):
        """키보드 입력"""
        send_keys = _pywinauto_modules.get('send_keys')
        if send_keys:
            send_keys(key)
            time.sleep(wait)
    
    def _select_declaration_with_ai(self, export_data: Dict[str, Any]) -> int:
        """
        AI를 사용하여 적절한 신고서 선택
        
        Args:
            export_data: 수출 데이터 (품명, 총액, route 등)
            
        Returns:
            선택할 행 번호 (1-based), AI 사용 불가 시 1 반환
        """
        if not self.use_ai_selection:
            print("[ReadyKorea] AI 선택 비활성화됨, 첫 번째 신고서 선택")
            return 1
        
        if not _lazy_import_screen_ai():
            print("[ReadyKorea] AI 모듈 사용 불가, 첫 번째 신고서 선택")
            return 1
        
        self._update_status(AutomationStatus.SELECTING, "AI가 화면을 분석하고 있습니다...")
        
        try:
            result = _screen_ai.analyze_declarations_screen(export_data)
            self._last_ai_result = result
            
            if "error" in result:
                print(f"[ReadyKorea] AI 분석 오류: {result['error']}")
                return 1
            
            selected_row = result.get("selected_row", 1)
            reason = result.get("reason", "AI 분석 결과")
            confidence = result.get("confidence", 0.5)
            
            print(f"[ReadyKorea] AI 선택: {selected_row}번 행 (확신도: {confidence:.0%})")
            print(f"[ReadyKorea] 선택 이유: {reason}")
            
            self._update_status(
                AutomationStatus.SELECTING, 
                f"AI 선택: {selected_row}번 신고서 (확신도: {confidence:.0%})"
            )
            
            return selected_row
            
        except Exception as e:
            print(f"[ReadyKorea] AI 선택 실패: {e}")
            return 1
    
    def _navigate_to_row(self, target_row: int):
        """
        그리드에서 특정 행으로 이동
        
        Args:
            target_row: 이동할 행 번호 (1-based)
        """
        if target_row <= 1:
            return  # 첫 번째 행은 기본 선택
        
        # 그리드 클릭 후 아래 화살표로 이동
        self._click_element(self.fields.GRID_DECLARATIONS, wait=0.1)
        
        for _ in range(target_row - 1):
            self._send_key("{DOWN}", wait=0.05)
        
        time.sleep(0.1)
    
    def run_automation(self, data: ExportInputData) -> bool:
        """
        전체 자동화 워크플로우 실행
        
        워크플로우:
        1. 수출신고서 클릭
        2. 검색 더블클릭 → 업체명 입력
        3. 1번 신고서 선택 → Alt+V → Enter×2
        4. 수출상세(F2) → 수정
        5. 총중량, 포장갯수, 결제금액 입력
        6. 란내역(F3) → Enter → 순중량, 포장갯수 입력
        7. 란수정 → 수량, 단가, 금액 입력
        8. 수출목록(F1)
        """
        if not self.main_window:
            if not self.connect():
                return False
        
        self._running = True
        
        try:
            # 1. 수출신고서 클릭
            self._update_status(AutomationStatus.SEARCHING, "수출신고서 버튼 클릭")
            self._click_element(self.fields.BTN_EXPORT_DECLARATION, wait=0.2)
            
            # 2. 검색 더블클릭 + 업체명 입력 (클립보드로 한글 입력 - IME 첫 글자 누락 방지)
            self._update_status(AutomationStatus.SEARCHING, f"업체 검색: {data.company_name}")
            self._double_click_element(self.fields.EDIT_SEARCH, wait=0.15)
            time.sleep(0.05)  # IME 안정화 대기 (최소화)
            
            # 클립보드를 통한 붙여넣기 (한글 첫 글자 누락 방지)
            try:
                import pyperclip
                pyperclip.copy(data.company_name)
                send_keys = _pywinauto_modules.get('send_keys')
                if send_keys:
                    send_keys("^a")  # 전체 선택
                    time.sleep(0.02)
                    send_keys("^v")  # 붙여넣기
                    time.sleep(0.05)
                    send_keys("{ENTER}")  # 검색 실행
            except ImportError:
                # pyperclip 없으면 기존 방식 사용 (첫 글자 누락 가능성 있음)
                send_keys = _pywinauto_modules.get('send_keys')
                if send_keys:
                    send_keys(data.company_name, with_spaces=True)
                    send_keys("{ENTER}")  # 검색 실행
            time.sleep(0.25)  # 검색 결과 로딩 대기 (필수)
            
            # 3. AI 기반 신고서 선택 (또는 첫 번째 신고서)
            export_data_dict = {
                "품명": getattr(data, 'item_name', ''),
                "총액": data.payment_amount,
                "수량": data.quantity,
                "route": getattr(data, 'route', ''),
                "is_free": getattr(data, 'is_free', False),  # 무상 여부
            }
            
            selected_row = self._select_declaration_with_ai(export_data_dict)
            
            # 선택한 행으로 이동
            self._update_status(AutomationStatus.SELECTING, f"{selected_row}번 신고서 선택 중")
            self._navigate_to_row(selected_row)
            
            # 복사 (Alt+V → Enter×3)
            self._send_key("%v", wait=0.08)  # Alt+V
            self._send_key("{ENTER}", wait=0.08)  # Enter 1
            self._send_key("{ENTER}", wait=0.08)  # Enter 2
            self._send_key("{ENTER}", wait=0.08)  # Enter 3
            time.sleep(0.15)  # 화면 전환 대기
            
            # 4. 헤더 정보 입력: 총중량, 총포장갯수, 결제금액 (정수로 입력)
            self._update_status(AutomationStatus.EDITING_HEADER, "헤더 정보 입력 중")
            self._set_text(self.fields.EDIT_TOTAL_WEIGHT, str(int(data.total_weight)))
            self._set_text(self.fields.EDIT_TOTAL_PACKAGE, str(int(data.total_package)))
            self._set_text(self.fields.EDIT_PAYMENT_AMOUNT, str(int(data.payment_amount)))
            
            # 5. 란내역 (F3) → Enter → 송품장(오늘 날짜), 순중량(총중량-10), 포장갯수
            self._update_status(AutomationStatus.EDITING_DETAIL, "란내역 정보 입력 중")
            self._send_key("{F3}", wait=0.15)  # 란내역
            self._send_key("{ENTER}", wait=0.08)
            
            # 송품장 = 오늘 날짜 (형식: YYYY.MM.DD)
            from datetime import datetime
            invoice_date = datetime.now().strftime("%Y.%m.%d")
            self._set_text(self.fields.EDIT_INVOICE, invoice_date)
            
            # 순중량 = 총중량 - 10 (정수)
            net_weight_calc = max(0, int(data.total_weight) - 10)
            self._set_text(self.fields.EDIT_NET_WEIGHT, str(net_weight_calc))
            self._set_text(self.fields.EDIT_PACKAGE_COUNT, str(int(data.package_count)))
            
            # 6. 란수정 (Alt+E) → 수량, 단가, 금액 (정수로 입력)
            self._send_key("%e", wait=0.15)  # Alt+E (란수정)
            self._set_text(self.fields.EDIT_QUANTITY, str(int(data.quantity)))
            self._set_text(self.fields.EDIT_UNIT_PRICE, str(int(data.unit_price)))
            self._set_text(self.fields.EDIT_AMOUNT, str(int(data.amount)))
            
            # 7. 수출목록 복귀 (F1) + Enter×2
            self._send_key("{F1}", wait=0.15)
            self._send_key("{ENTER}", wait=0.08)
            self._send_key("{ENTER}", wait=0.08)
            
            self._update_status(AutomationStatus.COMPLETED, "자동 입력 완료")
            return True
            
        except Exception as e:
            self._update_status(AutomationStatus.ERROR, f"자동화 실패: {e}")
            return False
        finally:
            self._running = False
    
    def stop(self):
        """자동화 중지"""
        self._running = False
        self._update_status(AutomationStatus.IDLE, "자동화 중지됨")
    
    def is_running(self) -> bool:
        """실행 중 여부"""
        return self._running


# 테스트용
if __name__ == "__main__":
    print("=== ReadyKorea Automation Test ===")
    
    if not _lazy_import_pywinauto():
        print("pywinauto가 설치되지 않았습니다.")
        print("설치: pip install pywinauto")
        exit(1)
    
    # 테스트 데이터
    test_data = ExportInputData(
        company_name="주식회사 와이에스씨",
        total_weight=10.5,
        total_package=1,
        payment_amount=1000.00,
        net_weight=10.5,
        package_count=1,
        quantity=100,
        unit_price=10.00,
        amount=1000.00
    )
    
    def on_status(status, msg):
        print(f"[상태] {status.value}: {msg}")
    
    automation = ReadyKoreaAutomation(on_status_change=on_status)
    
    print("\n[테스트] ReadyKorea 연결 시도...")
    if automation.connect():
        print("[테스트] 연결 성공! 자동화 실행 (3초 후)...")
        time.sleep(3)
        
        result = automation.run_automation(test_data)
        print(f"\n[결과] 자동화 {'성공' if result else '실패'}")
    else:
        print("[테스트] 연결 실패 - ReadyKorea 프로그램이 실행 중인지 확인하세요")
