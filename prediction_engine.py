import logging
from collections import deque
import json # Được giữ lại phòng trường hợp cần dùng cho các cấu hình AI phức tạp hơn

logger = logging.getLogger(__name__)

# --- Cấu hình cho AI ---
# Độ dài lịch sử mà các AI cần để phân tích. Phải khớp với database.py.
HISTORY_LENGTH = 13 
# Định nghĩa khoảng điểm tối thiểu/tối đa cho AI để tránh điểm quá thấp/cao
MIN_AI_SCORE = 50.0
MAX_AI_SCORE = 150.0

# Dữ liệu mẫu sẽ được tải từ dudoan.txt
# key: chuỗi 13 ký tự ('T' hoặc 'X'), value: {'prediction': 'T'/'X', 'type': 'Mô tả cầu'}
pattern_data = {} 

def load_patterns(filepath="dudoan.txt"):
    """Tải các mẫu dự đoán từ file dudoan.txt vào bộ nhớ."""
    global pattern_data
    loaded_count = 0
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue # Bỏ qua dòng trống hoặc comment
                
                parts = line.split('=> Dự đoán: ')
                if len(parts) == 2:
                    pattern_str = parts[0].strip() # Chuỗi 13 ký tự T/X
                    prediction_info_str = parts[1].strip()

                    pred_parts = prediction_info_str.split(' - Loại cầu: ')
                    if len(pred_parts) == 2:
                        prediction_char = pred_parts[0].replace('Tài', 'T').replace('Xỉu', 'X').strip()[0] # Chuẩn hóa thành 'T' hoặc 'X'
                        pattern_type = pred_parts[1].strip()
                        
                        if len(pattern_str) == HISTORY_LENGTH and prediction_char in ['T', 'X']:
                            pattern_data[pattern_str] = {'prediction': prediction_char, 'type': pattern_type}
                            loaded_count += 1
                        else:
                            logger.warning(f"Mẫu '{pattern_str}' không đúng độ dài {HISTORY_LENGTH} hoặc dự đoán không hợp lệ. Bỏ qua.")
                    else:
                        logger.warning(f"Dòng '{line}' không đúng định dạng 'Dự đoán: KẾT_QUẢ - Loại cầu: MÔ_TẢ'. Bỏ qua.")
                else:
                    logger.warning(f"Dòng '{line}' không đúng định dạng 'CHUỖI => Dự đoán: ...'. Bỏ qua.")
        logger.info(f"Loaded {loaded_count} patterns from {filepath}.")
        if loaded_count == 0 and HISTORY_LENGTH == 13: 
             logger.warning("Không tìm thấy mẫu nào. Đảm bảo dudoan.txt tồn tại và định dạng đúng (13 ký tự T/X).")
    except FileNotFoundError:
        logger.error(f"Lỗi: File dudoan.txt không tìm thấy tại {filepath}. AI3 sẽ không hoạt động.")
    except Exception as e:
        logger.error(f"Lỗi khi tải mẫu từ {filepath}: {e}")

# --- Các AI dự đoán ---

# AI 1: Phân tích Xu hướng & Tỷ lệ
def predict_ai1_trend(history: deque):
    """
    Dự đoán dựa trên các xu hướng cơ bản: chuỗi bệt, cầu 1-1, và tỷ lệ chiếm ưu thế.
    Trả về 'T' hoặc 'X', hoặc None nếu không có dự đoán rõ ràng.
    """
    if len(history) < 5: # Cần ít nhất 5 phiên để phân tích xu hướng có ý nghĩa
        return None 

    last_results = list(history) # Chuyển đổi deque thành list để dễ thao tác
    tai_count = last_results.count("T")
    xiu_count = last_results.count("X")

    # Ưu tiên chuỗi bệt (3 hoặc hơn)
    if len(last_results) >= 3 and last_results[-1] == last_results[-2] == last_results[-3]:
        return last_results[-1] # Dự đoán tiếp tục chuỗi

    # Ưu tiên mẫu 1-1 (tắc) nếu có đủ 4 phiên cuối
    if len(last_results) >= 4 and \
       last_results[-1] != last_results[-2] and \
       last_results[-2] != last_results[-3] and \
       last_results[-3] != last_results[-4]:
        # Nếu là A-B-A-B (ví dụ T-X-T-X), thì dự đoán A (T)
        return last_results[-3] 
    
    # Dự đoán theo xu hướng chiếm ưu thế trong tổng thể lịch sử ngắn
    if tai_count > xiu_count and (tai_count / len(last_results)) >= 0.6: # Tài chiếm > 60%
        return "T"
    elif xiu_count > tai_count and (xiu_count / len(last_results)) >= 0.6: # Xỉu chiếm > 60%
        return "X"
    
    return None # Không có dự đoán rõ ràng

