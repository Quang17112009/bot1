import os
import asyncio
import aiohttp
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode # Import để sử dụng HTML/Markdown parsing
import json
import logging
from datetime import date, datetime, timedelta

# Import các module tùy chỉnh
from keep_alive import keep_alive
import database # Để tương tác với SQLite
import prediction_engine # Để sử dụng các AI dự đoán

# Thiết lập logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO # Đặt INFO để xem log quan trọng, DEBUG để xem tất cả
)
logger = logging.getLogger(__name__)

# --- Cấu hình Bot (Hardcode - CẢNH BÁO: RỦI RO BẢO MẬT CAO!) ---
# Đã gắn token bot Telegram của bạn vào đây:
TELEGRAM_TOKEN = "7956593401:AAH-7zW1Hyr8Ak6GmEHiKcushkap2FWoxsw" 

# Đã gắn ID Telegram admin của bạn vào đây:
ADMIN_ID = 6915752059 # Đây là số nguyên, không có dấu nháy kép

# --------------------------------------------------------------------------------
# CẢNH BÁO BẢO MẬT: Hardcode thông tin nhạy cảm (token, ID) vào code là 
# KHÔNG ĐƯỢC KHUYẾN NGHỊ. Nếu code của bạn bị lộ, các thông tin này cũng sẽ bị lộ.
# Phương pháp an toàn hơn là sử dụng Biến môi trường trên Render.
# --------------------------------------------------------------------------------

# Các kiểm tra đảm bảo giá trị hợp lệ sau khi hardcode
if not isinstance(TELEGRAM_TOKEN, str) or not TELEGRAM_TOKEN:
    logger.critical("TELEGRAM_TOKEN không hợp lệ hoặc bị thiếu. Bot không thể khởi động.")
    exit(1)

if not isinstance(ADMIN_ID, int) or ADMIN_ID <= 0:
    logger.critical("ADMIN_ID không hợp lệ hoặc bị thiếu. Bot không thể khởi động.")
    exit(1)


HTTP_API_URL = "https://apisunwin1.up.railway.app/api/taixiu"

# Danh sách user_id của các cộng tác viên (CTV)
# Để đơn giản, vẫn lưu trong bộ nhớ. Dùng DB nếu muốn bền vững.
CTV_IDS = set() 

# Dictionary để lưu trữ thông tin người dùng (ngày hết hạn, xu, subscribed). 
# Để đơn giản, vẫn lưu trong bộ nhớ. Dùng DB nếu muốn bền vững.
# Format: {user_id: {"expiration_date": "YYYY-MM-DD", "xu": 0, "subscribed": False}}
user_data = {} 

# Biến toàn cục để giữ instance của Application
application_instance = None


# --- Hàm kiểm tra quyền ---
def is_admin(user_id):
    return user_id == ADMIN_ID


def is_ctv_or_admin(user_id):
    return user_id == ADMIN_ID or user_id in CTV_IDS


