import re
import os

from .constants import EXPENSE_SYNONYMS


def validate_mapping_amounts(mapping, directory):
    """
    매핑 리스트의 각 비용 항목 금액과 매칭된 파일의 OCR 금액을 1:1 비교하고,
    전체 합산도 비교하는 2단계 검증.

    Args:
        mapping: _determine_merge_order 결과 리스트
                 [{'label': '비용: 운송료', 'filename': '...pdf', 'item_amount': 100000}, ...]
        directory: 파일이 있는 디렉토리 경로

    Returns:
        dict: {
            'item_details': [{'label': ..., 'item_amount': ..., 'file_amount': ..., 'matched': bool}, ...],
            'item_all_matched': bool,
            'sum_items': int,
            'sum_files': int,
            'sum_matched': bool,
        }
    """
    from .ocr import gemini_ocr

    result = {
        'item_details': [],
        'item_all_matched': True,
        'sum_items': 0,
        'sum_files': 0,
        'sum_matched': False,
    }

    _summed_files = set()          # 파일별 sum_files 중복 합산 방지
    _used_bi_indices = {}          # {filename: set(idx)} - billing_item 사용 추적

    # [FIX] "(추가)" 항목의 파일 금액을 미리 수집 (부모 항목의 금액 비교 시 합산)
    _additional_file_totals = {}   # {expense_name: total of additional files}
    for item in mapping:
        label = item.get('label', '')
        filename = item.get('filename', '')
        if '(추가)' in label and filename and '비용: ' in label:
            expense_name = label.split('비용: ')[-1].split(' (')[0]
            file_path = os.path.join(directory, filename)
            cached_add = gemini_ocr._get_cached_result(file_path)
            if cached_add:
                add_total = parse_amount(cached_add.get('total_amount', 0))
                _additional_file_totals[expense_name] = _additional_file_totals.get(expense_name, 0) + add_total

    for item in mapping:
        label = item.get('label', '')
        filename = item.get('filename', '')
        raw_item_amt = item.get('item_amount', 0)

        # 비용 항목만 검증 대상
        if '비용: ' not in label:
            continue

        # "포함" 또는 "(추가)" 항목은 파일 없이 부모에 포함된 항목
        is_fee_included = '포함' in label or '(추가)' in label

        item_amt = parse_amount(raw_item_amt)
        result['sum_items'] += item_amt

        if is_fee_included:
            # [FIX] "(추가)" 항목에 자체 파일이 있으면 sum_files에 포함
            if filename and filename not in _summed_files:
                file_path = os.path.join(directory, filename)
                cached_add = gemini_ocr._get_cached_result(file_path)
                if cached_add:
                    file_total = parse_amount(cached_add.get('total_amount', 0))
                    result['sum_files'] += file_total
                _summed_files.add(filename)
            continue

        if not filename:
            # 파일 없는 항목은 불일치
            result['item_details'].append({
                'label': label, 'item_amount': item_amt,
                'file_amount': 0, 'matched': False, 'no_file': True
            })
            result['item_all_matched'] = False
            continue

        # 파일의 OCR 캐시 금액 조회
        file_path = os.path.join(directory, filename)
        file_amt = 0
        cached = gemini_ocr._get_cached_result(file_path)
        if cached:
            billing_items = cached.get('billing_items', [])
            item_name_from_label = label.replace('비용: ', '').split(' (')[0]
            bi_matched = False

            if billing_items:
                search_kws = build_search_kws(item_name_from_label)
                used_indices = _used_bi_indices.setdefault(filename, set())

                # [Bug 4 수정] 1차: 정확 매칭 우선, 부분 매칭 폴백
                exact_bi = None
                partial_bi = None
                exact_idx = None
                partial_idx = None

                for idx, bi in enumerate(billing_items):
                    # [Bug 5 수정] 이미 사용된 billing_item 건너뛰기
                    if idx in used_indices:
                        continue
                    bi_name = bi.get('name', '').upper().replace(' ', '')
                    for kw in search_kws:
                        if kw == bi_name:  # 정확 매칭
                            exact_bi = bi
                            exact_idx = idx
                            break
                        elif partial_bi is None and (kw in bi_name or bi_name in kw):
                            partial_bi = bi
                            partial_idx = idx
                    if exact_bi:
                        break

                matched_bi = exact_bi or partial_bi
                matched_idx = exact_idx if exact_bi else partial_idx

                if matched_bi:
                    file_amt = parse_amount(matched_bi.get('amount', 0))
                    bi_matched = True
                    if matched_idx is not None:
                        used_indices.add(matched_idx)

                # 2차: 금액 일치 항목 탐색 (복수 항목, 키워드 매칭 실패 시)
                if not bi_matched and len(billing_items) > 1:
                    for idx, bi in enumerate(billing_items):
                        if idx in used_indices:
                            continue
                        bi_amt = parse_amount(bi.get('amount', 0))
                        if bi_amt > 0 and bi_amt == item_amt:
                            file_amt = bi_amt
                            bi_matched = True
                            used_indices.add(idx)
                            break

            # total_amount 폴백: 키워드 매칭 실패 시 total_amount 사용
            if not bi_matched:
                file_amt = parse_amount(cached.get('total_amount', 0))

        # [Bug 1 수정] sum_files: 파일당 1번만 합산 (파일 total_amount 사용)
        if filename not in _summed_files:
            if cached:
                file_total = parse_amount(cached.get('total_amount', 0))
                result['sum_files'] += file_total if file_total > 0 else file_amt
            else:
                result['sum_files'] += file_amt
            _summed_files.add(filename)

        # [FIX] 추가 파일 금액 합산 + 파일 총액 폴백으로 다중 비교
        비용항목명 = label.replace('비용: ', '').split(' (')[0]
        추가파일_합계 = _additional_file_totals.get(비용항목명, 0)
        파일_총액 = parse_amount(cached.get('total_amount', 0)) if cached else 0

        # 여러 조합으로 매칭 시도:
        # 1) 청구항목 금액 + 추가파일 금액
        # 2) 파일 총액 + 추가파일 금액
        # 3) 청구항목 금액 단독
        # 4) 파일 총액 단독
        비교용_파일금액 = file_amt + 추가파일_합계
        matched = False
        if item_amt > 0:
            for 후보금액 in [
                file_amt + 추가파일_합계,    # 청구항목 금액 + 추가파일
                파일_총액 + 추가파일_합계,    # 파일 총액 + 추가파일
                file_amt,                    # 청구항목 금액 단독
                파일_총액,                    # 파일 총액 단독
            ]:
                if 후보금액 > 0 and item_amt == 후보금액:
                    matched = True
                    비교용_파일금액 = 후보금액
                    break
        elif item_amt == 0 and file_amt == 0:
            matched = True  # 양쪽 다 0이면 검증 불필요

        if not matched:
            result['item_all_matched'] = False

        result['item_details'].append({
            'label': label, 'item_amount': item_amt,
            'file_amount': 비교용_파일금액, 'matched': matched,
            'filename': filename
        })

    # 합산 비교 (오차 10원 이내 허용)
    result['sum_matched'] = abs(result['sum_items'] - result['sum_files']) < 10

    return result


