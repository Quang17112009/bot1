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

# --- Cấu hình Bot (Sử dụng biến môi trường - KHUYẾN NGHỊ BẢO MẬT) ---
# Lấy token bot Telegram từ biến môi trường
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") 
# Lấy ID Telegram admin từ biến môi trường
ADMIN_ID_STR = os.getenv("ADMIN_ID") # Lấy dưới dạng chuỗi
ADMIN_ID = None
try:
    if ADMIN_ID_STR:
        ADMIN_ID = int(ADMIN_ID_STR)
except ValueError:
    logger.critical("ADMIN_ID trong biến môi trường không phải là số nguyên hợp lệ.")

# Các kiểm tra đảm bảo giá trị hợp lệ
if not isinstance(TELEGRAM_TOKEN, str) or not TELEGRAM_TOKEN:
    logger.critical("TELEGRAM_TOKEN không hợp lệ hoặc bị thiếu. Bot không thể khởi động.")
    exit(1)

if not isinstance(ADMIN_ID, int) or ADMIN_ID <= 0:
    logger.critical("ADMIN_ID không hợp lệ hoặc bị thiếu. Bot không thể khởi động.")
    exit(1)


HTTP_API_URL = "https://apisunwin1.up.railway.app/api/taixiu"

# Danh sách user_id của các cộng tác viên (CTV)
# Để đơn giản, vẫn lưu trong bộ nhớ. Dùng DB nếu muốn bền vững hơn thì cần lưu vào SQLite
CTV_IDS = set() 

# Dictionary để lưu trữ thông tin người dùng (ngày hết hạn, xu). 
# Để đơn giản, vẫn lưu trong bộ nhớ. Dùng DB nếu muốn bền vững hơn thì cần lưu vào SQLite
# Format: {user_id: {"expiration_date": "YYYY-MM-DD", "xu": 0}}
user_data = {} 


# --- Hàm kiểm tra quyền ---
def is_admin(user_id):
    return user_id == ADMIN_ID


def is_ctv_or_admin(user_id):
    return user_id == ADMIN_ID or user_id in CTV_IDS


# --- Các lệnh cơ bản ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in user_data:
        # Mặc định thêm người dùng mới với 0 xu và ngày hết hạn hôm nay
        user_data[user.id] = {"expiration_date": date.today().strftime("%Y-%m-%d"), "xu": 0}
        logger.info(f"Người dùng mới đã tương tác: {user.id}")

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
        BOT SUNWIN XIN THÔNG BÁO BẢNG GIÁ SUN BOT
        20k 1 Ngày
        50k 1 Tuần
        80k 2 Tuần
        130k 1 Tháng
        BOT SUN TỈ Lệ 85-92%
        ĐỌC 24/24 Vui Lòng ib @heheviptool Để Gia Hạn
        """
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
    ⚜️ NẠP TIỀN MUA LƯỢT ⚜️

    Để mua lượt, vui lòng chuyển khoản đến:
    - Ngân hàng: MB BANK
    - Số tài khoản: 0939766383
    - Tên chủ TK: Nguyen Huynh Nhut Quang

    ❗️ Nội dung chuyển khoản (QUAN TRỌNG):
    mua luot {{user_id}}

    ❗️ Nội dung bắt buộc của bạn là:
    mua luot {user_id}

    (Vui lòng sao chép đúng nội dung trên để được cộng lượt tự động)
    Sau khi chuyển khoản, vui lòng chờ 1-2 phút và kiểm tra bằng lệnh /luot. Nếu có sự cố, hãy dùng lệnh /support.
    """
    await update.message.reply_text(nap_text)

