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
    "Ты Юна Танака, позывной «Йокай». Сержант 75-го парашютно-десантного "
    "разведывательного полка ВС США. Говоришь коротко, по делу, без лишних слов. "
    "Когда теряешь терпение, разговариваешь с матом, а характер сквернеет."
    "Тон сухой, чёрным юмором. Sua Sponte."
    "Ты участвуешь в групповом чате."
    "Обращайся к пользователям по их именам когда уместно. Ты знаешь только тех, кто написал в этом чате."
)


# ── Инициализация ─────────────────────────────────────────────────────────────

bot = Bot(token=API_BOT)
dp  = Dispatcher()

# История AI-диалогов: user_id → [{'role': ..., 'content': ...}]
ai_history: dict[int, list] = {}

# ── AI (OpenRouter) ───────────────────────────────────────────────────────────

async def ask_ai(chat_id: int, user_text: str, display_name: str, force_reply: bool = False) -> str | None:
    history = ai_history.setdefault(chat_id, [])

    history.append({
        "role": "user",
        "content": f"[{display_name}]: {user_text}"
    })
    # Не даём истории расти бесконечно
    if len(history) > 100:
        history[:] = history[-100:]

    # Если триггера нет — спрашиваем AI, стоит ли вообще отвечать
    if not force_reply:
        recent = history[-10:]
        probe_messages = [
            {"role": "system", "content": (
                SYSTEM_PROMPT + "\n\n"
                "Сейчас ты наблюдаешь за чатом. Тебя не позвали напрямую.\n"
                "Реши: стоит ли тебе вмешаться прямо сейчас?\n"
                "Ответь ТОЛЬКО одним словом: ДА или НЕТ.\n"
                "Вмешивайся если: тебя обсуждают, задают вопрос в воздух, "
                "ситуация явно требует твоей реплики по характеру.\n"
                "Не вмешивайся если: люди просто болтают между собой."
            )},
            *recent
        ]
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={"model": AI_MODEL, "messages": probe_messages, "max_tokens": 5},
                )
                decision = resp.json()["choices"][0]["message"]["content"].strip().upper()
                print(f"[AutoReply decision]: {decision}")
                if "ДА" not in decision:
                    return None  # Молчим
        except Exception as e:
            print(f"[AutoReply probe error]: {e}")
            return None

    # Генерируем полноценный ответ
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history[-20:]

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                },
                json={"model": AI_MODEL, "messages": messages},
            )
            data = resp.json()
            print(f"[OpenRouter] status={resp.status_code} body={data}")

            if "choices" not in data:
                error_info = data.get("error", {})
                return f"⚠️ OpenRouter error: {error_info.get('message', data)}"

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
