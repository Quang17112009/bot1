import os
import telebot
from datetime import datetime, timedelta
import json
import math
import time
import requests
import threading
import re
from collections import deque # Để quản lý lịch sử dài hạn hiệu quả hơn

# --- Cấu hình Bot và API ---
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "7951251597:AAEXH5OtBRxU8irZSd1S4Gh-jicRmSIOK_s")
ADMIN_ID = 6915752059 # ID của bạn
API_URL = "https://apisunwin1.up.railway.app/api/taixiu"
USER_DATA_FILE = "user_data.json"
CTV_DATA_FILE = "ctv_data.json"

bot = telebot.TeleBot(TOKEN)

# --- Biến toàn cục để lưu trạng thái bot ---
last_processed_session = 0 # Phiên cuối cùng bot đã xử lý và đưa ra dự đoán
history_data = [] # Lưu trữ dữ liệu lịch sử từ API (3 xí ngầu) - [(d1, d2, d3, session_id), ...]
cau_history = []  # Lưu trữ lịch sử 'T' hoặc 'X' để check cầu (5 phiên) - [('T'/'X', session_id), ...]

# Lịch sử cầu dài hạn cho AI học hỏi (ví dụ: 50 phiên gần nhất)
long_term_cau_history = deque(maxlen=50) # Sử dụng deque để quản lý kích thước cố định
last_prediction_message_id = {} # Lưu ID tin nhắn dự đoán để cập nhật/xóa nếu cần

# --- Hàm hỗ trợ ---
def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def load_user_data():
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Lỗi đọc file {USER_DATA_FILE}. Tạo file rỗng.")
            return {}
    return {}

