"""
JARVIS 수출 자동화 - 메일 모니터링 모듈
한비로 IMAP을 통해 특정 수출 요청 메일을 감지합니다.
"""

import os
import re
import email
import email.message
import imaplib
import threading
import time
from email.header import decode_header
from dataclasses import dataclass
from typing import Optional, List, Callable
from datetime import datetime


@dataclass
class ExportMailInfo:
    """수출 요청 메일 정보"""
    message_id: str
    subject: str
    sender: str
    request_number: str  # 요청번호 (예: 292)
    route: str  # 경로 (예: ICN/BKK)
    received_date: datetime
    to: str = ""  # 받는 사람 (원본 메일)
    cc: str = ""  # 참조 (추가됨)
    is_free: bool = False  # 무상 여부 (메일 제목에 "무상" 포함 시 True)
    attachment_path: Optional[str] = None
    
    def __str__(self) -> str:
        return (f"요청번호: #{self.request_number}\n"
                f"경로: {self.route}\n"
                f"제목: {self.subject}\n"
                f"발신자: {self.sender}\n"
                f"받는사람: {self.to}\n"
                f"참조: {self.cc}\n"
                f"수신일시: {self.received_date}")


class HanbiroMailMonitor:
    """
    한비로 메일 모니터링
    
    특정 패턴의 수출 요청 메일을 감지하고 첨부파일을 다운로드합니다.
    패턴: [ANS] ICN/BKK / 무상 수출건 면장 요청#292
    """
    
    # 메일 제목 패턴
    # [ANS] ICN/BKK / 무상 수출건 면장 요청#292
    # 주의: RE:, FW: 등 답장/포워드는 제외 (^로 시작 표시)
    SUBJECT_PATTERN = r"^\[ANS\]\s*([A-Z]{3}/[A-Z]{3})\s*/\s*.*면장 요청#(\d+)"
    
    def __init__(self, 
                 imap_server: str = "imap.hanbiro.com",
                 imap_port: int = 993,
                 email_address: str = "",
                 password: str = "",
                 download_folder: str = ""):
        """
        Args:
            imap_server: IMAP 서버 주소
            imap_port: IMAP 포트 (기본 993)
            email_address: 이메일 주소
            password: 비밀번호
            download_folder: 첨부파일 저장 폴더
        """
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.email_address = email_address
        self.password = password
        self.download_folder = download_folder or os.path.join(os.getcwd(), "export_attachments")
        
        self.mail_connection: Optional[imaplib.IMAP4_SSL] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        # 콜백 함수
        self.on_export_mail_detected: Optional[Callable[[ExportMailInfo], None]] = None
        
        # 처리한 메일 ID 저장 (중복 방지, 최대 1000개 유지)
        self._processed_ids: set = set()
        self._MAX_PROCESSED_IDS = 1000
        
        # 다운로드 폴더 생성
        if not os.path.exists(self.download_folder):
            os.makedirs(self.download_folder)
    
    def connect(self) -> bool:
        """IMAP 서버 연결"""
        try:
            self.mail_connection = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            self.mail_connection.login(self.email_address, self.password)
            # 연결 성공 로그 (터미널 출력 제거)
            return True
        except Exception as e:
            print(f"[메일] 연결 실패: {e}")
            return False
    
    def disconnect(self):
        """연결 종료"""
        if self.mail_connection:
            try:
                self.mail_connection.logout()
            except Exception:
                pass
            self.mail_connection = None
    
    def is_export_request(self, subject: str) -> Optional[dict]:
        """
        메일 제목이 수출 요청 패턴과 일치하는지 확인
        
        Args:
            subject: 메일 제목
            
        Returns:
            일치 시 {"route": "ICN/BKK", "number": "292", "is_free": True/False}, 불일치 시 None
        """
        match = re.search(self.SUBJECT_PATTERN, subject)
        if match:
            # 메일 제목에 "무상" 단어가 있는지 확인
            is_free = "무상" in subject
            return {
                "route": match.group(1),
                "number": match.group(2),
                "is_free": is_free
            }
        return None
    
    def _decode_header(self, header_value: str) -> str:
        """이메일 헤더 디코딩"""
        if not header_value:
            return ""
        
        decoded_parts = []
        for part, encoding in decode_header(header_value):
            if isinstance(part, bytes):
                # unknown-8bit 등 비표준 인코딩 처리
                enc = encoding or 'utf-8'
                if enc.lower().replace('-', '') in ('unknown8bit', 'unknown'):
                    enc = 'latin-1'
                try:
                    decoded_parts.append(part.decode(enc, errors='replace'))
                except (LookupError, UnicodeDecodeError):
                    decoded_parts.append(part.decode('latin-1', errors='replace'))
            else:
                decoded_parts.append(part)
        
        result = ''.join(decoded_parts)
        # 개행, 탭 등을 공백으로 치환 후 앞뒤 공백 제거
        return re.sub(r'[\r\n\t]+', ' ', result).strip()
    
    def _download_attachment(self, msg: email.message.Message, mail_info: ExportMailInfo) -> Optional[str]:
        """엑셀 첨부파일 다운로드"""
        for part in msg.walk():
            content_disposition = part.get("Content-Disposition", "")
            
            if "attachment" in content_disposition:
                filename = part.get_filename()
                
                if filename:
                    filename = self._decode_header(filename)
                    
                    # 엑셀 파일만 처리
                    if filename.lower().endswith(('.xlsx', '.xls')):
                        # 파일명에 요청번호 + 타임스탬프 추가 (유일성 보장)
                        base, ext = os.path.splitext(filename)
                        timestamp = datetime.now().strftime("%H%M%S")
                        safe_filename = f"export_{mail_info.request_number}_{timestamp}_{base}{ext}"
                        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', safe_filename)
                        
                        file_path = os.path.join(self.download_folder, safe_filename)
                        
                        with open(file_path, 'wb') as f:
                            f.write(part.get_payload(decode=True))
                        
                        print(f"[메일] 첨부파일 저장: {file_path}")
                        return file_path
        
        return None
    
    def check_new_mails(self) -> List[ExportMailInfo]:
        """
        새로운 수출 요청 메일 확인
        
        Returns:
            감지된 수출 요청 메일 목록
        """
        if not self.mail_connection:
            if not self.connect():
                return []
        
        detected_mails = []
        
        try:
            # 받은편지함 선택
            self.mail_connection.select('INBOX')
            
            # 읽지 않은 메일 검색
            status, messages = self.mail_connection.search(None, 'UNSEEN')
            
            if status != 'OK':
                return []
            
            mail_ids = messages[0].split()
            
            for mail_id in mail_ids:
                mail_id_str = mail_id.decode()
                
                # 이미 처리한 메일 건너뛰기
                if mail_id_str in self._processed_ids:
                    continue
                
                # 메일 가져오기 (PEEK으로 읽음 표시 방지)
                status, msg_data = self.mail_connection.fetch(mail_id, '(BODY.PEEK[])')
                
                if status != 'OK':
                    continue
                
                # 메일 파싱
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                # 제목 디코딩
                subject = self._decode_header(msg.get('Subject', ''))
                
                # 수출 요청 패턴 확인
                match_info = self.is_export_request(subject)
                
                if match_info:
                    # [중요] 패턴 일치 시에만 읽음 처리 (Seen 플래그 설정)
                    self.mail_connection.store(mail_id, '+FLAGS', '\\Seen')
                    
                    # 중복 방지: 이미 처리한 ID 등록 (성공 여부 상관없이 일단 등록하여 무한반복 방지)
                    self._processed_ids.add(mail_id_str)
                    # 메모리 누수 방지: 오래된 ID 정리
                    if len(self._processed_ids) > self._MAX_PROCESSED_IDS:
                        # set은 순서 없으므로 절반 제거 (오래된 것 추정)
                        to_remove = len(self._processed_ids) - self._MAX_PROCESSED_IDS // 2
                        for _ in range(to_remove):
                            self._processed_ids.pop()
                    
                    # 발신자, 받는 사람, 참조
                    sender = self._decode_header(msg.get('From', ''))
                    to = self._decode_header(msg.get('To', ''))
                    cc = self._decode_header(msg.get('Cc', ''))
                    
                    # 메일 정보 생성
                    mail_info = ExportMailInfo(
                        message_id=mail_id_str,
                        subject=subject,
                        sender=sender,
                        request_number=match_info["number"],
                        route=match_info["route"],
                        to=to,
                        cc=cc,
                        is_free=match_info.get("is_free", False),  # 무상 여부
                        received_date=datetime.now()
                    )
                    
                    # 첨부파일 다운로드
                    attachment_path = self._download_attachment(msg, mail_info)
                    mail_info.attachment_path = attachment_path
                    
                    detected_mails.append(mail_info)
                    
                    print(f"[메일] 수출 요청 감지: #{match_info['number']} ({match_info['route']})")
                    
                    # 콜백 호출
                    if self.on_export_mail_detected:
                        self.on_export_mail_detected(mail_info)
                        
        except Exception as e:
            print(f"[메일] 확인 중 오류: {e}")
            # 연결 재시도를 위해 연결 해제
            self.disconnect()
        
        return detected_mails
    
    def start_monitoring(self, interval_seconds: int = 30, use_idle: bool = True):
        """
        백그라운드 메일 모니터링 시작
        
        Args:
            interval_seconds: 폴링 주기 (IDLE 미지원 시 사용)
            use_idle: IMAP IDLE 사용 여부 (True = 실시간 감지)
        """
        if self._running:
            print("[메일] 이미 모니터링 중입니다.")
            return
        
        self._running = True
        
        if use_idle:
            self._thread = threading.Thread(target=self._idle_monitoring_loop, daemon=True)
        else:
            self._thread = threading.Thread(target=lambda: self._polling_monitoring_loop(interval_seconds), daemon=True)
        
        self._thread.start()
    
    def _idle_monitoring_loop(self):
        """IMAP IDLE 방식 실시간 모니터링 (즉시 감지)"""
        import select as _select

        # IDLE 재시작 주기: 4분 (RFC 권장 29분이나, 서버 호환성 위해 4분)
        IDLE_RESTART_SECONDS = 240

        while self._running:
            try:
                # 연결 확인
                if not self.mail_connection:
                    if not self.connect():
                        time.sleep(5)
                        continue

                # INBOX 선택
                self.mail_connection.select('INBOX')

                # 먼저 기존 메일 체크
                self.check_new_mails()

                # IDLE 모드 진입
                if not self.mail_connection:
                    continue
                self.mail_connection.send(b'a IDLE\r\n')

                elapsed = 0
                while self._running:
                    sock = self.mail_connection.socket()
                    readable, _, _ = _select.select([sock], [], [], 5)  # 5초 대기

                    if readable:
                        response = sock.recv(1024).decode('utf-8', errors='replace')

                        if 'EXISTS' in response:
                            print("[메일] 새 메일 감지! (IDLE)")
                            self.mail_connection.send(b'DONE\r\n')
                            time.sleep(0.5)

                            # 버퍼 비우기
                            try:
                                sock.setblocking(False)
                                while True:
                                    try:
                                        leftover = sock.recv(1024)
                                        if not leftover:
                                            break
                                    except (OSError, Exception):
                                        break
                                sock.setblocking(True)
                            except (OSError, Exception):
                                pass

                            # 연결 재설정 후 메일 체크
                            self.disconnect()
                            time.sleep(0.3)
                            if self.connect():
                                self.check_new_mails()
                            break

                        if '+ ' in response or 'idling' in response.lower():
                            continue

                    # IDLE 재시작 체크 (4분마다)
                    elapsed += 5
                    if elapsed >= IDLE_RESTART_SECONDS:
                        if self.mail_connection:
                            self.mail_connection.send(b'DONE\r\n')
                        time.sleep(0.3)
                        self.disconnect()
                        if self.connect():
                            self.check_new_mails()
                        break

            except Exception as e:
                print(f"[메일] IDLE 오류: {e}")
                self.disconnect()
                time.sleep(3)

        print("[메일] IDLE 모니터링 종료")
    
    def _polling_monitoring_loop(self, interval_seconds: int):
        """폴링 방식 모니터링 (IDLE 미지원 시 사용)"""
        print(f"[메일] 폴링 모니터링 시작 (주기: {interval_seconds}초)")
        
        while self._running:
            try:
                self.check_new_mails()
            except Exception as e:
                print(f"[메일] 모니터링 오류: {e}")
            
            # 대기
            for _ in range(interval_seconds):
                if not self._running:
                    break
                time.sleep(1)
        
        print("[메일] 폴링 모니터링 종료")
    
    def stop_monitoring(self):
        """모니터링 중지"""
        self._running = False
        self.disconnect()
        print("[메일] 모니터링 중지 요청")


# 테스트용
if __name__ == "__main__":
    # 패턴 매칭 테스트
    monitor = HanbiroMailMonitor()
    
    test_subjects = [
        "[ANS] ICN/BKK / 무상 수출건 면장 요청#292",
        "[ANS] ICN/HKG / 유상 수출건 면장 요청#1234",
        "[ANS] ICN/SIN / 무상 수출건 면장 요청#5",
        "일반 메일 제목",
        "RE: [ANS] ICN/BKK / 무상 수출건 면장 요청#292",  # 답장은 매칭 안됨
    ]
    
    print("=== Mail Subject Pattern Test ===\n")
    
    for subject in test_subjects:
        result = monitor.is_export_request(subject)
        if result:
            print(f"[O] Match: {subject}")
            print(f"    -> Route: {result['route']}, Request#: {result['number']}\n")
        else:
            print(f"[X] No Match: {subject}\n")
    
    print("\n=== Mail Server Connection Test ===")
    print("(Set account info in config.json to test actual connection)")

