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

import pypdfium2 as pdfium
from google.genai import types

from .config import client
from .utils import pdf_lock, cache_lock


class KnowledgeBase:
    """지식 베이스 (레거시 호환용)"""
    def __init__(self):
        if getattr(sys, 'frozen', False):
            bd = os.path.dirname(sys.executable)
        else:
            bd = os.path.dirname(os.path.dirname(__file__))
            
        data_dir = os.path.join(bd, 'data')
        os.makedirs(data_dir, exist_ok=True)
            
        self.path = os.path.join(data_dir, 'knowledge_base.json')
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                    if "analysis_cache" not in d:
                        d["analysis_cache"] = {}
                    if "examples" not in d:
                        d["examples"] = []
                    return d
            except:
                pass
        return {"analysis_cache": {}, "examples": []}

    def _save(self):
        from .utils import kb_lock
        with kb_lock:
            try:
                with open(self.path, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"지식 베이스 저장 오류: {e}")


knowledge_base = KnowledgeBase()


class GeminiOCR:
    """Gemini AI 기반 PDF OCR 분석기"""
    
    def __init__(self):
        self.model_id = 'gemini-3-flash-preview'
        self.base_prompt = """
당신은 최고의 전문 관세사 사무원입니다. PDF 문서의 이미지를 분석하여 다음 정보를 JSON 형식으로만 응답하세요.

[1단계: 분석 지침]
1. company_name (업체명 추출 규칙):
   - 수입신고필증, 수출신고필증, 수입신고서, 수출신고서: 수출업체 또는 수입업체 명
   - 자금정산서, 자금청구서: 실화주(화주) 명
   - 납부고지서: 납부자의 상호
   - 세금계산서, 계산서, 영수증, 입금표: 공급받는자(수신자)의 상호
   - 수입요건 서류: 수입자 상호
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
      - '수입신고필증', '수입신고서', '수출신고필증', '수출신고서', '자금정산서', '자금청구서', '납부고지서', '수입세금계산서'

   B. [내용 기반 심층 분석] 
      - 제목이 '세금계산서', '전자세금계산서', '계산서', '청구서', '영수증', '입금표' 등 범용적인 명칭일 경우, **반드시 품목/비고/내용을 분석**하여 실질에 맞는 이름을 부여하세요.
      
      [분류 규칙 - 심층 정밀 판정 로직]
      1) **해상운송계산서 (Sea Freight Invoice)**
         - 주된 청구 항목이 선박 운송 및 항만 부대비용인 경우.
         - 핵심 키워드: Ocean Freight(O/F), BAF, CAF, LSS, THC(Terminal Handling Charge), Wharfage(부두사용료), D/O Fee(화물인도지시서), CIC(컨테이너 수급 불균형 완화 차지), EBS, Documentation Fee, 부대비용.
      
      2) **운송료계산서 (Inland Transport Invoice)**
         - 주된 내용이 트럭을 이용한 내륙 화물 운임인 경우.
         - 핵심 키워드: 운송료, 배차료, 내륙운임, Trucking, Drayage(셔틀/부두이송), 셔틀비, 상하차비(운송 관련시), 컨테이너 운송.
      
      3) **창고료계산서 (Warehouse Fee Invoice)**
         - 주된 내용이 보세구역 또는 창고 보관 및 관련 작업비인 경우.
         - 핵심 키워드: 창고료, 보관료(Storage), 하역료(Handling/Stevedoring), CFS Charge, 입출고료, 작업료, Demurrage(체선료), Detention(지체료).
      
      4) **통관수수료계산서 (Customs Brokerage Invoice)**
         - 주된 내용이 관세사의 통관 대행 서비스 수수료인 경우.
         - 핵심 키워드: 통관수수료, 관세사수수료, 검역수수료(식품/검역/동물), 요건대행료, 취급수수료(관세사 청구시).
         - 주의: '창고료'나 '운송료' 단어가 섞여 있어도 주된 청구자가 '관세법인'이거나 통관 관련 내역이 더 많으면 무조건 통관수수료계산서로 분류.

      5) **항공운송계산서 (Air Freight Invoice)**
         - 핵심 키워드: Air Freight, FSC(유류할증료), SSC(보안할증료), AWB Fee, CCFE(착불수수료).
      
      6) 그 외: 위 규칙에 해당하지 않는 순수한 물품 대금 거래인 경우 원래 제목(세금계산서, 계산서 등)을 그대로 유지하세요.

5. doc_type_rationale:
   - 어떤 근거(키워드)로 위 doc_type을 선택했는지 설명하세요.

6. total_amount: 
   - 부가세를 포함한 최종 청구/결제 '합계 총금액' (단, 부가세가 없는 문서는 그 자체 금액, 공급가액만 추출 금지, 오직 숫자만 반환)

[2단계: 추가 정보 (자금정산서 전용)]
- 자금정산서인 경우에만 아래 필드를 추가로 포함하세요:
1. merge_info: 
   - expense_items: 명세서(Table)에 나열된 항목 중 금액이 0보다 큰 항목을 [{"name": "항목명", "amount": 100000}] 형태의 객체 리스트로 반환

응답은 오직 JSON 형식이어야 하며, 다른 텍스트는 포함하지 마세요.
"""

    def analyze_pdf(self, fp):
        """PDF 분석 (파일 캐싱 적용)"""
        if client is None:
            return {"company_name": "Unknown", "identifier": "Unknown", "id_type": "Unknown", "doc_type": "Unknown"}

        # --- 캐시 확인 ---
        cached_result = self._get_cached_result(fp)
        if cached_result:
            print(f"[캐시] 사용: {os.path.basename(fp)}")
            return cached_result

        try:
            # 파일을 메모리로 직접 로드
            with open(fp, 'rb') as f:
                pdf_bytes = f.read()

            img_data = None
            with pdf_lock:
                pdf = pdfium.PdfDocument(pdf_bytes)
                if len(pdf) > 0:
                    p = pdf[0]
                    bitmap = p.render(scale=1.5)
                    pil_image = bitmap.to_pil()
                    img_byte_arr = io.BytesIO()
                    pil_image.save(img_byte_arr, format='JPEG', quality=70)
                    img_data = img_byte_arr.getvalue()
                pdf.close()

            if not img_data:
                return {"company_name": "Unknown", "identifier": "Unknown", "id_type": "Unknown", "doc_type": "Unknown"}

            full_prompt = self.base_prompt

            response = client.models.generate_content(
                model=f"models/{self.model_id}",
                contents=[
                    full_prompt,
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
