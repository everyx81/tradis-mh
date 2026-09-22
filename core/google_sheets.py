# -*- coding: utf-8 -*-
"""
Google Sheets 연동 모듈
대납금 데이터를 Google Sheets에서 가져오기
"""

import os
import gspread
from google.oauth2.service_account import Credentials

# 스코프 설정 (읽기+쓰기)
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets'
]

# 기본 설정
DEFAULT_SPREADSHEET_ID = "1pUDZ5F36D-Z2oIS4vmNjAHRa4YpzPKplAONj-vyKCAU"
DEFAULT_SHEET_GID = 1250042047


def get_credentials_path() -> str:
    """credentials.json 파일 경로 반환"""
    import sys
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.dirname(__file__))

    data_dir = os.path.join(base_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, 'credentials.json')


def fetch_advances_from_sheet(
    spreadsheet_id: str = None,
    sheet_gid: int = None,
    credentials_path: str = None,
    include_reported: bool = False
) -> list:
    """
    Google Sheets에서 대납금 데이터 가져오기
    
    Args:
        spreadsheet_id: 스프레드시트 ID (기본값 사용 시 None)
        sheet_gid: 시트 GID (기본값 사용 시 None)
        credentials_path: credentials.json 경로 (기본값 사용 시 None)
        include_reported: True면 보고일자가 있는 항목도 포함, False면 제외
    
    Returns:
        대납금 리스트 [{'company': str, 'amount': int, 'expected_date': str, 'is_confirmed': bool, 'row_index': int}, ...]
    
    Raises:
        FileNotFoundError: credentials.json 파일이 없는 경우
        Exception: API 오류
    """
    spreadsheet_id = spreadsheet_id or DEFAULT_SPREADSHEET_ID
    sheet_gid = sheet_gid if sheet_gid is not None else DEFAULT_SHEET_GID
    credentials_path = credentials_path or get_credentials_path()
    
    # 인증 파일 확인
    if not os.path.exists(credentials_path):
        raise FileNotFoundError(
            f"Google 인증 파일이 없습니다: {credentials_path}\n"
            "credentials.json 파일을 프로젝트 폴더에 복사해주세요."
        )
    
    # 인증
    creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    
    # 스프레드시트 열기
    spreadsheet = client.open_by_key(spreadsheet_id)
    
    # GID로 시트 찾기
    sheet = None
    for ws in spreadsheet.worksheets():
        if ws.id == sheet_gid:
            sheet = ws
            break
    
    if sheet is None:
        # GID로 못 찾으면 첫 번째 시트 사용
        sheet = spreadsheet.sheet1
    
    # 데이터 가져오기 (첫 행은 헤더로 가정)
    records = sheet.get_all_records()
    
    advances = []
    for idx, record in enumerate(records):
        # 헤더 이름으로 데이터 매핑 (유연하게 처리)
        company = str(record.get('업체명', '') or record.get('회사명', '') or record.get('company', '')).strip()
        
        # 금액 파싱
        amount_raw = record.get('금액', 0) or record.get('amount', 0) or 0
        try:
            if isinstance(amount_raw, str):
                amount = int(amount_raw.replace(',', '').replace('원', '').strip() or 0)
            else:
                amount = int(amount_raw)
        except (ValueError, TypeError):
            amount = 0
        
        # 입금예정일
        expected_date = str(record.get('입금예정일', '') or record.get('예정일', '') or record.get('date', '')).strip()
        
        # 확인 여부
        confirmed_raw = record.get('확인', False) or record.get('is_confirmed', False) or record.get('confirmed', False)
        if isinstance(confirmed_raw, str):
            is_confirmed = confirmed_raw.upper() in ('TRUE', 'O', '예', 'Y', '1', '확인')
        else:
            is_confirmed = bool(confirmed_raw)
        
        # BL 번호 확인 (여러 키 시도)
        bl_no = str(record.get('BL', '') or record.get('B/L', '') or record.get('HBL', '') or record.get('MBL', '') or record.get('BL NO', '')).strip()

        # 보고일자 확인
        report_date = str(record.get('보고일자', '') or record.get('보고일', '') or '').strip()
        
        # 보고일자가 있으면 이미 보고된 항목
        if not include_reported and report_date:
            continue  # 이미 보고된 항목은 건너뜀
        
        # 유효한 데이터만 추가
        if company:
            advances.append({
                'company': company,
                'bl_no': bl_no,  # BL 번호 추가
                'amount': amount,
                'expected_date': expected_date,
                'is_confirmed': is_confirmed,
                'row_index': idx + 2  # 헤더가 1행이므로 데이터는 2행부터
            })
    
    return advances