# --- Hàm lấy và xử lý dữ liệu Tài Xỉu chung ---
async def get_and_process_taixiu_data():
    """
    Fetches the latest Tai Xiu data, processes it, updates DB, and returns
    the formatted prediction message if new data is found.
    Returns (message, actual_result_char) or (None, None) if no new data or error.
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(HTTP_API_URL) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # FIX LỖI: data.get('Ket_qua') đã là chuỗi Unicode, không cần encode/decode
                    ket_qua_decoded = data.get('Ket_qua', 'N/A') 
                    
                    phien_number = data.get('Phien', 0) 
                    tong = data.get('Tong', 0)
                    xuc_xac_1 = data.get('Xuc_xac_1', 0)
                    xuc_xac_2 = data.get('Xuc_xac_2', 0)
                    xuc_xac_3 = data.get('Xuc_xac_3', 0)
                    
                    actual_result_char = None
                    if ket_qua_decoded == 'Tài':
                        actual_result_char = 'T'
                    elif ket_qua_decoded == 'Xỉu':
                        actual_result_char = 'X'

                    # Lấy phiên cuối cùng đã xử lý từ DB
                    last_processed_phien = int(database.get_app_setting('last_processed_phien') or 0)

                    # Chỉ xử lý nếu có phiên mới và kết quả hợp lệ
                    if phien_number > last_processed_phien and actual_result_char:
                        logger.info(f"New phien detected: {phien_number}. Last processed: {last_processed_phien}")
                        
                        # 1. Lưu kết quả mới nhất vào DB
                        database.add_result(phien_number, ket_qua_decoded, actual_result_char, tong, xuc_xac_1, xuc_xac_2, xuc_xac_3)
                        
                        # 2. Lấy lịch sử 13 phiên gần nhất từ DB
                        history = database.get_latest_history()
                        
                        # 3. Lấy điểm hiện tại của các AI
                        ai_scores = database.get_ai_scores()
                        
                        # 4. Lấy trạng thái của AI2 (số lỗi liên tiếp)
                        ai2_consecutive_errors = database.get_ai_state('ai2_defensive')

                        # 5. Gọi AI tổng hợp để đưa ra dự đoán cuối cùng
                        final_prediction_display, ai_individual_predictions = prediction_engine.ensemble_predict(
                            history, ai_scores, ai2_consecutive_errors
                        )

                        # 6. Cập nhật điểm và trạng thái của các AI dựa trên kết quả thực tế
                        prediction_engine.update_ai_scores_and_states(
                            actual_result_char, 
                            ai_individual_predictions, 
                            ai_scores, 
                            ai2_consecutive_errors, 
                            database.update_ai_score, 
                            database.update_ai_state
                        )
                        
                        # 7. Cập nhật phiên cuối cùng đã xử lý vào DB
                        database.update_app_setting('last_processed_phien', str(phien_number))

                        # Xây dựng tin nhắn hiển thị (sử dụng HTML để định dạng)
                        message = f"""🎲 <b>KẾT QUẢ MỚI NHẤT:</b>
Phiên: <code>{phien_number}</code>
Kết quả: <b>{ket_qua_decoded}</b> ({'Tài' if ket_qua_decoded == 'Tài' else 'Xỉu'})
Tổng: <code>{tong}</code> (Xúc xắc: {xuc_xac_1}, {xuc_xac_2}, {xuc_xac_3})

💡 <b>DỰ ĐOÁN PHIÊN TIẾP THEO:</b> <b>{final_prediction_display}</b>

