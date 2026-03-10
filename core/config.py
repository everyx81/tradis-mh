# JARVIS Core - 설정 관리
"""
설정 파일 로드/저장 및 API 키 관리
- API 키는 Windows Credential Manager(keyring)에 저장
"""

import os
import sys
import json
import base64
import keyring
from google import genai

SERVICE_NAME = "TRADIS_MH"

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
    """설정 파일 저장"""
    try:
        with open(get_config_path(), 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
    except OSError:
        pass

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
    key = keyring.get_password(SERVICE_NAME, "gemini_api_key")
    if key:
        return key

    # 마이그레이션 시도 (기존 config.json에 키가 있으면)
    _migrate_api_key_to_keyring()
    return keyring.get_password(SERVICE_NAME, "gemini_api_key") or ""

# API 키 로드 + 클라이언트 초기화
api_key = get_api_key()
client = genai.Client(api_key=api_key) if api_key else None

def set_api_key(new_key: str):
    """API 키 설정 (keyring에 저장)"""
    global api_key, client

    actual_key = _decode_api_key(new_key) if new_key else ""

    if actual_key and not actual_key.startswith('AIza'):
        actual_key = new_key

    api_key = actual_key

    if actual_key:
        keyring.set_password(SERVICE_NAME, "gemini_api_key", actual_key)
        client = genai.Client(api_key=actual_key)
    else:
        keyring.delete_password(SERVICE_NAME, "gemini_api_key")
        client = None
