"""TRADIS MH 버전 정보"""

__version__ = "1.1.27"
APP_NAME = "TRADIS MH"
GITHUB_REPO = "everyx81/tradis-mh"

def get_admin_password():
    """Windows Credential Manager에서 관리자 비밀번호 로드 (미설정 시 None)"""
    import keyring
    return keyring.get_password("TRADIS_MH", "admin_password")

def set_admin_password(pw):
    """관리자 비밀번호를 Windows Credential Manager에 저장"""
    import keyring
    keyring.set_password("TRADIS_MH", "admin_password", pw)
