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
    INDEPENDENT_DOC_TYPES
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
                try:
                    if gemini_ocr._get_cached_result(fp) is None:
                        self.log(f"[재분석] BL 있지만 캐시 없음 - OCR 실행: {fn}")
                        extract_document_info_ai(fp)  # _save_to_cache 자동 호출
                        if self.rename_complete_callback:
                            self.rename_complete_callback()
                except Exception as e:
                    self.log(f"[재분석 실패] {fn}: {e}")
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

    def trigger_intelligent_merge(self, dr):
        files = [f for f in os.listdir(dr) if f.lower().endswith('.pdf')]
        groups = {}
        uncl = []
        independent_groups = {}  # 독립 문서 그룹 {doc_type: [파일 목록]}
        # 카드 그룹에 포함하지 않는 문서 유형
        _EXCLUDE_DOC_TYPES = {"수입신고서", "자금청구서"}

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
                # 1차: 기존 유사도 매칭 (suffix 일치 필수)
                fk = next((k for k in groups if is_similar_id(k, i)), None)
                # 2차: prefix 포함 매칭 (정확 매칭 실패 시, 후보가 1개일 때만)
                if fk is None:
                    prefix_candidates = [k for k in groups if is_prefix_match_id(k, i)]
                    fk = prefix_candidates[0] if len(prefix_candidates) == 1 else i
                # 신고필증의 B/L이 가장 정확하므로 그룹 키를 교체
                if fk != i and "신고필증" in (d or "") and fk in groups:
                    groups[i] = groups.pop(fk)
                    fk = i
                if fk not in groups:
                    groups[fk] = {'company_set': set(), 'docs': {}}
                if c and c != 'Unknown':
                    clean_c = cleanup_company_name(c)
                    groups[fk]['company_set'].add(clean_c)
                # 같은 문서 유형이 이미 있으면 suffix를 포함한 고유 키 사용
                doc_key = d
                if d in groups[fk]['docs']:
                    # suffix가 있으면 포함 (예: "운송료(1)"), 없으면 카운터 추가
                    if s:
                        doc_key = f"{d}{s}"
                    else:
                        counter = 1
                        while doc_key in groups[fk]['docs']:
                            doc_key = f"{d}({counter})"
                            counter += 1
                groups[fk]['docs'][doc_key] = f
            else:
                uncl.append(f)
        for k, v in groups.items():
            cs = v['company_set']  # 매칭에 재사용하기 위해 유지 (pop 대신)
            v['company'] = ", ".join(sorted(list(cs))[:2]) if cs else "Unknown"

        # ═══════════════════════════════════════════════
        # 미분류_{doctype}_{company}_{amount}.pdf 파일을
        # 회사명 (+ 비용계산서는 금액도) 매칭으로 BL 그룹에 자동 할당
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
        import re as _re
        from core.validator import parse_amount as _parse_amount, build_search_kws as _build_search_kws
        _GENERIC_COMPANIES = {"Unknown", "알수없는상호", "알수없는", "미상", ""}
        _FIXED_SLOT = {"수입세금계산서", "납부고지서", "자금정산서", "정산서",
                        "수입신고필증", "수출신고필증", "반송신고필증"}
        _SETTLEMENT_KEYS = ("자금정산서", "정산서")
        _uncl_moved = []

        def _find_settlement_cached(bl_data):
            """BL 의 정산서 OCR 캐시 + items 리스트 반환. 없으면 (None, None, [])."""
            for sk in _SETTLEMENT_KEYS:
                if sk in bl_data.get('docs', {}):
                    settlement_fn = bl_data['docs'][sk]
                    try:
                        cached = gemini_ocr._get_cached_result(os.path.join(dr, settlement_fn))
                    except Exception:
                        cached = None
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
            for bc in bl_data.get('company_set', set()):
                bc_clean = cleanup_company_name(bc)
                if not bc_clean or bc_clean in _GENERIC_COMPANIES:
                    continue
                if file_company in bc_clean or bc_clean in file_company:
                    return True
            return False

        for f in list(uncl):
            if not f.startswith("미분류_"):
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

            is_fixed = file_doctype in _FIXED_SLOT
            is_req = _is_requirement_doc(file_doctype)
            category = "FIXED" if is_fixed else ("REQ" if is_req else "COST")

            # 카테고리별 후보 수집
            # Tier1: 엄격 (회사+데이터 검증 통과)
            # Tier2: 차선 (회사만 OK 인데 정산서 데이터 부족)
            # Tier3: 금액-only (회사명은 안 맞지만 금액+항목이 유일하게 매칭)
            tier1 = []  # strict
            tier2 = []  # loose (settlement data missing)
            tier3 = []  # amount-only fallback (company inconsistent)

            for bl_id, bl_data in groups.items():
                if file_doctype in bl_data.get('docs', {}):
                    continue
                comp_ok = _company_match(bl_data, file_company)

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
                    req_kws_in_doc = [k for k in REQUIREMENT_DOC_KEYWORDS if k in file_doctype]
                    found_kw = False
                    for bi in items:
                        bi_name = bi.get('name', '')
                        if any(k in bi_name for k in req_kws_in_doc):
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

                # 회사 불일치지만 금액이 일치하면 tier3 (영문/한글 이명 케이스 커버)
                if not comp_ok and file_amount > 0 and file_amount in matching_amts:
                    tier3.append(bl_id)
                    continue

                # 회사는 맞지만 금액이 안 맞음 → 매칭 안 함 (tier 에 포함 X)

            # Tier 선택: 1 > 2 > 3, 각 tier 에서 정확히 1개일 때만
            chosen = None
            chosen_tier = None
            if len(tier1) == 1:
                chosen, chosen_tier = tier1[0], "tier1"
            elif len(tier1) == 0 and len(tier2) == 1:
                chosen, chosen_tier = tier2[0], "tier2"
            elif len(tier1) == 0 and len(tier2) == 0 and len(tier3) == 1:
                chosen, chosen_tier = tier3[0], "tier3"


            if chosen:
                groups[chosen].setdefault('docs', {})[file_doctype] = f
                _uncl_moved.append(f)
                self.log(f" -> [자동 매칭/{chosen_tier}] 미분류 → {chosen} / {file_doctype}: {f}")

        # 매칭이 끝나면 company_set 정리 (UI 기대 스키마 유지)
        for k, v in groups.items():
            v.pop('company_set', None)

        # 매칭된 파일은 uncl에서 제거
        for f in _uncl_moved:
            if f in uncl:
                uncl.remove(f)

        if self.merge_request_callback:
            self.merge_request_callback({'directory': dr, 'groups': groups, 'unclassified': uncl,
                                        'independent': independent_groups})

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

        if ti:
            normalized_ti_main = normalize_id(ti)
            for f in _all_dir_pdfs:
                if f in af:
                    continue
                # 청구서(자금청구서)는 정산서에 병합하면 안 되는 별도 서류이므로 제외
                if "청구서" in f and "계산서" not in f:
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

            search_kws = _build_search_kws(item_name)
            candidates = _find_keyword_candidates(search_kws, af)

            picked = None
            item_amt = _parse_item_amount(item_amount)

            if candidates:
                if item_amt > 0:
                    # 금액 일치하는 파일 우선 선택 (billing_items 개별 금액 우선 비교)
                    for c in candidates:
                        if _get_comparable_amount(c, search_kws) == item_amt:
                            picked = c
                            break
                # 금액 매칭 실패 또는 금액 없음 → 첫 번째 후보
                if not picked:
                    picked = candidates[0]

            if picked:
                m.append({'label': f'비용: {item_name}', 'filename': picked, 'item_amount': item_amount})
                af.append(picked)
                matched_kws.append(search_kws)
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
                    if "청구서" in f and "계산서" not in f:
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

        # ── 4단계: 나머지 미분류 서류 ──
        for pdf in allp:
            if pdf not in af:
                m.append({'label': '[추가] 미분류 서류', 'filename': pdf})
                af.append(pdf)

        # ── 5단계: 요건 증빙서류 매칭 (맨 마지막 페이지) ──
        # 정산서에 요건 수수료가 있고 수입자가 같은 미분류 요건 서류를 자동 매칭
        if an and isinstance(an, dict):
            group_company = cleanup_company_name(an.get("company_name", "")).replace(" ", "")

            if group_company and group_company != "Unknown":
                has_req_keywords = set()
                for item_data in expense_list:
                    if not item_data:
                        continue
                    item_name = item_data.get("name", "") if isinstance(item_data, dict) else str(item_data)
                    item_clean = item_name.replace(" ", "")
                    for kw in REQUIREMENT_DOC_KEYWORDS:
                        if kw in item_clean:
                            has_req_keywords.add(kw)

                if has_req_keywords:
                    try:
                        for f in _all_dir_pdfs:
                            if not f.startswith("미분류_"):
                                continue
                            if f in af:
                                continue

                            name_body = f[len("미분류_"):-4]
                            parts = name_body.split("_")
                            if len(parts) < 2:
                                continue

                            uncl_doc = parts[0]
                            uncl_company = parts[1]

                            if cleanup_company_name(uncl_company).replace(" ", "") != group_company:
                                continue

                            for kw in has_req_keywords:
                                if kw in uncl_doc:
                                    m.append({'label': f'[요건] {uncl_doc}', 'filename': f, 'requirement_doc': True})
                                    af.append(f)
                                    break
                    except OSError:
                        pass

        return m

    def execute_merge_task(self, dr, of, fo, export_docs_root=None, marked_files=None,
                          merge_verify_callback=None):
        """병합 수행 후 파일 정리

        Args:
            merge_verify_callback: 검증 실패 시 호출. (failed_files, total, success) → "retry"|"ignore"|"cancel"
        Returns:
            True: 병합 성공, False: 취소됨
        실패 첨부 파일 목록은 self.last_failed_attached 속성에 저장됨 (호출자 조회).
        """
        # 첨부(마킹) 파일 이동 실패 추적 초기화
        self.last_failed_attached = []
        if not fo:
            return False

        target_id = ""
        declaration_company = ""

        for f in fo:
            c, i, d, s = parse_renamed_filename(f)
            if i:
                target_id = i
                if "신고필증" in d:
                    if c and c != "Unknown":
                        declaration_company = c

        final_company = (declaration_company if declaration_company else of.split('(')[0]).replace(" ", "")
        folder_name = f"{final_company}_{target_id}"
        archive_dir = os.path.join(dr, folder_name)
        os.makedirs(archive_dir, exist_ok=True)

        try:
            if len(fo) >= 2:
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
                            return False
                        # "ignore" → 계속 진행
                        self.log(f" -> [무시] 실패 파일을 보존하고 진행합니다.")
                    elif not failed_files and verify_ok:
                        self.log(f" -> [병합] {len(fo)}개 파일 → {total_pages}페이지 정산서")

                    break  # while 루프 종료 (정상 또는 ignore)

                shutil.move(output_path, os.path.join(archive_dir, final_of))

                # 원본 파일 정리 (실패 파일은 보존)
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
                            if f in failed_names:
                                self.log(f" -> [보존] 병합 실패 파일: {f}")
                        except Exception:
                            pass
                    else:
                        try:
                            os.remove(src_path)
                        except Exception:
                            pass

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
                                except Exception:
                                    pass
                            else:
                                try:
                                    os.remove(os.path.join(dr, f))
                                except Exception:
                                    pass
            else:
                # 1개 (수출신고필증만): 병합 없이 원본을 폴더로 이동
                for f in fo:
                    if f:
                        src = os.path.join(dr, f)
                        dst = os.path.join(archive_dir, f)
                        if os.path.exists(src) and not os.path.exists(dst):
                            shutil.move(src, dst)

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
            self._collect_related_items(dr, archive_dir, target_id, exclude_names=moved_marked)

            self.log(f" -> [완료] 폴더 정리 완료: {folder_name}")
            return True
        except Exception as e:
            self.log(f"병합 실행 오류: {e}")
            print(f"병합 실행 오류: {e}")
            return False


    def _collect_related_items(self, dr, archive_dir, target_id, exclude_names=None):
        """송품장번호가 포함된 파일/폴더를 정리 폴더로 자동 수집"""
        if not target_id:
            return

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