_Để ngừng thông báo liên tục, gõ /tat_
"""
                        return message, actual_result_char
                    else:
                        # Không có phiên mới hoặc kết quả không hợp lệ, không cần gửi tin nhắn
                        logger.debug("No new phien or invalid result detected.")
                        return None, None
                else:
                    logger.warning(f"Lỗi API Tài Xỉu: Status {resp.status}")
                    return None, None
        except aiohttp.ClientError as e:
            logger.error(f"Lỗi kết nối đến server Tài Xỉu: {e}", exc_info=True)
            return (f"❌ Lỗi kết nối đến server Tài Xỉu: {e!s}. Vui lòng kiểm tra kết nối mạng hoặc API.", None)
        except json.JSONDecodeError as e:
            logger.error(f"Lỗi JSON decode từ API Tài Xỉu: {e}", exc_info=True)
            return (f"❌ Lỗi đọc dữ liệu từ server: Dữ liệu không phải JSON hợp lệ. Chi tiết: {e!s}", None)
        except Exception as e:
            logger.error(f"Lỗi không xác định khi xử lý dữ liệu Tài Xỉu: {e}", exc_info=True)
            return (f"❌ Lỗi không xác định đã xảy ra: {e!s}. Vui lòng liên hệ hỗ trợ.", None)


# --- Job chạy định kỳ để kiểm tra phiên mới và gửi thông báo ---
async def check_for_new_results_job(context: ContextTypes.DEFAULT_TYPE):
    logger.debug("Running check_for_new_results_job...")
    
    # Lấy và xử lý dữ liệu Tài Xỉu
    message, _ = await get_and_process_taixiu_data()
    
    if message:
        # Gửi tin nhắn đến tất cả người dùng đã đăng ký
        # Tạo bản sao của user_data.items() để tránh lỗi RuntimeError: dictionary changed size during iteration
        for user_id_str, user_info in list(user_data.items()): 
            if user_info.get('subscribed'): # Chỉ gửi nếu người dùng đã đăng ký
                try:
                    await context.bot.send_message(
                        chat_id=user_id_str, 
                        text=message, 
                        parse_mode=ParseMode.HTML # Sử dụng HTML để định dạng tin nhắn
                    )
                    logger.debug(f"Sent update to subscribed user {user_id_str}")
                except Exception as e:
                    logger.warning(f"Could not send update to user {user_id_str}: {e}")
                    # Nếu bot bị chặn, hủy đăng ký người dùng này
                    if "bot was blocked by the user" in str(e).lower():
                        user_info['subscribed'] = False
                        logger.info(f"Unsubscribed user {user_id_str} due to bot being blocked.")


# --- Các lệnh cơ bản ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Đảm bảo user_data được khởi tạo cho người dùng mới, với subscribed = False mặc định
    user_data.setdefault(user.id, {"expiration_date": date.today().strftime("%Y-%m-%d"), "xu": 0, "subscribed": False})

    await update.message.reply_text(
        f"Xin chào {user.full_name!s}! 🎲 Chào mừng đến với BOT SUNWIN TÀI XỈU DỰ ĐOÁN\n"
        "Gõ /help để xem các lệnh có thể sử dụng."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
👋 Các lệnh có sẵn:
/start - Bắt đầu và nhận thông báo chào mừng.
/help - Hiển thị danh sách các lệnh.
/support - Liên hệ hỗ trợ.
/gia - Xem bảng giá dịch vụ.
/gopy <nội dung> - Gửi góp ý tới Admin.
/nap - Hướng dẫn nạp tiền mua lượt.
/taixiu - Xem kết quả Tài Xỉu mới nhất và dự đoán.
/tat - Ngừng nhận thông báo dự đoán liên tục.

🔑 Lệnh dành cho Admin/CTV:
/full - Xem chi tiết thông tin người dùng (Admin/CTV).
/giahan <id> <ngày> - Gia hạn cho người dùng (Admin/CTV).

👑 Lệnh dành cho Admin chính:
/ctv <id> - Thêm CTV.
/xoactv <id> - Xóa CTV.
/tb <nội dung> - Gửi thông báo tới tất cả người dùng.
    """
    await update.message.reply_text(help_text)


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Nếu bạn cần hỗ trợ, vui lòng liên hệ:\n"
        "Telegram: @heheviptool\n"
        "Gmail: nhutquangdzs1@gmail.com"
    )


async def gia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        """
        ⚜️ <b>BẢNG GIÁ DỊCH VỤ SUN BOT</b> ⚜️
        
        💸 20k: 1 Ngày
        💸 50k: 1 Tuần
        💸 80k: 2 Tuần
        💸 130k: 1 Tháng
        
        Bot SUNWIN có tỉ lệ dự đoán <b>85-92%</b> và hoạt động 24/24.
        Vui lòng liên hệ <a href="https://t.me/heheviptool">@heheviptool</a> để gia hạn dịch vụ.
        """, parse_mode=ParseMode.HTML
    )


async def gopy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Vui lòng nhập nội dung góp ý. Ví dụ: /gopy Bot rất hay!")
        return

    gopy_text = " ".join(context.args)
    user = update.effective_user
    message_to_admin = (
        f"GÓP Ý MỚI từ @{user.username or user.full_name!s} (ID: {user.id}):\n\n"
        f"Nội dung: {gopy_text}"
    )

    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=message_to_admin)
        await update.message.reply_text("✅ Cảm ơn bạn đã gửi góp ý! Admin đã nhận được.")
    except Exception as e:
        logger.error(f"Lỗi khi gửi góp ý đến admin: {e}")
        await update.message.reply_text("❌ Có lỗi xảy ra khi gửi góp ý. Vui lòng thử lại sau.")