def update_report_dates(
    row_indices: list,
    report_date: str = None,
    spreadsheet_id: str = None,
    sheet_gid: int = None,
    credentials_path: str = None
) -> int:
    """
    스프레드시트의 보고일자 열을 업데이트
    
    Args:
        row_indices: 업데이트할 행 번호 리스트 (1-based index)
        report_date: 기록할 날짜 (None이면 오늘 날짜)
        spreadsheet_id: 스프레드시트 ID
        sheet_gid: 시트 GID
        credentials_path: credentials.json 경로
    
    Returns:
        업데이트된 행 수
    """
    from datetime import datetime
    import time
    
    if not row_indices:
        return 0
    
    spreadsheet_id = spreadsheet_id or DEFAULT_SPREADSHEET_ID
    sheet_gid = sheet_gid if sheet_gid is not None else DEFAULT_SHEET_GID
    credentials_path = credentials_path or get_credentials_path()
    report_date = report_date or datetime.now().strftime('%m/%d')
    
    # 인증
    creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    
    # 스프레드시트 열기
    spreadsheet = client.open_by_key(spreadsheet_id)
    
    # GID로 시트 찾기
    sheet = None
    for ws in spreadsheet.worksheets():
        if ws.id == sheet_gid:
            sheet = ws
            break
    
    if sheet is None:
        sheet = spreadsheet.sheet1
    
    # 헤더 가져오기 (컬럼 위치 확인용)
    headers = sheet.row_values(1)
    
    # 보고일자 열 찾기
    report_col = None
    for i, h in enumerate(headers):
        if h in ('보고일자', '보고일'):
            report_col = i + 1  # 1-indexed
            break
    
    if report_col is None:
        raise ValueError("스프레드시트에 '보고일자' 열이 없습니다. 열을 추가해주세요.")
    
    updated_count = 0
    
    # 유효한 행 번호 필터링 (헤더 제외)
    valid_indices = [r for r in row_indices if isinstance(r, int) and r > 1]
    
    # 개별 업데이트 (batch_update를 쓰면 좋지만, 불연속적인 셀 업데이트는 복잡함)
    # 셀 범위 리스트 생성하여 update_cells 사용할 수도 있음
    try:
        # 방식 1: 개별 업데이트 (안전하고 단순함)
        for row_idx in valid_indices:
            sheet.update_cell(row_idx, report_col, report_date)
            updated_count += 1
            time.sleep(0.1)  # API 속도 제한 방지 (안전장치)
            
    except Exception as e:
        print(f"업데이트 중 오류 발생: {e}")
        # 일부만 성공했을 수 있음
    
    return updated_count


# 테스트용
if __name__ == '__main__':
    try:
        advances = fetch_advances_from_sheet()
        print(f"가져온 대납금 데이터: {len(advances)}건")
        for adv in advances:
            print(f"  - {adv['company']}: {adv['amount']:,}원 (row: {adv['row_index']})")
    except Exception as e:
        print(f"오류: {e}")



# ─────────────────────────────────────────────────
# 정산 카드 → 시트 미러 (봇 화이트리스트)
#   탭 "계산서요청": A BL / B 회사명 / C 사업자번호
#   - 카드(신고필증 사업자번호 추출 성공)가 생기면 행 추가, 사라지면 행 삭제
#   - tradis 는 A~C 열만 쓴다. D 열 이후는 봇의 자리 — 절대 건드리지 않는다
# ─────────────────────────────────────────────────
CARD_SHEET_TITLE_DEFAULT = "계산서요청"
CARD_SHEET_HEADERS = ["BL", "회사명", "사업자번호"]
_HTTP_TIMEOUT_SEC = 15


