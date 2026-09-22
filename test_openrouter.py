import asyncio

from ai_service import get_ai_reply


async def main():

    print(
        "Проверяем OpenRouter..."
    )

    answer = await get_ai_reply(
        "Привет! Ответь коротко: "
        "если ты получил это сообщение, "
        "напиши 'Всё работает'."
    )

    if answer:

        print()
        print("✅ OPENROUTER РАБОТАЕТ")
        print()
        print("Ответ AI:")
        print(answer)

    else:

        print()
        print("❌ OpenRouter не ответил.")
        print(
            "Проверь API ключ и терминал."
        )


if __name__ == "__main__":

    asyncio.run(
        main()
    )