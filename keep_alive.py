import os
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
  # Lấy cổng từ biến môi trường do Render cung cấp, mặc định là 8080
  port = int(os.environ.get("PORT", 8080)) 
  app.run(host='0.0.0.0',port=port) 

def keep_alive():
    t = Thread(target=run)
    t.start()

if __name__ == '__main__':
    keep_alive() 
    print("Keep-alive server started.")
