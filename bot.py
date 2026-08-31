import os
import requests
import telebot

# Render-এর Environment Variable-এ থাকা BOT_TOKEN এখানে রিড করবে
TOKEN = os.environ.get('BOT_TOKEN')

if not TOKEN:
  raise ValueError(
      'BOT_TOKEN পাওয়া যায়নি! Render-এ সঠিকভাবে সেট করা আছে কিনা চেক করুন।'
  )

bot = telebot.TeleBot(TOKEN)


@bot.message_handler(commands=['start'])
def send_welcome(message):
  bot.reply_to(
      message,
      'স্বাগতম! যেকোনো ভিডিওর লিংক পাঠান, আমি ডাউনলোড লিংক বের করে দিচ্ছি।',
  )


@bot.message_handler(func=lambda message: True)
def handle_message(message):
  user_url = message.text
  bot.reply_to(message, 'লিংক প্রসেস করা হচ্ছে, একটু অপেক্ষা করুন...')

  try:
    api_url = (
        'https://api.vidssave.com/api/contentsite_api/media/download_redirect'
    )
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like'
            ' Gecko) Chrome/110.0.0.0 Mobile Safari/537.36'
        ),
        'Referer': 'https://vidssave.com/',
    }
    params = {'request': user_url}

    response = requests.get(
        api_url, headers=headers, params=params, allow_redirects=True
    )

    if response.url:
      final_link = response.url
      bot.reply_to(message, f'আপনার ডাউনলোড লিংক:\n{final_link}')
    else:
      bot.reply_to(message, 'ডাউনলোড লিংক পাওয়া যায়নি।')

  except Exception as e:
    bot.reply_to(message, f'একটি ত্রুটি ঘটেছে: {e}')


if __name__ == '__main__':
  bot.polling()
    