async def nap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nap_text = f"""
    ⚜️ <b>NẠP TIỀN MUA LƯỢT</b> ⚜️

    Để mua lượt, vui lòng chuyển khoản đến:
    - Ngân hàng: <b>MB BANK</b>
    - Số tài khoản: <code>0939766383</code>
    - Tên chủ TK: <b>Nguyen Huynh Nhut Quang</b>

    ❗️ <b>Nội dung chuyển khoản (QUAN TRỌNG):</b>
    <code>mua luot {user_id}</code>

    (Vui lòng sao chép đúng nội dung trên để được cộng lượt tự động)
    Sau khi chuyển khoản, vui lòng chờ 1-2 phút và kiểm tra. Nếu có sự cố, hãy dùng lệnh /support.
    """
    await update.message.reply_text(nap_text, parse_mode=ParseMode.HTML)

# --- Lệnh Tài Xỉu và Dự đoán Nâng cao (Bật thông báo liên tục) ---
async def taixiu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Khởi tạo hoặc cập nhật user_data, và đặt subscribed = True
    user_data.setdefault(user_id, {"expiration_date": date.today().strftime("%Y-%m-%d"), "xu": 0, "subscribed": False})
    user_data[user_id]['subscribed'] = True
    logger.info(f"User {user_id} subscribed to continuous updates.")

    message, _ = await get_and_process_taixiu_data()
    if message:
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("Hiện tại không có phiên mới hoặc có lỗi khi lấy dữ liệu. Bạn đã được đăng ký nhận thông báo khi có phiên mới.", parse_mode=ParseMode.HTML)

# --- Lệnh tắt thông báo liên tục ---
async def tat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_data:
        user_data[user_id]['subscribed'] = False
        await update.message.reply_text("Bạn đã ngừng nhận thông báo dự đoán liên tục. Gõ /taixiu để bật lại.")
        logger.info(f"User {user_id} unsubscribed from continuous updates.")
    else:
        await update.message.reply_text("Bạn chưa đăng ký nhận thông báo nào.")


# --- Lệnh dành cho Admin/CTV ---
async def full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_ctv_or_admin(user_id):
        await update.message.reply_text("❌ Bạn không có quyền sử dụng lệnh này.")
        return

    target_user_id = user_id # Mặc định là xem thông tin của chính người dùng
    if context.args and context.args[0].isdigit():
        target_user_id = int(context.args[0])

    if target_user_id in user_data:
        info = user_data[target_user_id]
        message = (
            f"Chi tiết người dùng ID: {target_user_id}\n"
            f"Ngày hết hạn: {info.get('expiration_date', 'N/A')}\n"
            f"Số xu: {info.get('xu', 0)}\n"
            f"Là CTV: {'Có' if target_user_id in CTV_IDS else 'Không'}\n"
            f"Đăng ký thông báo: {'Có' if info.get('subscribed') else 'Không'}"
        )
    else:
        message = f"Không tìm thấy thông tin cho người dùng ID: {target_user_id}. (Chỉ lưu trong RAM nếu người dùng chưa tương tác)"
    await update.message.reply_text(message)


async def giahan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_ctv_or_admin(user_id):
        await update.message.reply_text("❌ Bạn không có quyền sử dụng lệnh này.")
        return

    if len(context.args) != 2 or not context.args[0].isdigit() or not context.args[1].isdigit():
        await update.message.reply_text(
            "Sai cú pháp. Sử dụng: /giahan <ID người dùng> <số ngày>"
        )
        return

    target_user_id = int(context.args[0])
    days_to_add = int(context.args[1])

    # Khởi tạo user_data cho người dùng nếu chưa có, với subscribed = False mặc định
    user_data.setdefault(target_user_id, {"expiration_date": date.today().strftime("%Y-%m-%d"), "xu": 0, "subscribed": False})

    # Cập nhật ngày hết hạn cho người dùng
    current_exp_str = user_data[target_user_id].get("expiration_date", "1970-01-01")
    current_exp_date = datetime.strptime(current_exp_str, "%Y-%m-%d").date()

    new_expiration_date = current_exp_date + timedelta(days=days_to_add)
    user_data[target_user_id]["expiration_date"] = new_expiration_date.strftime("%Y-%m-%d")

    await update.message.reply_text(
        f"✅ Gia hạn thành công cho người dùng ID {target_user_id} thêm {days_to_add} ngày. "
        f"Ngày hết hạn mới: {new_expiration_date.strftime('%Y-%m-%d')}"
    )
    # Cố gắng thông báo cho người dùng được gia hạn
    try:
        await context.bot.send_message(chat_id=target_user_id, text=f"🎉 Tài khoản của bạn đã được gia hạn thêm {days_to_add} ngày. Ngày hết hạn mới: {new_expiration_date.strftime('%Y-%m-%d')}")
    except Exception as e:
        logger.warning(f"Không thể gửi thông báo gia hạn tới người dùng {target_user_id}: {e}")


