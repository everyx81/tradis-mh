# JARVIS Core - 파일 프로세서
"""
파일 모니터링 및 자동 이름 변경 처리
"""

import os
import sys
import re
import time
import threading
import concurrent.futures
import shutil

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .constants import (
    DOC_TYPE_IMPORT_DECLARATION, DOC_TYPE_EXPORT_DECLARATION,
    DOC_TYPE_PAYMENT_NOTICE, DOC_TYPE_IMPORT_TAX_INVOICE,
    FEE_INVOICE_ITEMS, EXPENSE_SYNONYMS, REQUIREMENT_DOC_KEYWORDS,
    INDEPENDENT_DOC_TYPES, FIXED_SLOT_KEYS
)
from .utils import (
    sanitize_filename, get_unique_filename, cleanup_company_name,
    parse_renamed_filename, RE_ID_PAREN, normalize_id, is_similar_id,
    is_prefix_match_id
)
from .ocr import gemini_ocr, extract_document_info_ai


class AutoRenamer:
    """자동 파일 이름 변경기"""
    
    def __init__(self, log_callback=None, merge_request_callback=None, rename_complete_callback=None):
        self.observer = None
        self.log_callback = log_callback
        self.merge_request_callback = merge_request_callback
        self.rename_complete_callback = rename_complete_callback
        self.executor = None
        self.processing_files = set()


    def log(self, msg):
        if self.log_callback:
            self.log_callback(msg)
        else:
            print(msg)

    def start(self, path):
        self.stop()

        if self.executor is None:
            workers = min(4, (os.cpu_count() or 2) + 1)
            self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)

        eh = PDFHandler(self)
        self.observer = Observer()
        self.observer.schedule(eh, path, recursive=False)
        self.observer.start()

        time.sleep(0.3)
        try:
            pdf_files = [os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith('.pdf')]
            for f in pdf_files:
                if self.executor:
                    self.executor.submit(self.process_pdf, f, True)
        except Exception as e:
            self.log(f"초기 스캔 오류: {e}")

    def stop(self):
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=5)
                if self.observer.is_alive():
                    print("[경고] Observer 스레드가 시간 내에 종료되지 않았습니다")
            except Exception as e:
                print(f"[경고] Observer 종료 오류: {e}")
            finally:
                self.observer = None

        if self.executor:
            try:
                if sys.version_info >= (3, 9):
                    self.executor.shutdown(wait=False, cancel_futures=True)
                else:
                    self.executor.shutdown(wait=False)
            except Exception as e:
                print(f"[경고] Executor 종료 오류: {e}")
            finally:
                self.executor = None

        self.processing_files.clear()

    def _wait_for_file_ready(self, fp, timeout=30):
        """파일 쓰기가 완료될 때까지 대기. 완료되면 True, 빈 파일이면 False."""
        elapsed = 0
        prev_size = -1
        stable_count = 0

        while elapsed < timeout:
            if not os.path.exists(fp):
                return False
            try:
                size = os.path.getsize(fp)
            except OSError:
                return False

            if size > 0 and size == prev_size:
                stable_count += 1
                if stable_count >= 2:
                    return True  # 2회 연속 동일 → 쓰기 완료 확정
            else:
                stable_count = 0

            prev_size = size
            # 초반 빠른 체크, 이후 간격 늘림
            interval = 0.2 if elapsed < 2 else 0.5
            time.sleep(interval)
            elapsed += interval

        try:
            return os.path.getsize(fp) > 0
        except OSError:
            return False

    def process_pdf(self, fp, is_initial=False):
        if not os.path.exists(fp):
            return
            
        fn = os.path.basename(fp)
        
        # [NEW] Skip files starting with '10.' or '미분류_'
        if fn.startswith("10.") or fn.startswith("미분류_"):
            return

        # [NEW] 파일명에 제외 키워드가 포함되면 자동 이름 변경 건너뜀
        # 사용자가 설정 탭에서 추가/삭제 가능 (core.config.rename_skip_keywords)
        try:
            from core.config import get_rename_skip_keywords
            kws = get_rename_skip_keywords()
            matched_kw = next((kw for kw in kws if kw and kw in fn), None)
            if matched_kw:
                self.log(f" -> [제외 키워드 '{matched_kw}'] 자동 이름 변경 건너뜀: {fn}")
                return
        except Exception:
            pass

        if fp in self.processing_files:
            return
        self.processing_files.add(fp)

        try:
            if not is_initial:
                # 파일 쓰기 완료 대기 (다운로드/복사 중인 파일 보호)
                if not self._wait_for_file_ready(fp, timeout=30):
                    self.log(f" -> [건너뜀] 파일이 비어있거나 쓰기 미완료: {fn}")
                    return
            else:
                time.sleep(0.1)
                # 초기 스캔에서도 0KB 파일은 건너뜀
                if os.path.getsize(fp) == 0:
                    return

            # 최소 파일 크기 체크 (2KB 미만은 불완전한 PDF로 간주)
            # 이체증 같이 작은 PDF (5~30KB)도 처리되도록 임계값 완화
            try:
                if os.path.getsize(fp) < 2048:
                    self.log(f" -> [건너뜀] 파일 크기 부족 ({os.path.getsize(fp)} bytes): {fn}")
                    return
            except OSError:
                return

            c, i, d, s = parse_renamed_filename(fn)
            if i:
                # BL 이 이미 파일명에 있음 — 이름 변경 불필요
                # 하지만 OCR 캐시가 없으면 billing_items 기반 매칭이 작동 안 하므로
                # 캐시만 채우고 종료 (rename X, OCR O)
                _res = None
                try:
                    _res = gemini_ocr._get_cached_result(fp)
                    if _res is None:
                        self.log(f"[재분석] BL 있지만 캐시 없음 - OCR 실행: {fn}")
                        _res = extract_document_info_ai(fp)  # _save_to_cache 자동 호출
                except Exception as e:
                    self.log(f"[재분석 실패] {fn}: {e}")

                # 보완 레이어가 신고필증 오분류를 교정한 건에 한해 파일명도 맞춘다.
                # BL 이 이름에 있다는 이유로 리네임을 건너뛰던 탓에 과거 오분류로
                # 굳어진 이름(신고서인데 …수입신고필증.pdf)이 영구히 남던 문제를 푼다.
                if _res and _res.get('doc_type_src') == 'text_layer_fix':
                    self._fix_doctype_in_filename(fp, fn, d, _res.get('doc_type'))
                # 캐시 유무와 무관하게 UI 갱신 — 외부(탐색기 등)에서 리네임된 파일도
                # 카드 스냅샷에 반영되도록 함. 콜백은 1초 디바운스라 부담 없음.
                if self.rename_complete_callback and not is_initial:
                    self.rename_complete_callback()
                return

            self.log(f"\n[AI 분석 대기/시작] {fn}")
            res = extract_document_info_ai(fp)

            # [NEW] 분석(캐싱)이 완료되었음을 UI에 알림 (디바운싱 됨)
            # 이름 변경 여부와 무관하게 금액 매칭용 데이터가 캐싱되었으므로 UI 갱신 필요
            if self.rename_complete_callback:
                self.rename_complete_callback()

            dt = res.get("doc_type", "Unknown")
            cn = res.get("company_name", "Unknown")
            iden = res.get("identifier", "Unknown")

            # doc_type 표준 정규화 (이중 안전망)
            from core.utils import normalize_doc_type
            dt = normalize_doc_type(dt)

            # OCR 전체 실패 시 1회 재시도 (다운로드 미완료 파일 대응)
            if dt == "Unknown" and cn == "Unknown" and iden == "Unknown":
                self.log(f" -> [OCR 재시도] 전체 Unknown - 5초 후 재분석: {fn}")
                time.sleep(5)
                # 캐시 무효화 후 재분석
                cache_path = gemini_ocr._get_cache_path(fp)
                if os.path.exists(cache_path):
                    try:
                        import json as _json
                        with open(cache_path, 'r', encoding='utf-8') as _cf:
                            _cache = _json.load(_cf)
                        _keys = [k for k in _cache if os.path.basename(fp) in k]
                        for _k in _keys:
                            del _cache[_k]
                        with open(cache_path, 'w', encoding='utf-8') as _cf:
                            _json.dump(_cache, _cf, ensure_ascii=False)
                    except Exception:
                        pass
                res = extract_document_info_ai(fp)
                dt = res.get("doc_type", "Unknown")
                cn = res.get("company_name", "Unknown")
                iden = res.get("identifier", "Unknown")
                if dt != "Unknown" or cn != "Unknown":
                    self.log(f" -> [OCR 재시도 성공] {dt} / {cn} / {iden}")

            # [NEW] BL 만 Unknown 인 경우 1회 재시도 (AI 비결정성 대응)
            # 자금청구서/정산서 등 일부 문서에서 BL 필드 인식이 간헐적으로 실패 → 재OCR 시 성공하는 케이스
            elif iden == "Unknown" and dt != "Unknown" and cn != "Unknown":
                self.log(f" -> [OCR 재시도] BL 만 Unknown - 재분석: {fn}")
                time.sleep(2)
                cache_path = gemini_ocr._get_cache_path(fp)
                if os.path.exists(cache_path):
                    try:
                        import json as _json
                        with open(cache_path, 'r', encoding='utf-8') as _cf:
                            _cache = _json.load(_cf)
                        _keys = [k for k in _cache if os.path.basename(fp) in k]
                        for _k in _keys:
                            del _cache[_k]
                        with open(cache_path, 'w', encoding='utf-8') as _cf:
                            _json.dump(_cache, _cf, ensure_ascii=False)
                    except Exception:
                        pass
                res2 = extract_document_info_ai(fp)
                new_iden = res2.get("identifier", "Unknown")
                if new_iden != "Unknown":
                    iden = new_iden
                    # doctype/company 도 새 결과로 업데이트 (일관성 유지)
                    new_dt = res2.get("doc_type", "Unknown")
                    new_cn = res2.get("company_name", "Unknown")
                    if new_dt != "Unknown":
                        dt = new_dt
                    if new_cn != "Unknown":
                        cn = new_cn
                    self.log(f" -> [OCR 재시도 성공] BL 확보: {new_iden}")

            # 수입자명이 전체 영문인지 판단 (한글이 포함되지 않음)
            # cn이 "Unknown"이면 무시하고 판별
            import re
            is_english_only = False
            if cn != "Unknown":
                if not re.search(r'[가-힣]', cn):
                    is_english_only = True

            # 독립 문서 (이체증 등) 전용 이름 패턴
            from core.constants import INDEPENDENT_DOC_TYPES
            if dt in INDEPENDENT_DOC_TYPES:
                amt = res.get("total_amount", 0)
                try:
                    amt_val = int(str(amt).replace(',', '').replace('원', ''))
                except ValueError:
                    amt_val = 0
                cn = sanitize_filename(cn).replace(" ", "")
                nn = f"{dt}_{cn}_{amt_val}.pdf" if amt_val else f"{dt}_{cn}.pdf"
                dir_name = os.path.dirname(fp)
                np = os.path.join(dir_name, nn)
                if fn != nn:
                    if os.path.exists(np):
                        np = get_unique_filename(np)
                        nn = os.path.basename(np)
                    try:
                        os.rename(fp, np)
                        self.log(f" -> [성공] {nn}")
                        gemini_ocr._update_cache_key(fp, np)
                        if self.rename_complete_callback:
                            self.rename_complete_callback()
                    except Exception as e:
                        self.log(f" -> [실패] 이름 변경 오류: {e}")
                return

            if dt == "Unknown" or iden == "Unknown" or is_english_only:
                amt = res.get("total_amount", 0)
                try:
                    amt_val = int(str(amt).replace(',', '').replace('원', ''))
                except ValueError:
                    amt_val = 0
                
                # 서류명과 수입자(상호) 처리
                doc_name = dt if dt != "Unknown" else "알수없는서류"
                comp_name = sanitize_filename(res.get("company_name", "알수없는상호")).replace(" ", "")
                if comp_name == "Unknown":
                    comp_name = "알수없는상호"
                
                base_name = f"미분류_{doc_name}_{comp_name}"

                # 품목명이 있으면 금액 대신 품목명 사용 (요건 증빙서류)
                product_name = res.get("product_name", "")
                if product_name:
                    product_clean = sanitize_filename(product_name).replace(" ", "")
                    if len(product_clean) > 20:
                        product_clean = product_clean[:20]

                if amt_val > 0:
                    nn = f"{base_name}_{amt_val}.pdf"
                elif product_name:
                    nn = f"{base_name}_{product_clean}.pdf"
                else:
                    nn = f"{base_name}_확인필요.pdf"
                
                # 이미 동일한 이름이면 건너뜀 (금액 변동 등 다른 미분류 이름인 경우 변경)
                if fn == nn:
                    return
                
                dir_name = os.path.dirname(fp)
                np = os.path.join(dir_name, nn)
                
                if os.path.exists(np):
                    np = get_unique_filename(np)
                    nn = os.path.basename(np)
                
                try:
                    os.rename(fp, np)
                    self.log(f" -> [미분류 처리] {nn}")
                    gemini_ocr._update_cache_key(fp, np)
                    if self.rename_complete_callback:
                        self.rename_complete_callback()
                except Exception as e:
                    self.log(f" -> [실패] 미분류 이름 변경 오류: {e}")
                
                return

            cn = sanitize_filename(cn).replace(" ", "")
            iden = sanitize_filename(iden).replace(" ", "").upper()

            from core.config import get_custom_naming
            _naming = get_custom_naming()
            try:
                nn = _naming["file_pattern"].format(company=cn, bl=iden, doctype=dt, amount="")
            except (KeyError, ValueError):
                nn = f"{cn}({iden}){dt}.pdf"
            dir_name = os.path.dirname(fp)
            np = os.path.join(dir_name, nn)

            if fn != nn:
                if os.path.exists(np):
                    np = get_unique_filename(np)
                    nn = os.path.basename(np)
                try:
                    os.rename(fp, np)
                    self.log(f" -> [성공] {nn}")
                    gemini_ocr._update_cache_key(fp, np)
                    # 이미 위에서 UI 갱신 시그널을 보냈지만, 파일명이 바뀌었으므로 한번 더 안전하게 보냄
                    if self.rename_complete_callback:
                        self.rename_complete_callback()
                except Exception as e:
                    self.log(f" -> [실패] 이름 변경 오류: {e}")
        finally:
            if fp in self.processing_files:
                self.processing_files.remove(fp)

    def _fix_doctype_in_filename(self, fp, fn, old_dt, new_dt):
        """파일명에 박힌 서류 종류를 확정 값으로 교정.

        직독으로 확정된 doc_type 에 대해서만 호출한다. 파일명 패턴(커스텀 포함)을
        건드리지 않도록, 종류 토큰 자리만 문자열 치환한다.
        """
        if not new_dt or not old_dt or new_dt == old_dt or old_dt not in fn:
            return
        pos = fn.rfind(old_dt)
        nn = fn[:pos] + new_dt + fn[pos + len(old_dt):]
        np = os.path.join(os.path.dirname(fp), nn)
        if os.path.exists(np):
            np = get_unique_filename(np)
            nn = os.path.basename(np)
        try:
            os.rename(fp, np)
            gemini_ocr._update_cache_key(fp, np)
            self.log(f" -> [종류 교정] {fn} → {nn}")
        except Exception as e:
            self.log(f" -> [실패] 종류 교정 이름 변경 오류: {e}")

    def trigger_intelligent_merge(self, dr):
        files = [f for f in os.listdir(dr) if f.lower().endswith('.pdf')]
        groups = {}
        uncl = []
        independent_groups = {}  # 독립 문서 그룹 {doc_type: [파일 목록]}
        # 카드 그룹에 포함하지 않는 문서 유형
        _EXCLUDE_DOC_TYPES = {"수입신고서", "자금청구서"}

        import re as _re
        import json as _json
        from core.validator import parse_amount as _parse_amount, build_search_kws as _build_search_kws
        from .constants import ANCHOR_DOC_TYPES, REQUIREMENT_FEE_SPECIFIC, REQUIREMENT_FEE_GENERIC
        from .form_parser import extract_declaration_no as _extract_decl_no
        _GENERIC_COMPANIES = {"Unknown", "알수없는상호", "알수없는", "미상", ""}
        _FIXED_SLOT = {"수입세금계산서", "납부고지서", "자금정산서", "정산서",
                        "수입신고필증", "수출신고필증", "반송신고필증"}
        _SETTLEMENT_KEYS = ("자금정산서", "정산서")

        # ── OCR 캐시 1회 로드 (파일×그룹 조합마다 디스크 JSON 재파싱 방지) ──
        _cache_map = None

        def _cache_lookup(fn):
            nonlocal _cache_map
            if _cache_map is None:
                try:
                    with open(gemini_ocr._get_cache_path(dr), 'r', encoding='utf-8') as _cf:
                        _cache_map = _json.load(_cf)
                except Exception:
                    _cache_map = {}
            entry = _cache_map.get(fn)
            if isinstance(entry, dict):
                res = entry.get('result')
                if isinstance(res, dict):
                    return res
            return None

        # ── 별칭 사전 + 사용자 결정 1회 로드 ──
        try:
            from core import match_memory as _mm
            _aliases = _mm.get_aliases()
            _decisions = _mm.get_decisions()
        except Exception:
            _mm = None
            _aliases = {}
            _decisions = {}

        def _alias_canon(name):
            """별칭 표기 → 한글 상호. 1:N 별칭은 판별력 없음 → None."""
            entry = _aliases.get(name)
            if isinstance(entry, dict) and len(entry) == 1:
                return next(iter(entry))
            return None

        def _accepted_bl(f):
            pref = f + '|'
            for k, a in _decisions.items():
                if a == 'accept' and k.startswith(pref):
                    return k.split('|', 1)[1]
            return None

        def _is_rejected(f, bl):
            return _decisions.get(f + '|' + bl) == 'reject'

        # ── 사업자등록번호 신호 ──
        def _norm_biz(no):
            digits = _re.sub(r'\D', '', str(no or ''))
            return digits if len(digits) == 10 else ""

        _group_biz_memo = {}

        def _card_business_no(bl_id, bl_data):
            """카드의 신원 번호 = 신고필증의 납세의무자 사업자번호."""
            if bl_id not in _group_biz_memo:
                no = ""
                for dk, fn in bl_data.get('docs', {}).items():
                    if "신고필증" in dk:
                        res = _cache_lookup(fn)
                        if res:
                            no = _norm_biz(res.get('business_no', ''))
                            if no:
                                break
                _group_biz_memo[bl_id] = no
            return _group_biz_memo[bl_id]

        def _file_business_no(fn):
            """파일의 신원 번호 = 공급받는자 사업자번호.
            공급자 번호와 동일하면 오추출로 보고 무시."""
            res = _cache_lookup(fn)
            if not res:
                return ""
            b = _norm_biz(res.get('buyer_business_no', ''))
            s_no = _norm_biz(res.get('supplier_business_no', ''))
            if b and b == s_no:
                return ""
            return b

        # ═══════════════════════════════════════════════
        # ID 신뢰 모델:
        # 괄호 안 ID는 문서 종류에 따라 신뢰도가 다르다.
        #  - 앵커 문서 (신고필증·정산서·납부고지서·세금계산서 등): BL이 공식 기재됨
        #    → 이 문서들의 ID만 그룹(카드) 생성 근거로 신뢰
        #  - 비용 계산서류: 검사기관 접수번호·주문번호 등 BL이 아닌 번호가
        #    ID 자리에 들어올 수 있음 (OCR 오추출)
        #    → 앵커 그룹과 ID 일치 시에만 편입, 불일치 시 회사명+금액 매칭으로 재배정
        # ═══════════════════════════════════════════════

        def _is_anchor_doc(d):
            return bool(d) and (d in ANCHOR_DOC_TYPES or "신고필증" in d)

        parsed_with_id = []
        for f in files:
            # 독립 문서 (이체증 등) → 파일명 앞부분으로 판별
            _indie_matched = False
            for _indie_type in INDEPENDENT_DOC_TYPES:
                if f.startswith(_indie_type + "_") or f.startswith(_indie_type + "("):
                    if _indie_type not in independent_groups:
                        independent_groups[_indie_type] = []
                    independent_groups[_indie_type].append(f)
                    _indie_matched = True
                    break
            if _indie_matched:
                continue

            c, i, d, s = parse_renamed_filename(f)

            if i:
                # 카드 제외 대상 문서는 미분류로 처리
                if d and d in _EXCLUDE_DOC_TYPES:
                    uncl.append(f)
                    continue
                parsed_with_id.append((f, c, i, d, s))
            else:
                uncl.append(f)

        def _norm_id(x):
            """ID 비교용 정규화 — 영숫자만 남기고 대문자화 (하이픈/공백 표기차 흡수)."""
            return _re.sub(r'[^0-9A-Z]', '', str(x or '').upper())

        def _find_group_key(i):
            """기존 그룹 중 ID가 일치(유사/prefix/보조ID)하는 그룹 키 반환. 없으면 None."""
            # 1차: 기존 유사도 매칭 (suffix 일치 필수)
            fk = next((k for k in groups if is_similar_id(k, i)), None)
            # 2차: prefix 포함 매칭 (정확 매칭 실패 시, 후보가 1개일 때만)
            if fk is None:
                prefix_candidates = [k for k in groups if is_prefix_match_id(k, i)]
                fk = prefix_candidates[0] if len(prefix_candidates) == 1 else None
            # 3차: 신고필증 신고번호(보조 ID) 일치 — 통관수수료계산서 등이
            #      BL 대신 신고번호를 괄호 ID 로 달고 온 경우 (후보가 1개일 때만)
            if fk is None:
                ni = _norm_id(i)
                if ni:
                    aux_candidates = [k for k, v in groups.items()
                                      if ni in v.get('aux_ids', set())]
                    fk = aux_candidates[0] if len(aux_candidates) == 1 else None
            return fk

        def _add_to_group(fk, f, c, d, s, trusted_company=True):
            # 회사명 신뢰 원칙: 매칭 기준(company_set)은 앵커 문서의 회사명만.
            # 비용 계산서의 회사명은 정산업체·지불대행사일 수 있으므로
            # 표시용(display_company_set)으로만 수집한다.
            if fk not in groups:
                groups[fk] = {'company_set': set(), 'display_company_set': set(), 'docs': {}}
            if c and c != 'Unknown':
                _ckey = 'company_set' if trusted_company else 'display_company_set'
                groups[fk][_ckey].add(cleanup_company_name(c))
            # 같은 문서 유형이 이미 있으면 suffix를 포함한 고유 키 사용
            doc_key = d
            if d in groups[fk]['docs']:
                # 고정 슬롯 중복 시 회사명이 placeholder(Unknown 등)인 파일이
                # 메인 슬롯을 차지하지 않도록 정상 회사명 파일을 우선 배치
                # (오분류된 파일이 필증 슬롯을 가로채 징수형태/세액 판정을
                #  오염시키는 것 방지)
                if d in _FIXED_SLOT:
                    occupant = groups[fk]['docs'][d]
                    occ_c = parse_renamed_filename(occupant)[0]
                    if (occ_c or "") in _GENERIC_COMPANIES and (c or "") not in _GENERIC_COMPANIES:
                        counter = 1
                        alt_key = f"{d}({counter})"
                        while alt_key in groups[fk]['docs']:
                            counter += 1
                            alt_key = f"{d}({counter})"
                        groups[fk]['docs'][alt_key] = occupant
                        groups[fk]['docs'][d] = f
                        return
                # suffix가 있으면 포함 (예: "운송료(1)"), 없으면 카운터 추가
                if s:
                    doc_key = f"{d}{s}"
                else:
                    counter = 1
                    while doc_key in groups[fk]['docs']:
                        doc_key = f"{d}({counter})"
                        counter += 1
            groups[fk]['docs'][doc_key] = f

        # ── 1차: 앵커 문서로 그룹 생성 ──
        pending_costs = []
        for f, c, i, d, s in parsed_with_id:
            if not _is_anchor_doc(d):
                pending_costs.append((f, c, i, d, s))
                continue
            fk = _find_group_key(i)
            if fk is None:
                fk = i
            # 신고필증의 B/L이 가장 정확하므로 그룹 키를 교체
            if fk != i and "신고필증" in (d or "") and fk in groups:
                groups[i] = groups.pop(fk)
                fk = i
            _add_to_group(fk, f, c, d, s)
            # 신고필증의 신고번호를 그룹 보조 ID 로 등록 —
            # 비용 계산서가 BL 대신 신고번호를 괄호 ID 로 달고 와도 편입되도록
            if "신고필증" in (d or ""):
                decl_no = _extract_decl_no(os.path.join(dr, f))
                if decl_no:
                    groups[fk].setdefault('aux_ids', set()).add(_norm_id(decl_no))

        # ── 2차: 비용 계산서류 — 앵커 그룹과 ID 일치 시에만 편입 ──
        # BL 일치가 회사명보다 우선: 회사명이 정산업체·영문이어도 BL 이 맞으면 편입
        unanchored_costs = []
        for f, c, i, d, s in pending_costs:
            fk = _find_group_key(i)
            if fk is not None:
                _add_to_group(fk, f, c, d, s, trusted_company=False)
            else:
                unanchored_costs.append((f, c, i, d, s))

        # ═══════════════════════════════════════════════
        # 회사명 + 정산서 데이터 기반 그룹 매칭 (공용 매처)
        # 대상: 미분류_{doctype}_{company}_{amount}.pdf 파일,
        #       앵커 미일치 ID를 가진 비용 계산서
        #
        # 분류 전략 (v1.1.8):
        #  - 고정 슬롯 (FIXED_SLOT): 1 BL 당 1개씩만 있는 문서
        #    → 회사명 매칭만으로 충분 (신고필증/정산서/수입세금계산서/납부고지서)
        #  - 비용 계산서 (COST_DOCTYPES): 창고료/운송료/항공운임/보험료 등
        #    → 회사명 + 금액이 정산서의 billing_items 에 포함되어야 매칭
        #      (같은 회사가 여러 BL 있을 때 엉뚱한 BL 로 가는 것 방지)
        #  - 정규화 비대칭 수정: 파일 측에도 cleanup_company_name 적용
        #  - company_set 전체 순회 ([:2] 축약본 대신)
        #  - placeholder (Unknown/알수없는상호) 는 매칭 제외
        # ═══════════════════════════════════════════════
        _uncl_moved = []

        def _find_settlement_cached(bl_data):
            """BL 의 정산서 OCR 캐시 + items 리스트 반환. 없으면 (None, None, [])."""
            for sk in _SETTLEMENT_KEYS:
                if sk in bl_data.get('docs', {}):
                    settlement_fn = bl_data['docs'][sk]
                    cached = _cache_lookup(settlement_fn)
                    # 정산서는 비용 항목을 merge_info.expense_items 에 저장 (billing_items 가 아님).
                    # 하위호환 위해 billing_items 도 fallback 으로 확인.
                    items = []
                    if cached:
                        ei = cached.get('merge_info', {}).get('expense_items', [])
                        bi = cached.get('billing_items', [])
                        items = ei if ei else bi
                    return settlement_fn, cached, items
            return None, None, []

        def _is_requirement_doc(doctype):
            """요건 증빙서류 여부 (식물검역/식품검역/동물검역/적합성평가/CITES)."""
            return any(kw in doctype for kw in REQUIREMENT_DOC_KEYWORDS)

        def _company_match(bl_data, file_company):
            # 별칭 사전 조회: 학습된 영문 표기 등을 한글 상호로 확장해 비교
            names = {file_company}
            canon = _alias_canon(file_company)
            if canon:
                cc = cleanup_company_name(canon)
                if cc:
                    names.add(cc)
            for bc in bl_data.get('company_set', set()):
                bc_clean = cleanup_company_name(bc)
                if not bc_clean or bc_clean in _GENERIC_COMPANIES:
                    continue
                for nm in names:
                    if nm in bc_clean or bc_clean in nm:
                        return True
            return False

        def _tier_match_group(file_doctype, file_company, file_amount, file_biz_no=""):
            """회사명·사업자번호 + 정산서 데이터로 파일이 속할 그룹 탐색. (chosen_bl, tier) 반환.

            신원 신호: 회사명(별칭 포함) 일치 OR 사업자번호 일치 → comp_ok
            Tier1: 엄격 (신원+데이터 검증 통과)
            Tier2: 차선 (신원만 OK 인데 정산서 데이터 부족)
            Tier3: 금액-only (신원은 안 맞지만 금액+항목이 유일하게 매칭)
                   단, 양쪽 사업자번호가 확인되고 서로 다르면 후보 제외 (타사 차단)
            각 tier 에서 후보가 정확히 1개일 때만 채택. 실패 시 (None, None).
            """
            is_fixed = file_doctype in _FIXED_SLOT
            is_req = _is_requirement_doc(file_doctype)

            tier1 = []  # strict
            tier2 = []  # loose (settlement data missing)
            tier3 = []  # amount-only fallback (company inconsistent)

            for bl_id, bl_data in groups.items():
                # [Plan B] 슬롯 이미 채워짐 체크 제거 —
                # AI 가 doctype 을 잘못 분류한 경우에도 회사+금액 유일성으로 매칭 시도 가능.
                # 매칭 확정 시 counter 키 (예: 통관수수료계산서(1)) 로 저장.
                card_biz = _card_business_no(bl_id, bl_data)
                biz_ok = bool(file_biz_no) and file_biz_no == card_biz
                biz_conflict = bool(file_biz_no) and bool(card_biz) and file_biz_no != card_biz
                comp_ok = biz_ok or _company_match(bl_data, file_company)

                # FIXED: 회사명만
                if is_fixed:
                    if comp_ok:
                        tier1.append(bl_id)
                    continue

                # REQ: 회사명 + 정산서 items 에 doctype 키워드 존재
                if is_req:
                    if not comp_ok:
                        continue
                    settlement_fn, cached, items = _find_settlement_cached(bl_data)
                    if not cached:
                        tier2.append(bl_id)
                        continue
                    if not items:
                        tier2.append(bl_id)
                        continue
                    # doctype 에 포함된 요건 키워드가 정산서 항목명에 존재?
                    # generic "요건수수료/요건대행" 으로 묶여 청구된 건은 서류 종류가
                    # 항목명에 안 드러나므로, 요건 계열 수수료가 하나라도 있으면 인정
                    req_kws_in_doc = [k for k in REQUIREMENT_DOC_KEYWORDS if k in file_doctype]
                    req_fee_kws = list(REQUIREMENT_FEE_SPECIFIC.keys()) + list(REQUIREMENT_FEE_GENERIC)
                    found_kw = False
                    for bi in items:
                        bi_name = bi.get('name', '').replace(' ', '')
                        if any(k in bi_name for k in req_kws_in_doc) \
                                or any(k in bi_name for k in req_fee_kws):
                            found_kw = True
                            break
                    if found_kw:
                        tier1.append(bl_id)
                    continue

                # COST: 회사명 + 대응 항목 금액 일치
                settlement_fn, cached, items = _find_settlement_cached(bl_data)
                if not cached:
                    if comp_ok:
                        tier2.append(bl_id)
                    continue
                search_kws = _build_search_kws(file_doctype)

                # 해당 doctype 항목들의 금액
                matching_amts = []
                for bi in items:
                    bi_name = bi.get('name', '').upper().replace(' ', '')
                    if not bi_name:
                        continue
                    if any(kw and (kw in bi_name or bi_name in kw) for kw in search_kws):
                        matching_amts.append(_parse_amount(bi.get('amount', 0)))

                if not items:
                    # 정산서 항목이 비어있음 (OCR 데이터 이슈) — 회사 일치하면 tier2
                    if comp_ok:
                        tier2.append(bl_id)
                    continue

                if comp_ok and file_amount > 0 and file_amount in matching_amts:
                    tier1.append(bl_id)
                    continue

                # 회사 OK + doctype 이름 매칭 안 됨 + 금액이 정산서 항목 중 정확히 1개와 일치
                # → generic doctype (전자세금계산서/세금계산서/계산서) 케이스 보완
                #   AI 가 카테고리에 없는 영수증을 그대로 "전자세금계산서" 로 반환할 때,
                #   회사 일치 + 금액 유일성으로 안전하게 매칭
                if comp_ok and file_amount > 0:
                    all_amts = [_parse_amount(bi.get('amount', 0)) for bi in items]
                    if all_amts.count(file_amount) == 1:
                        tier1.append(bl_id)
                        continue

                # 신원 불일치지만 금액이 일치하면 tier3
                # 단, 사업자번호가 양쪽 확인되고 서로 다르면 다른 회사 건 → 제외
                if not comp_ok and not biz_conflict and file_amount > 0 and file_amount in matching_amts:
                    tier3.append(bl_id)
                    continue

                # 회사는 맞지만 금액이 안 맞음 → 매칭 안 함 (tier 에 포함 X)

            # Tier 선택: 1 > 2 > 3, 각 tier 에서 정확히 1개일 때만
            if len(tier1) == 1:
                return tier1[0], "tier1"
            if len(tier1) == 0 and len(tier2) == 1:
                return tier2[0], "tier2"
            if len(tier1) == 0 and len(tier2) == 0 and len(tier3) == 1:
                return tier3[0], "tier3"
            return None, None

        def _assign_with_counter(chosen, file_doctype, f):
            # [Plan B] 슬롯 이미 채워졌으면 counter 키로 저장
            #   예: 첫 파일 → "통관수수료계산서", 둘째 → "통관수수료계산서(1)"
            docs = groups[chosen].setdefault('docs', {})
            doc_key = file_doctype
            counter = 1
            while doc_key in docs:
                doc_key = f"{file_doctype}({counter})"
                counter += 1
            docs[doc_key] = f
            return doc_key

        # ── 3차: 앵커 미일치 ID 비용 계산서 재배정 ──
        # 검사기관 접수번호 등 미검증 ID가 파일명에 박힌 경우,
        # ID 를 버리고 회사명·사업자번호+금액(OCR 캐시)으로 올바른 카드를 찾는다.
        # 이 시점의 groups 는 앵커 기반 그룹뿐이므로 미검증 카드끼리 잘못 묶이지 않음.
        _suggestions = []
        _fallback_costs = []
        for f, c, i, d, s in unanchored_costs:
            # 사용자가 이전에 승인한 (파일, 카드) 매칭 최우선 적용
            acc = _accepted_bl(f)
            if acc:
                fk_acc = acc if acc in groups else _find_group_key(acc)
                if fk_acc:
                    doc_key = _assign_with_counter(fk_acc, d or "문서", f)
                    self.log(f" -> [수동 확정] {fk_acc} / {doc_key}: {f}")
                    continue

            chosen, chosen_tier = None, None
            file_company = cleanup_company_name(c) if c and c != 'Unknown' else ""
            if d and file_company and file_company not in _GENERIC_COMPANIES:
                file_amount = 0
                cached = _cache_lookup(f)
                if cached:
                    file_amount = _parse_amount(cached.get('total_amount', 0))
                chosen, chosen_tier = _tier_match_group(d, file_company, file_amount,
                                                        _file_business_no(f))
                if chosen_tier == "tier3":
                    # 금액-only 매칭은 자동 편입하지 않고 사용자 확인 제안으로
                    if not _is_rejected(f, chosen):
                        _suggestions.append({'file': f, 'bl': chosen, 'doctype': d})
                    chosen, chosen_tier = None, None
                elif chosen_tier == "tier2":
                    # ID 보유 파일에 tier2 (신원만 일치, 데이터 검증 없음) 를 허용하면
                    # BL 이 올바르게 적힌 계산서가 같은 회사의 다른 건 카드로
                    # 흡수될 위험 → 기존 동작(자기 그룹) 유지
                    chosen, chosen_tier = None, None
            if chosen:
                doc_key = _assign_with_counter(chosen, d, f)
                self.log(f" -> [ID 재배정/{chosen_tier}] 미검증 ID '{i}' → {chosen} / {doc_key}: {f}")
            else:
                _fallback_costs.append((f, c, i, d, s))

        # 재배정 실패 파일은 기존 동작대로 자기 ID로 그룹 생성
        # (앵커 문서 없이 비용 계산서만 있는 건, BL이 정확히 적힌 계산서 선도착 등)
        for f, c, i, d, s in _fallback_costs:
            fk = _find_group_key(i)
            if fk is None:
                fk = i
            _add_to_group(fk, f, c, d, s, trusted_company=False)

        for k, v in groups.items():
            # 매칭 기준은 앵커 회사명(company_set), 표시는 없으면 display 로 보충
            cs = v['company_set'] or v.get('display_company_set', set())
            v['company'] = ", ".join(sorted(list(cs))[:2]) if cs else "Unknown"

        # ── 미분류_{doctype}_{company}_{amount}.pdf 파일 자동 매칭 ──
        for f in list(uncl):
            if not f.startswith("미분류_"):
                continue
            # 사용자가 이전에 승인한 매칭 최우선 적용
            acc = _accepted_bl(f)
            if acc:
                fk_acc = acc if acc in groups else _find_group_key(acc)
                if fk_acc:
                    _doc_guess = f[len("미분류_"):].split("_")[0] or "문서"
                    doc_key = _assign_with_counter(fk_acc, _doc_guess, f)
                    _uncl_moved.append(f)
                    self.log(f" -> [수동 확정] {fk_acc} / {doc_key}: {f}")
                    continue

            m = _re.match(r'^미분류_([^_]+)_(.+?)_(\d+|확인필요|[^_]+)\.pdf$', f, _re.IGNORECASE)
            if not m:
                continue
            file_doctype = m.group(1).strip()
            file_company_raw = m.group(2).strip()
            file_suffix = m.group(3).strip()
            if not file_company_raw:
                continue
            file_company = cleanup_company_name(file_company_raw)
            if not file_company or file_company in _GENERIC_COMPANIES:
                continue
            try:
                file_amount = int(file_suffix)
            except (TypeError, ValueError):
                file_amount = 0

            chosen, chosen_tier = _tier_match_group(file_doctype, file_company, file_amount,
                                                    _file_business_no(f))
            if chosen_tier == "tier3":
                # 금액-only 매칭은 자동 편입하지 않고 사용자 확인 제안으로
                if not _is_rejected(f, chosen):
                    _suggestions.append({'file': f, 'bl': chosen, 'doctype': file_doctype})
                chosen, chosen_tier = None, None
            if chosen:
                doc_key = _assign_with_counter(chosen, file_doctype, f)
                _uncl_moved.append(f)
                self.log(f" -> [자동 매칭/{chosen_tier}] 미분류 → {chosen} / {doc_key}: {f}")

        # 매칭이 끝나면 company_set 정리 (UI 기대 스키마 유지)
        for k, v in groups.items():
            v.pop('company_set', None)
            v.pop('display_company_set', None)

        # 매칭된 파일은 uncl에서 제거
        for f in _uncl_moved:
            if f in uncl:
                uncl.remove(f)

        # 폴더에서 사라진 파일의 승인/거부 기록 청소
        if _mm is not None:
            try:
                _mm.prune_decisions(files)
            except Exception:
                pass

        if self.merge_request_callback:
            self.merge_request_callback({'directory': dr, 'groups': groups, 'unclassified': uncl,
                                        'independent': independent_groups,
                                        'suggested': _suggestions})

    def _determine_merge_order(self, dr, sf, dm, mo, an=None, ti=None, pdf_files_cache=None):
        # 디렉토리 PDF 목록 캐싱 (함수 내 재사용)
        _all_dir_pdfs = pdf_files_cache if pdf_files_cache is not None else [
            f for f in os.listdir(dr) if f.lower().endswith('.pdf')
        ]
        # 고정 슬롯 구성
        from core.config import get_custom_naming
        _naming = get_custom_naming()
        _merge_order = _naming["merge_order"]

        # 슬롯별 데이터 준비
        _slot_data = {}
        _slot_data["정산서"] = {'label': '[명세서] 자금정산서', 'filename': sf if sf else ''}
        if mo == "수입":
            _slot_data["신고필증"] = {'label': '[신고필증] 수입신고필증', 'filename': dm.get(DOC_TYPE_IMPORT_DECLARATION, '')}
        elif mo == "수출":
            from core.constants import DOC_TYPE_RETURN_DECLARATION
            return_decl = dm.get(DOC_TYPE_RETURN_DECLARATION, '')
            if return_decl:
                _slot_data["신고필증"] = {'label': '[신고필증] 반송신고필증', 'filename': return_decl}
            else:
                _slot_data["신고필증"] = {'label': '[신고필증] 수출신고필증', 'filename': dm.get(DOC_TYPE_EXPORT_DECLARATION, '')}
        else:
            _slot_data["신고필증"] = {'label': '[신고필증] 신고필증', 'filename': ''}

        if mo == "수입":
            td = dm.get(DOC_TYPE_PAYMENT_NOTICE)
            if not td:
                for t, n in dm.items():
                    if "납부영수증" in n:
                        td = n
                        break
            _slot_data["납부고지서"] = {'label': '[세금] 납부고지서', 'filename': td if td else ''}
            _slot_data["세금계산서"] = {'label': '[세금] 수입세금계산서', 'filename': dm.get(DOC_TYPE_IMPORT_TAX_INVOICE, '')}

        # config 순서대로 m 리스트 구성 (비용계산서 이전까지)
        m = []
        for slot_name in _merge_order:
            if slot_name == "비용계산서":
                break
            if slot_name in _slot_data:
                m.append(_slot_data[slot_name])

        af = [x['filename'] for x in m if x['filename']]
        allp = []

        from core.constants import is_merge_excluded_file
        if ti:
            normalized_ti_main = normalize_id(ti)
            for f in _all_dir_pdfs:
                if f in af:
                    continue
                # 이체증·신고서·청구서는 정산서에 병합하면 안 되는 서류이므로 제외
                if is_merge_excluded_file(f):
                    continue
                match = RE_ID_PAREN.search(f)
                if match:
                    f_id_raw = match.group(1).strip()
                    f_id = normalize_id(f_id_raw)
                    # 정확 일치, prefix 포함 매칭(suffix 1글자), 또는 유사 매칭(선사코드 누락 등)
                    if (f_id == normalized_ti_main
                            or is_prefix_match_id(f_id, normalized_ti_main)
                            or is_similar_id(f_id_raw, ti)):
                        allp.append(f)

        # 그룹핑(카드)에서 편입이 확정된 문서는 파일명 ID가 달라도 병합 후보에 포함
        # (비용계산서에 검사기관 접수번호 등 미검증 ID가 박힌 경우, 미분류_ 파일 등
        #  파일명 ID 매칭만으로는 누락되는 카드 소속 문서 커버)
        if dm:
            for _fn in dm.values():
                if not _fn or _fn in af or _fn in allp or _fn not in _all_dir_pdfs:
                    continue
                if is_merge_excluded_file(_fn):
                    continue
                allp.append(_fn)

        # ── 동일 내용 중복 파일 제거 ──
        # 같은 파일을 두 번 넣으면 "xxx (1).pdf" 복사본이 생기고, 슬롯에 못 들어간
        # 복사본이 '[추가] 미분류 서류'로 병합에 이중 포함됨.
        # 슬롯 배정 파일(af) 및 후보끼리 내용이 같으면 한 장만 남긴다.
        # 1차: 파일 바이트 MD5. 2차: 추출 텍스트 해시 —
        # 유니패스 재다운로드본은 내용이 같아도 PDF 생성정보 차이로 바이트가 달라
        # MD5 로는 못 잡는다. 텍스트가 충분히 있을 때만 사용 (이미지 스캔본끼리
        # 빈 텍스트로 오인 병합되는 것 방지).
        import hashlib as _hashlib

        def _file_hash(_fn):
            try:
                with open(os.path.join(dr, _fn), 'rb') as _fh:
                    return _hashlib.md5(_fh.read()).hexdigest()
            except OSError:
                return None

        def _text_hash(_fn):
            try:
                import fitz
                with fitz.open(os.path.join(dr, _fn)) as _doc:
                    _txt = "".join(p.get_text() for p in _doc)
                _txt = "".join(_txt.split())  # 공백/줄바꿈 차이 무시
                if len(_txt) < 50:
                    return None  # 이미지 스캔본 등 텍스트 부족 → 판단 불가
                return _hashlib.md5(_txt.encode("utf-8")).hexdigest()
            except Exception:
                return None

        # 3차: 고정 슬롯 서류(BL당 1장 — 신고필증/정산서/납부고지서/수입세금계산서)는
        # 슬롯이 이미 다른 파일로 채워져 있으면 재다운로드 복사본으로 보고 제외.
        # 재다운로드본은 출력일자 등이 달라 바이트/텍스트 해시로도 못 잡는다.
        # (재발행 등 진짜 교체가 필요하면 매핑 화면에서 수동 배정 가능)
        _slot_doc_of = {}
        for _fn in af:
            _c0, _i0, _d0, _s0 = parse_renamed_filename(_fn)
            if _d0 in FIXED_SLOT_KEYS and _d0 not in _slot_doc_of:
                _slot_doc_of[_d0] = _fn

        _seen_hashes = {}
        _seen_texts = {}
        for _fn in af:
            _h = _file_hash(_fn)
            if _h and _h not in _seen_hashes:
                _seen_hashes[_h] = _fn
            _t = _text_hash(_fn)
            if _t and _t not in _seen_texts:
                _seen_texts[_t] = _fn
        _deduped = []
        for _fn in allp:
            _h = _file_hash(_fn)
            if _h and _h in _seen_hashes:
                self.log(f" -> [중복 제외] {_fn} (동일 내용: {_seen_hashes[_h]})")
                continue
            _t = _text_hash(_fn)
            if _t and _t in _seen_texts:
                self.log(f" -> [중복 제외] {_fn} (동일 텍스트: {_seen_texts[_t]})")
                continue
            _c0, _i0, _d0, _s0 = parse_renamed_filename(_fn)
            if _d0 in _slot_doc_of and _slot_doc_of[_d0] != _fn:
                self.log(f" -> [중복 제외] {_fn} (슬롯 이미 배정: {_slot_doc_of[_d0]})")
                continue
            if _h:
                _seen_hashes[_h] = _fn
            if _t:
                _seen_texts[_t] = _fn
            _deduped.append(_fn)
        allp = _deduped

        syns = EXPENSE_SYNONYMS

        merge_info = an.get("merge_info", {}) if isinstance(an, dict) else {}
        expense_list = merge_info.get("expense_items", [])
        if not expense_list and isinstance(an, dict):
            expense_list = an.get("expense_items", [])

        # 수수료계산서 파일 미리 찾기 (여러 수수료 항목이 같은 파일을 공유)
        fee_invoice_file = None
        for pdf in allp:
            if "수수료계산서" in pdf or "수수료" in pdf.upper():
                fee_invoice_file = pdf
                break

        def _is_fee_item(item_name):
            """항목이 통관수수료계산서에 포함되는 항목인지 확인"""
            item_clean = item_name.replace(" ", "")
            # 정확 매칭
            if item_clean in FEE_INVOICE_ITEMS or item_name in FEE_INVOICE_ITEMS:
                return True
            # 부분 매칭 (괄호 포함 항목: 요건수수료(생활) 등)
            for fee in FEE_INVOICE_ITEMS:
                if fee in item_clean or item_clean in fee:
                    return True
            return False

        # ── OCR 캐시 일괄 로드 (디스크 I/O 1회만) ──
        _ocr_cache = {}  # {filename: cached_result}
        for pdf in _all_dir_pdfs:
            cached = gemini_ocr._get_cached_result(os.path.join(dr, pdf))
            if cached:
                _ocr_cache[pdf] = cached

        def _get_file_amount(filename):
            cached = _ocr_cache.get(filename)
            if cached:
                try:
                    return int(str(cached.get('total_amount', 0)).replace(',', '').replace('원', ''))
                except ValueError:
                    pass
            return 0

        def _parse_item_amount(raw):
            try:
                return int(str(raw).replace(',', '').replace('원', ''))
            except ValueError:
                return 0

        def _build_search_kws(item_name):
            item_upper = item_name.upper().replace(" ", "")
            kws = [item_upper]
            for k, s in syns.items():
                if k in item_name:
                    kws.extend([x.upper().replace(" ", "") for x in s])
            return kws

        def _find_keyword_candidates(search_kws, exclude):
            """키워드로 매칭되는 후보 파일 목록 반환 (exclude 제외)"""
            candidates = []
            for pdf in allp:
                if pdf in exclude:
                    continue
                pdf_upper = pdf.upper().replace(" ", "")
                if any(kw in pdf_upper for kw in search_kws):
                    candidates.append(pdf)
            return candidates

        # ── billing_items 맵 + 공급자 맵 구축 (메모리 캐시 활용) ──
        file_billing_map = {}
        file_supplier_map = {}
        for pdf in allp:
            cached = _ocr_cache.get(pdf)
            if cached:
                bi = cached.get('billing_items', [])
                if bi:
                    file_billing_map[pdf] = bi
                sn = cached.get('supplier_name', '')
                if sn:
                    file_supplier_map[pdf] = sn

        def _get_comparable_amount(filename, item_search_kws):
            """파일의 비교 금액 반환 (billing_items 우선, 없으면 total_amount)"""
            if filename in file_billing_map:
                for bi in file_billing_map[filename]:
                    bi_name = bi.get('name', '').upper().replace(' ', '')
                    if any(kw in bi_name or bi_name in kw for kw in item_search_kws):
                        return _parse_item_amount(bi.get('amount', 0))
            return _get_file_amount(filename)

        def _supplier_key(fn):
            """공급자 식별 키 — 사업자번호 우선, 없으면 상호"""
            cached = _ocr_cache.get(fn)
            if not cached:
                return ""
            biz = re.sub(r'\D', '', str(cached.get('supplier_business_no', '') or ''))
            if len(biz) == 10:
                return biz
            return (cached.get('supplier_name', '') or '').replace(' ', '')

        def _find_supplier_bundle(candidates, item_amt):
            """정산서 항목 금액 = 같은 공급자 계산서들의 합계 인 묶음 탐색.

            포워더가 한 건의 비용을 여러 장(해상운임/부대비용 등)으로 분할 발행하면
            개별 파일 금액이 정산서 항목과 안 맞음 → 공급자(사업자번호) 단위로 묶어
            합계를 비교한다. 파일명 doc_type 라벨이 잘못 분류돼 있어도 동작.
            오매칭 방지: 묶음 중 최소 1개는 키워드 후보(candidates)여야 함.
            """
            if item_amt <= 0:
                return None
            by_supplier = {}
            for pdf in allp:
                if pdf in af:
                    continue
                key = _supplier_key(pdf)
                if key:
                    by_supplier.setdefault(key, []).append(pdf)
            cand_set = set(candidates)
            for key, group_files in by_supplier.items():
                if len(group_files) < 2 or not any(f in cand_set for f in group_files):
                    continue
                if sum(_get_file_amount(f) for f in group_files) == item_amt:
                    # 키워드 후보를 대표(슬롯 파일)로 앞세움
                    return sorted(group_files, key=lambda f: (f not in cand_set, f))
            return None

        # ── Step 0: 분리형/묶음형 파일 사전 분류 ──
        # 분리형: 파일의 billing_items 이름이 정산서 expense 이름과 2개 이상 정확 일치
        #         → 한 파일을 여러 expense 가 공유 (예: 운송료계산서 안에 보세운송료+운송료)
        # 묶음형: 안 항목 이름이 정산서 expense 이름과 매칭 0~1개
        #         → 한 expense 와만 매칭 (예: 선박운임계산서 안 OCEAN FREIGHT/BAF/TRUCKING CHARGE
        #            등은 정산서 "선박운임" 한 항목으로 통합)
        # ★ 금액 검증 없음 — 정산서(부가세 포함) vs 계산서(공급가액) 차이 흡수
        # ★ 이름 정확 일치만 — substring 매칭은 "TRUCKING CHARGE"가 "운송료" 동의어 "TRUCKING"
        #    와 잘못 매칭되는 false positive 야기
        def _norm_name(s):
            return (s or "").upper().replace(" ", "")

        _exp_index = []
        for _e in expense_list:
            if not _e:
                continue
            if isinstance(_e, str):
                _en, _ea = _e, 0
            else:
                _en = _e.get("name", "")
                _ea = _parse_item_amount(_e.get("amount", 0))
            if not _en or any(k in _en for k in ["관세", "부가세"]):
                continue
            _exp_index.append((_norm_name(_en), _ea, _en))

        # 분리형 사전 매칭 결과: {expense_name: pdf}
        pre_split_matches = {}
        for pdf, bi_list in file_billing_map.items():
            if len(bi_list) < 2:
                continue
            candidate = []  # [exp_orig_name]
            used_exp = set()
            for bi_idx, bi in enumerate(bi_list):
                bi_name_n = _norm_name(bi.get('name', ''))
                if not bi_name_n:
                    continue
                for exp_n, exp_a, exp_o in _exp_index:
                    if exp_o in used_exp:
                        continue
                    # 이름 정확 일치만 — 금액 검증 안 함
                    if bi_name_n == exp_n:
                        candidate.append(exp_o)
                        used_exp.add(exp_o)
                        break
            if len(candidate) >= 2:
                for exp_name in candidate:
                    pre_split_matches[exp_name] = pdf
        # 분리형 파일별 parent (첫 매칭) 추적용 — 2-1단계 반복 시 채워짐
        _split_parent_assigned = {}  # {pdf: parent_expense_name}

        # ── 2-1단계: 금액 우선 1:1 매칭 ──
        fee_invoice_added = False
        matched_kws = []  # 매칭된 항목의 키워드 기록 (2-2단계용)

        for item_data in expense_list:
            if not item_data:
                continue

            if isinstance(item_data, str):
                item_name = item_data
                item_amount = 0
            else:
                item_name = item_data.get("name", "")
                item_amount = item_data.get("amount", 0)

            if not item_name:
                continue
            if any(k in item_name for k in ["관세", "부가세"]):
                continue

            # 통관수수료 항목 → 기존 로직 유지
            if _is_fee_item(item_name):
                if fee_invoice_file:
                    if not fee_invoice_added:
                        m.append({'label': f'비용: {item_name}', 'filename': fee_invoice_file, 'item_amount': item_amount})
                        if fee_invoice_file not in af:
                            af.append(fee_invoice_file)
                        fee_invoice_added = True
                    else:
                        m.append({'label': f'비용: {item_name} (수수료계산서 포함)', 'filename': '', 'item_amount': item_amount})
                else:
                    m.append({'label': f'비용: {item_name}', 'filename': '', 'item_amount': item_amount})
                continue

            # ── Step 0 결과 체크: 분리형 split 매칭 ──
            if item_name in pre_split_matches:
                _split_pdf = pre_split_matches[item_name]
                if _split_pdf not in _split_parent_assigned:
                    # expense_list 에서 이 파일을 처음 만나는 expense → parent (파일 할당)
                    m.append({'label': f'비용: {item_name}', 'filename': _split_pdf, 'item_amount': item_amount})
                    if _split_pdf not in af:
                        af.append(_split_pdf)
                    matched_kws.append(_build_search_kws(item_name))
                    _split_parent_assigned[_split_pdf] = item_name
                else:
                    # 두 번째 이상 → "(parent expense 계산서 포함)" 라벨
                    parent_name = _split_parent_assigned[_split_pdf]
                    m.append({'label': f'비용: {item_name} ({parent_name}계산서 포함)',
                              'filename': '', 'item_amount': item_amount})
                continue

            search_kws = _build_search_kws(item_name)
            candidates = _find_keyword_candidates(search_kws, af)

            picked = None
            bundle_rest = []
            item_amt = _parse_item_amount(item_amount)

            if candidates:
                if item_amt > 0:
                    # 금액 일치하는 파일 우선 선택 (billing_items 개별 금액 우선 비교)
                    for c in candidates:
                        if _get_comparable_amount(c, search_kws) == item_amt:
                            picked = c
                            break
                # 개별 금액 불일치 → 같은 공급자 분할 발행 묶음의 합계 비교
                # (예: 포워더가 해상운임/부대비용을 두 장으로 발행, 정산서엔 합계 한 줄)
                if not picked:
                    bundle = _find_supplier_bundle(candidates, item_amt)
                    if bundle:
                        picked, bundle_rest = bundle[0], bundle[1:]
                # 금액 매칭 실패 또는 금액 없음 → 첫 번째 후보
                if not picked:
                    picked = candidates[0]

            if picked:
                m.append({'label': f'비용: {item_name}', 'filename': picked, 'item_amount': item_amount})
                af.append(picked)
                matched_kws.append(search_kws)
                # 묶음 나머지 파일은 "(추가)" 로 바로 뒤에 배치
                # — 금액 검증기가 (추가) 파일 금액을 부모 항목에 합산 비교함
                for extra in bundle_rest:
                    m.append({'label': f'비용: {item_name} (추가)', 'filename': extra, 'item_amount': 0})
                    af.append(extra)
            else:
                m.append({'label': f'비용: {item_name}', 'filename': '', 'item_amount': item_amount})
                matched_kws.append(search_kws)

        # ── 2-1.5단계: billing_items 기반 콘텐츠 매칭 ──
        for idx, item in enumerate(m):
            if item.get('filename') or '비용: ' not in item.get('label', ''):
                continue
            if '포함' in item['label'] or '(추가)' in item['label']:
                continue

            item_name = item['label'].replace('비용: ', '').split(' (')[0]
            search_kws = _build_search_kws(item_name)
            item_amt = _parse_item_amount(item.get('item_amount', 0))

            for pdf, bi_list in file_billing_map.items():
                matched_bi = False
                for bi in bi_list:
                    bi_name = bi.get('name', '').upper().replace(' ', '')
                    if any(kw in bi_name or bi_name in kw for kw in search_kws):
                        # 금액 비교
                        bi_amt = _parse_item_amount(bi.get('amount', 0))
                        if item_amt > 0 and bi_amt > 0 and item_amt != bi_amt:
                            continue

                        if pdf in af:
                            # 이미 할당된 파일 → "(계산서 포함)" 라벨
                            parent_label = next(
                                (x['label'] for x in m if x.get('filename') == pdf), ''
                            )
                            parent_short = parent_label.replace('비용: ', '').split(' (')[0]
                            m[idx] = {
                                'label': f'비용: {item_name} ({parent_short}계산서 포함)',
                                'filename': '', 'item_amount': item['item_amount']
                            }
                        else:
                            # 미할당 파일 → 직접 할당
                            m[idx]['filename'] = pdf
                            af.append(pdf)
                        matched_bi = True
                        break
                if matched_bi:
                    break

        # ── 2-2단계: 남은 파일 추가 편입 (공급자 우선) ──
        for pdf in allp:
            if pdf in af:
                continue
            pdf_upper = pdf.upper().replace(" ", "")
            pdf_supplier = file_supplier_map.get(pdf, '')
            absorbed = False
            for kws in matched_kws:
                if any(kw in pdf_upper for kw in kws):
                    # 키워드 매칭되는 비용 항목 후보 수집
                    candidates = []
                    for mi, item in enumerate(m):
                        if item.get('filename') and '비용: ' in item['label']:
                            label_kws = _build_search_kws(item['label'].split('비용: ')[-1].split(' (')[0])
                            if any(kw in pdf_upper for kw in label_kws):
                                candidates.append((mi, item))

                    if candidates:
                        # 같은 공급자 파일 우선 선택
                        picked = None
                        if pdf_supplier:
                            for ci, (mi, item) in enumerate(candidates):
                                item_supplier = file_supplier_map.get(item['filename'], '')
                                if item_supplier and item_supplier == pdf_supplier:
                                    picked = (mi, item)
                                    break
                        # 공급자 매칭 실패 → 첫 번째 후보
                        if not picked:
                            picked = candidates[0]

                        mi, item = picked
                        short_name = item['label'].split('비용: ')[-1].split(' (')[0]
                        m.insert(mi + 1, {'label': f'비용: {short_name} (추가)', 'filename': pdf, 'item_amount': 0})
                        af.append(pdf)
                        absorbed = True
                if absorbed:
                    break

        # ── 3단계: 금액 기반 보정 매칭 (BL 불일치 파일 포함) ──
        # BL 일치 파일(allp)이 우선이고, 그래도 못 찾으면 폴더 내 전체 파일에서 금액 매칭
        unmatched_items = [idx for idx, x in enumerate(m)
                          if x['filename'] == '' and '비용: ' in x['label']
                          and '포함' not in x['label'] and '(추가)' not in x['label']]

        if unmatched_items:
            # 1차: BL 일치 파일 중 미할당 파일
            uncl_files = [f for f in allp if f not in af]

            # 2차: 같은 폴더 내 미할당 PDF (BL 불일치 파일 중 다른 건 제외)
            if os.path.exists(dr):
                normalized_ti = normalize_id(ti) if ti else ""
                for f in _all_dir_pdfs:
                    if f in af or f in uncl_files:
                        continue
                    # 이체증·신고서·청구서는 금액이 일치해도 병합 금지
                    # (이체증은 BL이 없어 아래 BL 필터를 통과하므로 여기서 차단 필수)
                    if is_merge_excluded_file(f):
                        continue
                    # 파일에 BL번호가 있으면서 현재 건과 다른 BL이면 제외
                    f_match = RE_ID_PAREN.search(f)
                    if f_match and normalized_ti:
                        f_id_raw = f_match.group(1).strip()
                        f_id = normalize_id(f_id_raw)
                        if (f_id != normalized_ti
                                and not is_prefix_match_id(f_id, normalized_ti)
                                and not is_similar_id(f_id_raw, ti)):
                            continue  # 다른 건의 파일 → 스킵
                    uncl_files.append(f)

            uncl_amounts = {}
            for f in uncl_files:
                amt = _get_file_amount(f)
                if amt > 0:
                    uncl_amounts[f] = amt

            for idx in unmatched_items:
                item_amt = _parse_item_amount(m[idx].get('item_amount', 0))
                if item_amt > 0:
                    matching_files = [f for f, amt in uncl_amounts.items() if amt == item_amt and f not in af]
                    if len(matching_files) == 1:
                        m[idx]['filename'] = matching_files[0]
                        m[idx]['matched_by_amount'] = True
                        af.append(matching_files[0])

        # ── 5단계 준비: 요건 증빙서류 요구사항 분석 (등급형) ──
        # 정산서 수수료가 주는 정보량만큼만 검증:
        #  등급1 종류 특정 수수료(식물검역수수료, 요건수수료(전파) 등) → 종류별 체크 항목
        #  등급2 generic 수수료(요건수수료/요건대행 한 줄) → "요건서류 1건 이상" 통합 체크
        #  등급3 요건 수수료 없음 → 체크 항목 생성 안 함 (기존 동작)
        # 파일이 없어도 항목을 생성해 체크리스트에 누락으로 표시되게 한다.
        from core.constants import REQUIREMENT_FEE_SPECIFIC, REQUIREMENT_FEE_GENERIC
        _req_specific = []   # 등급1 요구 목록 [{'label', 'kws'}]
        _req_generic = False
        if an and isinstance(an, dict):
            for item_data in expense_list:
                if not item_data:
                    continue
                item_name = item_data.get("name", "") if isinstance(item_data, dict) else str(item_data)
                item_clean = item_name.replace(" ", "")
                matched_specific = False
                for fee_kw, spec in REQUIREMENT_FEE_SPECIFIC.items():
                    if fee_kw in item_clean:
                        if all(r['label'] != spec['label'] for r in _req_specific):
                            _req_specific.append(spec)
                        matched_specific = True
                if not matched_specific and any(g in item_clean for g in REQUIREMENT_FEE_GENERIC):
                    _req_generic = True

        # 요건 서류 후보 수집 (요구사항이 있을 때만):
        #  - 미분류_ 파일: 요건 키워드 + 수입자 일치
        #  - BL 리네임된 파일: allp(같은 건) 안의 요건 키워드 파일
        _req_candidates = []
        if _req_specific or _req_generic:
            _group_company = cleanup_company_name(
                (an or {}).get("company_name", "")).replace(" ", "")
            for f in _all_dir_pdfs:
                if f in af or f in _req_candidates:
                    continue
                fname_clean = f.replace(" ", "")
                if not any(kw in fname_clean for kw in REQUIREMENT_DOC_KEYWORDS):
                    continue
                if f.startswith("미분류_"):
                    parts = f[len("미분류_"):-4].split("_")
                    if len(parts) < 2:
                        continue
                    uncl_company = cleanup_company_name(parts[1]).replace(" ", "")
                    if not _group_company or _group_company == "Unknown" or not uncl_company:
                        continue
                    if uncl_company not in _group_company and _group_company not in uncl_company:
                        continue
                    _req_candidates.append(f)
                elif f in allp:
                    _req_candidates.append(f)

        # ── 4단계: 나머지 미분류 서류 (요건 후보는 5단계에서 [요건] 라벨로 처리) ──
        for pdf in allp:
            if pdf not in af and pdf not in _req_candidates:
                m.append({'label': '[추가] 미분류 서류', 'filename': pdf})
                af.append(pdf)

        # ── 5단계: 요건 증빙서류 체크 + 매칭 (맨 마지막 페이지) ──
        if _req_specific or _req_generic:
            def _req_display_name(f):
                if f.startswith("미분류_"):
                    parts = f[len("미분류_"):-4].split("_")
                    return parts[0] if parts and parts[0] else "요건서류"
                _c0, _i0, _d0, _s0 = parse_renamed_filename(f)
                return _d0 if _d0 else "요건서류"

            # 등급1: 종류별 매칭 — 파일 없으면 누락 항목으로 표시
            for spec in _req_specific:
                picked_req = None
                for f in _req_candidates:
                    fc = f.replace(" ", "")
                    if any(kw in fc for kw in spec['kws']):
                        picked_req = f
                        break
                if picked_req:
                    _req_candidates.remove(picked_req)
                    af.append(picked_req)
                    m.append({'label': f"[요건] {spec['label']}",
                              'filename': picked_req, 'requirement_doc': True})
                else:
                    m.append({'label': f"[요건] {spec['label']}",
                              'filename': '', 'requirement_doc': True})

            # 등급2: generic — 남은 요건 서류 전부 편입.
            # 종류·개수를 알 수 없으므로 "1건 이상" 만 보장 (0건이면 누락 표시)
            if _req_generic:
                if _req_candidates:
                    for f in list(_req_candidates):
                        _req_candidates.remove(f)
                        af.append(f)
                        m.append({'label': f"[요건] {_req_display_name(f)}",
                                  'filename': f, 'requirement_doc': True})
                else:
                    m.append({'label': "[요건] 요건서류 (1건 이상 필요)",
                              'filename': '', 'requirement_doc': True})

            # 수수료 항목이 없어도 도착해 있는 요건 서류는 병합에 포함
            # (무료 서비스로 처리한 전파인증 적합성평가확인서 등).
            # 슬롯/누락 표시는 만들지 않음 — 있을 때만 태우는 동반 서류.
            for f in list(_req_candidates):
                _req_candidates.remove(f)
                af.append(f)
                m.append({'label': f"[요건] {_req_display_name(f)}",
                          'filename': f, 'requirement_doc': True})

        return m

    def execute_merge_task(self, dr, of, fo, export_docs_root=None, marked_files=None,
                          merge_verify_callback=None, archive_only=False):
        """병합 수행 후 파일 정리

        Args:
            merge_verify_callback: 검증 실패 시 호출. (failed_files, total, success) → "retry"|"ignore"|"cancel"
            archive_only: True 면 병합 없이 모든 파일을 폴더로 이동만 수행 (정산서 없는 수출/수입건)
        Returns:
            True: 병합 성공, False: 취소됨
        실패 첨부 파일 목록은 self.last_failed_attached 속성에 저장됨 (호출자 조회).
        """
        # 첨부(마킹) 파일 이동 실패 추적 초기화
        self.last_failed_attached = []
        if not fo:
            return False

        from .constants import ANCHOR_DOC_TYPES
        target_id = ""
        decl_id = ""
        anchor_id = ""
        declaration_company = ""

        for f in fo:
            c, i, d, s = parse_renamed_filename(f)
            if i:
                target_id = i
                if "신고필증" in (d or ""):
                    decl_id = i
                    if c and c != "Unknown":
                        declaration_company = c
                elif d in ANCHOR_DOC_TYPES:
                    anchor_id = anchor_id or i

        # 폴더명/병합 파일명에 쓸 ID 는 앵커 문서 우선 (신고필증 > 정산서 등 > 기타)
        # — 미검증 ID 가 박힌 비용계산서가 목록 마지막에 있어도 이름이 오염되지 않도록
        if decl_id:
            target_id = decl_id
        elif anchor_id:
            target_id = anchor_id

        final_company = (declaration_company if declaration_company else of.split('(')[0]).replace(" ", "")
        folder_name = f"{final_company}_{target_id}"
        archive_dir = os.path.join(dr, folder_name)
        os.makedirs(archive_dir, exist_ok=True)

        # 되돌리기 기록 — 삭제 대신 백업, 이동은 원위치 기록
        from core import merge_history
        history = merge_history.new_entry(
            kind='archive' if archive_only or len(fo) < 2 else 'merge',
            bl_id=target_id, folder_name=folder_name,
            work_dir=dr, archive_dir=archive_dir)
        self.last_history_entry = None

        # 병합 확정 = "이 파일들은 같은 건" 확정 라벨 → 회사명 별칭 학습
        # (파일 이동 전에 실행해야 OCR 캐시 검증이 가능)
        try:
            for _alias, _canon in self._learn_company_aliases(dr, fo, final_company, target_id):
                merge_history.record_alias(history, _alias, _canon)
        except Exception as e:
            self.log(f" -> [별칭 학습 건너뜀] {e}")

        try:
            if not archive_only and len(fo) >= 2:
                import fitz
                from core.config import get_custom_naming
                _naming = get_custom_naming()
                try:
                    final_of = _naming["merge_pattern"].format(company=final_company, bl=target_id)
                except (KeyError, ValueError):
                    final_of = f"{final_company}({target_id})정산서.pdf"
                output_path = os.path.join(dr, final_of)

                # 병합 실행 (재시도 지원)
                while True:
                    merged_doc = fitz.open()
                    total_pages = 0
                    failed_files = []

                    for f in fo:
                        if f:
                            src_path = os.path.join(dr, f)
                            try:
                                src_doc = fitz.open(src_path)
                                page_count = len(src_doc)
                                if page_count == 0:
                                    self.log(f" -> [경고] 빈 PDF 건너뜀: {f}")
                                    failed_files.append((f, "빈 PDF"))
                                    src_doc.close()
                                    continue
                                merged_doc.insert_pdf(src_doc)
                                total_pages += page_count
                                src_doc.close()
                            except Exception as e:
                                self.log(f" -> [경고] PDF 읽기 실패 ({f}): {e}")
                                failed_files.append((f, str(e)))

                    if total_pages == 0:
                        self.log(f" -> [오류] 병합할 페이지가 없습니다. 병합 중단.")
                        merged_doc.close()
                        try: os.rmdir(archive_dir)
                        except OSError: pass
                        merge_history.discard_entry(history)
                        return False

                    merged_doc.save(output_path)
                    merged_doc.close()

                    # 병합 결과 검증
                    verify_ok = True
                    try:
                        verify_doc = fitz.open(output_path)
                        actual_pages = len(verify_doc)
                        verify_doc.close()
                        if actual_pages == 0:
                            self.log(f" -> [오류] 병합 결과가 빈 파일입니다.")
                            verify_ok = False
                        elif actual_pages != total_pages:
                            self.log(f" -> [경고] 페이지 수 불일치! 예상: {total_pages}, 실제: {actual_pages}")
                            verify_ok = False
                    except Exception as e:
                        self.log(f" -> [경고] 병합 결과 검증 실패: {e}")
                        verify_ok = False

                    # 실패 파일이 있거나 검증 실패 → 사용자 확인
                    if (failed_files or not verify_ok) and merge_verify_callback:
                        action = merge_verify_callback(
                            failed_files, len(fo), total_pages
                        )
                        if action == "retry":
                            # 병합 결과 삭제 후 재시도
                            try: os.remove(output_path)
                            except OSError: pass
                            self.log(f" -> [재시도] 병합을 다시 시도합니다.")
                            continue  # while 루프 재시작
                        elif action == "cancel":
                            # 병합 결과 삭제, 원본 유지
                            try: os.remove(output_path)
                            except OSError: pass
                            self.log(f" -> [취소] 병합이 취소되었습니다. 원본 파일 유지.")
                            # 빈 폴더 정리
                            try: os.rmdir(archive_dir)
                            except OSError: pass
                            merge_history.discard_entry(history)
                            return False
                        # "ignore" → 계속 진행
                        self.log(f" -> [무시] 실패 파일을 보존하고 진행합니다.")
                    elif not failed_files and verify_ok:
                        self.log(f" -> [병합] {len(fo)}개 파일 → {total_pages}페이지 정산서")

                    break  # while 루프 종료 (정상 또는 ignore)

                shutil.move(output_path, os.path.join(archive_dir, final_of))
                history['merged_file'] = final_of

                # 원본 파일 정리 (실패 파일은 보존, 삭제 대신 되돌리기용 백업)
                failed_names = {f for f, _ in failed_files} if failed_files else set()
                for f in fo:
                    if not f or f == final_of: continue
                    src_path = os.path.join(dr, f)
                    if not os.path.exists(src_path): continue

                    _, _, d, _ = parse_renamed_filename(f)
                    is_decl = ("신고필증" in d) if d else ("신고필증" in f)

                    if f in failed_names or is_decl:
                        # 실패 파일 또는 신고필증 → 폴더로 보존
                        try:
                            shutil.move(src_path, os.path.join(archive_dir, f))
                            merge_history.record_move(history, f, dr, archive_dir)
                            if f in failed_names:
                                self.log(f" -> [보존] 병합 실패 파일: {f}")
                        except Exception:
                            pass
                    else:
                        merge_history.backup_file(history, src_path)

                # 같은 ID의 남은 PDF 추가 정리 (기존 안전망)
                if target_id:
                    source_files_in_folder = [f for f in os.listdir(dr) if f.lower().endswith('.pdf')]
                    for f in source_files_in_folder:
                        if os.path.isdir(os.path.join(dr, f)) or f == final_of:
                            continue
                        c, i, d, s = parse_renamed_filename(f)
                        if i and is_similar_id(i, target_id):
                            if "신고필증" in (d or ""):
                                try:
                                    shutil.move(os.path.join(dr, f), os.path.join(archive_dir, f))
                                    merge_history.record_move(history, f, dr, archive_dir)
                                except Exception:
                                    pass
                            else:
                                merge_history.backup_file(history, os.path.join(dr, f))
            else:
                # archive_only=True 또는 1개 파일: 병합 없이 원본을 폴더로 이동
                for f in fo:
                    if f:
                        src = os.path.join(dr, f)
                        dst = os.path.join(archive_dir, f)
                        if os.path.exists(src) and not os.path.exists(dst):
                            shutil.move(src, dst)
                            merge_history.record_move(history, f, dr, archive_dir)
                if archive_only:
                    self.log(f" -> [아카이브] {len(fo)}개 파일을 병합 없이 폴더로 이동")

            # ──── 마킹된 파일 이동 (관련 파일 수집보다 먼저 실행) ────
            moved_marked = set()  # 이미 이동된 파일명 추적
            if marked_files:
                marked_count = 0
                self.log(f" -> [마킹] {len(marked_files)}개 파일 이동 시작...")
                # 파일 앱(Acrobat/Excel 등) 종료 대기
                time.sleep(1.5)

                # 검색 디렉토리: export_docs_root, 작업 폴더, 마킹 파일의 원래 디렉토리
                search_dirs_set = set()
                for sd in [export_docs_root, dr]:
                    if sd and os.path.exists(sd):
                        search_dirs_set.add(sd)
                for mf in marked_files:
                    orig_path = mf.get('path', '')
                    if orig_path:
                        orig_dir = os.path.dirname(orig_path)
                        if orig_dir and os.path.exists(orig_dir):
                            search_dirs_set.add(orig_dir)
                search_roots = list(search_dirs_set)

                for mf in marked_files:
                    src_path = mf.get('path', '')
                    file_name = mf.get('name', '')

                    self.log(f" -> [마킹 디버그] 파일: {file_name}, 경로: {src_path or '(없음)'}")

                    # 경로가 있고 파일이 존재하면 바로 사용
                    if src_path and os.path.exists(src_path):
                        pass  # 경로 확정
                    else:
                        # 이미 archive_dir에 있는지 먼저 확인
                        if file_name:
                            check_in_archive = os.path.join(archive_dir, file_name)
                            if os.path.exists(check_in_archive):
                                self.log(f" -> [마킹 건너뜀] {file_name} (이미 정리 폴더에 존재)")
                                moved_marked.add(file_name)
                                marked_count += 1
                                continue

                        if file_name:
                            # 경로가 없거나 파일이 없으면 재귀 검색
                            from core.open_file_detector import find_file_path
                            src_path = find_file_path(file_name, search_roots)
                            if src_path:
                                self.log(f" -> [마킹 디버그] 검색으로 찾음: {src_path}")
                            else:
                                self.log(f" -> [마킹 디버그] 검색 실패 (검색 경로: {search_roots})")
                    
                    if src_path and os.path.exists(src_path):
                        dst_path = os.path.join(archive_dir, os.path.basename(src_path))
                        if not os.path.exists(dst_path):
                            # copy + remove 분리 (부분 실패 시 롤백 가능)
                            # shutil.move는 copy 성공 + unlink 실패 시 양쪽에 파일 남는 문제가 있음
                            move_success = False
                            for attempt in range(3):
                                try:
                                    shutil.copy2(src_path, dst_path)  # 복사
                                    try:
                                        os.remove(src_path)  # 원본 삭제
                                        self.log(f" -> [마킹 이동] {os.path.basename(src_path)}")
                                        moved_marked.add(os.path.basename(src_path))
                                        merge_history.record_move(
                                            history, os.path.basename(src_path),
                                            os.path.dirname(src_path), archive_dir)
                                        marked_count += 1
                                        move_success = True
                                        break
                                    except PermissionError:
                                        # 원본 삭제 실패 → 복사본 유지, 원본 수동 처리 안내
                                        self.log(f" -> [첨부 복사] {os.path.basename(src_path)} (이동 실패 → 복사 완료, 원본 수동 처리 필요)")
                                        moved_marked.add(os.path.basename(src_path))
                                        marked_count += 1
                                        move_success = True
                                        self.last_failed_attached.append((file_name or os.path.basename(src_path), "이동 실패로 복사함. 원본 파일을 수동으로 처리해 주세요."))
                                        break
                                except PermissionError:
                                    # copy 자체 실패 (읽기 권한 없음)
                                    if attempt < 2:
                                        self.log(f" -> [마킹 재시도] {os.path.basename(src_path)} (복사 실패, {attempt+1}/3)")
                                        time.sleep(1.0)
                                    else:
                                        self.log(f" -> [마킹 이동 실패] {os.path.basename(src_path)}: 파일 접근 권한 없음")
                                        self.last_failed_attached.append((file_name or os.path.basename(src_path), "파일 접근 권한 없음"))
                                except Exception as e:
                                    # 기타 실패 시 dst 롤백
                                    try: os.remove(dst_path)
                                    except OSError: pass
                                    self.log(f" -> [마킹 이동 실패] {os.path.basename(src_path)}: {e}")
                                    self.last_failed_attached.append((file_name or os.path.basename(src_path), str(e)))
                                    break
                        else:
                            self.log(f" -> [마킹 건너뜀] {os.path.basename(src_path)} (이미 존재)")
                            moved_marked.add(os.path.basename(src_path))
                    else:
                        self.log(f" -> [마킹 찾기 실패] {file_name} (경로: {src_path or '없음'}, 존재: {os.path.exists(src_path) if src_path else False})")
                        self.last_failed_attached.append((file_name, "원본 파일을 찾을 수 없음"))
                if marked_count:
                    self.log(f" -> [마킹 이동 완료] {marked_count}개 파일")

            # 관련 파일/폴더 자동 수집 (merge 대상 폴더 - 이름변경 폴더에서만)
            # 마킹으로 이미 이동된 파일은 제외
            self._collect_related_items(dr, archive_dir, target_id,
                                        exclude_names=moved_marked, history=history)

            # 되돌리기 기록 확정
            merge_history.save_entry(history)
            self.last_history_entry = {
                'id': history['id'],
                'folder_name': folder_name,
                'kind': history['kind'],
                'file_count': merge_history.file_count(history),
            }

            self.log(f" -> [완료] 폴더 정리 완료: {folder_name}")
            return True
        except Exception as e:
            self.log(f"병합 실행 오류: {e}")
            print(f"병합 실행 오류: {e}")
            # 백업했던 원본은 작업 폴더로 복귀
            try:
                merge_history.discard_entry(history)
            except Exception:
                pass
            return False


    def _learn_company_aliases(self, dr, fo, canonical, target_id):
        """병합 확정 파일들의 회사명 표기를 카드의 한글 상호와 짝지어 학습.

        오학습 방어 (BL 우선 원칙):
        - 학습 소스는 파일명 BL 이 카드 BL 과 일치하는 강증거 파일만
          (금액-only 로 사용자가 승인한 파일 등은 제외)
        - 발행처(supplier) 표기와 동일하면 정산업체·검사기관 이름이므로 학습 금지
        - 2글자 이하 표기는 부분포함 매칭과 결합 시 과매칭 위험 → 제외
        """
        import re as _re
        learned = []
        if not canonical or not target_id or not fo:
            return learned
        canonical = cleanup_company_name(canonical).replace(" ", "")
        if not canonical or not _re.search(r'[가-힣]', canonical):
            return learned  # 표준명은 한글 상호만
        from core.match_memory import learn_alias
        for f in fo:
            if not f:
                continue
            c, i, d, s = parse_renamed_filename(f)
            if not i:
                continue
            if not (is_similar_id(i, target_id) or is_prefix_match_id(i, target_id)):
                continue
            cached = gemini_ocr._get_cached_result(os.path.join(dr, f))
            if not cached:
                continue
            alias = cleanup_company_name(cached.get('company_name', '') or '').replace(" ", "")
            supplier = cleanup_company_name(cached.get('supplier_name', '') or '').replace(" ", "")
            if not alias or len(alias) <= 2 or alias == canonical or alias == "Unknown":
                continue
            if supplier and alias == supplier:
                continue
            learn_alias(alias, canonical)
            learned.append((alias, canonical))
            self.log(f" -> [별칭 학습] '{alias}' → '{canonical}'")
        return learned

    def _collect_related_items(self, dr, archive_dir, target_id, exclude_names=None, history=None):
        """송품장번호가 포함된 파일/폴더를 정리 폴더로 자동 수집"""
        if not target_id:
            return
        from core import merge_history as _mh

        tid_upper = normalize_id(target_id)
        archive_name = os.path.basename(archive_dir)
        collected = 0
        exclude = exclude_names or set()

        try:
            items = os.listdir(dr)
        except Exception:
            return

        for item in items:
            item_path = os.path.join(dr, item)

            # 아카이브 폴더 자체는 건너뜀
            if item == archive_name:
                continue

            if os.path.isfile(item_path):
                # 마킹으로 이미 이동된 파일은 건너뜀
                if item in exclude:
                    continue
                # 파일명에 송품장번호 포함 여부 (대소문자 무시, 공백 제거)
                if tid_upper in normalize_id(item):
                    dst = os.path.join(archive_dir, item)
                    if not os.path.exists(dst):
                        try:
                            shutil.move(item_path, dst)
                            if history is not None:
                                _mh.record_move(history, item, dr, archive_dir)
                            self.log(f" -> [수집] {item}")
                            collected += 1
                        except Exception as e:
                            self.log(f" -> [수집 실패] {item}: {e}")

            elif os.path.isdir(item_path):
                # 폴더 내 파일 중 송품장번호 포함 파일이 있는지 확인
                try:
                    has_related = any(
                        tid_upper in normalize_id(f)
                        for f in os.listdir(item_path)
                        if os.path.isfile(os.path.join(item_path, f))
                    )
                except Exception:
                    has_related = False

                if has_related:
                    try:
                        # 폴더 안의 파일들만 정리 폴더로 이동
                        for f in os.listdir(item_path):
                            src = os.path.join(item_path, f)
                            if os.path.isfile(src):
                                dst = os.path.join(archive_dir, f)
                                if not os.path.exists(dst):
                                    shutil.move(src, dst)
                                    if history is not None:
                                        _mh.record_move(history, f, item_path, archive_dir)
                                    self.log(f" -> [수집] {f} (from {item}/)")
                                    collected += 1
                        # 빈 폴더 삭제 시도
                        try:
                            os.rmdir(item_path)
                        except OSError:
                            pass  # 폴더가 비어있지 않으면 그냥 둠
                    except Exception as e:
                        self.log(f" -> [수집 실패] {item}/: {e}")

        if collected:
            self.log(f" -> [수집 완료] {collected}개 항목을 {archive_name}/ 으로 이동")