def save_user_data(data):
    with open(USER_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def load_ctv_data():
    if os.path.exists(CTV_DATA_FILE):
        try:
            with open(CTV_DATA_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Lỗi đọc file {CTV_DATA_FILE}. Tạo file rỗng.")
            return []
    return []

def save_ctv_data(data):
    with open(CTV_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

user_data = load_user_data()
ctv_list = load_ctv_data()

def is_admin(user_id):
    return user_id == ADMIN_ID

def is_ctv(user_id):
    return user_id in ctv_list or is_admin(user_id)

def check_subscription(user_id):
    user_id_str = str(user_id)
    if user_id_str not in user_data:
        return False, "Bạn chưa đăng ký sử dụng bot. Vui lòng dùng lệnh /nap để nạp tiền."
    
    expiry_date_str = user_data[user_id_str].get('expiry_date')
    if not expiry_date_str:
        return False, "Tài khoản của bạn không có ngày hết hạn. Vui lòng liên hệ Admin."

    expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d %H:%M:%S')
    if datetime.now() > expiry_date:
        return False, f"Tài khoản của bạn đã hết hạn vào ngày {expiry_date_str}. Vui lòng gia hạn để tiếp tục sử dụng."
    
    return True, "Bạn đang có quyền truy cập."

# --- Thuật toán dự đoán từ Code 1 ---
def du_doan_theo_xi_ngau(dice_list):
    if not dice_list:
        return "Đợi thêm dữ liệu"
    
    d1, d2, d3 = dice_list[-1][:3]
    total = d1 + d2 + d3

    result_list = []
    for d in [d1, d2, d3]:
        tmp = d + total
        while tmp < 1:
            tmp += 6
        while tmp > 6:
            tmp -= 6
            
        result_list.append("Tài" if tmp % 2 == 0 else "Xỉu")

    count_tai = result_list.count("Tài")
    count_xiu = result_list.count("Xỉu")

    if count_tai > count_xiu:
        return "Tài"
    elif count_xiu > count_tai:
        return "Xỉu"
    else:
        return "Tài" if (d1 + d2 + d3) % 2 == 0 else "Xỉu"


def is_cau_xau(cau_str):
    mau_cau_xau = [
        "TXXTX", "TXTXT", "XXTXX", "XTXTX", "TTXTX",
        "XTTXT", "TXXTT", "TXTTX", "XXTTX", "XTXTT",
        "TXTXX", "XXTXT", "TTXXT", "TXTTT",
        "XTXXT", "XTTTX", "TTXTT", "XTXTT", "TXXTX"
    ]
    mau_cau_xau_set = set(mau_cau_xau)
    return cau_str in mau_cau_xau_set

def is_cau_dep(cau_str):
    mau_cau_dep = [
        "TTTTT", "XXXXX", "TTTXX", "XXTTT", "TXTXX",
        "TTTXT", "XTTTX", "TXXXT", "XXTXX", "TXTTT",
        "XTTTT", "TTXTX", "TXXTX", "XTXTX",
        "XTTXT", "TXXXX"
    ]
    mau_cau_dep_set = set(mau_cau_dep)
    return cau_str in mau_cau_dep_set

# --- AI "học" dạng cầu và dự đoán ---
def ai_predict_from_cau_history(current_cau_pattern, full_cau_history_deque, min_pattern_length=3):
    """
    AI đơn giản học hỏi từ lịch sử cầu dài hạn.
    Tìm kiếm các mẫu cầu tương tự trong full_cau_history_deque
    và dự đoán kết quả tiếp theo dựa trên tần suất.
    
    Args:
        current_cau_pattern (str): Chuỗi cầu hiện tại (ví dụ: 'TTX' nếu đang ở phiên thứ 3 của chuỗi).
                                   Chúng ta sẽ dùng 3-5 ký tự cuối cùng của chuỗi cầu hiện tại.
        full_cau_history_deque (deque): Lịch sử cầu dài hạn (deque of chars 'T' or 'X').
        min_pattern_length (int): Độ dài tối thiểu của mẫu cầu để AI bắt đầu tìm kiếm.
    
    Returns:
        tuple: (prediction_char: 'T'/'X', confidence: float) hoặc (None, 0.0) nếu không đủ dữ liệu.
    """
    
    if len(full_cau_history_deque) < min_pattern_length + 1:
        return None, 0.0 # Không đủ lịch sử để học
    
    # Chuyển deque thành chuỗi để tìm kiếm
    full_history_str = "".join(list(full_cau_history_deque))
    
    # Lấy một đoạn mẫu từ cầu hiện tại để tìm kiếm
    # Tối đa 5 ký tự, tối thiểu min_pattern_length
    search_pattern = current_cau_pattern[-5:] 
    if len(search_pattern) < min_pattern_length:
        return None, 0.0 # Mẫu hiện tại quá ngắn để AI học

    # Đếm số lần xuất hiện của mẫu và kết quả tiếp theo
    next_results = {'T': 0, 'X': 0}
    
    # Lặp qua lịch sử dài hạn để tìm mẫu
    for i in range(len(full_history_str) - len(search_pattern)):
        if full_history_str[i:i + len(search_pattern)] == search_pattern:
            # Nếu tìm thấy mẫu, kiểm tra kết quả ngay sau đó
            if i + len(search_pattern) < len(full_history_str):
                next_char = full_history_str[i + len(search_pattern)]
                if next_char in next_results:
                    next_results[next_char] += 1
    
    total_matches = next_results['T'] + next_results['X']
    
    if total_matches == 0:
        return None, 0.0 # Không tìm thấy mẫu nào trong lịch sử
    
    if next_results['T'] > next_results['X']:
        return 'T', next_results['T'] / total_matches
    elif next_results['X'] > next_results['T']:
        return 'X', next_results['X'] / total_matches
    else:
        # Nếu bằng nhau, không có khuyến nghị mạnh mẽ
        return None, 0.0 # Hoặc bạn có thể chọn một giá trị mặc định

# --- Lấy dữ liệu từ API ---
def get_latest_data_from_api():
    try:
        response = requests.get(API_URL)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Lỗi khi lấy dữ liệu từ API: {e}")
        return None

# --- Logic chính của Bot (Vòng lặp dự đoán) ---
def prediction_loop():
    global last_processed_session, history_data, cau_history, long_term_cau_history, last_prediction_message_id

    while True:
        try:
            data = get_latest_data_from_api()
            if data:
                current_session = data.get("Phien")
                current_result_text = data.get("Ket_qua")
                xuc_xac_1 = data.get("Xuc_xac_1")
                xuc_xac_2 = data.get("Xuc_xac_2")
                xuc_xac_3 = data.get("Xuc_xac_3")
                total_dice = data.get("Tong")

                current_result_char = 'T' if current_result_text == 'Tài' else 'X'

                # Chỉ xử lý nếu có phiên mới và dữ liệu đầy đủ
                if current_session and current_session > last_processed_session and \
                   all(d is not None for d in [xuc_xac_1, xuc_xac_2, xuc_xac_3, current_session, current_result_text, total_dice]):
                    
                    print(f"\n--- Phát hiện phiên mới từ API: {current_session} ---")

                    # Kiểm tra tính liên tục của phiên
                    if history_data and history_data[-1][3] != current_session - 1:
                        print(f"Cảnh báo: Mất phiên. Cuối cùng trong lịch sử: {history_data[-1][3]}, phiên hiện tại từ API: {current_session}. Reset lịch sử để tránh sai lệch.")
                        history_data = []
                        cau_history = []
                        # Không reset long_term_cau_history vì nó lưu lịch sử dài hạn, mất phiên không ảnh hưởng nhiều
                    elif not history_data and last_processed_session != 0 and current_session != last_processed_session + 1:
                        print(f"Cảnh báo: Lịch sử rỗng và mất phiên. Phiên cuối xử lý: {last_processed_session}, phiên hiện tại từ API: {current_session}. Reset last_processed_session.")
                        last_processed_session = 0

                    # Cập nhật lịch sử xí ngầu (cho dự đoán xí ngầu)
                    history_data.append((xuc_xac_1, xuc_xac_2, xuc_xac_3, current_session))
                    if len(history_data) > 5:
                        history_data.pop(0)

                    # Cập nhật lịch sử cầu ngắn hạn (cho cầu xấu/đẹp 5 phiên)
                    cau_history.append((current_result_char, current_session))
                    if len(cau_history) > 5:
                        cau_history.pop(0)
                    
                    # Cập nhật lịch sử cầu dài hạn (cho AI học hỏi)
                    long_term_cau_history.append(current_result_char)

                    last_processed_session = current_session # Cập nhật phiên đã xử lý

                    current_cau_str_short = "".join([item[0] for item in cau_history])
                    current_cau_str_long = "".join(list(long_term_cau_history))
                    
                    print(f"Lịch sử xí ngầu ({len(history_data)}): {history_data}")
                    print(f"Lịch sử cầu ngắn ({len(cau_history)}): {current_cau_str_short}")
                    print(f"Lịch sử cầu dài ({len(long_term_cau_history)}): {current_cau_str_long}")
                    print(f"Kết quả phiên {current_session}: {current_result_text} (Tổng: {total_dice} - Xí ngầu: {xuc_xac_1}, {xuc_xac_2}, {xuc_xac_3})")

                    # Dự đoán và gửi thông báo nếu đủ điều kiện
                    prediction_message_parts = []
                    
                    # --- Phần dự đoán từ thuật toán xí ngầu + cầu xấu/đẹp 5 phiên ---
                    if len(history_data) >= 5 and len(cau_history) >= 5:
                        prediction_full = du_doan_theo_xi_ngau(history_data)
                        prediction_char = 'T' if prediction_full == 'Tài' else 'X'

                        reason_tx = "[AI 1] Phân tích xí ngầu."
                        if len(current_cau_str_short) == 5:
                            if is_cau_xau(current_cau_str_short):
                                prediction_char = 'X' if prediction_char == 'T' else 'T' # Đảo ngược
                                reason_tx = f"[AI 1] Cầu xấu (`{current_cau_str_short}`) -> Đảo ngược."
                            elif is_cau_dep(current_cau_str_short):
                                reason_tx = f"[AI 1] Cầu đẹp (`{current_cau_str_short}`) -> Giữ nguyên."
                            else:
                                reason_tx = f"[AI 1] Cầu (`{current_cau_str_short}`) không rõ ràng."
                        
                        final_prediction_text_tx = 'Tài' if prediction_char == 'T' else 'Xỉu'
                        
                        prediction_message_parts.append(
                            f"🤖 Dự đoán (Xí ngầu + Cầu 5p): **{final_prediction_text_tx}**\n"
                            f"➡️ _Lý do:_ {reason_tx}"
                        )
                    else:
                        prediction_message_parts.append(
                            f"⏳ _Cần thêm {5 - len(history_data)} phiên xí ngầu để dự đoán theo xí ngầu._"
                        )
                    
                    # --- Phần dự đoán từ AI mới (học hỏi dạng cầu dài hạn) ---
                    ai_prediction_char, ai_confidence = ai_predict_from_cau_history(
                        current_cau_str_long, long_term_cau_history, min_pattern_length=3
                    )
                    
                    if ai_prediction_char:
                        ai_prediction_text = 'Tài' if ai_prediction_char == 'T' else 'Xỉu'
                        prediction_message_parts.append(
                            f"🧠 Dự đoán (AI2 test): **{ai_prediction_text}** (Độ tin cậy: {ai_confidence:.0%})\n"
                            f"➡️ _Lý do:_ Dựa trên phân tích mẫu cầu dài hạn."
                        )
                    else:
                        prediction_message_parts.append(
                            f"🧠 _AI đang thập thêm dữ liệu._ (Lịch sử: {len(long_term_cau_history)} phiên)"
                        )

                    # --- Gửi tin nhắn tổng hợp ---
                    if prediction_message_parts: # Chỉ gửi nếu có ít nhất một phần dự đoán
                        message_text = (
                            f"🎮 Kết quả phiên hiện tại: **{current_result_text}** (Tổng: {total_dice})\n"
                            f"🔢 Phiên: `{current_session}` → `{current_session + 1}`\n"
                            f"{'\n'.join(prediction_message_parts)}\n\n"
                            f"⚠️ Hãy đặt cược sớm trước khi phiên kết thúc!"
                        )

                        for user_id_str, user_info in user_data.items():
                            user_id = int(user_id_str)
                            is_sub, sub_message = check_subscription(user_id)
                            if is_sub:
                                try:
                                    if user_id in last_prediction_message_id:
                                        try:
                                            bot.delete_message(user_id, last_prediction_message_id[user_id])
                                        except telebot.apihelper.ApiTelegramException as e:
                                            if "message to delete not found" not in str(e).lower():
                                                print(f"Lỗi khi xóa tin nhắn cũ cho user {user_id}: {e}")
                                        except Exception as e:
                                            print(f"Lỗi không xác định khi xóa tin nhắn cũ cho user {user_id}: {e}")
                                    
                                    sent_message = bot.send_message(user_id, message_text, parse_mode='Markdown')
                                    last_prediction_message_id[user_id] = sent_message.message_id
                                    print(f"Gửi dự đoán cho user {user_id}")
                                except telebot.apihelper.ApiTelegramException as e:
                                    if "bot was blocked by the user" in str(e).lower():
                                        print(f"Người dùng {user_id} đã chặn bot. Không gửi tin nhắn.")
                                    else:
                                        print(f"Lỗi API Telegram khi gửi dự đoán cho user {user_id}: {e}")
                                except Exception as e:
                                    print(f"Lỗi không xác định khi gửi dự đoán cho user {user_id}: {e}")
                                    
                    else:
                        print(f"Không có đủ dữ liệu để tạo tin nhắn dự đoán.")

                # else: # Log này có thể gây nhiễu nếu API cập nhật chậm
                #     print(f"Không có phiên mới hoặc dữ liệu không đầy đủ. Phiên hiện tại: {current_session}, Phiên cuối xử lý: {last_processed_session}")
            else:
                print("Không nhận được dữ liệu từ API hoặc dữ liệu trống.")

        except Exception as e:
            print(f"Lỗi trong vòng lặp dự đoán (prediction_loop): {e}")
        
        time.sleep(5) # Kiểm tra API mỗi 5 giây

# --- Xử lý lệnh Telegram (Không thay đổi các lệnh này) ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id_str = str(message.chat.id)
    if user_id_str not in user_data:
        user_data[user_id_str] = {
            'username': message.from_user.username or message.from_user.first_name,
            'expiry_date': None,
            'is_ctv': False
        }
        save_user_data(user_data)
        print(f"Người dùng mới đã thêm: {user_id_str} - {user_data[user_id_str]['username']}")
    
    bot.reply_to(message, 
        f"Chào mừng bạn đến với BOT DỰ ĐOÁN TÀI XỈU SUNWIN!\n"
        f"Gõ /help để xem danh sách các lệnh hỗ trợ."
    )

@bot.message_handler(commands=['help'])
def show_help(message):
    help_text = (
        "🤖 **DANH SÁCH LỆNH HỖ TRỢ** 🤖\n\n"
        "**Lệnh người dùng:**\n"
        "🔸 /start: Khởi động bot và thêm bạn vào hệ thống.\n"
        "🔸 /help: Hiển thị danh sách các lệnh.\n"
        "🔸 /support: Thông tin hỗ trợ Admin.\n"
        "🔸 /gia: Xem bảng giá dịch vụ.\n"
        "🔸 /gopy <nội dung>: Gửi góp ý/báo lỗi cho Admin.\n"
        "🔸 /nap: Hướng dẫn nạp tiền.\n"
        "🔸 /dudoan: Bắt đầu nhận dự đoán từ bot.\n\n"
    )
    
    if is_ctv(message.chat.id):
        help_text += (
            "**Lệnh Admin/CTV:**\n"
            "🔹 /full <id>: Xem thông tin người dùng (để trống ID để xem của bạn).\n"
            "🔹 /giahan <id> <số ngày>: Gia hạn tài khoản người dùng.\n\n"
        )
    
    if is_admin(message.chat.id):
        help_text += (
            "**Lệnh Admin Chính:**\n"
            "👑 /ctv <id>: Thêm người dùng làm CTV.\n"
            "👑 /xoactv <id>: Xóa người dùng khỏi CTV.\n"
            "👑 /tb <nội dung>: Gửi thông báo đến tất cả người dùng.\n"
        )
    
    bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['support'])
def show_support(message):
    bot.reply_to(message, 
        "Để được hỗ trợ, vui lòng liên hệ Admin:\n"
        "@heheviptool hoặc @Besttaixiu999"
    )

@bot.message_handler(commands=['gia'])
def show_price(message):
    price_text = (
        "📊 **BOT SUNWIN XIN THÔNG BÁO BẢNG GIÁ SUN BOT** 📊\n\n"
        "💸 **20k**: 1 Ngày\n"
        "💸 **50k**: 1 Tuần\n"
        "💸 **80k**: 2 Tuần\n"
        "💸 **130k**: 1 Tháng\n\n"
        "🤖 BOT SUN TỈ Lệ **85-92%**\n"
        "⏱️ ĐỌC 24/24\n\n"
        "Vui Lòng ib @heheviptool hoặc @Besttaixiu999 Để Gia Hạn"
    )
    bot.reply_to(message, price_text, parse_mode='Markdown')

@bot.message_handler(commands=['gopy'])
def send_feedback(message):
    feedback_text = telebot.util.extract_arguments(message.text)
    if not feedback_text:
        bot.reply_to(message, "Vui lòng nhập nội dung góp ý. Ví dụ: `/gopy Bot dự đoán rất chuẩn!`", parse_mode='Markdown')
        return
    
    admin_id = ADMIN_ID
    user_name = message.from_user.username or message.from_user.first_name
    bot.send_message(admin_id, 
                     f"📢 **GÓP Ý MỚI TỪ NGƯỜI DÙNG** 📢\n\n"
                     f"**ID:** `{message.chat.id}`\n"
                     f"**Tên:** @{user_name}\n\n"
                     f"**Nội dung:**\n`{feedback_text}`",
                     parse_mode='Markdown')
    bot.reply_to(message, "Cảm ơn bạn đã gửi góp ý! Admin đã nhận được.")

@bot.message_handler(commands=['nap'])
def show_deposit_info(message):
    user_id = message.chat.id
    deposit_text = (
        "⚜️ **NẠP TIỀN MUA LƯỢT** ⚜️\n\n"
        "Để mua lượt, vui lòng chuyển khoản đến:\n"
        "- Ngân hàng: **MB BANK**\n"
        "- Số tài khoản: **0939766383**\n"
        "- Tên chủ TK: **Nguyen Huynh Nhut Quang**\n\n"
        "**NỘI DUNG CHUYỂN KHOẢN (QUAN TRỌNG):**\n"
        "`mua luot {user_id}`\n\n"
        f"❗️ Nội dung bắt buộc của bạn là:\n"
        f"`mua luot {user_id}`\n\n"
        "(Vui lòng sao chép đúng nội dung trên để được cộng lượt tự động)\n"
        "Sau khi chuyển khoản, vui lòng chờ 1-2 phút. Nếu có sự cố, hãy dùng lệnh /support."
    )
    bot.reply_to(message, deposit_text, parse_mode='Markdown')

@bot.message_handler(commands=['dudoan'])
def start_prediction(message):
    user_id = message.chat.id
    is_sub, sub_message = check_subscription(user_id)
    
    if not is_sub:
        bot.reply_to(message, sub_message + "\nVui lòng liên hệ Admin @heheviptool hoặc @Besttaixiu999 để được hỗ trợ.", parse_mode='Markdown')
        return
    
    bot.reply_to(message, "✅ Bot Sunwin đã kích hoạt.")

# --- Lệnh Admin/CTV ---
@bot.message_handler(commands=['full'])
def get_user_info(message):
    if not is_ctv(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return
    
    args = telebot.util.extract_arguments(message.text).split()
    target_user_id_str = str(message.chat.id)
    if args and args[0].isdigit():
        target_user_id_str = args[0]
    
    if target_user_id_str not in user_data:
        bot.reply_to(message, f"Không tìm thấy thông tin cho người dùng ID `{target_user_id_str}`.")
        return

    user_info = user_data[target_user_id_str]
    expiry_date_str = user_info.get('expiry_date', 'Không có')
    username = user_info.get('username', 'Không rõ')
    is_ctv_status = "Có" if is_ctv(int(target_user_id_str)) else "Không"

    info_text = (
        f"**THÔNG TIN NGƯỜI DÙNG**\n"
        f"**ID:** `{target_user_id_str}`\n"
        f"**Tên:** @{username}\n"
        f"**Ngày hết hạn:** `{expiry_date_str}`\n"
        f"**Là CTV/Admin:** {is_ctv_status}"
    )
    bot.reply_to(message, info_text, parse_mode='Markdown')

@bot.message_handler(commands=['giahan'])
def extend_subscription(message):
    if not is_ctv(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return
    
    args = telebot.util.extract_arguments(message.text).split()
    if len(args) != 2 or not args[0].isdigit() or not args[1].isdigit():
        bot.reply_to(message, "Cú pháp sai. Ví dụ: `/giahan <id_nguoi_dung> <số_ngày>`", parse_mode='Markdown')
        return
    
    target_user_id_str = args[0]
    days_to_add = int(args[1])
    
    if target_user_id_str not in user_data:
        user_data[target_user_id_str] = {
            'username': "UnknownUser",
            'expiry_date': None,
            'is_ctv': False
        }
        bot.send_message(message.chat.id, f"Đã tạo tài khoản mới cho user ID `{target_user_id_str}`.")

    current_expiry_str = user_data[target_user_id_str].get('expiry_date')
    if current_expiry_str:
        current_expiry_date = datetime.strptime(current_expiry_str, '%Y-%m-%d %H:%M:%S')
        if datetime.now() > current_expiry_date:
            new_expiry_date = datetime.now() + timedelta(days=days_to_add)
        else:
            new_expiry_date = current_expiry_date + timedelta(days=days_to_add)
    else:
        new_expiry_date = datetime.now() + timedelta(days=days_to_add)
    
    user_data[target_user_id_str]['expiry_date'] = new_expiry_date.strftime('%Y-%m-%d %H:%M:%S')
    save_user_data(user_data)
    
    bot.reply_to(message, 
                 f"Đã gia hạn thành công cho user ID `{target_user_id_str}` thêm **{days_to_add} ngày**.\n"
                 f"Ngày hết hạn mới: `{user_data[target_user_id_str]['expiry_date']}`",
                 parse_mode='Markdown')
    
    try:
        bot.send_message(int(target_user_id_str), 
                         f"🎉 Tài khoản của bạn đã được gia hạn thêm **{days_to_add} ngày** bởi Admin/CTV!\n"
                         f"Ngày hết hạn mới của bạn là: `{user_data[target_user_id_str]['expiry_date']}`",
                         parse_mode='Markdown')
    except Exception as e:
        print(f"Không thể thông báo gia hạn cho user {target_user_id_str}: {e}")

# --- Lệnh Admin/CTV: Nhập lịch sử thủ công ---
@bot.message_handler(commands=['ls'])
def set_manual_history(message):
    global history_data, cau_history, long_term_cau_history, last_processed_session

    if not is_ctv(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    args = telebot.util.extract_arguments(message.text)
    
    if not args:
        bot.reply_to(message, "Cú pháp sai. Vui lòng nhập theo định dạng:\n"
                               "`/ls <5_kết_quả_T/X> <phiên_cuối_cùng> <x1> <x2> <x3>`\n"
                               "Ví dụ: `/ls TXTTT 2690853 3 5 2`", parse_mode='Markdown')
        return

    parts = args.split()
    if len(parts) != 5:
        bot.reply_to(message, "Lỗi cú pháp. Vui lòng đảm bảo bạn nhập đủ 5 phần: chuỗi 5 kết quả, số phiên, và 3 xí ngầu.", parse_mode='Markdown')
        return

    cau_str_input = parts[0].upper()
    if not (len(cau_str_input) == 5 and all(c in ['T', 'X'] for c in cau_str_input)):
        bot.reply_to(message, "Chuỗi 5 kết quả phải là 'T' hoặc 'X' và đủ 5 ký tự (VD: `TXTTT`).", parse_mode='Markdown')
        return
    
    try:
        session_id_input = int(parts[1])
        dice_inputs = [int(d) for d in parts[2:]]
        if not all(1 <= d <= 6 for d in dice_inputs):
            bot.reply_to(message, "Các giá trị xí ngầu phải từ 1 đến 6.", parse_mode='Markdown')
            return
    except ValueError:
        bot.reply_to(message, "Số phiên và các giá trị xí ngầu phải là số nguyên hợp lệ.", parse_mode='Markdown')
        return
    
    # Reset lịch sử hiện tại
    history_data = []
    cau_history = []
    long_term_cau_history.clear() # Xóa lịch sử dài hạn khi nhập thủ công

    # Cập nhật lịch sử cầu ngắn hạn từ chuỗi nhập vào
    current_session_for_cau = session_id_input - (len(cau_str_input) - 1)
    for char in cau_str_input:
        cau_history.append((char, current_session_for_cau))
        long_term_cau_history.append(char) # Thêm vào cả lịch sử dài hạn
        current_session_for_cau += 1

    # Cập nhật lịch sử xí ngầu
    for i in range(4):
        history_data.append((1, 1, 1, session_id_input - (4 - i)))
    history_data.append((dice_inputs[0], dice_inputs[1], dice_inputs[2], session_id_input))

    last_processed_session = session_id_input

    bot.reply_to(message, 
                 f"✅ Đã cập nhật lịch sử thủ công:\n"
                 f"- 5 cầu gần nhất: `{cau_str_input}`\n"
                 f"- Phiên cuối: `{session_id_input}` với xí ngầu: `{dice_inputs[0]} {dice_inputs[1]} {dice_inputs[2]}`\n"
                 f"Bot sẽ tiếp tục dự đoán từ phiên `{session_id_input + 1}`.", parse_mode='Markdown')
    
    print(f"Admin/CTV {message.chat.id} đã cập nhật lịch sử thủ công:")
    print(f"  cau_history (short): {cau_history}")
    print(f"  long_term_cau_history: {list(long_term_cau_history)}") # Chuyển deque sang list để in
    print(f"  history_data: {history_data}")
    print(f"  last_processed_session: {last_processed_session}")


# --- Lệnh Admin Chính (Không thay đổi các lệnh này) ---
@bot.message_handler(commands=['ctv'])
def add_ctv(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return
    
    args = telebot.util.extract_arguments(message.text).split()
    if len(args) != 1 or not args[0].isdigit():
        bot.reply_to(message, "Cú pháp sai. Ví dụ: `/ctv <id_nguoi_dung>`", parse_mode='Markdown')
        return
    
    target_user_id = int(args[0])
    if target_user_id not in ctv_list:
        ctv_list.append(target_user_id)
        save_ctv_data(ctv_list)
        bot.reply_to(message, f"Đã thêm user ID `{target_user_id}` làm Cộng Tác Viên.")
    else:
        bot.reply_to(message, f"User ID `{target_user_id}` đã là Cộng Tác Viên.")

@bot.message_handler(commands=['xoactv'])
def remove_ctv(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return
    
    args = telebot.util.extract_arguments(message.text).split()
    if len(args) != 1 or not args[0].isdigit():
        bot.reply_to(message, "Cú pháp sai. Ví dụ: `/xoactv <id_nguoi_dung>`", parse_mode='Markdown')
        return
    
    target_user_id = int(args[0])
    if target_user_id in ctv_list:
        ctv_list.remove(target_user_id)
        save_ctv_data(ctv_list)
        bot.reply_to(message, f"Đã xóa user ID `{target_user_id}` khỏi danh sách Cộng Tác Viên.")
    else:
        bot.reply_to(message, f"User ID `{target_user_id}` không phải là Cộng Tác Viên.")

@bot.message_handler(commands=['tb'])
def broadcast_message(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return
    
    broadcast_text = telebot.util.extract_arguments(message.text)
    if not broadcast_text:
        bot.reply_to(message, "Vui lòng nhập nội dung thông báo. Ví dụ: `/tb Bot sẽ bảo trì vào lúc 22:00 hôm nay!`", parse_mode='Markdown')
        return
    
    sent_count = 0
    fail_count = 0
    for user_id_str in user_data.keys():
        try:
            bot.send_message(int(user_id_str), f"📢 **THÔNG BÁO TỪ ADMIN** 📢\n\n{broadcast_text}", parse_mode='Markdown')
            sent_count += 1
            time.sleep(0.1)
        except Exception as e:
            print(f"Không thể gửi thông báo tới user {user_id_str}: {e}")
            fail_count += 1
            
    bot.reply_to(message, f"Đã gửi thông báo tới **{sent_count} người dùng** thành công. Thất bại: **{fail_count}**.", parse_mode='Markdown')

# --- Keep alive server cho Render ---
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_flask_server():
    app.run(host='0.0.0.0', port=os.environ.get('PORT', 5000))

# --- Hàm chính để khởi động bot và luồng dự đoán ---
if __name__ == "__main__":
    print("Bot đang khởi động...")

    flask_thread = Thread(target=run_flask_server)
    flask_thread.daemon = True
    flask_thread.start()
    print("Máy chủ Flask Keep Alive đã khởi động.")

    prediction_thread = Thread(target=prediction_loop)
    prediction_thread.daemon = True
    prediction_thread.start()
    print("Luồng dự đoán đã khởi động.")

    print("Bot Telegram đang lắng nghe tin nhắn...")
    bot.infinity_polling()

