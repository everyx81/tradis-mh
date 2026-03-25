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
        self.model_id = 'gemini-3.1-flash-lite'
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

2. identifier (식별 번호) - [매우 중요]:
   - 문서 내에서 B/L 번호 또는 Invoice 번호를 반드시 찾아 추출하세요.
   - [주의] 13133으로 시작하는 번호는 '신고번호'이며, identifier가 절대 아닙니다!
     예시: 13133-26-000199X, HSIV-26011513133-26-000199X 등은 신고번호입니다.
   - B/L 번호는 보통 선사 코드로 시작합니다 (예: HDMU, COSU, MAEU, ONEY 등)
   - [필독] 명확한 B/L 또는 Invoice 번호가 확인되지 않는 경우, 승인번호나 관리번호 등을 무리하게 유추하지 말고 반드시 'Unknown'을 반환하세요. 잘못된 번호 추출보다 Unknown을 반환하는 것이 필수입니다.

3. id_type: 'BL' 또는 'Invoice'

4. doc_type (문서 종류 결정 - [매우 중요]):
   A. [절대 기준] 다음 제목이 명확히 보이면 그대로 사용하세요:
      - '수입신고필증', '수입신고서', '수출신고필증', '수출신고서', '자금정산서', '자금청구서', '납부고지서', '수입세금계산서', '적합성평가확인서'

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
   - 합계금액과 별도의 총금액이 함께 있으면, 가장 큰(최종) 금액을 사용
   - 공급가액만 추출 금지, 부가세 포함 금액 우선

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
            import pypdfium2 as pdfium
            from google.genai import types

            with open(fp, 'rb') as f:
                pdf_bytes = f.read()

            img_data = None
            with pdf_lock:
                pdf = pdfium.PdfDocument(pdf_bytes)
                try:
                    if len(pdf) > 0:
                        p = pdf[0]
                        bitmap = p.render(scale=1.5)
                        pil_image = bitmap.to_pil()
                        img_byte_arr = io.BytesIO()
                        try:
                            pil_image.save(img_byte_arr, format='JPEG', quality=70)
                            img_data = img_byte_arr.getvalue()
                        finally:
                            img_byte_arr.close()
                            pil_image.close()  # 메모리 즉시 해제 (~13MB/페이지)
                finally:
                    pdf.close()

            if not img_data:
                return {"company_name": "Unknown", "identifier": "Unknown", "id_type": "Unknown", "doc_type": "Unknown"}

            response = client.models.generate_content(
                model=f"models/{self.model_id}",
                contents=[
                    self.base_prompt,
                    types.Part.from_bytes(data=img_data, mime_type="image/jpeg")
                ]
            )
            text_response = response.text.strip()
            text_response = re.sub(r'```(?:json)?\n?(.*?)\n?```', r'\1', text_response, flags=re.DOTALL).strip()
            match = re.search(r'\{.*\}', text_response, re.DOTALL)
            if match:
                text_response = match.group(0)

            result = json.loads(text_response)

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

            if file_mtime > entry.get('mtime', 0):
                return None

            return entry.get('result')
        except Exception as e:
            print(f"캐시 읽기 오류: {e}")
            return None

    def _save_to_cache(self, fp, result):
        """결과를 캐시에 저장"""
        MAX_CACHE_SIZE = 200

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

                cache[filename] = {
                    'mtime': file_mtime,
                    'cached_at': time.time(),
                    'result': result
                }

                if len(cache) > MAX_CACHE_SIZE:
                    sorted_items = sorted(cache.items(), key=lambda x: x[1].get('cached_at', 0))
                    to_remove = len(cache) - MAX_CACHE_SIZE
                    for i in range(to_remove):
                        del cache[sorted_items[i][0]]

                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(cache, f, ensure_ascii=False, indent=2)

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
