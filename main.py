import os
import threading
from flask import Flask, request
import requests
from yt_dlp import YoutubeDL

app = Flask(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TOKEN}"

def download_and_send(chat_id, url):
    output_template = f"downloads/{chat_id}.%(ext)s"
    os.makedirs("downloads", exist_ok=True)
    
    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
            }
        }
    }
    
    try:
        send_message(chat_id, "⏳ ভিডিও ডাউনলোড হচ্ছে, একটু অপেক্ষা করুন...")
        
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
        # টেলিগ্রামে ভিডিও পাঠানোর কোড
        with open(filename, "rb") as video_file:
            requests.post(
                f"{TELEGRAM_API_URL}/sendVideo",
                data={"chat_id": chat_id},
                files={"video": video_file}
            )
            
        # ফাইল পাঠানোর পর লোকাল স্টোরেজ থেকে ডিলিট করা
        if os.path.exists(filename):
            os.remove(filename)
            
    except Exception as e:
        send_message(chat_id, f"❌ ডাউনলোড করতে সমস্যা হয়েছে: {str(e)}")

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json()
    
    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
        
        if text.startswith("http"):
            # ব্যাকগ্রাউন্ডে থ্রেড দিয়ে ভিডিও প্রসেস করা, যেন ওয়েব হুক টাইমআউট না করে
            threading.Thread(target=download_and_send, args=(chat_id, text)).start()
        else:
            send_message(chat_id, "দয়া করে একটি সঠিক ইউটিউব লিংক পাঠান।")
            
    return "OK", 200

def send_message(chat_id, text):
    requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={"chat_id": chat_id, "text": text})

@app.route("/", methods=["GET"])
def home():
    print("Webhook is active!")
    return "Bot is running!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
        