# --- Hàm chung để xử lý và gửi thông báo Tài Xỉu ---
# Hàm này sẽ được gọi bởi tác vụ định kỳ và lệnh /taixiu
async def process_and_send_taixiu(context: ContextTypes.DEFAULT_TYPE, target_chat_id: int = None):
    """
    Lấy dữ liệu API, xử lý, cập nhật DB và gửi thông báo.
    Nếu target_chat_id được cung cấp, chỉ gửi tới chat đó (dùng cho lệnh /taixiu).
    Nếu target_chat_id là None, gửi tới tất cả người dùng hợp lệ (dùng cho tác vụ định kỳ).
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(HTTP_API_URL) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    ket_qua_display = data.get('Ket_qua', 'N/A')
                    phien_number = data.get('Phien', 0) 
                    tong = data.get('Tong', 0)
                    xuc_xac_1 = data.get('Xuc_xac_1', 0)
                    xuc_xac_2 = data.get('Xuc_xac_2', 0)
                    xuc_xac_3 = data.get('Xuc_xac_3', 0) 

                    actual_result_char = None
                    if ket_qua_display == 'Tài':
                        actual_result_char = 'T'
                    elif ket_qua_display == 'Xỉu':
                        actual_result_char = 'X'

                    if actual_result_char:
                        is_new_phien = False
                        if target_chat_id is None: # Chỉ kiểm tra phiên mới nếu là tác vụ định kỳ (gửi cho tất cả)
                            last_processed_phien = int(database.get_app_setting('last_processed_phien') or '0')
                            if phien_number > last_processed_phien:
                                is_new_phien = True
                                logger.info(f"Phát hiện phiên mới: {phien_number}. Phiên cuối đã xử lý: {last_processed_phien}")
                            else:
                                logger.debug(f"Phiên {phien_number} đã được xử lý. Không có phiên mới để thông báo tự động.")
                                return # Không có phiên mới, thoát khỏi hàm

                        # Nếu là phiên mới (từ tác vụ định kỳ) HOẶC là lệnh /taixiu thủ công, thì cập nhật DB và AI
                        if is_new_phien or target_chat_id is not None:
                            database.add_result(phien_number, ket_qua_display, actual_result_char, tong, xuc_xac_1, xuc_xac_2, xuc_xac_3)
                            # Cập nhật phiên cuối cùng đã xử lý nếu là tác vụ định kỳ
                            if is_new_phien:
                                database.update_app_setting('last_processed_phien', str(phien_number))
                        
                        # Lấy dữ liệu để dự đoán và hiển thị (luôn làm, dù là phiên mới hay cũ)
                        history = database.get_latest_history()
                        ai_scores = database.get_ai_scores()
                        ai2_consecutive_errors = database.get_ai_state('ai2_defensive')

                        final_prediction_display, ai_individual_predictions = prediction_engine.ensemble_predict(
                            history, ai_scores, ai2_consecutive_errors
                        )

                        # Chỉ cập nhật điểm AI nếu đây là phiên MỚI được xử lý (tránh cập nhật nhiều lần)
                        if is_new_phien:
                            prediction_engine.update_ai_scores_and_states(
                                actual_result_char, 
                                ai_individual_predictions, 
                                ai_scores, 
                                ai2_consecutive_errors, 
                                database.update_ai_score, 
                                database.update_ai_state  
                            )
                        
                        # Tạo tin nhắn
                        message = f"""🎲 <b>Kết quả phiên mới nhất:</b>
Phiên: <code>{phien_number}</code>
Kết quả: <b><span style="color:{"#4CAF50" if actual_result_char == "T" else "#FF5722"};">{ket_qua_display}</span></b>
Tổng: <b>{tong}</b> ({ket_qua_display})
Xúc xắc: <code>{xuc_xac_1}</code>, <code>{xuc_xac_2}</code>, <code>{xuc_xac_3}</code>

✨ <b>Dự đoán phiên tiếp theo:</b> <b>{final_prediction_display}</b>