# AI 2: Nhận diện Cầu xấu / Dự đoán Phòng thủ
def predict_ai2_defensive(history: deque, consecutive_errors: int):
    """
    AI này theo dõi số lần sai liên tiếp của chính nó.
    Nếu sai 3 lần trở lên, nó sẽ chuyển sang chế độ "dự đoán phòng thủ" (dự đoán ngược lại kết quả cuối cùng).
    """
    if len(history) == 0:
        return None

    if consecutive_errors >= 3:
        # Nếu đang trong chuỗi sai, dự đoán phòng thủ: ngược lại với kết quả cuối cùng
        last_actual_result = history[-1]
        defensive_prediction = "X" if last_actual_result == "T" else "T"
        logger.info(f"AI2 (Defensive Mode): {consecutive_errors} consecutive errors. Predicting {defensive_prediction} (opposite of last result).")
        return defensive_prediction
    
    # Khi không trong chế độ phòng thủ, AI2 sẽ dự đoán theo logic của AI1
    # hoặc bạn có thể phát triển một logic riêng khác cho nó ở trạng thái bình thường.
    return predict_ai1_trend(history) 

# AI 3: Dựa trên Mẫu hình dudoan.txt
def predict_ai3_pattern(history: deque):
    """
    Tìm kiếm chuỗi 13 phiên lịch sử trong các mẫu từ dudoan.txt.
    Trả về dự đoán từ mẫu, hoặc None nếu không tìm thấy mẫu.
    """
    if len(history) < HISTORY_LENGTH: # Cần đủ 13 phiên để tạo chuỗi so sánh
        return None
    
    current_pattern_string = "".join(list(history)) # Chuyển deque thành chuỗi "TTX..."
    
    if current_pattern_string in pattern_data:
        prediction_info = pattern_data[current_pattern_string]
        return prediction_info['prediction']
    
    return None # Không tìm thấy mẫu khớp

# --- Cơ chế Tổng hợp & Cập nhật điểm ---