class PDFHandler(FileSystemEventHandler):
    """PDF 파일 이벤트 핸들러"""
    
    def __init__(self, r):
        self.r = r

    def on_created(self, e):
        if not e.is_directory and e.src_path.lower().endswith('.pdf'):
            self.r.executor.submit(self.r.process_pdf, e.src_path)

    def on_moved(self, e):
        if not e.is_directory and e.dest_path.lower().endswith('.pdf'):
            self.r.executor.submit(self.r.process_pdf, e.dest_path)

    def on_modified(self, e):
        """파일 수정 시 처리 - 복사/다운로드 완료 시점 감지"""
        if not e.is_directory and e.src_path.lower().endswith('.pdf'):
            # 이미 처리 중인 파일은 건너뜀 (중복 방지)
            if e.src_path not in self.r.processing_files:
                self.r.executor.submit(self.r.process_pdf, e.src_path)

    def on_deleted(self, e):
        """파일 삭제(외부 리네임으로 옛 이름이 사라진 경우 포함) 시 카드 갱신 —
        지워진 파일명을 물고 있는 카드 스냅샷이 낡은 채 남지 않도록 함."""
        if not e.is_directory and e.src_path.lower().endswith('.pdf'):
            if self.r.rename_complete_callback:
                self.r.rename_complete_callback()
