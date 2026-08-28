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
    await message.reply_text("হ্যালো! আমাকে YouTube, Instagram বা Facebook-এর লিঙ্ক পাঠান।")

@app.on_message(filters.text & filters.private & ~filters.me & ~filters.bot)
async def download_video(client, message):
    url = message.text.strip()
    if not url.startswith("http"):
        return

    msg = await message.reply_text("ডাউনলোড হচ্ছে, অপেক্ষা করুন...")

    # TeraBox লিঙ্ক হ্যান্ডলিং
    if any(domain in url for domain in ["terabox", "1024tera", "freeterabox", "teraboxapp"]):
        terabox_api = f"https://terabox-dl.qtcloud.workers.dev/api/get-download?url={url}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(terabox_api) as resp:
                    data = await resp.json()
                    if data.get("downloadLink"):
                        await message.reply_video(video=data.get("downloadLink"), caption=data.get("fileName", "video.mp4"))
                        await msg.delete()
                    else:
                        await msg.edit_text("TeraBox থেকে ফাইল পাওয়া যায়নি।")
        except Exception as e:
            await msg.edit_text(f"ত্রুটি: {str(e)}")
        return

    # Cobalt API with proper headers for Instagram/Facebook/YouTube
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    payload = {
        "url": url,
        "videoQuality": "720",
        "audioFormat": "mp3"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.cobalt.tools/api/json", json=payload, headers=headers) as response:
                res_data = await response.json()
                
                status = res_data.get("status")
                if status in ["stream", "redirect"]:
                    await message.reply_video(video=res_data.get("url"))
                    await msg.delete()
                elif status == "picker":
                    picker_list = res_data.get("picker")
                    if picker_list and len(picker_list) > 0:
                        await message.reply_video(video=picker_list[0].get("url"))
                        await msg.delete()
                    else:
                        await msg.edit_text("মিডিয়া ফাইল খুঁজে পাওয়া যায়নি।")
                else:
                    await msg.edit_text("এই লিঙ্কটি এই মুহূর্তে প্রসেস করা সম্ভব হচ্ছে না। অন্য লিঙ্ক দিয়ে চেষ্টা করুন।")
    except Exception as e:
        await msg.edit_text(f"ত্রুটি ঘটেছে: {str(e)}")

if __name__ == "__main__":
    app.run()
                         
