import logging
from collections import deque

logger = logging.getLogger(__name__)

# Các mẫu dự đoán sẽ được tải từ file dudoan.txt
# Sẽ lưu dưới dạng list of dict: [{'pattern': 'TTTTTTTTTTTTT', 'predict': 'T', 'type': 'Cầu bệt'}, ...]
PREDICTION_PATTERNS = []

def load_patterns():
    """Tải các mẫu từ file dudoan.txt."""
    global PREDICTION_PATTERNS
    PREDICTION_PATTERNS = [] # Reset để tránh trùng lặp nếu gọi nhiều lần
    try:
        with open('dudoan.txt', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line: # Bỏ qua dòng trống
                    continue
                
                parts = line.split('=>')
                if len(parts) == 2:
                    pattern_and_predict_part = parts[0].strip() # "TTTTTTTTTTTTT"
                    type_part = parts[1].strip() # "Dự đoán: T - Loại cầu: Cầu bệt (liên tiếp giống nhau)"

                    # Tách phần dự đoán khỏi phần mẫu
                    pattern_match = pattern_and_predict_part.split('Dự đoán:')
                    if len(pattern_match) == 2:
                        pattern_str = pattern_match[0].strip() # Lấy phần mẫu: TTTTTTTTTTTTT
                        predict_char = pattern_match[1].strip() # Lấy ký tự dự đoán: T

                        # Tách loại cầu
                        type_match = type_part.split('Loại cầu:')
                        type_name = type_match[1].strip() if len(type_match) == 2 else 'N/A'

                        PREDICTION_PATTERNS.append({
                            'pattern': pattern_str,
                            'predict': predict_char,
                            'type': type_name
                        })
                    else:
                        logger.warning(f"Invalid pattern format (missing 'Dự đoán:') in line: {line}")
                else:
                    logger.warning(f"Invalid line format (missing '=>') in dudoan.txt: {line}")
                    
        logger.info(f"Loaded {len(PREDICTION_PATTERNS)} patterns from dudoan.txt.")
    except FileNotFoundError:
        logger.warning("dudoan.txt not found. Pattern AI will not function.")
        PREDICTION_PATTERNS = []
    except Exception as e:
        logger.error(f"Error loading patterns from dudoan.txt: {e}")
        PREDICTION_PATTERNS = []

def ai1_trend_predictor(history: deque):
    """AI dựa trên xu hướng: dự đoán tiếp tục xu hướng gần nhất (3-5 phiên)."""
    if len(history) < 3: # Cần ít nhất 3 phiên để nhận biết xu hướng
        return None 
    
    last_3 = list(history)[-3:]
    # Nếu 3 phiên gần nhất đều là T, dự đoán T
    if all(x == 'T' for x in last_3):
        return {'predict': 'T', 'type': 'Cầu bệt T (ngắn)'}
    # Nếu 3 phiên gần nhất đều là X, dự đoán X
    if all(x == 'X' for x in last_3):
        return {'predict': 'X', 'type': 'Cầu bệt X (ngắn)'}
    
    # Nếu là chuỗi luân phiên (TXT, TXT), dự đoán ngược lại
    if len(history) >= 2:
        last_2 = list(history)[-2:]
        if last_2[0] != last_2[1]: # Ví dụ TX hoặc XT
            # Dự đoán tiếp tục luân phiên
            return {'predict': 'T' if last_2[1] == 'X' else 'X', 'type': 'Cầu luân phiên'}

    return None # Không có xu hướng rõ ràng

def ai2_defensive_predictor(history: deque, consecutive_errors: int):
    """
    AI phòng thủ:
    - Bình thường: Dự đoán ngược lại với phiên gần nhất (phương pháp Martingale ngược).
    - Nếu đã 'gãy' 2 lần liên tiếp (tức là 2 lần sai), thì dự đoán theo xu hướng (giống AI1 hoặc chiến lược khác)
      (Dựa vào lưu ý của bạn: "cứ 2 lần phân tích MD5 cho kết quả 'Gãy' thì sẽ có 1 lần cho kết quả khác")
      -> Ở đây tôi hiểu là nếu AI2 sai liên tiếp 2 lần, lần thứ 3 nó sẽ dùng chiến lược khác (ví dụ: xu hướng).
         Và sau lần dự đoán khác đó, nó sẽ quay lại chiến lược ban đầu (dự đoán ngược).
    """
    if not history:
        return None

    last_result = history[-1]

    # Kiểm tra quy tắc "cứ 2 lần gãy thì 1 lần khác"
    # consecutive_errors = 0: chưa sai
    # consecutive_errors = 1: sai 1 lần
    # consecutive_errors = 2: sai 2 lần -> lần này cần dự đoán khác
    if consecutive_errors == 2:
        # Nếu đã sai 2 lần liên tiếp, dự đoán theo xu hướng (dùng lại logic của AI1)
        logger.debug("AI2 in defensive mode (after 2 consecutive errors). Using trend predictor.")
        trend_pred = ai1_trend_predictor(history)
        if trend_pred:
            return {'predict': trend_pred['predict'], 'type': f"Phòng thủ ({trend_pred['type']})"}
        else:
            # Nếu AI1 cũng không có xu hướng, quay lại dự đoán ngược
            return {'predict': 'T' if last_result == 'X' else 'X', 'type': 'Phòng thủ (Ngược)'}
    else:
        # Bình thường: dự đoán ngược lại
        return {'predict': 'T' if last_result == 'X' else 'X', 'type': 'Phòng thủ (Ngược)'}


def ai3_pattern_predictor(history: deque):
    """AI dựa trên mẫu: tìm kiếm các mẫu đã biết trong lịch sử và trả về dự đoán cùng loại cầu."""
    if not PREDICTION_PATTERNS or not history:
        return None

    current_history_str = "".join(list(history)) # Chuyển deque thành chuỗi

    # Ưu tiên các mẫu dài hơn để tìm kiếm mẫu chính xác hơn
    sorted_patterns = sorted(PREDICTION_PATTERNS, key=lambda x: len(x['pattern']), reverse=True)

    for pattern_data in sorted_patterns:
        pattern_str = pattern_data['pattern']
        
        # Để khớp với các mẫu "TTTXXX" mà dự đoán dựa trên toàn bộ mẫu đó
        # (ví dụ TTT => T thì pattern_str sẽ là TTT và predict là T)
        # Chúng ta cần kiểm tra nếu history kết thúc bằng pattern_str (trước khi dự đoán)
        if current_history_str.endswith(pattern_str):
            logger.debug(f"AI3 found exact pattern '{pattern_str}' in history. Predicting '{pattern_data['predict']}'")
            return {'predict': pattern_data['predict'], 'type': pattern_data['type']}
        
    return None # Không tìm thấy mẫu nào khớp


def ensemble_predict(history: deque, ai_scores: dict, ai2_consecutive_errors: int):
    """
    Kết hợp dự đoán từ các AI khác nhau dựa trên điểm số/trọng số.
    """
    predictions_with_types = {} # {ai_name: {'predict': 'T'/'X', 'type': 'Cầu bệt'}}
    
    # AI1: Xu hướng
    ai1_result = ai1_trend_predictor(history)
    if ai1_result:
        predictions_with_types['ai1_trend'] = ai1_result
    
    # AI2: Phòng thủ
    ai2_result = ai2_defensive_predictor(history, ai2_consecutive_errors)
    if ai2_result:
        predictions_with_types['ai2_defensive'] = ai2_result

    # AI3: Mẫu
    ai3_result = ai3_pattern_predictor(history)
    if ai3_result:
        predictions_with_types['ai3_pattern'] = ai3_result

    # Tính toán dự đoán cuối cùng
    weighted_votes = {'T': 0.0, 'X': 0.0}
    ai_individual_predictions_char = {} # Chỉ lưu ký tự dự đoán cho phần cập nhật điểm

    for ai_name, pred_data in predictions_with_types.items():
        score = ai_scores.get(ai_name, 100.0) # Lấy điểm từ DB, mặc định 100
        weighted_votes[pred_data['predict']] += score
        ai_individual_predictions_char[ai_name] = pred_data['predict'] # Lưu ký tự dự đoán

    final_prediction_char = 'T' if weighted_votes['T'] >= weighted_votes['X'] else 'X' # Chọn T nếu hòa hoặc T cao hơn
    
    # Chọn loại cầu ưu tiên từ AI có trọng số cao nhất hoặc AI có dự đoán trùng với final_prediction_char
    final_type = "Không rõ"
    max_score_for_final_pred = -1
    for ai_name, pred_data in predictions_with_types.items():
        if pred_data['predict'] == final_prediction_char:
            score = ai_scores.get(ai_name, 100.0)
            if score > max_score_for_final_pred:
                max_score_for_final_pred = score
                final_type = pred_data['type']


    final_prediction_display = f"{final_prediction_char} ({final_type})"
    if final_prediction_char == 'T':
        final_prediction_display = f"Tài ({final_type})"
    else:
        final_prediction_display = f"Xỉu ({final_type})"

    logger.info(f"Ensemble raw predictions: {predictions_with_types}. Weighted votes: {weighted_votes}. Final char: {final_prediction_char}, Type: {final_type}")
    
    return final_prediction_display, ai_individual_predictions_char


def update_ai_scores_and_states(
    actual_result_char: str, 
    ai_individual_predictions: dict, # Dictionary chỉ chứa ký tự dự đoán của từng AI
    ai_scores: dict, 
    ai2_consecutive_errors: int,
    update_ai_score_func, 
    update_ai_state_func 
):
    """
    Cập nhật điểm số của các AI và trạng thái của AI2 dựa trên kết quả thực tế.
    """
    for ai_name, predicted_char in ai_individual_predictions.items():
        current_score = ai_scores.get(ai_name, 100.0)
        
        if predicted_char == actual_result_char:
            # AI dự đoán đúng, tăng điểm
            new_score = current_score * 1.05 # Tăng 5%
            logger.info(f"AI {ai_name} predicted correctly. Score: {current_score:.0f} -> {new_score:.0f}")
            if ai_name == 'ai2_defensive': # Reset lỗi liên tiếp nếu AI2 đúng
                update_ai_state_func('ai2_defensive', 0)
        else:
            # AI dự đoán sai, giảm điểm
            new_score = current_score * 0.95 # Giảm 5%
            logger.info(f"AI {ai_name} predicted incorrectly. Score: {current_score:.0f} -> {new_score:.0f}")
            if ai_name == 'ai2_defensive': # Tăng lỗi liên tiếp nếu AI2 sai
                new_errors = ai2_consecutive_errors + 1
                # Quy tắc bạn đã cho: "cứ 2 lần phân tích MD5 cho kết quả 'Gãy' thì sẽ có 1 lần cho kết quả khác."
                # => Điều này ngụ ý rằng sau 2 lần sai, lần thứ 3 AI2 sẽ có một "chiến lược khác".
                # Nếu sai lần 3,4,5... thì consecutive_errors vẫn cứ tăng.
                # Tôi sẽ giữ nguyên logic: nếu đã sai 2 lần thì cứ để consecutive_errors = 2 cho đến khi đúng.
                # Hoặc bạn muốn reset về 0 sau khi nó sai lần thứ 2 và chuyển sang chiến lược khác?
                # Hiện tại, tôi sẽ không reset nó về 0 ở đây. Logic reset nằm trong AI2 predictor khi nó chọn chiến lược khác.
                update_ai_state_func('ai2_defensive', new_errors)
        
        # Đảm bảo điểm không quá thấp hoặc quá cao
        new_score = max(50.0, min(200.0, new_score)) # Giới hạn điểm từ 50 đến 200
        update_ai_score_func(ai_name, new_score)

