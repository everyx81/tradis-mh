"""
JARVIS 수출 자동화 - 메일 발송 모듈
한비로 SMTP를 사용하여 수출신고필증을 첨부한 답장 메일을 발송합니다.
"""

import os
import re
import smtplib
import imaplib
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.application import MIMEApplication
from email import encoders
from email.header import decode_header
from email.utils import getaddresses, parsedate_to_datetime
from typing import Optional, Callable, List
from dataclasses import dataclass


@dataclass
class FoundEmailThread:
    """IMAP 검색으로 찾은 메일 스레드 정보"""
    message_id: str      # Message-ID (In-Reply-To용)
    subject: str         # 제목
    sender: str          # 보낸 사람
    to: str              # 받는 사람
    cc: str              # 참조
    date: str            # 날짜 (표시용 문자열)
    folder: str          # 발견된 폴더 (INBOX/Sent)


@dataclass
class EmailConfig:
    """한비로 메일 설정"""
    smtp_server: str = "raeon.hanbiro.net"
    smtp_port: int = 465
    imap_server: str = "raeon.hanbiro.net"
    imap_port: int = 993
    email: str = ""
    password: str = ""
    sent_folder: str = "Sent"  # 보낸 메일함 폴더명 (확인 필요)
    sender_email: Optional[str] = None  # 실제 발신자 주소 (From 헤더용)


