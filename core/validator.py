import re
import os


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

    fee_file_amount_used = False  # 수수료계산서 파일 금액 중복 합산 방지

    for item in mapping:
        label = item.get('label', '')
        filename = item.get('filename', '')
        raw_item_amt = item.get('item_amount', 0)

        # 비용 항목만 검증 대상
        if '비용: ' not in label:
            continue

        # 수수료계산서 포함 항목은 파일이 없으므로 건너뜀 (합산에만 포함)
        is_fee_included = '수수료계산서 포함' in label or '(추가)' in label

        item_amt = _parse_amount(raw_item_amt)
        result['sum_items'] += item_amt

        if not filename or is_fee_included:
            if is_fee_included:
                # 수수료계산서 포함 항목은 검증 불필요 (같은 파일에 포함)
                continue
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
            file_amt = _parse_amount(cached.get('total_amount', 0))

        # 수수료계산서/추가 파일은 파일 금액을 1번만 합산
        if not fee_file_amount_used or '수수료' not in label:
            result['sum_files'] += file_amt
            if '수수료' in label:
                fee_file_amount_used = True

        matched = (item_amt == file_amt) if item_amt > 0 and file_amt > 0 else True
        if not matched:
            result['item_all_matched'] = False

        result['item_details'].append({
            'label': label, 'item_amount': item_amt,
            'file_amount': file_amt, 'matched': matched,
            'filename': filename
        })

    # 합산 비교 (오차 10원 이내 허용)
    result['sum_matched'] = abs(result['sum_items'] - result['sum_files']) < 10

    return result


def _parse_amount(raw):
    try:
        return int(re.sub(r'[^0-9]', '', str(raw)))
    except (ValueError, TypeError):
        return 0
