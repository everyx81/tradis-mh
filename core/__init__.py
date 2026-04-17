# JARVIS Core Package
"""
핵심 비즈니스 로직 모듈
- config: 설정 관리
- constants: 상수 정의
- utils: 유틸리티 함수
- ocr: Gemini OCR 분석
- screen_ai: 화면 분석 AI
- file_processor: 파일 모니터링 및 처리
- archiver: 아카이빙 로직
"""

from .constants import (
    PORT, MAX_RETRIES, RETRY_DELAY,
    DOC_TYPE_FUNDS_REQUEST, DOC_TYPE_IMPORT_STATEMENT,
    DOC_TYPE_IMPORT_DECLARATION, DOC_TYPE_PAYMENT_NOTICE,
    DOC_TYPE_IMPORT_TAX_INVOICE, DOC_TYPE_FEE_TAX_INVOICE,
    DOC_TYPE_EXPORT_DECLARATION
)

from .config import (
    get_config_path, load_config, set_api_key,
    CONFIG, api_key, client
)

from .utils import (
    sanitize_filename, get_unique_filename, cleanup_company_name,
    parse_renamed_filename, extract_text, check_single_instance,
    RE_FILE_PATTERN, RE_ID_PAREN, RE_DOC_MATCH
)

from .ocr import GeminiOCR, gemini_ocr, extract_document_info_ai

# screen_ai는 readykorea_automation에서만 사용되며 거기서 lazy-load됨.
# 여기서 eager import하면 pyautogui까지 끌려와 시작 시간 ~320ms 증가하므로 제외.
# 접근이 필요할 때는: from core.screen_ai import screen_ai

from .file_processor import AutoRenamer, PDFHandler

from .archiver import Archiver

