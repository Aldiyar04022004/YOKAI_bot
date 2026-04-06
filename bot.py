import asyncio
import httpx
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

# ── Конфигурация ──────────────────────────────────────────────────────────────

API_BOT         = os.getenv("BOT_TOKEN", "8746055683:AAGhSAGMDit_8S0aV1M1-5rPkOhD49pr-uo")
OPENROUTER_KEY  = os.getenv("OPENROUTER_API_KEY", "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")
AI_MODEL        = os.getenv("MODEL", "deepseek-v3.1-nex-n1")
BOT_USERNAME: str = "YokaiSoldier_bot"

SYSTEM_PROMPT = (
    "You are Yuna Tanaka, callsign "Yokai" — Sergeant of the 75th Ranger Regiment's Regimental Reconnaissance Company, an elite special operations force operating under Joint Special Operations Command. Half-Japanese, raised on discipline and silence. You move like a ghost, think three steps ahead, and talk only when words carry weight. Your tone is dry, direct, occasionally sardonic — never warm, never loud. You don't explain yourself twice. Sua Sponte. Rangers Lead the Way."
)


# ── Инициализация ─────────────────────────────────────────────────────────────

bot = Bot(token=API_BOT)
dp  = Dispatcher()

# История AI-диалогов: user_id → [{'role': ..., 'content': ...}]
ai_history: dict[int, list] = {}

# ── Определение триггера ──────────────────────────────────────────────────────
 
def is_bot_triggered(message: Message) -> bool:
    """
    Возвращает True если сообщение адресовано боту:
      - личный чат (private)
      - ответ на сообщение бота
      - упоминание @username через entities (регистронезависимо)
      - упоминание @username в тексте (fallback, регистронезависимо)
    """
    # Личный чат — всегда отвечаем
    if message.chat.type == "private":
        return True
 
    # Ответ на сообщение бота
    if (message.reply_to_message
            and message.reply_to_message.from_user
            and message.reply_to_message.from_user.username
            and message.reply_to_message.from_user.username.lower() == BOT_USERNAME.lower()):
        return True
 
    # Упоминание через Telegram entities — самый надёжный способ
    if message.entities:
        for entity in message.entities:
            if entity.type == MessageEntityType.MENTION:
                # Вырезаем текст упоминания из сообщения
                mention_text = message.text[entity.offset : entity.offset + entity.length]
                # Сравниваем без учёта регистра и символа @
                if mention_text.lstrip("@").lower() == BOT_USERNAME.lower():
                    return True
 
    # Fallback: простой поиск в тексте (регистронезависимо)
    if message.text and BOT_USERNAME:
        if f"@{BOT_USERNAME}".lower() in message.text.lower():
            return True
 
    return False
 
 
# ── AI (OpenRouter) ───────────────────────────────────────────────────────────
 
def get_display_name(user) -> str:
    return f"@{user.username}" if user.username else (user.full_name or f"user_{user.id}")
 
 
async def ask_ai(chat_id: int, user_text: str, display_name: str,
                 force_reply: bool = False) -> str | None:
    history = ai_history.setdefault(chat_id, [])
    history.append({"role": "user", "content": f"[{display_name}]: {user_text}"})
    if len(history) > 100:
        history[:] = history[-100:]
 
    # В групповом чате без явного триггера — спрашиваем AI стоит ли отвечать
    if not force_reply:
        probe = [
            {"role": "system", "content": (
                SYSTEM_PROMPT + "\n\n"
                "You are observing a group chat. You were NOT directly addressed.\n"
                "Decide: should you intervene RIGHT NOW?\n"
                "Reply with ONE word only: YES or NO.\n"
                "Intervene if: someone is discussing you, asking a question into the air, "
                "or the situation clearly calls for your character's remark.\n"
                "Stay silent if: people are just chatting among themselves."
            )},
            *history[-10:]
        ]
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENROUTER_KEY}",
                             "Content-Type": "application/json"},
                    json={"model": AI_MODEL, "messages": probe, "max_tokens": 5},
                )
                decision = resp.json()["choices"][0]["message"]["content"].strip().upper()
                print(f"[AutoReply] decision={decision!r}")
                if "YES" not in decision and "ДА" not in decision:
                    return None
        except Exception as e:
            print(f"[AutoReply probe error] {e}")
            return None
 
    # Генерируем ответ
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history[-20:]
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_KEY}",
                         "Content-Type": "application/json"},
                json={"model": AI_MODEL, "messages": messages},
            )
            data = resp.json()
            print(f"[OpenRouter] status={resp.status_code}")
            if "choices" not in data:
                err = data.get("error", {})
                return f"⚠️ OpenRouter error: {err.get('message', data)}"
            reply = data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"⚠️ Ошибка связи: {e}"
 
    history.append({"role": "assistant", "content": reply})
    return reply


# ── Хендлеры команд ───────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "На месте"
    )

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    ai_history.pop(message.chat.id, None)
    await message.answer("🗑 История диалога очищена.")


# ── Основной хендлер сообщений ────────────────────────────────────────────────

def get_display_name(user) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name or f"user_{user.id}"


@dp.message(F.text)
async def handle_text(message: Message):
    is_private = message.chat.type == "private"
    is_mentioned = bool(
        message.text and BOT_USERNAME and f"@{BOT_USERNAME}" in message.text
    )
    is_reply_to_bot = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.username == BOT_USERNAME
    )

    display_name = get_display_name(message.from_user)  # используем готовую функцию
    force = is_private or is_mentioned or is_reply_to_bot

    reply = await ask_ai(message.chat.id, message.text, display_name, force_reply=force)

    if reply:
        await message.bot.send_chat_action(message.chat.id, "typing")  # только если есть что сказать
        await message.answer(reply)


# ── Запуск ────────────────────────────────────────────────────────────────────

async def main():
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username
    print(f"Nuke deployed — Sergeant Yokai online (@{BOT_USERNAME})")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
