# Запуск AutoReplyBot на Linux-сервере

Два варианта: **без root/sudo** (обычный пользователь) и **с root** (systemd).
Для вашего случая используйте вариант A.

Требуется Python **3.11+** (проверка: `python3 --version`).

---

## ВАРИАНТ A — без root и sudo (всё в домашней папке)

### A1. Загрузить код

```bash
mkdir -p ~/autoreplybot
cd ~/autoreplybot
# скопируйте сюда файлы проекта (bot.py, database.py, ... requirements.txt)
# например через git clone или scp/sftp
```

### A2. Виртуальное окружение (sudo не нужно)

```bash
cd ~/autoreplybot
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### A3. Конфигурация

```bash
cp .env.example .env
nano .env     # BOT_TOKEN, ADMIN_IDS, ключи AI-провайдеров
```

База создастся автоматически рядом с `bot.py` (`autoreply.db`, режим WAL).
`.env` и `*.db` уже в `.gitignore`.

### A4. Запуск

**Простой запуск в фоне (nohup):**

```bash
cd ~/autoreplybot
nohup .venv/bin/python bot.py > bot.log 2>&1 &
echo $! > bot.pid          # запомнили PID
```

Остановить:

```bash
kill "$(cat ~/autoreplybot/bot.pid)"
```

Логи:

```bash
tail -f ~/autoreplybot/bot.log
```

**Или через tmux/screen** (удобнее — можно «зайти» в сессию):

```bash
tmux new -s bot
source ~/autoreplybot/.venv/bin/activate
python ~/autoreplybot/bot.py
# отключиться от сессии: Ctrl+b затем d
# вернуться:  tmux attach -t bot
```

### A5. Автозапуск без root

Вариант 1 — **user systemd** (если админ включил `linger`):

```bash
mkdir -p ~/.config/systemd/user
# в файле autoreplybot-user.service замените ВАШ_ЛОГИН на свой логин
nano autoreplybot-user.service
cp autoreplybot-user.service ~/.config/systemd/user/autoreplybot.service
systemctl --user daemon-reload
systemctl --user enable --now autoreplybot
systemctl --user status autoreplybot
journalctl --user -u autoreplybot -f
```

Вариант 2 — **cron @reboot** (работает почти всегда):

```bash
crontab -e
# добавьте строку:
@reboot cd /home/ВАШ_ЛОГИН/autoreplybot && nohup .venv/bin/python bot.py > bot.log 2>&1 &
```

> Важно: с одним токеном должен работать **только один** процесс бота.
> Не запускайте вторую копию — Telegram будет рвать одно из соединений.

---

## ВАРИАНТ B — с root (системный systemd)

```bash
sudo apt update && sudo apt install -y python3 python3-venv git
sudo mkdir -p /opt/autoreplybot && sudo cp -r . /opt/autoreplybot
cd /opt/autoreplybot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env

sudo useradd --system --no-create-home --shell /usr/sbin/nologin autoreply
sudo chown -R autoreply:autoreply /opt/autoreplybot
sudo cp autoreplybot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now autoreplybot
journalctl -u autoreplybot -f
```

---

## Обновление кода

```bash
cd ~/autoreplybot        # или /opt/autoreplybot
# замените файлы
# перезапустите процесс (kill + nohup) или:
systemctl --user restart autoreplybot     # вариант A5-1
sudo systemctl restart autoreplybot       # вариант B
```

---

## Размер сервера, нагрузка и затраты

### Минимальные и рекомендуемые ресурсы

| Ресурс | Минимум | Комфортно |
|--------|---------|-----------|
| CPU    | 1 vCPU  | 1–2 vCPU  |
| RAM    | 512 МБ  | 1–2 ГБ    |
| Диск   | 5 ГБ    | 10–20 ГБ SSD |
| Сеть   | исходящая разрешена (long-polling) | — |

Сам процесс бота в простое занимает **~90–150 МБ RAM** и почти **0% CPU**.
Открытые входящие порты **не нужны** — бот сам «тянет» обновления из
Telegram (исходящее HTTPS-соединение).

### Что реально ограничивает нагрузку

Узкое место — не CPU, а:
1. **одно long-polling соединение** с Telegram (один инстанс бота);
2. **задержки внешних AI-API** (ожидание асинхронное, процесс не блокирует);
3. **запись в SQLite** (сглажена режимом WAL).

Практически **1 vCPU / 1 ГБ** уверенно держит **сотни — 1–2 тысячи**
активных пользователей, потому что большинство сообщений попадают в
FAQ/запасной ответ (без AI) или ждут внешний AI асинхронно.

Защита от перегрузки уже встроена:
- дневные лимиты AI на пользователя (Free 5 / Premium 25) —
  ограничивают число обращений к платным API;
- `broadcast_interval` (по умолчанию 1 с) — рассылка не словит
  спам-блок Telegram;
- failover + cooldown провайдеров.

### Затраты

- **Сервер:** дешёвый VPS ≈ **3–5 €/мес** (Hetzner, Contabo и т.п.).
  Подойдёт любой shared/ VPS с Python 3.11+ и исходящим интернетом.
- **AI:** главные расходы. На бесплатных провайдерах
  (openrouter/free, gemini-2.5-flash-lite, groq, deepseek) ≈ **0 $**
  в пределах их суточных квот. Платно только если включите
  OpenAI/своих провайдеров.
- **Трафик:** текстовые сообщения — единицы ГБ/мес, пренебрежимо.
- **Telegram Stars:** платят пользователи, сервер это не нагружает.

### Масштабирование дальше

- Держите **один** инстанс бота (несколько копий с одним токеном конфликтуют).
- При росте выше ~нескольких тысяч активных пользователей мигрируйте
  БД на PostgreSQL: слой `database.py` изолирован, замена точечная.
