# JARVIS Auto Renamer - 레거시 호환 레이어
"""
기존 import 호환성을 위한 re-export 모듈
모든 실제 구현은 core/ 패키지로 이동됨

사용법:
    from auto_rename import AutoRenamer, GeminiOCR, Archiver, set_api_key
    # 기존과 동일하게 작동
"""

import sys

# Console Encoding
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

# --- Re-export all public APIs from core package ---

# Constants
from core.constants import (
    PORT, MAX_RETRIES, RETRY_DELAY,
    DOC_TYPE_FUNDS_REQUEST, DOC_TYPE_IMPORT_STATEMENT,
    DOC_TYPE_IMPORT_DECLARATION, DOC_TYPE_PAYMENT_NOTICE,
    DOC_TYPE_IMPORT_TAX_INVOICE, DOC_TYPE_FEE_TAX_INVOICE,
    DOC_TYPE_EXPORT_DECLARATION
)

# Config
from core.config import (
    get_config_path, load_config, set_api_key,
    CONFIG, api_key, client
)

# Utils
from core.utils import (
    sanitize_filename, get_unique_filename, cleanup_company_name,
    parse_renamed_filename, extract_text, check_single_instance,
    pdf_lock,
    RE_FILE_PATTERN, RE_INVALID_CHARS, RE_ID_PAREN, RE_DOC_MATCH,
    RE_COMPANY_CLEAN_1, RE_COMPANY_CLEAN_2, RE_COMPANY_CLEAN_3,
    RE_COMPANY_KOREAN, RE_COMPANY_SPLIT,
    RE_BL_GENERAL, RE_INV_GENERAL,
    RE_TAX_PAYER, RE_SHIPPER, RE_BIZ_ID, RE_BUSINESS_ID_OR_NUM,
    RE_상호, RE_수출화주, RE_송품장부호, RE_BL_IV_NO
)

# OCR
from core.ocr import (
    GeminiOCR, gemini_ocr, extract_document_info_ai
)

# File Processor
from core.file_processor import AutoRenamer, PDFHandler

# Archiver
from core.archiver import Archiver


# --- Main Entry (레거시 호환) ---
if __name__ == "__main__":
    import time
    try:
        s = check_single_instance()
        if s:
            print("TRADIS MH RE-INIT SUCCESSFUL")
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