def ensemble_predict(history: deque, ai_scores: dict, ai2_consecutive_errors: int):
    """
    Tổng hợp dự đoán từ 3 AI dựa trên điểm số hiện tại của chúng.
    Trả về dự đoán cuối cùng ('Tài'/'Xỉu') và dự đoán của từng AI.
    """
    # Lấy dự đoán từ mỗi AI
    pred1_char = predict_ai1_trend(history)
    pred2_char = predict_ai2_defensive(history, ai2_consecutive_errors)
    pred3_char = predict_ai3_pattern(history)

    # Dictionary để lưu trữ tổng điểm của Tài và Xỉu
    weighted_votes = {"T": 0.0, "X": 0.0}
    ai_predictions = {} # Lưu lại dự đoán của từng AI để cập nhật điểm sau

    # AI 1
    if pred1_char:
        score1 = ai_scores.get('ai1_trend', 100.0)
        weighted_votes[pred1_char] += score1
        ai_predictions['ai1_trend'] = pred1_char
        logger.debug(f"AI1: {pred1_char} (Score: {score1})")
    else:
        ai_predictions['ai1_trend'] = None

    # AI 2
    if pred2_char:
        score2 = ai_scores.get('ai2_defensive', 100.0)
        weighted_votes[pred2_char] += score2
        ai_predictions['ai2_defensive'] = pred2_char
        logger.debug(f"AI2: {pred2_char} (Score: {score2})")
    else:
        ai_predictions['ai2_defensive'] = None

    # AI 3
    if pred3_char:
        score3 = ai_scores.get('ai3_pattern', 100.0)
        weighted_votes[pred3_char] += score3
        ai_predictions['ai3_pattern'] = pred3_char
        logger.debug(f"AI3: {pred3_char} (Score: {score3})")
    else:
        ai_predictions['ai3_pattern'] = None

    logger.debug(f"Weighted votes: Tài={weighted_votes['T']:.2f}, Xỉu={weighted_votes['X']:.2f}")

    # Quyết định dự đoán cuối cùng
    final_prediction_char = None
    if weighted_votes["T"] > weighted_votes["X"]:
        final_prediction_char = "T"
    elif weighted_votes["X"] > weighted_votes["T"]:
        final_prediction_char = "X"
    else:
        # Nếu hòa điểm, ưu tiên AI1 nếu nó có dự đoán, hoặc AI2, AI3
        if pred1_char: final_prediction_char = pred1_char
        elif pred2_char: final_prediction_char = pred2_char
        elif pred3_char: final_prediction_char = pred3_char
        # Nếu tất cả đều không dự đoán hoặc hòa và không có ưu tiên, mặc định là Tài
        else: final_prediction_char = "T" # Hoặc None để báo "không rõ ràng"

    # Chuyển đổi ký tự dự đoán thành 'Tài' hoặc 'Xỉu' để hiển thị
    final_prediction_display = "Tài" if final_prediction_char == "T" else "Xỉu" if final_prediction_char == "X" else "Không rõ ràng"
        
    return final_prediction_display, ai_predictions

def update_ai_scores_and_states(
    actual_result_char: str, 
    ai_predictions: dict, 
    ai_scores: dict, 
    ai2_current_errors: int, 
    db_update_score_func, 
    db_update_state_func
):
    """
    Cập nhật điểm của các AI và trạng thái của AI2 dựa trên kết quả thực tế.
    """
    new_ai2_errors = ai2_current_errors

    for ai_name, pred_char in ai_predictions.items():
        if pred_char is None:
            continue # AI không đưa ra dự đoán, không cập nhật điểm

        current_score = ai_scores.get(ai_name, 100.0) # Lấy điểm hiện tại từ dictionary truyền vào
        
        if pred_char == actual_result_char:
            new_score = min(MAX_AI_SCORE, current_score + 1.0) # Tăng điểm khi đúng
            if ai_name == 'ai2_defensive':
                new_ai2_errors = 0 # Reset lỗi liên tiếp của AI2 nếu đúng
            logger.debug(f"AI {ai_name} predicted correctly. New score: {new_score:.2f}. AI2 errors: {new_ai2_errors}")
        else:
            new_score = max(MIN_AI_SCORE, current_score - 2.0) # Giảm điểm nhiều hơn khi sai
            if ai_name == 'ai2_defensive':
                new_ai2_errors += 1 # Tăng lỗi liên tiếp của AI2 nếu sai
                logger.debug(f"AI {ai_name} predicted incorrectly. New score: {new_score:.2f}. AI2 errors: {new_ai2_errors}")
            else:
                logger.debug(f"AI {ai_name} predicted incorrectly. New score: {new_score:.2f}.")
        
        db_update_score_func(ai_name, new_score) # Cập nhật điểm AI vào DB
    
    db_update_state_func('ai2_defensive', new_ai2_errors) # Cập nhật lỗi liên tiếp của AI2 vào DB


# Tải các mẫu dự đoán khi module này được import lần đầu
load_patterns()
