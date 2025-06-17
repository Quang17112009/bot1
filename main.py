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

# Import các module mới
from keep_alive import keep_alive
import database # Để tương tác với SQLite
import prediction_engine # Để sử dụng các AI dự đoán

# Thiết lập logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Cấu hình Bot ---
TELEGRAM_TOKEN = "7951251597:AAEXH5OtBRxU8irZS1S4Gh-jicRmSIOK_s" # Token của bạn đã được cập nhật
HTTP_API_URL = "https://apisunwin1.up.railway.app/api/taixiu"

# Thay thế bằng Telegram User ID của Admin chính (là bạn)
ADMIN_ID = 6915752059 # ID Admin của bạn đã được cập nhật

# Danh sách user_id của các cộng tác viên (CTV)
# Vẫn nên lưu trong DB hoặc file riêng nếu muốn persistent
CTV_IDS = set() 

# Dictionary để lưu trữ thông tin người dùng (cho mục đích demo, VẪN NÊN DÙNG DATABASE THỰC TẾ)
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
        user_data[user.id] = {"expiration_date": date.today().strftime("%Y-%m-%d"), "xu": 0}
        logger.info(f"Người dùng mới đã tương tác: {user.id}")

    await update.message.reply_text(
        f"Xin chào {user.full_name}! 🎲 Chào mừng đến với BOT SUNWIN TÀI XỈU DỰ ĐOÁN\n"
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
        f"GÓP Ý MỚI từ @{user.username or user.full_name} (ID: {user.id}):\n\n"
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

    NỘI DUNG CHUYỂN KHOẢN (QUAN TRỌNG):
    mua luot {{user_id}}

    ❗️ Nội dung bắt buộc của bạn là:
    mua luot {user_id}

    (Vui lòng sao chép đúng nội dung trên để được cộng lượt tự động)
    Sau khi chuyển khoản, vui lòng chờ 1-2 phút và kiểm tra bằng lệnh /luot. Nếu có sự cố, hãy dùng lệnh /support.
    """
    await update.message.reply_text(nap_text)

# --- Lệnh Tài Xỉu và Dự đoán Nâng cao ---
async def taixiu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(HTTP_API_URL) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    ket_qua_decoded = data.get('Ket_qua', 'N/A').encode('latin1').decode('unicode_escape')
                    
                    phien_number = data.get('Phien')
                    tong = data.get('Tong')
                    xuc_xac_1 = data.get('Xuc_xac_1')
                    xuc_xac_2 = data.get('Xuc_xac_2')
                    xuc_xac_3 = data.get('Xuc_xac_3')

                    # Chuẩn hóa kết quả về 'T' hoặc 'X' để lưu DB và phân tích
                    actual_result_char = 'T' if ket_qua_decoded == 'Tài' else 'X' if ket_qua_decoded == 'Xỉu' else None

                    if actual_result_char:
                        # 1. Lưu kết quả mới nhất vào DB
                        database.add_result(phien_number, ket_qua_decoded, tong, xuc_xac_1, xuc_xac_2, xuc_xac_3)
                        
                        # 2. Lấy lịch sử 13 phiên gần nhất từ DB
                        history = database.get_latest_history()
                        
                        # 3. Lấy điểm hiện tại của các AI
                        ai_scores = database.get_ai_scores()
                        
                        # 4. Lấy trạng thái của AI2 (số lỗi liên tiếp)
                        ai2_consecutive_errors = database.get_ai_state('ai2_defensive')

                        # 5. Gọi AI tổng hợp để đưa ra dự đoán cuối cùng
                        final_prediction, ai_individual_predictions = prediction_engine.ensemble_predict(
                            history, ai_scores, ai2_consecutive_errors
                        )

                        # 6. Cập nhật điểm và trạng thái của các AI dựa trên kết quả thực tế
                        prediction_engine.update_ai_scores_and_states(
                            actual_result_char,
                            ai_individual_predictions,
                            ai_scores,
                            ai2_consecutive_errors,
                            database.update_ai_score, # Pass function to update score in DB
                            database.update_ai_state  # Pass function to update state in DB
                        )

                        message = f"""🎲 Kết quả mới nhất:
Phiên: {phien_number}
Kết quả: {ket_qua_decoded}
Tổng: {tong} ({ket_qua_decoded})
Xúc xắc: {xuc_xac_1}, {xuc_xac_2}, {xuc_xac_3}

💡 **Dự đoán phiên tiếp theo:** {final_prediction}
"""
                        # Thông tin thêm cho debug hoặc admin (có thể bỏ đi)
                        current_ai_scores = database.get_ai_scores()
                        current_ai2_state = database.get_ai_state('ai2_defensive')
                        message += "\n(Điểm AI: "
                        for ai_name, score in current_ai_scores.items():
                            message += f"{ai_name[:3]}: {score:.0f} "
                        message += f"| Lỗi AI2: {current_ai2_state})"

                    else:
                        message = f"❌ Dữ liệu kết quả không hợp lệ: {data.get('Ket_qua')}"

                else:
                    message = "❌ Không thể lấy dữ liệu từ server Tài Xỉu. Vui lòng thử lại sau."
                    logger.warning(f"Lỗi API Tài Xỉu: Status {resp.status}")
        except aiohttp.ClientError as e:
            message = f"❌ Lỗi kết nối đến server Tài Xỉu: {e}"
            logger.error(f"Lỗi kết nối API Tài Xỉu: {e}")
        except json.JSONDecodeError as e:
            message = f"❌ Lỗi đọc dữ liệu từ server: {e}"
            logger.error(f"Lỗi JSON decode từ API Tài Xỉu: {e}")
        except Exception as e:
            message = f"❌ Lỗi không xác định: {e}"
            logger.error(f"Lỗi chung khi lấy dữ liệu Tài Xỉu: {e}", exc_info=True) # exc_info để in stack trace

    await update.message.reply_text(message)


# --- Lệnh dành cho Admin/CTV ---
async def full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_ctv_or_admin(user_id):
        await update.message.reply_text("❌ Bạn không có quyền sử dụng lệnh này.")
        return

    target_user_id = user_id
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
        message = f"Không tìm thấy thông tin cho người dùng ID: {target_user_id}."
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

    from datetime import date, datetime, timedelta

    if target_user_id not in user_data:
        new_expiration_date = date.today() + timedelta(days=days_to_add)
        user_data[target_user_id] = {
            "expiration_date": new_expiration_date.strftime("%Y-%m-%d"),
            "xu": 0, 
        }
        await update.message.reply_text(
            f"✅ Tạo mới người dùng ID {target_user_id} và gia hạn thành công {days_to_add} ngày. "
            f"Ngày hết hạn mới: {new_expiration_date.strftime('%Y-%m-%d')}"
        )
        try:
            await context.bot.send_message(chat_id=target_user_id, text=f"🎉 Tài khoản của bạn đã được gia hạn thêm {days_to_add} ngày. Ngày hết hạn mới: {new_expiration_date.strftime('%Y-%m-%d')}")
        except Exception as e:
            logger.warning(f"Không thể gửi thông báo gia hạn tới người dùng {target_user_id}: {e}")
        return


    current_exp_str = user_data[target_user_id].get("expiration_date", "1970-01-01")
    current_exp_date = datetime.strptime(current_exp_str, "%Y-%m-%d").date()

    new_expiration_date = current_exp_date + timedelta(days=days_to_add)
    user_data[target_user_id]["expiration_date"] = new_expiration_date.strftime("%Y-%m-%d")

    await update.message.reply_text(
        f"✅ Gia hạn thành công cho người dùng ID {target_user_id} thêm {days_to_add} ngày. "
        f"Ngày hết hạn mới: {new_expiration_date.strftime('%Y-%m-%d')}"
    )
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
    for uid in list(user_data.keys()):
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 THÔNG BÁO TỪ ADMIN:\n\n{broadcast_message}")
            sent_count += 1
            await asyncio.sleep(0.05) 
        except Exception as e:
            logger.warning(f"Không thể gửi thông báo tới người dùng {uid}: {e}")
            failed_count += 1
    
    await update.message.reply_text(f"✅ Đã gửi thông báo tới {sent_count} người dùng. Thất bại: {failed_count}.")


# --- Hàm chính để chạy bot ---
def main():
    database.init_db() # Khởi tạo cơ sở dữ liệu khi bot chạy
    prediction_engine.load_patterns() # Tải các mẫu từ dudoan.txt khi bot chạy
    
    keep_alive() # Gọi hàm này để khởi động server keep-alive
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Thêm các lệnh
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

    logger.info("Bot đang chạy...")
    app.run_polling(poll_interval=1.0) 

if __name__ == '__main__':
    main()