<pre>
--- Thống kê AI ---
AI Trend: {ai_scores.get('ai1_trend', 0):.0f} điểm
AI Defensive: {ai_scores.get('ai2_defensive', 0):.0f} điểm (Lỗi liên tiếp: {ai2_consecutive_errors})
AI Pattern: {ai_scores.get('ai3_pattern', 0):.0f} điểm
</pre>
"""
                        # Gửi tin nhắn
                        if target_chat_id: # Gửi cho một chat cụ thể (lệnh /taixiu)
                            await context.bot.send_message(chat_id=target_chat_id, text=message, parse_mode='HTML')
                        else: # Gửi cho tất cả người dùng hợp lệ (tác vụ định kỳ)
                            for uid in list(user_data.keys()): # Lặp qua bản sao của keys để tránh lỗi thay đổi kích thước
                                try:
                                    user_info = user_data.get(uid)
                                    if user_info and datetime.strptime(user_info["expiration_date"], "%Y-%m-%d").date() >= date.today():
                                        await context.bot.send_message(chat_id=uid, text=message, parse_mode='HTML')
                                        await asyncio.sleep(0.1) # Tránh bị flood
                                    # else:
                                    #     logger.debug(f"Không gửi thông báo tới user {uid} vì đã hết hạn hoặc không có dữ liệu.")
                                except Exception as e:
                                    logger.warning(f"Không thể gửi thông báo tự động tới người dùng {uid}: {e}")
                            logger.info(f"Đã xử lý và thông báo phiên {phien_number} cho tất cả người dùng.")

                    else:
                        error_message = f"❌ Không thể lấy dữ liệu từ server Tài Xỉu. Vui lòng thử lại sau. (Status: {resp.status})"
                        logger.warning(error_message)
                        if target_chat_id: # Chỉ gửi lỗi cho người dùng nếu họ gọi lệnh thủ công
                            await context.bot.send_message(chat_id=target_chat_id, text=error_message)

        except aiohttp.ClientError as e:
            error_message = f"❌ Lỗi kết nối đến server Tài Xỉu: {e!s}. Vui lòng kiểm tra kết nối mạng hoặc API."
            logger.error(error_message, exc_info=True)
            if target_chat_id:
                await context.bot.send_message(chat_id=target_chat_id, text=error_message)
        except json.JSONDecodeError as e:
            error_message = f"❌ Lỗi đọc dữ liệu từ server: Dữ liệu không phải JSON hợp lệ. Chi tiết: {e!s}"
            logger.error(error_message, exc_info=True)
            if target_chat_id:
                await context.bot.send_message(chat_id=target_chat_id, text=error_message)
        except Exception as e:
            error_message = f"❌ Lỗi không xác định đã xảy ra: {e!s}. Vui lòng liên hệ hỗ trợ."
            logger.error(error_message, exc_info=True)
            if target_chat_id:
                await context.bot.send_message(chat_id=target_chat_id, text=error_message)

# Lệnh Tài Xỉu (người dùng gọi thủ công)
async def taixiu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await process_and_send_taixiu(context, target_chat_id=user_id)

# Hàm gọi bởi JobQueue để kiểm tra phiên mới tự động
async def check_for_new_phien(context: ContextTypes.DEFAULT_TYPE):
    # Gọi hàm xử lý chung, không cung cấp target_chat_id để nó gửi cho tất cả người dùng
    await process_and_send_taixiu(context)


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
            f"Là CTV: {'Có' if target_user_id in CTV_IDS else 'Không'}"
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

    # Nếu người dùng chưa có trong user_data (RAM), thêm mới với ngày hết hạn từ hôm nay
    if target_user_id not in user_data:
        current_exp_date = date.today()
        user_data[target_user_id] = {"xu": 0} # Mặc định 0 xu
    else:
        # Cập nhật ngày hết hạn cho người dùng hiện có
        current_exp_str = user_data[target_user_id].get("expiration_date", date.today().strftime("%Y-%m-%d"))
        try:
            current_exp_date = datetime.strptime(current_exp_str, "%Y-%m-%d").date()
        except ValueError: # Xử lý trường hợp ngày không hợp lệ, mặc định từ hôm nay
            current_exp_date = date.today()
            logger.warning(f"Ngày hết hạn '{current_exp_str}' của user {target_user_id} không hợp lệ, đặt lại từ hôm nay.")

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
    
    # Các kiểm tra TELEGRAM_TOKEN và ADMIN_ID được thực hiện ở đầu file
    # Nếu có lỗi, chương trình sẽ thoát sớm

    keep_alive() # Gọi hàm này để khởi động server keep-alive (cho Render)
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Lấy JobQueue từ ứng dụng
    job_queue = app.job_queue

    # Đăng ký tác vụ định kỳ: kiểm tra API mỗi 10 giây (điều chỉnh theo tần suất API cập nhật)
    job_queue.run_repeating(check_for_new_phien, interval=10, first=0) # first=0 để chạy ngay khi bot khởi động

    # Đăng ký các lệnh
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("support", support))
    app.add_handler(CommandHandler("gia", gia))
    app.add_handler(CommandHandler("gopy", gopy))
    app.add_handler(CommandHandler("nap", nap))
    app.add_handler(CommandHandler("taixiu", taixiu))

    # Lệnh cho Admin/CTV
    app.add_handler(CommandHandler("full", full))
    app.add_handler(CommandHandler("giahan", giahan))

    # Lệnh cho Admin chính
    app.add_handler(CommandHandler("ctv", ctv))
    app.add_handler(CommandHandler("xoactv", xoactv))
    app.add_handler(CommandHandler("tb", tb))

    logger.info("Bot đang chạy... Đang lắng nghe các cập nhật và kiểm tra API tự động.")
    app.run_polling(poll_interval=1.0) # Lắng nghe update mỗi 1 giây

if __name__ == '__main__':
    main()
