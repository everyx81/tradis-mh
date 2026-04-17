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

from .config import get_client
from .utils import pdf_lock, cache_lock


class GeminiOCR:
    """Gemini AI 기반 PDF OCR 분석기"""
    
    def __init__(self):
        self.model_id = 'gemini-3.1-flash-lite-preview'
        self.base_prompt = """
당신은 최고의 전문 관세사 사무원입니다. PDF 문서의 이미지를 분석하여 다음 정보를 JSON 형식으로만 응답하세요.

[1단계: 분석 지침]
1. company_name (업체명 추출 규칙):
   - 수입신고필증, 수출신고필증, 수입신고서, 수출신고서: 수출업체 또는 수입업체 명
   - 자금정산서, 자금청구서: 실화주(화주) 명
   - 납부고지서: 납부자의 상호
   - 세금계산서, 계산서, 영수증, 입금표: 공급받는자(수신자)의 상호
   - 수입요건 서류: 수입자 상호
   - 적합성평가확인서 (방송통신기자재등의 적합성평가확인 신청서 등): 수입자(신청인) 상호
   - 공통: (주), 주식회사 등 법인명 접미사는 제외하고 본 이름만 추출하며, 모든 공백(띄어쓰기)은 반드시 제거하세요.
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

   [주의] 다음은 B/L 번호가 아닙니다. 절대 identifier로 추출하지 마세요:
     • 신고번호 (예: 13133-26-000199X, HSIV-26011513133-26-000199X) — '-'로 구분된 형태
     • 접수번호, 승인번호, 관리번호, 세관번호, 신고확인번호
     • 적하목록관리번호(MRN) — 세관 관리용
     • 사업자등록번호, 통관고유부호
     • 문서 상단이나 하단의 행정 관리용 번호

   [필독] 명확한 B/L 또는 Invoice 번호가 확인되지 않는 경우, 다른 번호를 무리하게 유추하지 말고 반드시 'Unknown'을 반환하세요. 잘못된 번호 추출보다 Unknown을 반환하는 것이 안전합니다.

3. id_type: 'BL' 또는 'Invoice'

4. doc_type (문서 종류 결정 - [매우 중요]):
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
      - 문서에 적힌 제목이 예시에 없더라도 임의로 바꾸지 말고 적힌 그대로 반환하세요. (시스템이 후처리로 표준화합니다)

   B. [내용 기반 심층 분석]
      - 제목이 '세금계산서', '전자세금계산서', '계산서', '청구서', '영수증', '입금표' 등 범용적인 명칭일 경우, **반드시 품목/비고/내용을 분석**하여 실질에 맞는 이름을 부여하세요.

      [카테고리 목록]
      1) **선박운임계산서** — Ocean Freight(O/F), BAF, CAF, LSS, THC, Wharfage, D/O Fee, CIC, EBS, Documentation Fee, Drayage(셔틀/부두이송), 부대비용, Handling Charge(포워더/선사/물류사 발행 시).
      2) **보세운송료계산서** — 보세운송료, 보세운송, Bonded Trucking.
      3) **운송료계산서** — 운송료, 배차료, 내륙운임, Trucking, 셔틀비, 상하차비, 컨테이너 운송.
      4) **창고료계산서** — 창고료, 보관료(Storage), 보험료(화재보험/적하보험 등), 하역료, CFS Charge, 입출고료.
      5) **통관수수료계산서** — 통관수수료, 관세사수수료, 검역수수료(식품/검역/동물), 요건대행료, 취급수수료(관세사 청구시).
         주의: '창고료'나 '운송료' 단어가 섞여 있어도 주된 청구자가 '관세법인'이거나 통관 관련 내역이 더 많으면 통관수수료계산서로 분류.
         주의: 'Handling Charge'만 있고 공급자가 포워더/선사/물류사인 경우 → 선박운임계산서(1번)로 분류. 통관수수료계산서는 반드시 관세법인/관세사무소가 발행한 경우에만 해당.
      6) **항공운임계산서** — Air Freight, FSC(유류할증료), SSC(보안할증료), AWB Fee, CCFE(착불수수료).
      7) 그 외: 위 카테고리에 해당하지 않는 순수한 물품 대금 거래인 경우 원래 제목 유지.

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

[3단계: 청구 항목 추출]
- 계산서/세금계산서/영수증/입금표인 경우:
  - billing_items: 문서 내 모든 청구 항목을 [{"name": "항목명", "amount": 금액}] 리스트로 반환
  - 품목란뿐만 아니라 비고란, 부기사항 등에 기재된 추가 비용 항목도 반드시 포함
  - 금액 0인 항목 제외, 항목이 1개여도 리스트로 반환
- 그 외 문서(신고필증, 납부고지서, 정산서 등)는 billing_items를 빈 리스트 [] 반환

응답은 오직 JSON 형식이어야 하며, 다른 텍스트는 포함하지 마세요.
"""

    def analyze_pdf(self, fp):
        """PDF 분석 (파일 캐싱 적용)"""
        client = get_client()
        if client is None:
            return {"company_name": "Unknown", "identifier": "Unknown", "id_type": "Unknown", "doc_type": "Unknown"}

        # --- 캐시 확인 ---
        cached_result = self._get_cached_result(fp)
        if cached_result:
            print(f"[캐시] 사용: {os.path.basename(fp)}")
            return cached_result

        try:
            from google.genai import types

            with open(fp, 'rb') as f:
                pdf_bytes = f.read()

            if not pdf_bytes:
                return {"company_name": "Unknown", "identifier": "Unknown", "id_type": "Unknown", "doc_type": "Unknown"}

            response = client.models.generate_content(
                model=f"models/{self.model_id}",
                contents=[
                    self.base_prompt,
                    types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
                ]
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

            # --- 결과 캐싱 저장 (모든 파일) ---
            self._save_to_cache(fp, result)

            return result
        except Exception as e:
            print(f"AI 분석 오류: {e}")
            return {"company_name": "Unknown", "identifier": "Unknown", "id_type": "Unknown", "doc_type": "Unknown"}

    def _get_cache_path(self, fp):
        """캐시 파일 경로 반환"""
        run_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if getattr(sys, 'frozen', False):
            run_dir = os.path.dirname(sys.executable)
            
        data_dir = os.path.join(run_dir, 'data')
        os.makedirs(data_dir, exist_ok=True)
        
        return os.path.join(data_dir, ".analysis_cache.json")

    def _get_cached_result(self, fp):
        """캐시에서 결과 조회"""
        try:
            cache_path = self._get_cache_path(fp)
            if not os.path.exists(cache_path):
                return None

            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)

            filename = os.path.basename(fp)
            if filename not in cache:
                return None

            entry = cache[filename]
            file_mtime = os.path.getmtime(fp)
            file_size = os.path.getsize(fp)

            # 수정시간이 변경됐으면 캐시 무효
            if file_mtime > entry.get('mtime', 0):
                return None
            # 파일 크기가 다르면 캐시 무효 (동명 파일 교체 감지)
            # 단, 기존 캐시(size 필드 없음)는 하위 호환을 위해 통과
            cached_size = entry.get('size')
            if cached_size is not None and file_size != cached_size:
                return None

            result = entry.get('result')
            # 기존 캐시에 정규화되지 않은 doc_type이 있으면 로드 시점에 정규화
            if result and 'doc_type' in result:
                from .utils import normalize_doc_type
                result['doc_type'] = normalize_doc_type(result['doc_type'])
            return result
        except Exception as e:
            print(f"캐시 읽기 오류: {e}")
            return None

    def _save_to_cache(self, fp, result):
        """결과를 캐시에 저장 (최적화: indent 제거, O(n) 정리)"""
        MAX_CACHE_SIZE = 500

        with cache_lock:
            try:
                cache_path = self._get_cache_path(fp)

                if os.path.exists(cache_path):
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        cache = json.load(f)
                else:
                    cache = {}

                filename = os.path.basename(fp)
                file_mtime = os.path.getmtime(fp)
                file_size = os.path.getsize(fp)

                cache[filename] = {
                    'mtime': file_mtime,
                    'size': file_size,
                    'cached_at': time.time(),
                    'result': result
                }

                if len(cache) > MAX_CACHE_SIZE:
                    # O(n) 방식으로 가장 오래된 항목 제거
                    to_remove = len(cache) - MAX_CACHE_SIZE
                    oldest_keys = sorted(cache, key=lambda k: cache[k].get('cached_at', 0))[:to_remove]
                    for k in oldest_keys:
                        del cache[k]

                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(cache, f, ensure_ascii=False, separators=(',', ':'))

            except Exception as e:
                print(f"캐시 저장 오류: {e}")

    def _update_cache_key(self, old_path, new_path):
        """파일 이름 변경 시 캐시 키도 업데이트"""
        with cache_lock:
            try:
                cache_path = self._get_cache_path(old_path)
                if not os.path.exists(cache_path):
                    return

                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache = json.load(f)

                old_name = os.path.basename(old_path)
                new_name = os.path.basename(new_path)

                if old_name in cache:
                    entry = cache.pop(old_name)
                    entry['mtime'] = os.path.getmtime(new_path)
                    cache[new_name] = entry

                    with open(cache_path, 'w', encoding='utf-8') as f:
                        json.dump(cache, f, ensure_ascii=False, indent=2)
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
