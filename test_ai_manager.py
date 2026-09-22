import asyncio


from ai.manager import (
    configured_providers,
    generate,
)


async def main():

    providers = (
        configured_providers()
    )


    print()
    print(
        "Настроенные AI:"
    )


    for name, data in (
        providers.items()
    ):

        print(
            f"✅ {name}: "
            f"{data['model']}"
        )


    print()

    print(
        "Отправляем тест..."
    )


    result = await generate(

        system_prompt=(
            "Ответь очень коротко."
        ),

        user_text=(
            "Напиши: система AI работает."
        ),
    )


    print()


    if result.ok:

        print(
            "✅ УСПЕШНО"
        )

        print(
            "Провайдер:",
            result.provider,
        )

        print(
            "Модель:",
            result.model,
        )

        print(
            "Ответ:",
            result.text,
        )

    else:

        print(
            "❌ ВСЕ AI НЕДОСТУПНЫ"
        )

        print(
            "Ошибка:",
            result.error_type,
        )


if __name__ == "__main__":

    asyncio.run(
        main()
    )