"""
JARVIS 수출 자동화 - 메일 발송 모듈
한비로 SMTP를 사용하여 수출신고필증을 첨부한 답장 메일을 발송합니다.
"""

import os
import re
import smtplib
import imaplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.application import MIMEApplication
from email import encoders
from email.utils import getaddresses
from typing import Optional, Callable
from dataclasses import dataclass


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
    
    def __init__(self, config: EmailConfig, log_callback: Optional[Callable[[str], None]] = None):
        self.config = config
        self.log_callback = log_callback
    
    def log(self, msg: str):
        if self.log_callback:
            self.log_callback(msg)
        print(f"[MailSender] {msg}")
    
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
        
        # 파일명 패턴: (ID)수출신고필증.pdf
        pattern = re.compile(r'\(([^)]+)\)수출신고필증\.pdf$', re.IGNORECASE)
        
        for filename in os.listdir(folder_path):
            if not filename.lower().endswith('.pdf'):
                continue
            
            match = pattern.search(filename)
            if match:
                file_id = match.group(1).replace(" ", "").upper()
                if file_id == normalized_id:
                    full_path = os.path.join(folder_path, filename)
                    self.log(f"수출신고필증 발견: {filename}")
                    return full_path
        
        self.log(f"수출신고필증을 찾을 수 없음 (ID: {identifier})")
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
        msg['From'] = self.config.sender_email if self.config.sender_email else self.config.email
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
            smtp.login(self.config.email, self.config.password)
            # 명시적으로 수신자 목록(To+Cc)을 전달 (순수 이메일 주소만)
            smtp.send_message(msg, to_addrs=real_recipients) 
            smtp.quit()
            self.log("메일 발송 완료!")
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
        imap = imaplib.IMAP4_SSL(self.config.imap_server, self.config.imap_port)
        imap.login(self.config.email, self.config.password)
        
        # 보낸 메일함 폴더명 확인 (한비로는 Sent, INBOX.Sent, 보낸편지함 등일 수 있음)
        # 폴더 목록 조회하여 적절한 폴더 찾기
        sent_folder = self._find_sent_folder(imap)
        
        if sent_folder:
            imap.append(sent_folder, "\\Seen", None, msg.as_bytes())
        else:
            self.log("보낸 메일함 폴더를 찾을 수 없음")
        
        imap.logout()
    
    def _find_sent_folder(self, imap: imaplib.IMAP4_SSL) -> Optional[str]:
        """보낸 메일함 폴더 찾기"""
        _, folders = imap.list()
        
        # 일반적인 보낸 메일함 이름들
        sent_names = ['Sent', 'INBOX.Sent', '보낸편지함', 'Sent Messages', 'Sent Items']
        
        for folder_info in folders:
            folder_name = folder_info.decode().split('"')[-2] if folder_info else ""
            if folder_name in sent_names:
                return folder_name
            if 'sent' in folder_name.lower():
                return folder_name
        
        # 기본값 시도
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
