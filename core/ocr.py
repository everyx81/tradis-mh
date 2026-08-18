# JARVIS Core - Gemini OCR
"""
Gemini AI 기반 PDF OCR 분석
"""

import os
import sys
import re
import io
import json
import time
import threading
import hashlib
import copy

from .config import get_client
from .utils import pdf_lock, cache_lock

# (절대경로, mtime, size) → md5. 같은 파일을 반복문에서 여러 번 검증할 때
# 전체 재읽기+재해시를 피한다. 파일이 수정되면 mtime/size가 바뀌어 키가 달라짐.
_hash_memo = {}
_HASH_MEMO_MAX = 2000

# 서류 종류 판별 로직 버전. 값을 올리면 캐시에 남아 있는 신고서/신고필증 분류를
# 다음 조회 때 텍스트 레이어로 1회 재검증한다 (AI 재호출 없음).
DOC_CLASSIFIER_VER = 2
_DECL_TYPES = ('수입신고필증', '수출신고필증', '반송신고필증', '수입신고서', '수출신고서')


def _compute_file_hash(fp):
    """파일 내용 해시 반환 (md5, 16진수 문자열).
    PDF 수정(금액 변경 등) 시 size 가 같아도 해시는 달라지므로 정확한 내용 비교 가능."""
    try:
        st = os.stat(fp)
        key = (os.path.abspath(fp), st.st_mtime, st.st_size)
        memoized = _hash_memo.get(key)
        if memoized is not None:
            return memoized
        h = hashlib.md5()
        with open(fp, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        digest = h.hexdigest()
        if len(_hash_memo) >= _HASH_MEMO_MAX:
            _hash_memo.clear()
        _hash_memo[key] = digest
        return digest
    except Exception:
        return None


class GeminiOCR:
    """Gemini AI 기반 PDF OCR 분석기"""
    
    def __init__(self):
        # 캐시 JSON 메모리 상주 사본 — 매 조회마다 파일 전체를 재파싱하지 않는다.
        # 파일 mtime이 로드 시점과 다르면(외부 변경) 자동 재로드.
        self._cache_data = None
        self._cache_file_mtime = None
        self.model_id = 'gemini-3.5-flash-lite'
        self.base_prompt = """
당신은 최고의 전문 관세사 사무원입니다. PDF 문서의 이미지를 분석하여 다음 정보를 JSON 형식으로만 응답하세요.

[1단계: 분석 지침]
1. company_name (업체명 추출 규칙):
   - 수입신고필증, 수입신고서: **납세의무자(수입자)의 상호** — 문서의 "수입자" 또는 "납세의무자" 칸에서 추출
     • [절대 금지] "해외거래처"/"해외공급자" 칸의 외국 회사명(예: OOO HK LTD, OOO TRADING CO, OOO CO.,LTD)을 추출하지 마세요. 해외거래처는 물건을 판 외국 회사이지 수입자가 아닙니다.
   - 수출신고필증, 수출신고서, 반송신고필증: **수출대행자/수출화주의 상호** (해외 구매자 아님)
   - 자금정산서, 자금청구서: 실화주(화주) 명
   - 납부고지서: 납부자의 상호
   - 세금계산서, 계산서, 영수증, 입금표: 공급받는자(수신자)의 상호
   - 수입요건 서류: 수입자 상호
   - 적합성평가확인서 (방송통신기자재등의 적합성평가확인 신청서 등): 수입자(신청인) 상호
   - [절대 금지 — 공통] "성명"/"(대표자)성명" 칸의 사람 이름을 상호로 추출하지 마세요. 대표자 이름이 영문 로마자(예: HONG GUANGMI, JIN XIN)여도 사람 이름이지 상호가 아닙니다. 상호 칸 옆이 비어 보이면 문서의 다른 위치(하단 납부자/수입자 블록 등)에서 상호를 찾으세요.
   - 공통: (주), 주식회사 등 법인명 접미사는 제외하고 본 이름만 추출하며, 모든 공백(띄어쓰기)은 반드시 제거하세요.
   - 공통: 상호가 영문·한글 병기인 경우(예: "GUNS N WORKS(건즈앤웍스)", "ABC CO.,LTD(에이비씨)") 반드시 **한글 표기**를 추출하세요. 한글 표기가 아예 없을 때만 영문 상호를 그대로 사용하세요.
   - [중요] 업체명은 문서에 기재된 그대로 완전하게 추출하세요. 절대 축약하거나 일부만 추출하지 마세요. 예: "에이수스코리아"를 "에이수스"로 줄이지 마세요. "한의코퍼레이션"을 "한의"로 줄이지 마세요.

2. identifier (식별 번호) - [매우 중요]:
   - 문서 내에서 B/L 번호 또는 Invoice 번호를 반드시 찾아 추출하세요.

   [★ 수입신고서 / 수입신고필증 특별 안내 ★]
   - 수입신고서·수입신고필증은 반드시 **"B/L(AWB)번호"** 필드를 찾아 추출하세요.
   - 보통 신고번호 근처의 박스 안에 기재되며, 영문 선사코드 + 숫자 조합입니다.
     • 예시: HDMU1234567890, COSU98765432, MAEU12345678, ONEY123456789
     • 항공건은 AWB 번호 (숫자 11자리): 123-45678901
   - "적하목록관리번호(MRN)"는 세관 관리용 번호이며 **B/L 번호가 아닙니다** — 혼동 금지.

   [★ 수출신고필증 / 반송신고필증 특별 안내 ★]
   - "송품장부호" 필드가 Invoice 번호입니다. 반드시 송품장부호를 identifier로 추출하세요.

   [★ 자금청구서 / 자금정산서 특별 안내 ★]
   - "B/L I/V No", "B/L No", "B/L 번호" 필드에 기재된 값을 identifier 로 추출하세요.
   - 영문 선사코드 + 숫자 조합이며, **끝에 영문자 1자** 가 붙는 경우가 있습니다. 이 경우에도 반드시 그대로 포함해 추출:
     • 예: HSLI024354400078I, COHEAR591YN040, MAEU267065552A
   - 같은 문서에 '신고번호'(하이픈 포함, 예: 13133-26-000839M) 가 함께 있어도 **B/L I/V No 필드를 우선** 으로 추출.
   - O/0, I/1/l 구분이 모호해도 문서에 보이는 그대로 최선으로 읽고, 아예 필드가 보이지 않을 때만 Unknown.

   [★ BL 필드에 복수 값이 있을 때 ★]
   - 계산서/세금계산서 등에서 BL 필드에 여러 번호가 함께 기재된 경우 (예: "BL : 26PRO000859 TRITON 0791-045E"),
     **첫 번째로 등장하는 값을 identifier 로 선택** 하세요.
   - 한국식 통관 코드 형식 (예: 26PRO000859 — YY 숫자 + 영문 2-4자 + 숫자) 과 선사 B/L (예: TRITON0791-045E, HDMU12340001)
     이 함께 있을 때는 **첫 번째로 등장하는 것 우선**. 보통 한국식 코드가 먼저 기재됨.
   - 값 사이에 공백/구분자가 있으면 확실히 다른 번호임. 절대 합쳐서 하나로 처리 금지.

   [주의] 다음은 B/L 번호가 아닙니다. 절대 identifier로 추출하지 마세요:
     • 신고번호 (예: 13133-26-000199X, HSIV-26011513133-26-000199X) — '-'로 구분된 형태
     • 접수번호, 승인번호, 관리번호, 세관번호, 신고확인번호
     • 적하목록관리번호(MRN) — 세관 관리용
     • 사업자등록번호, 통관고유부호
     • 문서 상단이나 하단의 행정 관리용 번호
     • 시험·검사기관(SGS, KCL, KTL, FITI 등) 계산서의 접수번호/시험번호/성적서번호 — 'M' + 숫자 형태 (예: M/2601/04760, M260104760). 정밀검사·시험 계산서에 B/L 번호가 없으면 반드시 'Unknown'

   [필독] 명확한 B/L 또는 Invoice 번호가 확인되지 않는 경우, 다른 번호를 무리하게 유추하지 말고 반드시 'Unknown'을 반환하세요. 잘못된 번호 추출보다 Unknown을 반환하는 것이 안전합니다.

3. id_type: 'BL' 또는 'Invoice'

4. doc_type (문서 종류 결정 - [매우 중요]):
   A-0. [최우선 선행 체크 — 신고필증/신고서]: 신고 서식(수입/수출)으로 보이면 doc_type을 정하기 전에 아래 순서로 확인하세요.
        (1) 제목 칸이 "견   본 (수입)" / "견   본 (수출)" 으로 인쇄되어 있거나, 문서 맨 위 또는 맨 아래에 "이 문서는 임시용 견본입니다" 문구가 있으면
            → 제목이 무엇이든 무조건 '수입신고서'(수입건) 또는 '수출신고서'(수출건)
        (2) 견본 표기가 없으면 제목 글자를 그대로 읽으세요. 제목은 자간을 넓게 인쇄합니다 ("수 입 신 고 서", "수 입 신 고 필 증").
            공백을 지우고 읽되 **"필 증" 두 글자의 유무** 만으로 판정하세요.
        [경고] 견본 표기가 없다는 사실은 신고필증의 근거가 **아닙니다**. 견본 표기가 전혀 없는 정상 '수 입 신 고 서' 가 흔하게 존재합니다.
        '수입신고서'는 '수입신고필증'보다 드물다는 이유로 필증 쪽으로 기울이지 마세요. 글자에 '필증'이 없으면 신고서입니다.
   A. [절대 기준] 문서 제목을 그대로 정확히 읽어 반환하세요:
      - 자주 등장하는 제목 예시: '수입신고필증', '수입신고서', '수출신고필증', '수출신고서', '반송신고필증', '자금정산서', '자금청구서', '납부고지서', '수입세금계산서', '적합성평가확인서', '이체증'
      - [이체증 특별 규칙] 은행 이체 확인증/이체증인 경우:
        • doc_type: '이체증'
        • company_name: **받는분통장표시** (받는 분 이름/상호)를 추출하세요.
        • identifier: 'Unknown'
        • total_amount: 이체 금액
      - [중요 — 구분이 필요한 문서들]:
        • '자금정산서'와 '자금청구서'는 **다른 문서**입니다. 제목을 정확히 읽어 구분하세요.
        • '수입신고서'와 '수입신고필증'은 **다른 문서**입니다. 구분하세요.
        • '수출신고서'와 '수출신고필증'은 **다른 문서**입니다. 구분하세요.
      - [★ 절대 규칙 — 임시용 견본 감지 ★]
        제목 칸이 "견   본 (수입)" / "견   본 (수출)" 이거나, 문서 최상단·최하단에 "이 문서는 임시용 견본입니다" 문구가 있으면:
        • 제목이 "수입신고필증" 으로 적혀 있어도 → 반드시 **doc_type: "수입신고서"** 로 반환
        • 제목이 "수출신고필증" 으로 적혀 있어도 → 반드시 **doc_type: "수출신고서"** 로 반환
        • 이유: 견본은 신고수리 전 단계의 임시 출력물이며, 신고필증은 수리 후 발급됩니다.
        • 이 규칙은 제목 텍스트보다 **우선** 합니다.
      - [참고 — 신고필증 vs 신고서 판정 근거 (있는 것만 근거로 쓰세요)]:
        • 신고필증에만 있는 것: 최상단 "* 본 신고필증은 전자문서(PDF파일)로 발급된 신고필증입니다" 안내문,
          "시점확인필" 스템프, 하단 "발 행 번 호 : ..." 줄, 그리고 "수리일자" 칸에 날짜가 채워져 있음.
        • 신고서: 위 안내문·스템프·발행번호가 **전혀 없고**, "수리일자" 칸이 비어 있으며, 문서 상단이 업태/종목·신고번호 줄로 시작.
        • 임시용 견본(구서식): 제목 자리가 "견   본 (수입)" 이고 상·하단에 "이 문서는 임시용 견본입니다" → '수입신고서'
      - [★ 한글이 깨져 보이는 문서 — 오분류 금지 ★]
        폰트 문제로 한글 라벨/제목이 거의 렌더링되지 않고 숫자·영문만 보이는 문서는, 제목을 추측해 '수입신고필증'으로 단정하지 마세요.
        • 좌우 2개의 사업자등록번호 박스(공급자=세관 / 공급받는자) + 큰 금액(과세표준)과 그 약 1/10 금액(세액) + 수납계좌·customs.go.kr 안내 구조 → 세관 발행 **'수입세금계산서'**
        • 세관 사업자등록번호가 공급자 위치에 보이면 수입세금계산서 가능성 높음. 예: 121-83-00561(인천본부세관), 109-83-02763(인천공항세관), 601-83-00048(부산세관)
        • 수입신고필증의 판별 근거(품명/규격 표, 세번부호, 결제금액 란 등)가 전혀 보이지 않으면 무리하게 추측하지 말고 doc_type 'Unknown'을 반환하세요.
      - 문서에 적힌 제목이 예시에 없더라도 임의로 바꾸지 말고 적힌 그대로 반환하세요. (시스템이 후처리로 표준화합니다)

   B. [내용 기반 심층 분석]
      - 제목이 '세금계산서', '전자세금계산서', '계산서', '청구서', '영수증', '입금표' 등 범용적인 명칭일 경우, **반드시 품목/비고/내용을 분석**하여 실질에 맞는 이름을 부여하세요.

      [카테고리 목록]
      1) **선박운임계산서** — Ocean Freight(O/F), BAF, CAF, LSS, THC, Wharfage, D/O Fee, CIC, EBS, Documentation Fee, Drayage(셔틀/부두이송), 부대비용, Handling Charge(포워더/선사/물류사 발행 시).
         [★ 포워더 분할 발행 규칙] 공급자가 포워더/선사/물류사이고 D/O CHARGE, THC, Wharfage 등 해상 부대비용 항목이 **하나라도** 포함되면, TRUCKING/내륙운송 항목이 함께 있고 금액이 더 커도 → 반드시 **선박운임계산서**로 분류.
         (예: TRUCKING CHARGE 48,400 + DO CHARGE 27,500 → 선박운임계산서. 포워더는 해상운임과 부대비용을 여러 장으로 나눠 발행하는 경우가 많음)
      2) **보세운송료계산서** — 보세운송료, 보세운송, Bonded Trucking.
      3) **운송료계산서** — 운송료, 배차료, 내륙운임, Trucking, 셔틀비, 상하차비, 컨테이너 운송.
         단, D/O CHARGE 등 해상 부대비용이 항목에 함께 있으면 → 1) 선박운임계산서. 순수 운송사의 컨테이너운송비/운송료 단독 청구만 여기에 해당.
      4) **창고료계산서** — 창고료, 보관료(Storage), 보험료(화재보험/적하보험 등), 하역료, CFS Charge, 입출고료, **세관설비사용료**, **경비료**(창고 경비/보안료).
         [★ 창고업 판정 힌트] 공급자의 **업태가 '창고'** 이거나 **종목에 '보관' 또는 '창고'** 가 포함되면 창고 관련 계산서로 간주. 품목이 세관설비사용료/경비료만 있어도 창고료계산서로 분류 (공급자 상호에 '관세' 가 포함되어 기관명처럼 보여도 마찬가지 — 예: 한국관세무역개발원).
      5) **통관수수료계산서** — 통관수수료, 관세사수수료, 검역수수료(식품/검역/동물), 요건대행료, 취급수수료(관세사 청구시).
         주의: '창고료'나 '운송료' 단어가 섞여 있어도 주된 청구자가 '관세법인'이거나 통관 관련 내역이 더 많으면 통관수수료계산서로 분류.
         주의: 'Handling Charge'만 있고 공급자가 포워더/선사/물류사인 경우 → 선박운임계산서(1번)로 분류. 통관수수료계산서는 반드시 관세법인/관세사무소가 발행한 경우에만 해당.
         [★ 제외 규칙] 공급자 상호에 '관세' 가 포함되어도 실제로는 창고업 (업태 '창고', 종목 '보관/운수') 인 경우 (예: 한국관세무역개발원) → 4번 창고료계산서로 분류.
         [★ 제외 규칙] 세관설비사용료/경비료/시설사용료 등 시설 관련 비용만 청구된 경우 → 4번 창고료계산서로 분류.
         [★ 제외 규칙] 품목이 '검사수수료/정밀검사/실험비용/분석수수료/시험수수료' 이고 공급자가 관세법인이 아닌 검사·시험·분석 기관 인 경우 → 7번 정밀검사실험비용계산서로 분류. 검역수수료(식품/식물/동물)는 계속 통관수수료계산서 유지.
      6) **항공운임계산서** — Air Freight, FSC(유류할증료), SSC(보안할증료), AWB Fee, CCFE(착불수수료).
      7) **정밀검사실험비용계산서** — 품목이 '검사수수료', '정밀검사', '실험비용', '실험비', '분석수수료', '시험수수료', '시험성적서' 등인 경우. 수입품의 세관 지정 정밀검사·시험·분석 관련 비용.
         공급자 예: 한국건설생활환경시험연구원(KCL), 한국산업기술시험원(KTL), FITI 시험연구원, 기타 시험·분석·분석 연구기관.
         [★ 주의] 식물/식품/동물 검역수수료는 여기 아님 — 5번 통관수수료계산서 유지.
      8) 그 외: 위 카테고리에 해당하지 않는 순수한 물품 대금 거래인 경우 원래 제목 유지.

      [★ 핵심 분류 원칙 — 반드시 준수 ★]
      a) 모든 청구 항목이 같은 카테고리 → 해당 카테고리 계산서명 사용.
      b) 청구 항목이 여러 카테고리에 걸쳐 있는 통합 계산서인 경우:
         → 각 항목을 위 카테고리에 대입하고, 카테고리별 금액 합계가 가장 큰 카테고리로 doc_type을 결정.
         → 어떤 카테고리에도 해당하지 않는 항목(라벨제작비용, 창고보수작업료 등)은 카테고리 판정에서 제외.
         예시: 품목란이 보세운송료 143,000 / 창고보수작업료 440,000 / 운송료 44,000 / 라벨제작비용 264,000 이면
               카테고리 매칭: 보세운송료(143,000)=2), 운송료(44,000)=3), 나머지=해당없음
               → 가장 큰 카테고리 2) → doc_type: "보세운송료계산서"

5. total_amount:
   - 문서에 표시된 최종 청구/결제 총금액 (오직 숫자만 반환)
   - [최우선] "대납비용 포함 총 합계 금액은 XXX 입니다", "총합계: XXX", "최종금액: XXX" 등 세금계산서 표 바깥(하단)에 별도 기재된 최종 합계 문구가 있으면 그 금액을 반드시 사용
   - 비고란에 W/F, Wharfage 등 별도 부과 항목이 있으면 이를 포함한 최종 합계를 사용
   - 합계금액과 별도의 총금액이 함께 있으면, 가장 큰(최종) 금액을 사용
   - 공급가액만 추출 금지, 부가세 포함 금액 우선
   - billing_items 합산값이 아닌, 문서에 명시된 최종 금액을 사용할 것

6. product_name:
   - 수입요건 증빙서류(검역증명서, 적합성평가확인서 등)인 경우에만, 해당 품목명(품명)을 추출하세요.
   - 예: 수입식물검역합격증의 품목명 → "바나나", "커피생두" 등
   - 그 외 문서는 빈 문자열("")을 반환하세요.

7. supplier_name:
   - 세금계산서, 계산서, 영수증, 입금표인 경우: 공급자의 상호를 추출하세요.
   - 공급자가 명시되지 않은 보험료 영수증 등의 경우: 문서에 기재된 창고명(보관 업체명)을 추출하세요.
   - (주), 주식회사 등 법인명 접미사는 제외하고 본 이름만 추출하며, 모든 공백은 반드시 제거하세요.
   - 그 외 문서는 빈 문자열("")을 반환하세요.

[2단계: 추가 정보 (자금정산서 전용)]
- 자금정산서인 경우에만 아래 필드를 추가로 포함하세요:
1. merge_info:
   - expense_items: 명세서(Table)에 나열된 항목 중 금액이 0보다 큰 항목을 [{"name": "항목명", "amount": 100000}] 형태의 객체 리스트로 반환
   - [중요] "식품검역수수료"와 "식물검역수수료"는 별개 항목입니다. 원문에 "식물"이라 쓰여있으면 반드시 "식물검역수수료"로 반환하세요. "식품"으로 바꾸지 마세요.

[2-1단계: 추가 정보 (수입신고필증 전용)]
- 수입신고필증인 경우에만 아래 필드를 추가로 포함하세요:
1. levy_type (징수형태):
   - 문서에 기재된 "징수형태" 코드 2자리 숫자를 추출 (예: "11", "14", "43")
   - 징수형태가 명시되어 있지 않으면 "Unknown"
2. customs_duty (관세): 관세 금액 (숫자만, 없으면 0)
3. vat (부가세): 부가가치세 금액 (숫자만, 없으면 0)

[2-2단계: 사업자등록번호 (수입신고필증/수출신고필증/반송신고필증 전용)]
- business_no: 사업자등록번호를 "123-45-67890" 형식 그대로 추출
  - 수입신고필증: **납세의무자**의 사업자등록번호 (통관고유부호와 혼동 금지, 하이픈 포함 형식)
  - 수출신고필증/반송신고필증: **수출화주(수출자)**의 사업자등록번호
  - [주의] 신고인(관세사무소/관세법인)의 사업자번호를 추출하면 안 됩니다
  - 명확히 확인되지 않으면 "Unknown"

[3단계: 청구 항목 추출]
- 계산서/세금계산서/영수증/입금표인 경우:
  - billing_items: 문서 내 모든 청구 항목을 [{"name": "항목명", "amount": 금액}] 리스트로 반환
  - [매우 중요] amount는 반드시 **부가세(세액) 포함 금액**으로 반환하세요.
    공급가액과 세액이 별도 칸에 분리 기재된 경우 두 값을 합산한 금액을 반환하세요.
    (예: 공급가액 70,000 + 세액 7,000 → amount: 77000)
  - 품목란뿐만 아니라 비고란, 부기사항 등에 기재된 추가 비용 항목도 반드시 포함
  - 금액 0인 항목 제외, 항목이 1개여도 리스트로 반환
- 그 외 문서(신고필증, 납부고지서, 정산서 등)는 billing_items를 빈 리스트 [] 반환

[3-1단계: 사업자등록번호 (계산서/세금계산서/영수증/입금표 전용)]
- supplier_business_no: 공급자(발행처)의 사업자등록번호 ("123-45-67890" 형식 그대로)
- buyer_business_no: 공급받는자의 사업자등록번호 ("123-45-67890" 형식 그대로)
- [주의] 공급자 칸과 공급받는자 칸을 절대 혼동하지 마세요. 각 칸에서 따로 읽으세요.
- 각각 명확히 확인되지 않으면 "Unknown". 그 외 문서는 두 필드 모두 "Unknown"

응답은 오직 JSON 형식이어야 하며, 다른 텍스트는 포함하지 마세요.
"""

    def analyze_pdf(self, fp, force=False):
        """PDF 분석 (파일 캐싱 적용). force=True면 캐시를 무시하고 재분석 후 캐시 갱신
        (business_no 백필 등 구 캐시에 새 필드를 채울 때 사용)."""
        client = get_client()
        if client is None:
            return {"company_name": "Unknown", "identifier": "Unknown", "id_type": "Unknown", "doc_type": "Unknown"}

        # --- 캐시 확인 ---
        if not force:
            cached_result = self._get_cached_result(fp)
            if cached_result:
                print(f"[캐시] 사용: {os.path.basename(fp)}")
                return cached_result

        # --- 표준 서식 직독 (관세청 전산 출력물은 텍스트 레이어로 확정, AI 불필요) ---
        from .form_parser import parse_standard_form
        parsed = parse_standard_form(fp)
        if parsed:
            print(f"[직독] 표준서식 확정: {os.path.basename(fp)} → {parsed['doc_type']} / {parsed['company_name']}")
            self._save_to_cache(fp, parsed)
            return parsed

        try:
            from google.genai import types

            # 토큰 절약: 다중 페이지 PDF 는 1페이지만 추출해 전송
            # (페이지당 ~258 토큰 절감, 5페이지 → 1페이지 시 ~1,000 토큰 절약)
            pdf_bytes = self._extract_first_page_bytes(fp)

            if not pdf_bytes:
                return {"company_name": "Unknown", "identifier": "Unknown", "id_type": "Unknown", "doc_type": "Unknown"}

            # 텍스트 레이어 동봉: 이미지 인식이 서식의 라벨-값 짝짓기를 틀리는 오독
            # (해외거래처를 수입자로, 성명을 상호로)을 원문 문자열로 교정.
            # 스캔본(텍스트 없음)은 기존과 동일하게 이미지만 전송.
            prompt = self.base_prompt
            page_text = ''
            try:
                from .form_parser import _first_page_text
                page_text = (_first_page_text(fp) or '').strip()
                if len(page_text) >= 50:
                    prompt = (self.base_prompt
                              + "\n\n[참고 — 아래는 PDF에서 기계 추출한 원문 텍스트입니다. "
                              + "상호/번호 등 라벨-값 판단 시 이미지와 함께 반드시 활용하세요]\n"
                              + page_text[:4000])
            except Exception:
                pass

            response = client.models.generate_content(
                model=f"models/{self.model_id}",
                contents=[
                    prompt,
                    types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
                ],
                # 기본 해상도가 낮아지면 OCR 환각(번호 오독)이 발생하므로 high 고정
                config=types.GenerateContentConfig(
                    media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH
                )
            )
            text_response = response.text.strip()
            text_response = re.sub(r'```(?:json)?\n?(.*?)\n?```', r'\1', text_response, flags=re.DOTALL).strip()
            match = re.search(r'\{.*\}', text_response, re.DOTALL)
            if match:
                text_response = match.group(0)

            result = json.loads(text_response)

            # doc_type 표준 정규화
            from .utils import normalize_doc_type
            if "doc_type" in result:
                result["doc_type"] = normalize_doc_type(result["doc_type"])

            # --- 신고서/신고필증 직독 확정 (AI 판정보다 우선) ---
            # 이미지 판독은 자간이 넓은 "수 입 신 고 서" 를 빈번형인 "수입신고필증" 으로
            # 정규화해 읽는 오분류가 반복된다. 제목·견본 문구는 텍스트 레이어에 그대로
            # 들어 있으므로 확정 판별되면 AI 값을 덮어쓴다. (스캔본은 None → AI 값 유지)
            from .form_parser import classify_declaration
            confirmed = classify_declaration(page_text)
            if confirmed:
                if result.get("doc_type") != confirmed:
                    print(f"[직독] 신고 서류 교정: {result.get('doc_type')} → {confirmed} "
                          f"({os.path.basename(fp)})")
                result["doc_type"] = confirmed
                result["doc_type_src"] = "text_layer"

            # 신고필증 3종은 business_no 키를 보장 — 모델이 키를 생략해도
            # 'Unknown'으로 확정 저장해 캐시가 영구 유효하도록 (재분석 루프 방지)
            if result.get('doc_type') in ('수입신고필증', '수출신고필증', '반송신고필증'):
                result.setdefault('business_no', 'Unknown')

            # --- 결과 캐싱 저장 (모든 파일) ---
            self._save_to_cache(fp, result)

            return result
        except Exception as e:
            print(f"AI 분석 오류: {e}")
            return {"company_name": "Unknown", "identifier": "Unknown", "id_type": "Unknown", "doc_type": "Unknown"}

    def _extract_first_page_bytes(self, fp):
        """1페이지 PDF 바이트 반환. 단일 페이지 PDF 는 원본 바이트 그대로.
        토큰 비용 절감 목적 (Gemini PDF 페이지당 ~258 토큰).
        실패 시 원본 PDF 바이트 fallback."""
        try:
            import pypdfium2 as pdfium
            import io as _io
            src = pdfium.PdfDocument(fp)
            try:
                if len(src) <= 1:
                    with open(fp, 'rb') as f:
                        return f.read()
                dst = pdfium.PdfDocument.new()
                try:
                    dst.import_pages(src, [0])
                    buf = _io.BytesIO()
                    dst.save(buf)
                    return buf.getvalue()
                finally:
                    dst.close()
            finally:
                src.close()
        except Exception as e:
            print(f"[OCR] 1페이지 추출 실패, 원본 사용: {e}")
            try:
                with open(fp, 'rb') as f:
                    return f.read()
            except Exception:
                return None

    def _get_cache_path(self, fp):
        """캐시 파일 경로 반환"""
        run_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if getattr(sys, 'frozen', False):
            run_dir = os.path.dirname(sys.executable)
            
        data_dir = os.path.join(run_dir, 'data')
        os.makedirs(data_dir, exist_ok=True)
        
        return os.path.join(data_dir, ".analysis_cache.json")

    def _load_cache(self):
        """캐시 JSON을 메모리 사본으로 반환. 최초 1회만 디스크에서 파싱하고,
        이후에는 파일 mtime이 바뀐 경우(외부 변경)에만 다시 읽는다.
        호출자는 cache_lock을 잡은 상태여야 한다."""
        cache_path = self._get_cache_path('')
        try:
            disk_mtime = os.path.getmtime(cache_path)
        except OSError:
            # 캐시 파일 없음
            self._cache_data = {}
            self._cache_file_mtime = None
            return self._cache_data

        if self._cache_data is None or disk_mtime != self._cache_file_mtime:
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    self._cache_data = json.load(f)
            except Exception as e:
                print(f"캐시 읽기 오류: {e}")
                self._cache_data = {}
            self._cache_file_mtime = disk_mtime
        return self._cache_data

    def _write_cache(self):
        """메모리 캐시를 디스크에 기록하고 mtime을 동기화.
        호출자는 cache_lock을 잡은 상태여야 한다."""
        cache_path = self._get_cache_path('')
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(self._cache_data, f, ensure_ascii=False, separators=(',', ':'))
        try:
            self._cache_file_mtime = os.path.getmtime(cache_path)
        except OSError:
            self._cache_file_mtime = None

    def _get_cached_result(self, fp):
        """캐시에서 결과 조회.

        무효화 규칙 (우선순위):
        1. hash 필드 있으면: 파일 내용 해시 비교 (내용 변경 100% 감지, cross-volume 이동 보호)
        2. hash 없고 size 있으면: 크기 비교 (v1.1.8~ 구 캐시 하위호환)
        3. hash/size 모두 없으면: mtime 비교 (최초기 캐시 하위호환)
        hash 미존재 엔트리는 다음 OCR 시 자동으로 해시 포함 버전으로 교체됨.
        """
        try:
            filename = os.path.basename(fp)
            with cache_lock:
                cache = self._load_cache()
                entry = cache.get(filename)
            if entry is None:
                return None

            file_mtime = os.path.getmtime(fp)
            file_size = os.path.getsize(fp)

            cached_hash = entry.get('hash')
            cached_size = entry.get('size')

            if cached_hash is not None:
                # 해시 기반 검증 (가장 정확)
                file_hash = _compute_file_hash(fp)
                if file_hash is None or file_hash != cached_hash:
                    return None  # 내용 변경 또는 해시 계산 실패 → 무효
                # 내용 동일 → 유효. mtime 이 다르면 비동기 반영 (서버 이동 등)
                if file_mtime != entry.get('mtime', 0):
                    with cache_lock:
                        try:
                            _cache = self._load_cache()
                            if filename in _cache:
                                _cache[filename]['mtime'] = file_mtime
                                self._write_cache()
                        except Exception:
                            pass
            elif cached_size is not None:
                # 구 캐시 (hash 없음) — 크기로 검증 + 다음 OCR 시 자동 해시화
                if file_size != cached_size:
                    return None
                if file_mtime != entry.get('mtime', 0):
                    with cache_lock:
                        try:
                            _cache = self._load_cache()
                            if filename in _cache:
                                _cache[filename]['mtime'] = file_mtime
                                self._write_cache()
                        except Exception:
                            pass
            else:
                # 최초기 캐시 (size 도 없음) — mtime 으로만 검증
                if file_mtime > entry.get('mtime', 0):
                    return None

            result = entry.get('result')
            # 기존 캐시에 정규화되지 않은 doc_type이 있으면 로드 시점에 정규화
            if result and 'doc_type' in result:
                from .utils import normalize_doc_type
                result['doc_type'] = normalize_doc_type(result['doc_type'])
            # 신고서/신고필증 분류 로직이 바뀌었으면 텍스트 레이어로 1회 재검증한다
            # (AI 재호출 없음). 사용자가 수동 교정한 값은 건드리지 않는다.
            # levy_type 무효화 검사보다 먼저 수행해야, 실제로는 신고서인 항목이
            # levy_type 없다는 이유로 통째 재OCR 되는 낭비를 막는다.
            if (result and result.get('doc_type') in _DECL_TYPES
                    and result.get('doc_type_src') != 'manual'
                    and entry.get('cls_ver', 0) < DOC_CLASSIFIER_VER):
                self._revalidate_declaration(fp, filename, result)

            # 수입신고필증에 levy_type 필드가 없는 구 캐시는 재분석을 위해 무효화
            if result and result.get('doc_type') == '수입신고필증':
                if 'levy_type' not in result:
                    return None
            # 주의: business_no 누락은 무효화하지 않음 (소프트 미스) —
            # 무효화하면 levy_type 등 유효한 캐시까지 소실되고 파일 처리 파이프라인이
            # 전부 재분석을 유발함. business_no 백필은 GroupCard가 force 재분석으로 처리.
            #
            # 메모리 캐시가 호출자와 공유되지 않도록 사본 반환 (호출자가 result를
            # 수정해도 캐시 원본이 오염되지 않게).
            return copy.deepcopy(result) if result is not None else None
        except Exception as e:
            print(f"캐시 읽기 오류: {e}")
            return None

    def _revalidate_declaration(self, fp, filename, result):
        """구 버전 캐시의 신고서/신고필증 분류를 텍스트 레이어로 1회 재검증.

        AI 재호출 없이 doc_type 만 교정하고 cls_ver 를 각인해 다음부터는 건너뛴다.
        판정 불가(스캔본)면 기존 값을 그대로 두되 cls_ver 는 각인해 반복 검사를 막는다.
        """
        from .form_parser import classify_declaration_file
        verdict = classify_declaration_file(fp)
        if verdict:
            if result.get('doc_type') != verdict:
                print(f"[직독] 캐시 종류 교정: {result.get('doc_type')} → {verdict} ({filename})")
            result['doc_type'] = verdict
            result['doc_type_src'] = 'text_layer'
            # 신고필증 3종은 캐시 유효 판정 조건상 아래 두 키가 있어야 한다
            if verdict in ('수입신고필증', '수출신고필증', '반송신고필증'):
                result.setdefault('levy_type', 'Unknown')
                result.setdefault('business_no', 'Unknown')
        with cache_lock:
            try:
                cache = self._load_cache()
                entry = cache.get(filename)
                if entry is None:
                    return
                if verdict:
                    entry['result'] = copy.deepcopy(result)
                entry['cls_ver'] = DOC_CLASSIFIER_VER
                self._write_cache()
            except Exception as e:
                print(f"캐시 재검증 저장 오류: {e}")

    def _save_to_cache(self, fp, result):
        """결과를 캐시에 저장 (최적화: indent 제거, O(n) 정리)"""
        MAX_CACHE_SIZE = 500

        with cache_lock:
            try:
                cache = self._load_cache()

                filename = os.path.basename(fp)
                file_mtime = os.path.getmtime(fp)
                file_size = os.path.getsize(fp)
                file_hash = _compute_file_hash(fp)

                entry = {
                    'mtime': file_mtime,
                    'size': file_size,
                    'cached_at': time.time(),
                    # 호출자가 들고 있는 result와 메모리 캐시가 얽히지 않도록 사본 저장
                    'result': copy.deepcopy(result),
                }
                if file_hash is not None:
                    entry['hash'] = file_hash
                entry['cls_ver'] = DOC_CLASSIFIER_VER
                cache[filename] = entry

                if len(cache) > MAX_CACHE_SIZE:
                    # O(n) 방식으로 가장 오래된 항목 제거
                    to_remove = len(cache) - MAX_CACHE_SIZE
                    oldest_keys = sorted(cache, key=lambda k: cache[k].get('cached_at', 0))[:to_remove]
                    for k in oldest_keys:
                        del cache[k]

                self._write_cache()

            except Exception as e:
                print(f"캐시 저장 오류: {e}")

    def override_doc_type(self, old_path, new_path, new_doc_type,
                          company_name=None, identifier=None):
        """사용자 수동 교정: 캐시 키를 새 파일명으로 옮기고 결과의 문서 종류·회사명을
        덮어쓴다. AI 오분류를 UI에서 바로잡을 때 사용 — 재OCR 없이 교정값이 유지된다."""
        with cache_lock:
            try:
                cache = self._load_cache()
                old_name = os.path.basename(old_path)
                new_name = os.path.basename(new_path)
                entry = cache.pop(old_name, None)
                if entry is None:
                    entry = {'cached_at': time.time(), 'result': {}}
                res = entry.get('result') or {}
                res['doc_type'] = new_doc_type
                if company_name:
                    res['company_name'] = company_name
                if identifier:
                    res.setdefault('identifier', identifier)
                    res.setdefault('id_type', 'BL')
                # 수입신고필증으로 교정 시 levy_type 없으면 캐시가 무효 판정되므로 보장
                if new_doc_type in ('수입신고필증', '수출신고필증', '반송신고필증'):
                    res.setdefault('levy_type', 'Unknown')
                    res.setdefault('business_no', 'Unknown')
                # 수동 교정은 직독 재검증이 덮어쓰지 않도록 출처를 각인한다
                res['doc_type_src'] = 'manual'
                entry['result'] = res
                entry['cls_ver'] = DOC_CLASSIFIER_VER
                try:
                    entry['mtime'] = os.path.getmtime(new_path)
                    entry['size'] = os.path.getsize(new_path)
                    file_hash = _compute_file_hash(new_path)
                    if file_hash is not None:
                        entry['hash'] = file_hash
                except OSError:
                    pass
                cache[new_name] = entry
                self._write_cache()
                print(f"[캐시] 종류 교정: {old_name} -> {new_name} ({new_doc_type})")
            except Exception as e:
                print(f"캐시 종류 교정 오류: {e}")

    def _update_cache_key(self, old_path, new_path):
        """파일 이름 변경 시 캐시 키도 업데이트"""
        with cache_lock:
            try:
                cache = self._load_cache()

                old_name = os.path.basename(old_path)
                new_name = os.path.basename(new_path)

                if old_name in cache:
                    entry = cache.pop(old_name)
                    entry['mtime'] = os.path.getmtime(new_path)
                    cache[new_name] = entry

                    self._write_cache()
                    print(f"[캐시] 키 업데이트: {old_name} -> {new_name}")
            except Exception as e:
                print(f"캐시 키 업데이트 오류: {e}")

    def analyze_statement_for_merge(self, fp):
        """병합용 정산서 분석"""
        return self.analyze_pdf(fp)


# 싱글톤 인스턴스
gemini_ocr = GeminiOCR()


def extract_document_info_ai(fp):
    """AI 기반 문서 정보 추출"""
    return gemini_ocr.analyze_pdf(fp)
