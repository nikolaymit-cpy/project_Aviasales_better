
import logging
import os
import sys
from datetime import date, timedelta, datetime
import requests

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import InvalidToken
from dotenv import load_dotenv

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TRAVELPAYOUTS_API_KEY = os.getenv("TRAVELPAYOUTS_API_KEY")

PARTNER_MARKER = "424310"
PROMO_ID = "telegram_bot"
LEAD = "flights_search"

TRAVELPAYOUTS_API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"

CITY_TO_IATA = {
    "москва": "MOW", "санкт-петербург": "LED", "кемерово": "KEJ",
    "киров": "KVX", "кострома": "KMW", "челябинск": "CEK",
    "тюмень": "TJM", "новосибирск": "OVB", "томск": "TOF",
    "уфа": "UFA", "калининград": "KGD", "париж": "PAR",
    "нью-йорк": "NYC", "тбилиси": "TBS", "дубаи": "DXB",
}


def get_iata_code(city_name):
    return CITY_TO_IATA.get(city_name.lower())


def search_flights(origin_iata, destination_iata, date_str, api_key):
    params = {"origin": origin_iata, "destination": destination_iata, "departure_at": date_str,
              "currency": "RUB", "unique": "false", "token": api_key}
    logger.info(f"Выполняю запрос к Travelpayouts API: {TRAVELPAYOUTS_API_URL} (токен скрыт)")
    try:
        response = requests.get(TRAVELPAYOUTS_API_URL, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        if 'data' not in data or not isinstance(data['data'], list):
            logger.error(f"Неожиданный формат ответа от API: {data}")
            return None
        logger.info(f"Получен ответ от API. Найдено билетов: {len(data['data'])}")
        return data['data']
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка HTTP/запроса к Travelpayouts API: {e}")
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при обработке ответа API: {e}", exc_info=True)
        return None


def escape_markdown_v2(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-=|}{.!\\'
    return ''.join(['\\' + char if char in escape_chars else char for char in str(text)])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        '✈️ Привет\\! Я бот для поиска самых дешевых прямых авиабилетов\\.\n'
        'Используйте команду `/flights` для поиска\\.\n'
        'Пример: `/flights Москва Санкт-Петербург 28.06.2025` или `/flights Кемерово Новосибирск завтра`\n'
        'Для подробностей используйте /help',
        parse_mode="MarkdownV2"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cities = ', '.join([c.capitalize() for c in CITY_TO_IATA.keys()])
    await update.message.reply_text(
        'Я ищу *только прямые* рейсы\\. Используйте формат: `/flights Город1 Город2 ДАТА`\n\n'
        'В качестве `ДАТЫ` можно использовать слово `завтра` или дату в формате `ДД.ММ.ГГГГ` \\(например, `25.12.2024`\\)\\.\n\n'
        f'Поддерживаемые города: {escape_markdown_v2(cities)}\\.',
        parse_mode="MarkdownV2"
    )


async def flights(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) != 3:
        await update.message.reply_text("Неверный формат команды\\. Используйте: `/flights Город1 Город2 ДАТА`",
                                        parse_mode="MarkdownV2")
        return

    origin_city, dest_city, date_input_str = args[0], args[1], args[2]


    target_date = None
    if date_input_str.lower() == "завтра":
        target_date = date.today() + timedelta(days=1)
    else:
        try:
            target_date = datetime.strptime(date_input_str, "%d.%m.%Y").date()
            if target_date < date.today():
                await update.message.reply_text("Вы не можете искать билеты на прошедшие даты\\.",
                                                parse_mode="MarkdownV2")
                return
        except ValueError:
            await update.message.reply_text("Неверный формат даты\\. Используйте `завтра` или `ДД.ММ.ГГГГ`\\.",
                                            parse_mode="MarkdownV2")
            return

    date_api_str = target_date.strftime("%Y-%m-%d")
    date_url_str = target_date.strftime("%d%m")
    escaped_display_date = escape_markdown_v2(date_api_str)

    origin_iata, dest_iata = get_iata_code(origin_city), get_iata_code(dest_city)

    if not all([origin_iata, dest_iata]):
        await update.message.reply_text("Не удалось распознать один из городов\\. Проверьте /help\\.",
                                        parse_mode="MarkdownV2")
        return

    await update.message.reply_text(
        f"✈️ Ищу билеты из *{escape_markdown_v2(origin_city)}* в *{escape_markdown_v2(dest_city)}* на *{escaped_display_date}*\\.\\.\\.",
        parse_mode="MarkdownV2")

    flights_data = search_flights(origin_iata, dest_iata, date_api_str, TRAVELPAYOUTS_API_KEY)

    if flights_data is None or not flights_data:
        await update.message.reply_text(f"Билетов на *{escaped_display_date}* не найдено или произошла ошибка\\.",
                                        parse_mode="MarkdownV2")
        return

    message = f"✅ Найдены прямые рейсы на *{escaped_display_date}*:\n\n"
    sorted_flights = sorted(flights_data, key=lambda x: x.get('price', float('inf')))
    results_count = 0

    for flight in sorted_flights:
        if flight.get('destination') != dest_iata or flight.get('transfers') != 0:
            continue

        if results_count >= 5:
            break

        price = flight.get('price', 'N/A')
        airline = flight.get('airline', 'N/A')
        flight_number = flight.get('flight_number', 'N/A')
        dep_time = 'N/A'
        if flight.get('departure_at'):
            try:
                dep_time = datetime.fromisoformat(flight['departure_at'].replace('Z', '+00:00')).strftime('%H:%M')
            except (ValueError, AttributeError):
                pass

        partner_url = f"https://www.aviasales.ru/search/{origin_iata}{date_url_str}{dest_iata}1?marker={PARTNER_MARKER}"

        message += (
            f"*{results_count + 1}\\. Цена: {escape_markdown_v2(str(price))} RUB*\n"
            f"  ✈️ {escape_markdown_v2(airline)} \\(Рейс {escape_markdown_v2(str(flight_number))}\\)\n"
            f"  ⏰ Вылет: {escape_markdown_v2(dep_time)}\n"
            f"  [➡️ Найти на Aviasales]({partner_url})\n\n"
        )
        results_count += 1

    if results_count == 0:
        await update.message.reply_text(f"Прямых рейсов на *{escaped_display_date}* не найдено\\.",
                                        parse_mode="MarkdownV2")
        return

    if len(flights_data) > results_count:
        partner_url = f"https://www.aviasales.ru/search/{origin_iata}{date_url_str}{dest_iata}1?marker={PARTNER_MARKER}"
        message += f"_Показаны первые {results_count} из {len(flights_data)} найденных вариантов\\._\n"

    try:
        await update.message.reply_text(message, parse_mode="MarkdownV2", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Ошибка при отправке MarkdownV2: {e}")


def main():
    if not all([TELEGRAM_BOT_TOKEN, TRAVELPAYOUTS_API_KEY]):
        sys.exit("!!! Ошибка: Токены не установлены.")

    try:
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    except InvalidToken:
        sys.exit("!!! Ошибка: Токен Telegram неверен.")
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("flights", flights))

    print("\n✈️🤖 Бот запущен! Нажмите Ctrl+C для остановки.\n")
    application.run_polling()



if __name__ == '__main__':
    main()
