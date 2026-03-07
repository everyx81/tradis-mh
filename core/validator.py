import fitz
import re
import os

# 금액으로 간주될 수 있는 숫자 패턴 (세 자리마다 콤마 포함, 10,000 이상 위주의 큰 금액 패턴 고려 가능하나 일단 포괄적)
AMOUNT_PATTERN = re.compile(r'\b\d{1,3}(?:,\d{3})+\b')

def extract_amounts_from_pdf(pdf_path: str) -> list:
    """PDF 파일에서 콤마가 포함된 금액성 숫자들을 추출하여 내림차순 정렬된 리스트로 반환"""
    if not os.path.exists(pdf_path):
        return []
    
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        
        amounts = AMOUNT_PATTERN.findall(text)
        
        # 중복 제거 및 숫자 크기(정수 변환) 기준 내림차순 정렬
        unique_amounts = list(set(amounts))
        unique_amounts.sort(key=lambda x: int(x.replace(',', '')), reverse=True)
        
        return unique_amounts
    except Exception as e:
        print(f"[Amount Extraction Error] {os.path.basename(pdf_path)}: {e}")
        return []

def cross_check_with_totals(main_pdf_path: str, sub_pdf_paths: list, target_total: int = 0) -> dict:
    """
    메인 정산서에서 지정된 목표 금액(target_total)과 
    여러 서브 파일(sub_pdf_paths)들의 AI 파싱 총합계(total_amount)를 비교.
    
    Args:
        main_pdf_path: 자금정산서 경로
        sub_pdf_paths: 비교할 증빙 파일들 (영세율 + 과세 등 여러 장일 수 있음)
        target_total: 정산서에서 계산된 해당 명목의 청구 합계
        
    Returns:
        dict: 검증 성공 여부 및 상세 내역
    """
    from .ocr import gemini_ocr
    
    result = {
        "is_all_matched": False,
        "details": [],
        "target_total": target_total,
        "sum_of_subs": 0,
        "diff": 0
    }
    
    if target_total <= 0:
        # 목표 금액이 없으면 기존 방식(텍스트 교집합)으로 후퇴
        return cross_check_amounts(main_pdf_path, sub_pdf_paths)

    total_sub_sum = 0
    for sub_path in sub_pdf_paths:
        if not sub_path or not os.path.exists(sub_path):
            continue
            
        # AI 캐시에서 이 파일의 총금액(total_amount)을 가져옴
        cached = gemini_ocr._get_cached_result(sub_path)
        f_amt = 0
        if cached:
            raw_amt = cached.get('total_amount', 0)
            try:
                # 숫자 외 문자 제거 후 정수 변환
                f_amt = int(re.sub(r'[^0-9]', '', str(raw_amt)))
            except:
                f_amt = 0
        
        total_sub_sum += f_amt
        result["details"].append({
            "filename": os.path.basename(sub_path),
            "amount": f_amt,
            "is_matched": True # 개별 파일은 합산 대상이므로 일단 True
        })
    
    result["sum_of_subs"] = total_sub_sum
    result["diff"] = abs(target_total - total_sub_sum)
    
    # 오차 범위 (보통 0원이어야 하나 원단위 절사 등 고려시 10원 미만 허용 가능성 고려)
    if result["diff"] < 10:
        result["is_all_matched"] = True
    else:
        # 합계가 안 맞으면 기존 텍스트 교집합 방식도 한 번 더 시도 (보수적 검사)
        legacy_res = cross_check_amounts(main_pdf_path, sub_pdf_paths)
        if legacy_res["is_all_matched"]:
            result["is_all_matched"] = True
            
    return result

def cross_check_amounts(main_pdf_path: str, sub_pdf_paths: list) -> dict:
    """
    (Legacy) 메인 정산서의 금액 풀 내에 각 증빙 서류의 숫자가 포함되어 있는지 교차 대조.
    """
    result = {
        "is_all_matched": False,
        "details": []
    }
    
    if not main_pdf_path or not os.path.exists(main_pdf_path):
        return result
        
    main_amounts = extract_amounts_from_pdf(main_pdf_path)
    if not main_amounts:
        return result
        
    all_matched = True
    for sub_path in sub_pdf_paths:
        if not sub_path or not os.path.exists(sub_path):
            continue
            
        sub_amounts = extract_amounts_from_pdf(sub_path)
        matched_amounts = [amt for amt in sub_amounts if amt in main_amounts]
        
        # 유연한 확인 (공백 등 포함)
        if not matched_amounts:
            sub_text = ""
            try:
                sub_doc = fitz.open(sub_path)
                for page in sub_doc:
                    sub_text += page.get_text()
            except: pass
                
            for amt in main_amounts:
                pure_num = amt.replace(',', '')
                if len(pure_num) < 4: continue
                    
                flexible_pattern = r'[ ,\n]*'.join(list(pure_num))
                if re.search(flexible_pattern, sub_text):
                    matched_amounts.append(amt)
            matched_amounts = list(set(matched_amounts))
        
        is_matched = len(matched_amounts) > 0
        if not is_matched:
            all_matched = False
            
        result["details"].append({
            "filename": os.path.basename(sub_path),
            "is_matched": is_matched,
            "matched_amounts": matched_amounts
        })
        
    result["is_all_matched"] = all_matched and len(result["details"]) > 0
    return result
