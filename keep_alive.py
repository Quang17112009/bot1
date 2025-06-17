from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
  # You can try port 8080 or 5000 depending on the deployment platform
  app.run(host='0.0.0.0',port=8080) 

def keep_alive():
    t = Thread(target=run)
    t.start()

# This part is generally not run directly if imported into main.py,
# but it shows how keep_alive() is called.
if __name__ == '__main__':
    keep_alive() 
    print("Keep-alive server started.")
