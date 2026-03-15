# JARVIS Core - Screen AI
"""
Gemini AI 기반 화면 분석 모듈
레디코리아 화면을 캡처하고 AI로 분석하여 적절한 신고서를 선택합니다.
"""

import io
import json
import re
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass

try:
    import pyautogui
    from PIL import Image
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    print("[경고] pyautogui 또는 PIL 패키지가 없습니다. pip install pyautogui pillow")

from .config import get_client


@dataclass
class DeclarationInfo:
    """신고서 정보"""
    row_number: int  # 행 번호 (1-based)
    company_name: str  # 업체명
    bl_number: str  # B/L 번호
    amount: float  # 금액
    destination: str  # 목적지
    confidence: float  # AI 확신도 (0.0 ~ 1.0)


class ScreenAI:
    """레디코리아 화면을 Gemini Vision으로 분석"""
    
    def __init__(self):
        self.model_id = 'gemini-3-flash-preview'
        
    def capture_window(self, window_handle=None) -> Optional[bytes]:
        """
        윈도우 캡처 (JPEG 바이트로 반환)
        
        Args:
            window_handle: 특정 윈도우 핸들 (None이면 전체 화면)
            
        Returns:
            JPEG 이미지 바이트 또는 None
        """
        if not PYAUTOGUI_AVAILABLE:
            print("[오류] pyautogui가 설치되지 않았습니다")
            return None
            
        try:
            # 전체 화면 캡처 (윈도우 핸들 지정은 추후 구현)
            screenshot = pyautogui.screenshot()
            
            # JPEG로 변환
            img_byte_arr = io.BytesIO()
            try:
                screenshot.save(img_byte_arr, format='JPEG', quality=85)
                return img_byte_arr.getvalue()
            finally:
                img_byte_arr.close()
            
        except Exception as e:
            print(f"[오류] 화면 캡처 실패: {e}")
            return None
    
    def capture_region(self, left: int, top: int, width: int, height: int) -> Optional[bytes]:
        """
        특정 영역 캡처
        
        Args:
            left, top, width, height: 캡처 영역
            
        Returns:
            JPEG 이미지 바이트 또는 None
        """
        if not PYAUTOGUI_AVAILABLE:
            return None
            
        try:
            screenshot = pyautogui.screenshot(region=(left, top, width, height))
            img_byte_arr = io.BytesIO()
            try:
                screenshot.save(img_byte_arr, format='JPEG', quality=85)
                return img_byte_arr.getvalue()
            finally:
                img_byte_arr.close()
        except Exception as e:
            print(f"[오류] 영역 캡처 실패: {e}")
            return None
    
    def analyze_declarations_screen(self, export_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        레디코리아 신고서 목록 화면을 분석하여 적절한 신고서 선택
        
        Args:
            export_data: 수출 데이터 (품명, 총액, 목적지 등)
            
        Returns:
            {
                "selected_row": int,  # 선택할 행 번호 (1-based)
                "reason": str,  # 선택 이유
                "declarations": list,  # 화면에 보이는 신고서 목록
                "confidence": float  # AI 확신도
            }
        """
        client = get_client()
        if client is None:
            return {"error": "Gemini API 클라이언트가 초기화되지 않았습니다", "selected_row": 1}
        
        # 화면 캡처
        img_data = self.capture_window()
        if not img_data:
            return {"error": "화면 캡처 실패", "selected_row": 1}
        
        # 프롬프트 생성
        prompt = self._build_declaration_selection_prompt(export_data)

        try:
            from google.genai import types
            response = client.models.generate_content(
                model=f"models/{self.model_id}",
                contents=[
                    prompt,
                    types.Part.from_bytes(data=img_data, mime_type="image/jpeg")
                ]
            )
            
            text_response = response.text.strip()
            
            # JSON 추출
            text_response = re.sub(r'```(?:json)?\n?(.*?)\n?```', r'\1', text_response, flags=re.DOTALL).strip()
            match = re.search(r'\{.*\}', text_response, re.DOTALL)
            if match:
                text_response = match.group(0)
            
            result = json.loads(text_response)
            
            # 기본값 보장
            if "selected_row" not in result:
                result["selected_row"] = 1
            if "reason" not in result:
                result["reason"] = "AI 분석 결과"
            if "confidence" not in result:
                result["confidence"] = 0.5
                
            return result
            
        except json.JSONDecodeError as e:
            print(f"[오류] AI 응답 파싱 실패: {e}")
            print(f"[원본 응답] {text_response[:500]}")
            return {"error": "AI 응답 파싱 실패", "selected_row": 1, "raw_response": text_response[:500]}
        except Exception as e:
            print(f"[오류] AI 분석 실패: {e}")
            return {"error": str(e), "selected_row": 1}
    
    def _build_declaration_selection_prompt(self, export_data: Dict[str, Any]) -> str:
        """신고서 선택용 프롬프트 생성 (레디코리아 실제 화면 구조 기반)"""
        
        품명 = export_data.get("품명", "알 수 없음")
        총액 = export_data.get("총액", 0)
        route = export_data.get("route", "알 수 없음")  # ICN/BKK 같은 경로
        수량 = export_data.get("수량", 0)
        is_free = export_data.get("is_free", False)  # 무상 여부
        
        # route에서 목적지 추출 (예: "ICN/BKK" → "BKK", "ICN/LAX" → "LAX")
        destination = ""
        if route and "/" in route:
            destination = route.split("/")[-1].strip()
        
        # 무상/유상에 따른 # 값
        target_hash = "H 94" if is_free else "H 11"  # 무상=H 94, 유상=H 11
        trade_type = "무상" if is_free else "유상"
        
        prompt = f"""
당신은 관세사 사무원입니다. 이 화면은 "레디코리아" 수출신고 프로그램의 신고서 목록입니다.

[레디코리아 화면 구조]
신고서 목록의 주요 컬럼:
- 신고번호: 13133-26-XXXXXX 형식
- 신고일자
- 차수
- **# 컬럼**: 거래 유형 코드 (매우 중요!)
  - "H 94" = 무상 수출
  - "H 11" = 유상 수출
  - 형식: "H" + 공백 + 숫자 두 자리
- 수출대행자
- 수출화주
- 목적국: TH, VN, US, JP 등 국가 코드
- 송품장번호
- 신고가격

[현재 처리할 수출 건 정보]
- **거래 유형: {trade_type}** (# 컬럼이 "{target_hash}"인 신고서를 찾아야 함!)
- 품명: {품명}
- 금액(USD): {총액}
- 목적지: {destination} (경로: {route})
- 수량: {수량}

[신고서 선택 규칙]
1. **최우선: # 컬럼이 "{target_hash}"인 행**을 찾으세요 ({trade_type} 수출이므로)
2. 그 중에서 **목적국이 "{destination}"과 일치**하는 것 우선

[응답 형식 - 반드시 JSON으로만 응답]
{{
    "selected_row": 행 번호 (첫 번째 데이터 행이 1),
    "reason": "선택 이유 (# 값, 목적국, 금액 등 구체적으로)",
    "selected_declaration": {{
        "신고번호": "화면에서 읽은 값",
        "hash": "# 컬럼 값 (H 94 또는 H 11 등)",
        "목적국": "화면에서 읽은 값",
        "신고가격": "화면에서 읽은 값"
    }},
    "confidence": 0.0 ~ 1.0
}}

[주의사항]
- {trade_type} 수출이므로 반드시 # 컬럼이 "{target_hash}"인 행을 우선 선택하세요!
- # 컬럼을 찾지 못하면 selected_row: 1로 응답하세요.
- 반드시 JSON 형식으로만 응답하세요.
"""
        return prompt
    
    def find_ui_element(self, element_description: str) -> Optional[Tuple[int, int]]:
        """
        AI를 사용하여 화면에서 UI 요소의 좌표를 찾습니다.
        
        Args:
            element_description: 찾을 요소 설명 (예: "수정 버튼", "총중량 입력 필드")
            
        Returns:
            (x, y) 좌표 또는 None
        """
        client = get_client()
        if client is None:
            return None
            
        img_data = self.capture_window()
        if not img_data:
            return None
            
        prompt = f"""
이 화면에서 "{element_description}"의 위치를 찾아주세요.

[응답 형식 - 반드시 JSON으로만 응답]
{{
    "found": true 또는 false,
    "x": 요소 중심의 X 좌표 (픽셀),
    "y": 요소 중심의 Y 좌표 (픽셀),
    "description": "찾은 요소에 대한 설명"
}}

요소를 찾지 못하면 found: false로 응답하세요.
"""

        try:
            from google.genai import types
            response = client.models.generate_content(
                model=f"models/{self.model_id}",
                contents=[
                    prompt,
                    types.Part.from_bytes(data=img_data, mime_type="image/jpeg")
                ]
            )
            
            text_response = response.text.strip()
            text_response = re.sub(r'```(?:json)?\n?(.*?)\n?```', r'\1', text_response, flags=re.DOTALL).strip()
            match = re.search(r'\{.*\}', text_response, re.DOTALL)
            if match:
                text_response = match.group(0)
            
            result = json.loads(text_response)
            
            if result.get("found", False):
                x = int(result.get("x", 0))
                y = int(result.get("y", 0))
                if x > 0 and y > 0:
                    return (x, y)
            
            return None
            
        except Exception as e:
            print(f"[오류] UI 요소 찾기 실패: {e}")
            return None
    
    def describe_current_screen(self) -> str:
        """현재 화면 상태를 AI로 분석하여 설명"""
        client = get_client()
        if client is None:
            return "Gemini API 클라이언트가 초기화되지 않았습니다"
            
        img_data = self.capture_window()
        if not img_data:
            return "화면 캡처 실패"
            
        prompt = """
현재 화면을 분석하고 간단히 설명해주세요.

[응답 형식]
1. 어떤 프로그램/화면인지
2. 현재 상태 (어떤 작업 중인지)
3. 보이는 주요 UI 요소들
4. 다음에 할 수 있는 작업

간결하게 한국어로 응답하세요.
"""

        try:
            from google.genai import types
            response = client.models.generate_content(
                model=f"models/{self.model_id}",
                contents=[
                    prompt,
                    types.Part.from_bytes(data=img_data, mime_type="image/jpeg")
                ]
            )
            return response.text.strip()
        except Exception as e:
            return f"화면 분석 실패: {e}"


# 싱글톤 인스턴스
screen_ai = ScreenAI()