# --- Lệnh dành riêng cho Admin chính ---
async def ctv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Bạn không phải Admin chính để sử dụng lệnh này.")
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Sai cú pháp. Sử dụng: /ctv <ID người dùng>")
        return

    target_user_id = int(context.args[0])
    CTV_IDS.add(target_user_id)
    await update.message.reply_text(f"✅ Người dùng ID {target_user_id} đã được thêm vào danh sách CTV.")


async def xoactv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Bạn không phải Admin chính để sử dụng lệnh này.")
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Sai cú pháp. Sử dụng: /xoactv <ID người dùng>")
        return

    target_user_id = int(context.args[0])
    try:
        CTV_IDS.remove(target_user_id)
        await update.message.reply_text(f"✅ Người dùng ID {target_user_id} đã bị xóa khỏi danh sách CTV.")
    except KeyError:
        await update.message.reply_text(f"Người dùng ID {target_user_id} không có trong danh sách CTV.")


async def tb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Bạn không phải Admin chính để sử dụng lệnh này.")
        return

    if not context.args:
        await update.message.reply_text("Vui lòng nhập nội dung thông báo. Ví dụ: /tb Bot sẽ bảo trì lúc 22h.")
        return

    broadcast_message = " ".join(context.args)
    
    sent_count = 0
    failed_count = 0
    # Lặp qua một bản sao của user_data.keys() để tránh lỗi thay đổi kích thước khi gửi
    for uid in list(user_data.keys()):
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 THÔNG BÁO TỪ ADMIN:\n\n{broadcast_message}")
            sent_count += 1
            await asyncio.sleep(0.05) # Tránh bị flood limit của Telegram
        except Exception as e:
            logger.warning(f"Không thể gửi thông báo tới người dùng {uid}: {e}")
            failed_count += 1
    
    await update.message.reply_text(f"✅ Đã gửi thông báo tới {sent_count} người dùng. Thất bại: {failed_count}.")


# --- Hàm chính để chạy bot ---
def main():
    database.init_db() # Khởi tạo cơ sở dữ liệu khi bot chạy
    prediction_engine.load_patterns() # Tải các mẫu từ dudoan.txt khi bot chạy
    
    global application_instance # Gán instance cho biến toàn cục
    application_instance = Application.builder().token(TELEGRAM_TOKEN).build()

    # Lấy JobQueue instance để lên lịch tác vụ nền
    job_queue = application_instance.job_queue
    
    # Lên lịch job để kiểm tra phiên mới và gửi thông báo mỗi 30 giây
    # `first=0` để chạy lần đầu ngay lập tức khi bot khởi động
    job_queue.run_repeating(check_for_new_results_job, interval=30, first=0) 

    # Đăng ký các lệnh
    app = application_instance # Dùng biến cục bộ app cho dễ đọc
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("support", support))
    app.add_handler(CommandHandler("gia", gia))
    app.add_handler(CommandHandler("gopy", gopy))
    app.add_handler(CommandHandler("nap", nap))
    
    # Đăng ký lệnh /taixiu và /tat
    app.add_handler(CommandHandler("taixiu", taixiu))
    app.add_handler(CommandHandler("tat", tat))

    # Lệnh cho Admin/CTV
    app.add_handler(CommandHandler("full", full))
    app.add_handler(CommandHandler("giahan", giahan))

    # Lệnh cho Admin chính
    app.add_handler(CommandHandler("ctv", ctv))
    app.add_handler(CommandHandler("xoactv", xoactv))
    app.add_handler(CommandHandler("tb", tb))

    logger.info("Bot đang chạy... Đang lắng nghe các cập nhật.")
    app.run_polling(poll_interval=1.0) # Lắng nghe update mỗi 1 giây

if __name__ == '__main__':
    main()

