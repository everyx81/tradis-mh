"""TRADIS MH 버전 정보"""

__version__ = "1.1.58"
APP_NAME = "TRADIS MH"
GITHUB_REPO = "everyx81/tradis-mh"

# 관리자 비밀번호의 PBKDF2-HMAC-SHA256 해시 (원문은 코드에 저장하지 않음)
# 공개 저장소에 노출되어도 오프라인 대입이 어렵도록 고반복 PBKDF2 사용
# 모든 PC에서 동일하게 동작 — keyring 기반 '최초 입력 = 등록' 부트스트랩 제거
_ADMIN_PW_SALT = b"TRADIS_MH_ADMIN_V1"
_ADMIN_PW_ITERATIONS = 600_000
_ADMIN_PW_HASH = "c6bfd98c40a963eb5e26ccbfcab93e64ced6b01bc2bdaa2791eab2bfc9934979"

def verify_admin_password(pw):
    """입력한 비밀번호가 관리자 비밀번호와 일치하는지 검증"""
    import hashlib
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"),
                             _ADMIN_PW_SALT, _ADMIN_PW_ITERATIONS)
    return dk.hex() == _ADMIN_PW_HASH