class ExportMailSender:
    """수출신고필증 답장 메일 발송"""
    
    # 메일 템플릿
    EMAIL_TEMPLATE = """안녕하세요 대표님!!

해도관세사무소 최명헌입니다.

{filename} 보내드립니다.

감사합니다.
최명헌 드림"""
    
    _sent_folder_cache: Optional[str] = None
    _imap_connections: dict = {}  # 폴더별 전용 IMAP 연결: {"INBOX": conn, "Sent": conn}
    _search_cache: dict = {}     # B/L별 검색 결과 캐시: {bl: (timestamp, results)}
    _CACHE_TTL = 600             # 캐시 유효시간 (초) - 프리페치 결과 유지

    def __init__(self, config: EmailConfig, log_callback: Optional[Callable[[str], None]] = None):
        self.config = config
        self.log_callback = log_callback

    def log(self, msg: str):
        if self.log_callback:
            self.log_callback(msg)
        print(f"[MailSender] {msg}")

    def _decode_header_value(self, value: str) -> str:
        """MIME 인코딩된 헤더 값을 디코딩"""
        if not value:
            return ""
        decoded_parts = decode_header(value)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or 'utf-8', errors='replace'))
            else:
                result.append(part)
        return " ".join(result)

    def _get_connection(self, folder: str) -> imaplib.IMAP4_SSL:
        """폴더별 전용 IMAP 연결 반환 (재사용 or 신규 생성+SELECT)"""
        conn = ExportMailSender._imap_connections.get(folder)
        if conn:
            try:
                conn.noop()
                return conn  # 기존 연결 재사용 (이미 SELECT된 상태)
            except Exception:
                conn = None

        # 신규 연결
        conn = imaplib.IMAP4_SSL(self.config.imap_server, self.config.imap_port, timeout=15)
        conn.login(self.config.email, self.config.password)
        conn.select(folder, readonly=True)
        ExportMailSender._imap_connections[folder] = conn
        return conn

    def ensure_connections(self):
        """사전 연결: INBOX + Sent 폴더용 IMAP 연결을 미리 생성"""
        import concurrent.futures
        if ExportMailSender._sent_folder_cache is None:
            try:
                tmp = imaplib.IMAP4_SSL(self.config.imap_server, self.config.imap_port, timeout=15)
                tmp.login(self.config.email, self.config.password)
                ExportMailSender._sent_folder_cache = self._find_sent_folder(tmp) or ""
                tmp.logout()
            except Exception:
                ExportMailSender._sent_folder_cache = ""

        folders = ["INBOX"]
        if ExportMailSender._sent_folder_cache:
            folders.append(ExportMailSender._sent_folder_cache)

        def connect(folder):
            try:
                self._get_connection(folder)
            except Exception:
                pass

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(connect, folders))

    def _search_folder(self, folder: str, bl_number: str, since_date: str) -> List[FoundEmailThread]:
        """단일 폴더에서 B/L 검색 (전용 연결 사용)"""
        results = []
        try:
            imap = self._get_connection(folder)

            search_criteria = f'(SUBJECT "{bl_number}" SINCE {since_date})'
            status, msg_ids = imap.search(None, search_criteria)
            if status != "OK" or not msg_ids[0]:
                return results

            ids = msg_ids[0].split()
            if not ids:
                return results

            id_set = b','.join(ids)
            status, fetch_data = imap.fetch(
                id_set,
                "(INTERNALDATE BODY.PEEK[HEADER.FIELDS (MESSAGE-ID SUBJECT FROM TO CC DATE)])"
            )
            if status != "OK":
                return results

            folder_label = "받은메일" if folder == "INBOX" else "보낸메일"

            for item in fetch_data:
                if not isinstance(item, tuple) or len(item) < 2:
                    continue
                try:
                    # INTERNALDATE 추출 (fallback용)
                    internal_date = ""
                    meta_line = item[0]
                    if isinstance(meta_line, bytes):
                        meta_line = meta_line.decode('utf-8', errors='replace')
                    import re as _re
                    idate_match = _re.search(r'INTERNALDATE "([^"]+)"', meta_line)
                    if idate_match:
                        try:
                            from email.utils import parsedate_to_datetime as _pdt
                            idt = _pdt(idate_match.group(1))
                            internal_date = idt.strftime("%Y-%m-%d %H:%M")
                        except Exception:
                            internal_date = idate_match.group(1)[:16] if idate_match.group(1) else ""

                    raw_header = item[1]
                    if isinstance(raw_header, bytes):
                        raw_header = raw_header.decode('utf-8', errors='replace')

                    headers = {}
                    current_key = None
                    for line in raw_header.split('\r\n'):
                        if line.startswith((' ', '\t')) and current_key:
                            headers[current_key] += ' ' + line.strip()
                        elif ':' in line:
                            key, _, val = line.partition(':')
                            current_key = key.strip().lower()
                            headers[current_key] = val.strip()

                    message_id = headers.get('message-id', '')
                    subject = self._decode_header_value(headers.get('subject', ''))
                    sender = self._decode_header_value(headers.get('from', ''))
                    to = self._decode_header_value(headers.get('to', ''))
                    cc = self._decode_header_value(headers.get('cc', ''))
                    date_str = headers.get('date', '')

                    try:
                        dt = parsedate_to_datetime(date_str)
                        display_date = dt.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        display_date = internal_date if internal_date else (date_str[:20] if date_str else "")

                    results.append(FoundEmailThread(
                        message_id=message_id,
                        subject=subject,
                        sender=sender,
                        to=to,
                        cc=cc,
                        date=display_date,
                        folder=folder_label,
                    ))
                except Exception as e:
                    self.log(f"메일 헤더 파싱 오류: {e}")
                    continue
        except Exception as e:
            self.log(f"폴더 검색 오류 ({folder}): {e}")
            # 연결 오류 시 해당 폴더 캐시 제거
            ExportMailSender._imap_connections.pop(folder, None)

        return results

    def search_threads_by_bl(self, bl_number: str) -> List[FoundEmailThread]:
        """
        B/L 번호로 IMAP 검색하여 관련 메일 목록 반환
        INBOX + Sent 폴더를 병렬 검색, 결과 캐시 적용
        """
        import concurrent.futures

        # 1) 캐시 확인
        cached = ExportMailSender._search_cache.get(bl_number)
        if cached:
            ts, cached_results = cached
            if (datetime.datetime.now() - ts).total_seconds() < self._CACHE_TTL:
                self.log(f"B/L '{bl_number}' 캐시 반환: {len(cached_results)}건")
                return cached_results

        # 2) 보낸메일함 폴더명 확보
        if ExportMailSender._sent_folder_cache is None:
            try:
                tmp = imaplib.IMAP4_SSL(self.config.imap_server, self.config.imap_port, timeout=15)
                tmp.login(self.config.email, self.config.password)
                ExportMailSender._sent_folder_cache = self._find_sent_folder(tmp) or ""
                tmp.logout()
            except Exception:
                ExportMailSender._sent_folder_cache = ""

        sent_folder = ExportMailSender._sent_folder_cache
        folders = ["INBOX"]
        if sent_folder:
            folders.append(sent_folder)

        since_date = (datetime.datetime.now() - datetime.timedelta(days=14)).strftime("%d-%b-%Y")

        # 3) 병렬 검색 (폴더별 전용 연결)
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(self._search_folder, folder, bl_number, since_date): folder
                for folder in folders
            }
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.extend(future.result())
                except Exception as e:
                    self.log(f"병렬 검색 오류: {e}")

        results.sort(key=lambda x: x.date, reverse=True)
        self.log(f"B/L '{bl_number}' 검색 완료: {len(results)}건 발견")

        # 4) 캐시 저장 (최대 50개)
        if len(ExportMailSender._search_cache) > 50:
            oldest = min(ExportMailSender._search_cache, key=lambda k: ExportMailSender._search_cache[k][0])
            del ExportMailSender._search_cache[oldest]
        ExportMailSender._search_cache[bl_number] = (datetime.datetime.now(), results)

        return results

    def find_export_declaration(self, folder_path: str, identifier: str) -> Optional[str]:
        """
        지정 폴더에서 ID가 일치하는 수출신고필증 찾기
        
        파일명 패턴: {회사명}({ID})수출신고필증.pdf
        """
        if not os.path.exists(folder_path):
            self.log(f"폴더를 찾을 수 없음: {folder_path}")
            return None
        
        # ID 정규화 (공백 제거, 대문자화)
        normalized_id = identifier.replace(" ", "").upper()
        
        # 파일명 패턴: (ID)수출신고필증.pdf 또는 (ID)반송신고필증.pdf
        pattern = re.compile(r'\(([^)]+)\)(?:수출|반송)신고필증\.pdf$', re.IGNORECASE)

        for filename in os.listdir(folder_path):
            if not filename.lower().endswith('.pdf'):
                continue

            match = pattern.search(filename)
            if match:
                file_id = match.group(1).replace(" ", "").upper()
                if file_id == normalized_id:
                    full_path = os.path.join(folder_path, filename)
                    self.log(f"수출/반송신고필증 발견: {filename}")
                    return full_path

        self.log(f"수출/반송신고필증을 찾을 수 없음 (ID: {identifier})")
        return None
    
    def send_reply(self, to_email: str, subject: str, attachment_path: str, 
                   original_message_id: str = None, cc: str = "") -> bool:
        """
        답장 메일 발송 + 보낸 메일함 저장
        """
        if not os.path.exists(attachment_path):
            self.log(f"첨부파일을 찾을 수 없음: {attachment_path}")
            return False
        
        filename = os.path.basename(attachment_path)
        # 확장자 제거한 파일명 (본문용)
        filename_no_ext = os.path.splitext(filename)[0]
        
        # 메일 본문 생성
        body = self.EMAIL_TEMPLATE.format(filename=filename_no_ext)
        
        # MIME 메시지 생성
        msg = MIMEMultipart()
        # 발신자 주소 설정 (별도 설정이 있으면 사용)
        from_addr = self.config.sender_email if self.config.sender_email else self.config.email
        msg['From'] = f'"최명헌" <{from_addr}>'
        msg['To'] = to_email
        if cc:
            msg['Cc'] = cc
            
        msg['Subject'] = f"Re: {subject}" if not subject.startswith("Re:") else subject
        
        # 원본 메시지 참조 (스레드 연결)
        if original_message_id:
            msg['In-Reply-To'] = original_message_id
            msg['References'] = original_message_id
        
        # 본문 추가
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # 첨부파일 추가
        try:
            with open(attachment_path, 'rb') as f:
                # MIMEApplication 사용 (자동으로 base64 인코딩됨)
                part = MIMEApplication(f.read(), Name=filename)
            
            # Content-Disposition 헤더 설정 (한글 파일명 처리)
            part.add_header('Content-Disposition', 'attachment', filename=filename)
            msg.attach(part)
        except Exception as e:
            self.log(f"첨부파일 처리 오류: {e}")
            return False
        
        # SMTP로 메일 발송
        # SMTP로 메일 발송
        try:
            # 수신자 목록 (To + Cc) 구성
            headers_list = []
            if to_email:
                headers_list.append(to_email)
            if cc:
                headers_list.append(cc)
            
            # getaddresses를 사용하여 (이름, 주소) 튜플 리스트 추출
            # 예: [('최명헌', 'mhchoi@ihaedo.com'), ('', 'test@example.com')]
            parsed_addrs = getaddresses(headers_list)
            
            # 실제 이메일 주소만 추출 (이름 제외하여 SMTPUTF8 오류 방지)
            real_recipients = [addr for name, addr in parsed_addrs if addr]
            
            recipients_str = ", ".join(real_recipients)
            self.log(f"메일 발송 중... → {recipients_str}")
            
            smtp = smtplib.SMTP_SSL(self.config.smtp_server, self.config.smtp_port)
            try:
                smtp.login(self.config.email, self.config.password)
                smtp.send_message(msg, to_addrs=real_recipients)
                self.log("메일 발송 완료!")
            finally:
                try:
                    smtp.quit()
                except Exception:
                    pass
        except Exception as e:
            self.log(f"메일 발송 실패: {e}")
            return False
        
        # 보낸 메일함에 저장
        try:
            self.log("보낸 메일함에 저장 중...")
            self._save_to_sent_folder(msg)
            self.log("보낸 메일함 저장 완료!")
        except Exception as e:
            self.log(f"보낸 메일함 저장 실패: {e}")
            # 메일 발송은 성공했으므로 True 반환
        
        return True
    
    def _save_to_sent_folder(self, msg: MIMEMultipart):
        """IMAP으로 보낸 메일함에 저장"""
        imap = None
        try:
            imap = imaplib.IMAP4_SSL(self.config.imap_server, self.config.imap_port)
            imap.login(self.config.email, self.config.password)

            sent_folder = self._find_sent_folder(imap)

            if sent_folder:
                imap.append(sent_folder, "\\Seen", None, msg.as_bytes())
            else:
                self.log("보낸 메일함 폴더를 찾을 수 없음")
        finally:
            if imap:
                try:
                    imap.logout()
                except Exception:
                    pass
    
    def _find_sent_folder(self, imap: imaplib.IMAP4_SSL) -> Optional[str]:
        """보낸 메일함 폴더 찾기 (\\Sent 플래그 기반)"""
        _, folders = imap.list()

        for folder_info in folders:
            decoded = folder_info.decode() if folder_info else ""
            # \Sent 플래그로 찾기 (가장 정확)
            if '\\Sent' in decoded:
                # 폴더명 추출: (...) "/" "폴더명"
                parts = decoded.split('"')
                if len(parts) >= 4:
                    return parts[-2]

        # 폴백: 이름 기반 검색
        sent_names = ['Sent', 'INBOX.Sent', 'Sent Messages', 'Sent Items']
        for folder_info in folders:
            decoded = folder_info.decode() if folder_info else ""
            parts = decoded.split('"')
            folder_name = parts[-2] if len(parts) >= 4 else ""
            if folder_name in sent_names or 'sent' in folder_name.lower():
                return folder_name

        return self.config.sent_folder


# 테스트용
if __name__ == "__main__":
    print("=== ExportMailSender Test ===")
    
    config = EmailConfig(
        email="test@example.com",
        password="test_password"
    )
    
    sender = ExportMailSender(config)
    
    # 테스트: 수출신고필증 찾기
    test_folder = r"C:\test_folder"
    test_id = "ABC123"
    
    result = sender.find_export_declaration(test_folder, test_id)
    print(f"결과: {result}")