def _open_card_sheet(client, spreadsheet_id: str, title: str):
    """제목으로 탭을 찾고, 없으면 만들어 헤더를 채운다. 헤더가 비어 있으면 채운다."""
    spreadsheet = client.open_by_key(spreadsheet_id)
    sheet = None
    for ws in spreadsheet.worksheets():
        if ws.title == title:
            sheet = ws
            break
    if sheet is None:
        sheet = spreadsheet.add_worksheet(title=title, rows=200, cols=10)
        sheet.update(range_name='A1:C1', values=[CARD_SHEET_HEADERS])
        return sheet
    first = sheet.row_values(1)
    if not any(str(v).strip() for v in first[:3]):
        sheet.update(range_name='A1:C1', values=[CARD_SHEET_HEADERS])
    return sheet


def sync_cards_to_sheet(
    rows: list,
    spreadsheet_id: str = None,
    sheet_title: str = None,
    credentials_path: str = None,
) -> dict:
    """카드 목록을 시트 A~C 열에 거울처럼 맞춘다 (BL 키).

    Args:
        rows: [{'bl': str, 'company': str, 'business_no': str}, ...]
              — 호출측이 사업자번호 있는 카드만 넘긴다
    Returns:
        {'added': n, 'updated': n, 'deleted': n}
    Raises:
        FileNotFoundError: credentials.json 없음 / Exception: API 오류
    """
    spreadsheet_id = spreadsheet_id or DEFAULT_SPREADSHEET_ID
    sheet_title = sheet_title or CARD_SHEET_TITLE_DEFAULT
    credentials_path = credentials_path or get_credentials_path()
    if not os.path.exists(credentials_path):
        raise FileNotFoundError(f"Google 인증 파일이 없습니다: {credentials_path}")

    # 원하는 상태: BL → (회사명, 사업자번호). 같은 BL 이 두 번 오면 뒤가 이긴다
    want = {}
    for r in rows or []:
        bl = str(r.get('bl', '') or '').strip()
        if not bl:
            continue
        want[bl] = (str(r.get('company', '') or '').strip(),
                    str(r.get('business_no', '') or '').strip())

    creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    try:
        client.http_client.session.request = _with_timeout(client.http_client.session.request)
    except Exception:
        pass
    sheet = _open_card_sheet(client, spreadsheet_id, sheet_title)

    # 현재 상태 (A~C 만 읽는다). 행 번호는 1-based, 1행은 헤더
    current = sheet.get_values('A2:C')
    have = {}          # BL → (row_no, company, biz)
    dup_rows = []      # 같은 BL 중복 행 → 삭제 대상
    for i, vals in enumerate(current):
        vals = list(vals) + [''] * (3 - len(vals))
        bl = str(vals[0]).strip()
        row_no = i + 2
        if not bl:
            continue
        if bl in have:
            dup_rows.append(row_no)
            continue
        have[bl] = (row_no, str(vals[1]).strip(), str(vals[2]).strip())

    updates = []   # gspread batch_update 용 {'range':..., 'values':...}
    added = updated = 0
    for bl, (row_no, comp, biz) in have.items():
        if bl in want and want[bl] != (comp, biz):
            updates.append({'range': f'B{row_no}:C{row_no}', 'values': [list(want[bl])]})
            updated += 1
    new_rows = [[bl, comp, biz] for bl, (comp, biz) in want.items() if bl not in have]
    delete_rows = sorted([rn for bl, (rn, _, _) in have.items() if bl not in want] + dup_rows,
                         reverse=True)   # 아래부터 지워야 위 행 번호가 밀리지 않는다

    if updates:
        sheet.batch_update(updates, value_input_option='RAW')
    # 삭제를 추가보다 먼저 — 삭제 후 append 하면 빈 자리부터 채워진다
    for rn in delete_rows:
        sheet.delete_rows(rn)
    if new_rows:
        sheet.append_rows(new_rows, value_input_option='RAW', table_range='A1')
        added = len(new_rows)
    return {'added': added, 'updated': updated, 'deleted': len(delete_rows)}


def _with_timeout(request_fn, timeout=_HTTP_TIMEOUT_SEC):
    """requests.Session.request 에 기본 timeout 을 끼운다 — 인터넷 끊김에 스레드가 매달리지 않게."""
    def _wrapped(method, url, **kw):
        kw.setdefault('timeout', timeout)
        return request_fn(method, url, **kw)
    return _wrapped
