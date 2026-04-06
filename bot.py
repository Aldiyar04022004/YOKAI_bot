import asyncio
import httpx
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, MessageEntityType

# ── Конфигурация ──────────────────────────────────────────────────────────────

API_BOT        = os.getenv("BOT_TOKEN",         "YOUR_BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "YOUR_OPENROUTER_KEY")
AI_MODEL       = os.getenv("MODEL",              "deepseek/deepseek-r1:free")

BOT_USERNAME: str = ""  # заполняется при старте через get_me()

SYSTEM_PROMPT = (
    'You are Yuna Tanaka, callsign "Yokai" — Sergeant of the 75th Ranger Regiment\'s '
    "Regimental Reconnaissance Company, an elite special operations force operating under "
    "Joint Special Operations Command. Half-Japanese, raised on discipline and silence. "
    "You move like a ghost, think three steps ahead, and talk only when words carry weight. "
    "Your tone is dry, direct, occasionally sardonic — never warm, never loud. "
    "You don't explain yourself twice. Sua Sponte. Rangers Lead the Way."
)

# ── Инициализация ─────────────────────────────────────────────────────────────

bot = Bot(token=API_BOT)
dp  = Dispatcher()

ai_history: dict[int, list] = {}  # chat_id -> messages


# ── Определение триггера ──────────────────────────────────────────────────────

def is_bot_triggered(message: Message) -> bool:
    if message.chat.type == "private":
        return True

    if (message.reply_to_message
            and message.reply_to_message.from_user
            and message.reply_to_message.from_user.username
            and message.reply_to_message.from_user.username.lower() == BOT_USERNAME.lower()):
        return True

    if message.entities:
        for entity in message.entities:
            if entity.type == MessageEntityType.MENTION:
                mention = message.text[entity.offset : entity.offset + entity.length]
                if mention.lstrip("@").lower() == BOT_USERNAME.lower():
                    return True

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

    # В группе без явного триггера — спрашиваем AI стоит ли отвечать
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


# ── Хендлеры ─────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("На месте.")


@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    ai_history.pop(message.chat.id, None)
    await message.answer("🗑 История диалога очищена.")


@dp.message(F.text)
async def handle_text(message: Message):
    triggered = is_bot_triggered(message)
    display   = get_display_name(message.from_user)

    reply = await ask_ai(message.chat.id, message.text, display, force_reply=triggered)
    if reply:
        await message.bot.send_chat_action(message.chat.id, "typing")
        await message.answer(reply)


# ── Запуск ────────────────────────────────────────────────────────────────────

async def main():
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username or ""
    print(f"Nuke deployed — Sergeant Yokai online (@{BOT_USERNAME})")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
