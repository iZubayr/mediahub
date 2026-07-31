# MediaHub

MediaHub — Telegram bot orqali public Instagram Reel, video, rasm va carousel media’larini yuklab beruvchi MVP.

## Hozirgi imkoniyatlar

- Instagram URL validatsiyasi;
- public Reel, video, rasm va carousel uchun downloader adapteri;
- stream-first Telegram upload (`URLInputFile`);
- stream ishlamasa, chunked temporary-file fallback;
- Postgres (Supabase) asosidagi queue va cheklangan worker pool — Redis kerak emas;
- 100+ parallel so‘rovda queue limit, rate limit va backpressure;
- foydalanuvchi uchun faol job limiti va kunlik limit;
- retry/fallback, timeout, cleanup va xatolik xabarlari;
- majburiy obuna (force-subscribe) — kanal(lar)ga qo‘shilmagan foydalanuvchi botdan foydalana olmaydi;
- **inline tugmali admin panel** (`/admin`) — statistika, broadcast, kanal
  boshqaruvi va foydalanuvchi matnlarini tahrirlash, bittasi xabar bo‘lib
  ketmasdan, bitta xabar ichida navigatsiya qilinadi;
- foydalanuvchiga chiqadigan barcha matnlar (salomlashuv, yordam, xato
  xabarlari va h.k.) admin panel orqali kodga tegmasdan tahrirlanadi;
- `/health` endpoint;
- Telegram webhook va webhook-secret validation.

Private kontent va story qasddan qo‘llab-quvvatlanmaydi — bular Instagram
login sessiyasi talab qiladi, va bunday sessiyani botga ulash bot egasining
shaxsiy Instagram hisobini bloklanish xavfiga qo‘yardi.

## Admin panel

`.env` faylida faqat admin ro'yxatini beriladi:

```env
ADMIN_IDS=123456789,987654321
```

`ADMIN_IDS` ro‘yxatidagi Telegram ID’lar botga `/admin` yozganda tugmali
panelni ko‘radi:

- **📊 Statistika** — jami/faol/so‘nggi 24 soatdagi foydalanuvchilar soni.
- **📢 Xabar yuborish** — matn so‘raladi, so‘ng barcha (bloklamagan)
  foydalanuvchilarga kichik partiyalarda, Telegram flood-limitidan pastda
  yuboriladi. `TelegramRetryAfter` chiqsa avtomatik kutib qayta urinadi,
  `TelegramForbiddenError` (bot bloklangan) chiqsa foydalanuvchi
  "bloklangan" deb belgilanadi va keyingi broadcast’larda o‘tkazib
  yuboriladi.
- **📡 Majburiy obuna kanallari** — ro‘yxatni ko‘rish, ➕ tugmasi orqali
  kanal qo‘shish, 🗑 tugmasi orqali o‘chirish. Kanal qo‘shishda bot avval
  o‘sha kanalda haqiqatan ham admin ekanini tekshiradi va bo‘lmasa aniq xato
  qaytaradi (shu tufayli keyinroq "majburiy obuna hech kimga ishlamayapti"
  degan holatning oldi olinadi). Ro‘yxat bo‘sh bo‘lsa, tekshiruv butunlay
  o‘chirilgan hisoblanadi — hech kim bloklanmaydi.
- **✏️ Matnlarni tahrirlash** — foydalanuvchiga chiqadigan har bir xabarni
  (salomlashuv, yordam, limit xabarlari, yuklash holati va h.k.) ro‘yxatdan
  tanlab, joriy matnini ko‘rib, ✏️ orqali yangi matn yozib almashtirish yoki
  ↩️ orqali standart matnga qaytarish mumkin. O‘zgarishlar bazada saqlanadi
  va darhol kuchga kiradi — kodni qayta deploy qilish shart emas.

Panel ichidagi barcha tugmalar **shu xabarning o‘zini** (`edit_message_text`
orqali) yangilaydi — har bosishda yangi xabar kelib, chatni to‘ldirmaydi.
Eski `/stats` va `/channels` matn-buyruqlari ham qisqa yo‘l sifatida ishlaydi.

## Ishga tushirish

1. Telegram’da bot yarating va token oling.
2. `.env` ichidagi `TELEGRAM_BOT_TOKEN` qiymatini to‘ldiring.
3. Servislarni ishga tushiring:

```powershell
docker compose up --build
```

Health-check:

```text
http://localhost:8080/health
```

## Lokal polling rejimi

Python 3.12 va Redis kerak bo‘ladi.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.bot
python -m app.worker
```

`.env` lokal rejimda `REDIS_URL=redis://localhost:6379/0` bo‘lishi kerak.

## Webhook rejimi

Webhook uchun public HTTPS URL va maxfiy secret kerak:

```env
PUBLIC_BASE_URL=https://your-domain.example
WEBHOOK_PATH=/telegram/webhook
TELEGRAM_WEBHOOK_SECRET=kamida-16-belgidan-iborat-maxfiy-string
```

Ishga tushirish:

```powershell
uvicorn app.webhook:app --host 0.0.0.0 --port 8080
python -m app.worker
```

Telegram webhook faqat HTTPS URL’ga ulanadi. AlwaysData service sozlamalari uchun [DEPLOY_ALWAYSDATA.md](DEPLOY_ALWAYSDATA.md) fayliga qarang.

## Testlar

```powershell
pytest
```

## Muhim arxitektura qarori

Bot process’i faqat URL’ni validatsiya qilib, job’ni Postgres jadvaliga
qo‘shadi (`SELECT ... FOR UPDATE SKIP LOCKED` orqali). Og‘ir downloader va
Telegram upload ishlari worker process’ida bajariladi. Bu 100 ta foydalanuvchi
birdan link yuborganda bot update loop’ining qotib qolishining oldini oladi.

Avval `URLInputFile` orqali to‘g‘ridan-to‘g‘ri stream upload qilinadi. Bu ishlamasa, media cheklangan bufferlar bilan vaqtinchalik faylga yoziladi va upload tugagach darhol o‘chiriladi.

**Worker chidamliligi:** har bir worker tsikli (`queue.claim()` va
`process_job()`) o‘zining try/except bilan o‘ralgan — vaqtinchalik baza yoki
tarmoq xatosi butun worker process’ini o‘ldirmaydi, faqat log yozib, keyingi
tsiklda davom etadi. Bundan tashqari Postgres pool uzoq turgan (idle)
ulanishlarni har 5 daqiqada avtomatik yangilaydi
(`max_inactive_connection_lifetime=300`), chunki Supabase pooler orqali
uzoq vaqt ishlatilmagan ulanish jim uzilib qolishi mumkin.

## Keyingi bosqichlar

- media group uchun optimallashtirilgan yuborish;
- monitoring va alertlar;
- yanada to‘liq integration testlar;
- downloader adapterlarini alohida provider interfeysiga ajratish.

AlwaysData’ga joylashtirish bo‘yicha batafsil ko‘rsatma: [DEPLOY_ALWAYSDATA.md](DEPLOY_ALWAYSDATA.md)
