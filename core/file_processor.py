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
    FEE_INVOICE_ITEMS, EXPENSE_SYNONYMS
)
from .utils import (
    sanitize_filename, get_unique_filename, cleanup_company_name,
    parse_renamed_filename, RE_ID_PAREN, normalize_id, is_similar_id
)
from .ocr import gemini_ocr, extract_document_info_ai


class AutoRenamer:
    """자동 파일 이름 변경기"""
    
    def __init__(self, log_callback=None, merge_request_callback=None, rename_complete_callback=None):
        self.observer = None
        self.log_callback = log_callback
        self.merge_request_callback = merge_request_callback
        self.rename_complete_callback = rename_complete_callback
        self.export_declaration_callback = None  # 수출신고필증 마킹 콜백
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
            self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=6)

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
                self.observer.join(timeout=2)
                self.observer = None
            except:
                pass

        if self.executor:
            try:
                if sys.version_info >= (3, 9):
                    self.executor.shutdown(wait=False, cancel_futures=True)
                else:
                    self.executor.shutdown(wait=False)
            except:
                pass
            self.executor = None

        self.processing_files.clear()

    def _wait_for_file_ready(self, fp, timeout=10):
        """파일 쓰기가 완료될 때까지 대기. 완료되면 True, 빈 파일이면 False."""
        interval = 0.5
        elapsed = 0
        prev_size = -1

        while elapsed < timeout:
            if not os.path.exists(fp):
                return False
            try:
                size = os.path.getsize(fp)
            except OSError:
                return False

            if size > 0 and size == prev_size:
                return True  # 크기가 안정됨 → 쓰기 완료

            prev_size = size
            time.sleep(interval)
            elapsed += interval

        # 타임아웃 후에도 크기가 0이면 빈 파일
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

        if fp in self.processing_files:
            return
        self.processing_files.add(fp)

        try:
            if not is_initial:
                # 파일 쓰기 완료 대기 (다운로드/복사 중인 파일 보호)
                if not self._wait_for_file_ready(fp, timeout=10):
                    self.log(f" -> [건너뜀] 파일이 비어있거나 쓰기 미완료: {fn}")
                    return
            else:
                time.sleep(0.1)
                # 초기 스캔에서도 0KB 파일은 건너뜀
                if os.path.getsize(fp) == 0:
                    return

            c, i, d, s = parse_renamed_filename(fn)
            if i:
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

            # 수입자명이 전체 영문인지 판단 (한글이 포함되지 않음)
            # cn이 "Unknown"이면 무시하고 판별
            import re
            is_english_only = False
            if cn != "Unknown":
                if not re.search(r'[가-힣]', cn):
                    is_english_only = True

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
                
                if amt_val > 0:
                    nn = f"{base_name}_{amt_val}.pdf"
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
                    # 수출신고필증이면 마킹 콜백 호출
                    if "수출신고필증" in dt and self.export_declaration_callback:
                        self.export_declaration_callback(cn, iden, np)
                except Exception as e:
                    self.log(f" -> [실패] 이름 변경 오류: {e}")
        finally:
            if fp in self.processing_files:
                self.processing_files.remove(fp)

    def trigger_intelligent_merge(self, dr):
        files = [f for f in os.listdir(dr) if f.lower().endswith('.pdf')]
        groups = {}
        uncl = []
        for f in files:
            c, i, d, s = parse_renamed_filename(f)
            if i:
                fk = next((k for k in groups if is_similar_id(k, i)), i)
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
            cs = v.pop('company_set')
            v['company'] = ", ".join(sorted(list(cs))[:2]) if cs else "Unknown"
        if self.merge_request_callback:
            self.merge_request_callback({'directory': dr, 'groups': groups, 'unclassified': uncl})

    def _determine_merge_order(self, dr, sf, dm, mo, an=None, ti=None):
        m = []
        m.append({'label': '[명세서] 자금정산서', 'filename': sf if sf else ''})
        if mo == "수입":
            m.append({'label': '[신고필증] 수입신고필증', 'filename': dm.get(DOC_TYPE_IMPORT_DECLARATION, '')})
        elif mo == "수출":
            m.append({'label': '[신고필증] 수출신고필증', 'filename': dm.get(DOC_TYPE_EXPORT_DECLARATION, '')})
        else:
            m.append({'label': '[신고필증] 신고필증', 'filename': ''})
        if mo == "수입":
            td = dm.get(DOC_TYPE_PAYMENT_NOTICE)
            if not td:
                for t, n in dm.items():
                    if "납부영수증" in n:
                        td = n
                        break
            m.append({'label': '[세금] 납부고지서', 'filename': td if td else ''})
            m.append({'label': '[세금] 수입세금계산서', 'filename': dm.get(DOC_TYPE_IMPORT_TAX_INVOICE, '')})

        af = [x['filename'] for x in m if x['filename']]
        allp = []

        if ti:
            for f in [f for f in os.listdir(dr) if f.lower().endswith('.pdf')]:
                if f in af:
                    continue
                # 청구서(자금청구서)는 정산서에 병합하면 안 되는 별도 서류이므로 제외
                if "청구서" in f and "계산서" not in f:
                    continue
                match = RE_ID_PAREN.search(f)
                if match and normalize_id(match.group(1).strip()) == normalize_id(ti):
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

        fee_invoice_added = False  # 수수료계산서 파일 중복 병합 방지
        for item_data in expense_list:
            if not item_data:
                continue
            
            # 구버전 호환 (문자열)
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

            # 수수료계산서 항목이면 수수료계산서 파일에 매칭
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

            item_upper = item_name.upper().replace(" ", "")

            search_kws = [item_upper]
            for k, s in syns.items():
                if k in item_name:
                    search_kws.extend([x.upper().replace(" ", "") for x in s])

            found_any_for_this_item = False
            for pdf in allp:
                if pdf in af:
                    continue

                pdf_upper = pdf.upper().replace(" ", "")
                if any(kw in pdf_upper for kw in search_kws):
                    m.append({'label': f'비용: {item_name}', 'filename': pdf, 'item_amount': item_amount})
                    af.append(pdf)
                    found_any_for_this_item = True

            if not found_any_for_this_item:
                m.append({'label': f'비용: {item_name}', 'filename': '', 'item_amount': item_amount})
        # [NEW] 3차: 금액 기반 보정 매칭 (미분류 파일 캐시 조회)
        # 매칭 안 된 항목들 식별
        unmatched_items = [idx for idx, x in enumerate(m) if x['filename'] == '' and '비용: ' in x['label'] and '수수료계산서 포함' not in x['label']]
        
        if unmatched_items:
            # 남은 미분류 파일들 (기존 allp 목록 중)
            uncl_files = [f for f in allp if f not in af]
            
            # [NEW] 파일명에 괄호로 된 B/L번호가 없는 파일들도 금액 매칭 후보에 추가
            if os.path.exists(dr):
                for f in os.listdir(dr):
                    if not f.lower().endswith('.pdf'):
                        continue
                    if f in af or f in uncl_files:
                        continue
                        
                    # 청구서(자금청구서)는 정산서에 병합하면 안 되는 별도 서류이므로 제외
                    if "청구서" in f and "계산서" not in f:
                        continue
                        
                    c, i, d, s = parse_renamed_filename(f)
                    if not i:
                        uncl_files.append(f)

            uncl_amounts = {}
            
            for f in uncl_files:
                fp = os.path.join(dr, f)
                cached = gemini_ocr._get_cached_result(fp)
                if cached:
                    amt_val = cached.get('total_amount', 0)
                    try:
                        amt = int(str(amt_val).replace(',', '').replace('원', ''))
                    except ValueError:
                        amt = 0
                    if amt > 0:
                        uncl_amounts[f] = amt
            
            for idx in unmatched_items:
                item_amt = m[idx].get('item_amount', 0)
                try:
                    item_amt = int(str(item_amt).replace(',', '').replace('원', ''))
                except ValueError:
                    item_amt = 0
                    
                if item_amt > 0:
                    # 일치하는 파일 찾기
                    matching_files = [f for f, amt in uncl_amounts.items() if amt == item_amt and f not in af]
                    # 유일하게 1개만 매칭될 때만 자동 편입 (오매칭 방지)
                    if len(matching_files) == 1:
                        target_f = matching_files[0]
                        m[idx]['filename'] = target_f
                        m[idx]['matched_by_amount'] = True
                        af.append(target_f)
        
        for pdf in allp:
            if pdf not in af:
                m.append({'label': '[추가] 미분류 서류', 'filename': pdf})
                af.append(pdf)
        return m

    def execute_merge_task(self, dr, of, fo, export_docs_root=None, marked_files=None):
        """병합 수행 후 파일 정리 및 아카이빙"""
        if not fo:
            return

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
                # 2개 이상: PyMuPDF(fitz)로 병합 (PyPDF2는 폼/레이어 PDF에서 빈 페이지 버그)
                import fitz  # PyMuPDF
                final_of = f"{final_company}({target_id})정산서.pdf"
                output_path = os.path.join(dr, final_of)

                merged_doc = fitz.open()
                total_pages = 0
                for f in fo:
                    if f:
                        src_path = os.path.join(dr, f)
                        try:
                            src_doc = fitz.open(src_path)
                            page_count = len(src_doc)
                            if page_count == 0:
                                self.log(f" -> [경고] 빈 PDF 건너뜀: {f}")
                                src_doc.close()
                                continue
                            merged_doc.insert_pdf(src_doc)
                            total_pages += page_count
                            src_doc.close()
                        except Exception as e:
                            self.log(f" -> [경고] PDF 읽기 실패 ({f}): {e}")
                
                if total_pages == 0:
                    self.log(f" -> [오류] 병합할 페이지가 없습니다. 병합 중단.")
                    merged_doc.close()
                    return
                
                merged_doc.save(output_path)
                merged_doc.close()
                
                # 병합 결과 검증
                try:
                    verify_doc = fitz.open(output_path)
                    actual_pages = len(verify_doc)
                    verify_doc.close()
                    if actual_pages != total_pages:
                        self.log(f" -> [경고] 페이지 수 불일치! 예상: {total_pages}, 실제: {actual_pages}")
                    elif actual_pages == 0:
                        self.log(f" -> [오류] 병합 결과가 빈 파일입니다. 이동하지 않습니다.")
                        os.remove(output_path)
                        return
                    else:
                        self.log(f" -> [병합] {len(fo)}개 파일 → {total_pages}페이지 정산서")
                except Exception as e:
                    self.log(f" -> [경고] 병합 결과 검증 실패: {e}")

                shutil.move(output_path, os.path.join(archive_dir, final_of))

                # 1. 병합에 사용된 원본 파일 직접 정리 (미분류 파일 등 확실하게 처리)
                for f in fo:
                    if not f or f == final_of: continue
                    src_path = os.path.join(dr, f)
                    if not os.path.exists(src_path): continue
                    
                    _, _, d, _ = parse_renamed_filename(f)
                    # 파일명에 '신고필증'이 있으면 보존을 위해 이동, 그 외는 병합되었으므로 삭제
                    is_decl = ("신고필증" in d) if d else ("신고필증" in f)
                    
                    if is_decl:
                        try:
                            shutil.move(src_path, os.path.join(archive_dir, f))
                        except Exception:
                            pass
                    else:
                        try:
                            os.remove(src_path)
                        except Exception:
                            pass
                
                # 2. 같은 ID의 남은 PDF 추가 정리 (기존 안전망)
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
                search_roots = [d for d in [export_docs_root, dr] if d and os.path.exists(d)]
                
                for mf in marked_files:
                    src_path = mf.get('path', '')
                    file_name = mf.get('name', '')
                    base_name = os.path.splitext(file_name)[0] if file_name else ''
                    
                    self.log(f" -> [마킹 디버그] 파일: {file_name}, 경로: {src_path or '(없음)'}")
                    
                    # 경로가 있고 파일이 존재하면 바로 사용
                    if src_path and os.path.exists(src_path):
                        pass  # 경로 확정
                    else:
                        # 이미 archive_dir에 있는지 먼저 확인
                        if file_name:
                            check_in_archive = os.path.join(archive_dir, file_name)
                            if os.path.exists(check_in_archive):
                                self.log(f" -> [마킹 건너뜀] {file_name} (이미 아카이브에 존재)")
                                moved_marked.add(file_name)
                                marked_count += 1
                                continue
                        
                        if file_name:
                            # 경로가 없거나 파일이 없으면 검색
                            src_path = ''
                            for search_root in search_roots:
                                if src_path:
                                    break
                                try:
                                    for item in os.listdir(search_root):
                                        item_path = os.path.join(search_root, item)
                                        if os.path.isfile(item_path):
                                            if item == file_name or os.path.splitext(item)[0] == base_name:
                                                src_path = item_path
                                                break
                                        elif os.path.isdir(item_path):
                                            for sub in os.listdir(item_path):
                                                sub_path = os.path.join(item_path, sub)
                                                if os.path.isfile(sub_path):
                                                    if sub == file_name or os.path.splitext(sub)[0] == base_name:
                                                        src_path = sub_path
                                                        break
                                            if src_path:
                                                break
                                except Exception:
                                    continue
                            if src_path:
                                self.log(f" -> [마킹 디버그] 검색으로 찾음: {src_path}")
                            else:
                                self.log(f" -> [마킹 디버그] 검색 실패 (검색 경로: {search_roots})")
                    
                    if src_path and os.path.exists(src_path):
                        dst_path = os.path.join(archive_dir, os.path.basename(src_path))
                        if not os.path.exists(dst_path):
                            # 재시도 로직 (PermissionError 대비)
                            move_success = False
                            for attempt in range(3):
                                try:
                                    shutil.move(src_path, dst_path)
                                    self.log(f" -> [마킹 이동] {os.path.basename(src_path)}")
                                    moved_marked.add(os.path.basename(src_path))
                                    marked_count += 1
                                    move_success = True
                                    break
                                except PermissionError:
                                    if attempt < 2:
                                        self.log(f" -> [마킹 재시도] {os.path.basename(src_path)} (파일 잠금, {attempt+1}/3)")
                                        time.sleep(1.0)
                                    else:
                                        self.log(f" -> [마킹 이동 실패] {os.path.basename(src_path)}: 파일이 사용 중 (3회 재시도 실패)")
                                except Exception as e:
                                    self.log(f" -> [마킹 이동 실패] {os.path.basename(src_path)}: {e}")
                                    break
                        else:
                            self.log(f" -> [마킹 건너뜀] {os.path.basename(src_path)} (이미 존재)")
                            moved_marked.add(os.path.basename(src_path))
                    else:
                        self.log(f" -> [마킹 찾기 실패] {file_name} (경로: {src_path or '없음'}, 존재: {os.path.exists(src_path) if src_path else False})")
                if marked_count:
                    self.log(f" -> [마킹 이동 완료] {marked_count}개 파일")

            # 관련 파일/폴더 자동 수집 (merge 대상 폴더 - 이름변경 폴더에서만)
            # 마킹으로 이미 이동된 파일은 제외
            self._collect_related_items(dr, archive_dir, target_id, exclude_names=moved_marked)

            self.log(f" -> [완료] 아카이빙 완료: {folder_name}")
        except Exception as e:
            self.log(f"병합 실행 오류: {e}")
            print(f"병합 실행 오류: {e}")


    def _collect_related_items(self, dr, archive_dir, target_id, exclude_names=None):
        """송품장번호가 포함된 파일/폴더를 아카이브 폴더로 자동 수집"""
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
                        # 폴더 안의 파일들만 아카이브 폴더로 이동
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
