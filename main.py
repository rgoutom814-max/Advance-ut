from flask import Flask
import threading

app_web = Flask('')

@app_web.route('/')
def home():
    return "Bot is running!"

def run():
    app_web.run(host='0.0.0.0', port=8080)

threading.Thread(target=run).start()
import os
import asyncio
import aiohttp
from pyrogram import Client, filters

BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID = int(os.environ.get("API_ID", "123456"))
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH")

app = Client("downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("হ্যালো! আমাকে YouTube, Terabox, Instagram বা Facebook-এর যেকোনো সঠিক লিঙ্ক পাঠান, আমি ভিডিও নামিয়ে দেব।")

@app.on_message(filters.text & filters.private & ~filters.me & ~filters.bot)
async def download_video(client, message):
    url = message.text.strip()
    
    # লিঙ্ক http দিয়ে শুরু না হলে বট কোনো রিপ্লাই বা লুপ তৈরি করবে না, সাইলেন্ট থাকবে
    if not url.startswith("http"):
        return

    msg = await message.reply_text("ডাউনলোড প্রসেস হচ্ছে, একটু অপেক্ষা করুন...")

    # TeraBox লিঙ্ক প্রসেস করার অংশ
    if any(domain in url for domain in ["terabox", "1024tera", "freeterabox", "teraboxapp"]):
        terabox_api = f"https://terabox-dl.qtcloud.workers.dev/api/get-download?url={url}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(terabox_api) as resp:
                    data = await resp.json()
                    if data.get("downloadLink"):
                        file_url = data.get("downloadLink")
                        file_name = data.get("fileName", "video.mp4")
                        await msg.edit_text("টেলিগ্রামে ফাইল পাঠানো হচ্ছে...")
                        await message.reply_video(video=file_url, caption=file_name)
                        await msg.delete()
                    else:
                        await msg.edit_text("TeraBox লিঙ্ক থেকে ফাইল পাওয়া যায়নি। সঠিক লিঙ্ক দিন।")
        except Exception as e:
            await msg.edit_text(f"TeraBox ডাউনলোডে সমস্যা: {str(e)}")
        return

    # YouTube, Instagram, Facebook ইত্যাদির অংশ (Cobalt API)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {
        "url": url,
        "videoQuality": "720"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.cobalt.tools/api/json", json=payload, headers=headers) as response:
                res_data = await response.json()
                
                if res_data.get("status") in ["stream", "redirect"]:
                    video_url = res_data.get("url")
                    await msg.edit_text("টেলিগ্রামে আপলোড করা হচ্ছে...")
                    await message.reply_video(video=video_url)
                    await msg.delete()
                elif res_data.get("status") == "picker":
                    video_url = res_data.get("picker")[0].get("url")
                    await msg.edit_text("টেলিগ্রামে আপলোড করা হচ্ছে...")
                    await message.reply_video(video=video_url)
                    await msg.delete()
                else:
                    await msg.edit_text("ভিডিওটি প্রসেস করা যায়নি, অন্য লিঙ্ক দিয়ে চেষ্টা করুন।")

    except Exception as e:
        await msg.edit_text(f"ত্রুটি ঘটেছে: {str(e)}")

if __name__ == "__main__":
    app.run()
    