# [Bug 6+7 수정] 음수, 소수점, 숫자 타입 올바르게 처리
def parse_amount(raw):
    """금액을 정수로 변환 (음수, 소수점, 콤마 등 처리)"""
    try:
        if isinstance(raw, (int, float)):
            return round(raw)
        s = str(raw).strip()
        if not s:
            return 0
        # 음수 판정: '-' 접두사 또는 (금액) 형식
        negative = s.startswith('-') or (s.startswith('(') and s.endswith(')'))
        # 숫자와 소수점만 추출
        s_clean = re.sub(r'[^\d.]', '', s)
        if not s_clean:
            return 0
        result = round(float(s_clean))
        return -result if negative else result
    except (ValueError, TypeError):
        return 0


# [Bug 8 수정] 양방향 EXPENSE_SYNONYMS 검색
def build_search_kws(item_name):
    """항목명에서 검색 키워드 생성 (양방향 EXPENSE_SYNONYMS 확장)"""
    item_upper = item_name.upper().replace(" ", "")
    kws = {item_upper}

    for key, synonyms in EXPENSE_SYNONYMS.items():
        key_upper = key.upper().replace(" ", "")
        syn_uppers = [s.upper().replace(" ", "") for s in synonyms]

        # 정방향: key가 항목명에 포함
        if key_upper in item_upper or item_upper in key_upper:
            kws.add(key_upper)
            kws.update(syn_uppers)
            continue

        # 역방향: 동의어 중 하나가 항목명에 포함
        for su in syn_uppers:
            if su in item_upper or item_upper in su:
                kws.add(key_upper)
                kws.update(syn_uppers)
                break

    return list(kws)
