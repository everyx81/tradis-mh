# JARVIS Core - 설정 관리
"""
설정 파일 로드/저장 및 API 키 관리
"""

import os
import sys
import json
import base64
from google import genai

def get_config_path():
    """설정 파일 경로 반환"""
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    data_dir = os.path.join(base_path, 'data')
    os.makedirs(data_dir, exist_ok=True)
    
    return os.path.join(data_dir, 'config.json')

def load_config():
    """설정 파일 로드"""
    try:
        cp = get_config_path()
        if os.path.exists(cp):
            with open(cp, 'r', encoding='utf-8') as f:
                return json.load(f)
    except:
        pass
    return {}

# 전역 설정 로드
CONFIG = load_config()

def _decode_api_key(encoded_key: str) -> str:
    """
    API 키 디코딩 (중첩 인코딩 대응)
    - 반복적으로 Base64 디코딩하여 실제 API 키 추출
    - Gemini API 키는 'AIza'로 시작함
    """
    if not encoded_key:
        return ""
    
    key = encoded_key
    for _ in range(20):  # 최대 20번 디코딩 시도
        try:
            decoded = base64.b64decode(key).decode('utf-8')
            # Gemini API 키 형식 체크 (AIza로 시작)
            if decoded.startswith('AIza'):
                return decoded
            key = decoded
        except:
            break
    
    # 디코딩 실패 시 원본 반환 (평문 키일 수 있음)
    return key if key.startswith('AIza') else encoded_key

# API 키 디코딩
_encoded_key = CONFIG.get("api_key", "")
api_key = _decode_api_key(_encoded_key)

# Gemini 클라이언트 초기화
client = genai.Client(api_key=api_key) if api_key else None

def set_api_key(new_key: str):
    """
    API 키 설정 및 저장
    - 중복 인코딩 방지: 이미 인코딩된 키는 디코딩 후 재인코딩
    - 저장 시 항상 단일 Base64 인코딩만 적용
    """
    global api_key, client, CONFIG
    
    # 입력된 키가 이미 인코딩된 상태인지 확인하고 디코딩
    actual_key = _decode_api_key(new_key) if new_key else ""
    
    # 유효한 API 키 형식 확인 (AIza로 시작)
    if actual_key and not actual_key.startswith('AIza'):
        # 디코딩 실패 시 원본을 평문 키로 간주
        actual_key = new_key
    
    api_key = actual_key
    
    # 단일 Base64 인코딩으로 저장 (평문 저장 방지)
    encoded_key = base64.b64encode(actual_key.encode('utf-8')).decode('utf-8') if actual_key else ""
    CONFIG["api_key"] = encoded_key
    
    if actual_key:
        client = genai.Client(api_key=actual_key)
        try:
            with open(get_config_path(), 'w', encoding='utf-8') as f:
                json.dump(CONFIG, f, ensure_ascii=False, indent=4)
        except:
            pass
    else:
        client = None
