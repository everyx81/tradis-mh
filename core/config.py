# JARVIS Core - 설정 관리
"""
설정 파일 로드/저장 및 API 키 관리
- API 키는 Windows Credential Manager(keyring)에 저장
"""

import os
import sys
import json
import base64

SERVICE_NAME = "TRADIS_MH"

# 커스텀 네이밍 기본값
DEFAULT_FILE_PATTERN = "{company}({bl}){doctype}.pdf"
DEFAULT_MERGE_PATTERN = "{company}({bl})정산서.pdf"
DEFAULT_MERGE_ORDER = ["정산서", "신고필증", "납부고지서", "세금계산서", "비용계산서"]


def get_custom_naming():
    """커스텀 네이밍 설정 반환 (미설정 시 기본값)"""
    cfg = CONFIG.get("custom_naming", {})
    return {
        "file_pattern": cfg.get("file_pattern", DEFAULT_FILE_PATTERN),
        "merge_pattern": cfg.get("merge_pattern", DEFAULT_MERGE_PATTERN),
        "merge_order": cfg.get("merge_order", DEFAULT_MERGE_ORDER),
    }


# ─────────────────────────────────────────────────
# 자동 이름 변경 제외 키워드 (사용자 추가/삭제 가능)
# ─────────────────────────────────────────────────
def get_rename_skip_keywords() -> list:
    """config.json 의 rename_skip_keywords (없으면 constants 의 기본값)."""
    cfg = CONFIG.get("rename_skip_keywords")
    if isinstance(cfg, list):
        return [str(k) for k in cfg if k]
    # 최초엔 constants 의 기본값 반환
    try:
        from core.constants import RENAME_SKIP_KEYWORDS
        return list(RENAME_SKIP_KEYWORDS)
    except Exception:
        return []


def set_rename_skip_keywords(keywords: list):
    """config.json 에 키워드 리스트 저장 (중복 제거, 공백 제거)."""
    seen = set()
    cleaned = []
    for k in keywords:
        k = str(k).strip()
        if k and k not in seen:
            seen.add(k)
            cleaned.append(k)
    CONFIG["rename_skip_keywords"] = cleaned
    _save_config(CONFIG)
    return cleaned


def add_rename_skip_keyword(keyword: str) -> list:
    """단일 키워드 추가 후 전체 리스트 반환."""
    kws = get_rename_skip_keywords()
    k = str(keyword).strip()
    if k and k not in kws:
        kws.append(k)
        set_rename_skip_keywords(kws)
    return kws


def remove_rename_skip_keyword(keyword: str) -> list:
    """단일 키워드 삭제 후 전체 리스트 반환."""
    kws = get_rename_skip_keywords()
    if keyword in kws:
        kws.remove(keyword)
        set_rename_skip_keywords(kws)
    return kws

def get_config_path():
    """설정 파일 경로 반환 (data/config.json)"""
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    data_dir = os.path.join(base_path, 'data')
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, 'config.json')

def _migrate_root_config():
    """루트 config.json → data/config.json 마이그레이션"""
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    old_path = os.path.join(base_path, 'config.json')
    new_path = get_config_path()

    if os.path.exists(old_path) and not os.path.exists(new_path):
        try:
            import shutil
            shutil.move(old_path, new_path)
            print(f"[설정] config.json 마이그레이션: {old_path} → {new_path}")
        except OSError as e:
            print(f"[설정] 마이그레이션 실패: {e}")

def load_config():
    """설정 파일 로드"""
    _migrate_root_config()
    try:
        cp = get_config_path()
        if os.path.exists(cp):
            with open(cp, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    return {}

def _save_config(config):
    """설정 파일 저장 (atomic write)"""
    try:
        cfg = get_config_path()
        tmp = cfg + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        os.replace(tmp, cfg)
    except OSError:
        try: os.unlink(get_config_path() + ".tmp")
        except OSError: pass

# 전역 설정 로드
CONFIG = load_config()

def _decode_api_key(encoded_key: str) -> str:
    """API 키 디코딩 (Base64 중첩 인코딩 대응)"""
    if not encoded_key:
        return ""

    key = encoded_key
    for _ in range(20):
        try:
            decoded = base64.b64decode(key).decode('utf-8')
            if decoded.startswith('AIza'):
                return decoded
            key = decoded
        except Exception:
            break

    return key if key.startswith('AIza') else encoded_key

def _migrate_api_key_to_keyring():
    """config.json의 api_key를 keyring으로 마이그레이션 (최초 1회)"""
    import keyring
    encoded = CONFIG.get("api_key", "")
    if not encoded:
        return

    actual_key = _decode_api_key(encoded)
    if actual_key:
        keyring.set_password(SERVICE_NAME, "gemini_api_key", actual_key)
        # config.json에서 api_key 제거
        CONFIG.pop("api_key", None)
        _save_config(CONFIG)

def get_api_key() -> str:
    """keyring에서 API 키 로드 (없으면 config.json에서 마이그레이션)"""
    import keyring
    key = keyring.get_password(SERVICE_NAME, "gemini_api_key")
    if key:
        return key

    # 마이그레이션 시도 (기존 config.json에 키가 있으면)
    _migrate_api_key_to_keyring()
    return keyring.get_password(SERVICE_NAME, "gemini_api_key") or ""

# API 키 지연 로딩 (keyring 접근을 시작 시 지연)
api_key = None  # _ensure_api_key()로 초기화
client = None  # get_client()로 접근
_api_key_loaded = False

def _ensure_api_key():
    """API 키 지연 로딩 (최초 1회)"""
    global api_key, _api_key_loaded
    if not _api_key_loaded:
        api_key = get_api_key()
        _api_key_loaded = True
    return api_key

def get_client():
    """Gemini 클라이언트 지연 초기화"""
    global client
    if client is None and _ensure_api_key():
        from google import genai
        client = genai.Client(api_key=api_key)
    return client

def set_api_key(new_key: str):
    """API 키 설정 (keyring에 저장)"""
    global api_key, client, _api_key_loaded
    import keyring

    actual_key = _decode_api_key(new_key) if new_key else ""

    if actual_key and not actual_key.startswith('AIza'):
        actual_key = new_key

    api_key = actual_key
    _api_key_loaded = True

    if actual_key:
        keyring.set_password(SERVICE_NAME, "gemini_api_key", actual_key)
        from google import genai
        client = genai.Client(api_key=actual_key)
    else:
        keyring.delete_password(SERVICE_NAME, "gemini_api_key")
        client = None
