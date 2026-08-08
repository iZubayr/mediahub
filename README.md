# MediaHub

MediaHub — Telegram bot orqali public Instagram Reel, video, rasm va carousel media’larini yuklab beruvchi MVP.

## Hozirgi imkoniyatlar

- Instagram URL validatsiyasi; **bitta xabarda bir nechta havola** yuborilsa,
  har biri mustaqil, alohida rate-limit/navbat orqali qayta ishlanadi;
- public Reel, video, rasm va carousel uchun downloader adapteri —
  `yt-dlp` orqali, `ignore_no_formats_error=True` bilan carousel’dagi har
  bir slaydni alohida qayta ishlaydi; format topilmagan (rasm) slaydlar
  yt-dlp’ning o‘z `thumbnails` ma’lumotidan tiklanadi — carousel’ning
  **barcha** elementlari (Instagram’ning tashqi GraphQL’iga
  murojaat qilmasdan) qaytariladi. Faqat yagona-rasmli post uchun (yt-dlp
  o‘zi "video yo‘q" deb butun so‘rovni rad etganda) `instaloader`, so‘ng
  Open Graph scrape ikkinchi darajali fallback sifatida ishlatiladi;
- har bir yuborilgan media’ning tagyozuvi (caption) ikki qismli: original
  postga yashiringan havola (matni tahrirlanadi, admin panel orqali
  butunlay yoqib/o‘chirib qo‘yish ham mumkin) + pastda oddiy caption matni;
- stream-first Telegram upload (`URLInputFile`);
- stream ishlamasa, chunked temporary-file fallback;
- Postgres (Supabase) asosidagi queue va cheklangan worker pool — Redis kerak emas;
- 100+ parallel so‘rovda queue limit, rate limit va backpressure;
- foydalanuvchi uchun faol job limiti va kunlik limit;
- retry/fallback, timeout, cleanup va xatolik xabarlari;
- majburiy obuna (force-subscribe) — kanal(lar)ga qo‘shilmagan foydalanuvchi botdan foydalana olmaydi;
- **reply-keyboard admin panel tugmasi** — `/admin` yozish shart emas,
  `/start`dan keyin matn maydoni tepasida doim ko‘rinib turadigan "🛠 Admin
  panel" tugmasi bosilganda panel to‘g‘ridan-to‘g‘ri ochiladi (faqat
  adminlarga ko‘rinadi);
- statistika, broadcast, kanal boshqaruvi, matn va rate-limit tahrirlash —
  bittasi xabar bo‘lib ketmasdan, bitta xabar ichida navigatsiya qilinadi;
- foydalanuvchiga chiqadigan barcha matnlar (salomlashuv, yordam, xato
  xabarlari va h.k.) admin panel orqali kodga tegmasdan tahrirlanadi;
- rate limitlar (daqiqalik so‘rov, foydalanuvchi boshiga faol job, kunlik
  limit, navbat hajmi) `.env`ga tegmasdan admin panel orqali jonli
  o‘zgartiriladi;
- **standalone rejimda navbatni chetlab o‘tish**: hech bir worker band
  bo‘lmasa, so‘rov Postgres navbatiga yozilmasdan to‘g‘ridan-to‘g‘ri
  ishga tushadi — faqat real yuklama bo‘lganda navbat ishlatiladi;
- **tezlik optimallashtirishlari**: daqiqalik va kunlik rate-limit
  tekshiruvlari ketma-ket emas, parallel (`asyncio.gather`) bajariladi;
  majburiy obuna bir nechta kanal bo‘lsa, ularning barchasi ham parallel
  tekshiriladi (avval ketma-ket, har biri alohida Telegram so‘rovi edi);
  rate-limit jadvalini tozalash endi har bir xabarda emas, background
  tsiklda (2 daqiqada bir marta) bajariladi; matn/limit/kanal keshlari
  60 soniyagacha uzaytirildi, admin tahrirlasa esa darhol (keshni
  kutmasdan) bekor qilinadi; broadcast xabarlari endi partiya ichida
  parallel yuboriladi (avval bittalab, endi 20 tadan bir vaqtda);
- **bitta process ichida polling + worker** (`app/standalone.py`) —
  alohida webhook Site’siz, faqat bitta Service’da to‘liq ishlaydi;
- worker xato bo‘lsa to‘xtamaydi — har bir tsikl va har bir worker
  supervisor bilan o‘ralgan, muammo faqat log’ga yoziladi;
- baza ulanishi Supabase pooler tomonidan uzilib qolsa, avtomatik bir marta
  qayta uriniladigan `acquire_with_retry` yordamchisi;
- `/health` endpoint (webhook rejimida);
- Telegram webhook va webhook-secret validation.

Private kontent va story qasddan qo‘llab-quvvatlanmaydi — bular Instagram
login sessiyasi talab qiladi, va bunday sessiyani botga ulash bot egasining
shaxsiy Instagram hisobini bloklanish xavfiga qo‘yardi.

## Admin panel

`.env` faylida faqat admin ro'yxatini beriladi:

```env
ADMIN_IDS=123456789,987654321
```

`ADMIN_IDS` ro‘yxatidagi Telegram ID’lar botga `/admin` yozganda **yoki**
`/start` dan keyin matn maydoni tepasida doim ko‘rinib turadigan
**"🛠 Admin panel"** tugmasini bosganda tugmali panelni ko‘radi. Tugma —
oddiy reply-keyboard, bosilganda uning matni oddiy xabar sifatida keladi
va bot buni ushlab, panelni to‘g‘ridan-to‘g‘ri ochadi (buyruq yozish yoki
Menu’dagi taklifni tanlab, alohida Yuborish bosish kerak emas). Faqat
adminlarga ko‘rinadi — oddiy foydalanuvchilar bu tugmani ko‘rmaydi.

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
  - Yuklangan har bir media faylning tagyozuvi (caption) ikki qismdan
    iborat va ikkalasi ham alohida tahrirlanadi: **«Caption’dagi havola
    matni»** — original Instagram postiga yashiringan havola sifatida
    tepada chiqadigan matn (masalan «Video havolasi»), bosilganda original
    postga o‘tkazadi; **«Media fayl tagyozuvi (caption)»** — undan pastda,
    oddiy matn sifatida chiqadigan qism. Telegram media (rasm/video)
    caption’ida havola preview ko‘rsatilmaydi (bu Telegram’ning o‘zining
    cheklovi) — faqat bosilganda ochiladi.
- **⚙️ Rate limit sozlamalari** — daqiqalik so‘rov limiti, foydalanuvchi
  boshiga faol yuklashlar soni, kunlik yuklash limiti, va navbat hajmi
  limitini `.env`ga tegmasdan, panel orqali jonli o‘zgartirish. Har bir
  qiymat ruxsat etilgan oralig‘i bilan ko‘rsatiladi; ↩️ orqali `.env`dagi
  standart qiymatga qaytarish mumkin. Bu qiymatlar hozircha admin
  tahrirlagandan keyin darhol (15 soniyalik keshdan so‘ng) kuchga kiradi.
- **🔍 Foydalanuvchilar** — ID, @username yoki ism bo‘yicha qidiruv
  (botga hech bo‘lmasa bir marta yozgan barcha foydalanuvchilar orasidan).
  Topilgan foydalanuvchini **⭐ Ro‘yxatga qo‘shish** bilan «kuzatiladigan»
  qilib belgilash mumkin — shundan keyingina uning yuklagan har bir
  post/reel havolasi va sanasi saqlanadi (**🗂 Tarixni ko‘rish**). Boshqa
  hech bir foydalanuvchining yuklash tarixi saqlanmaydi — bu ro‘yxat
  qasddan kichik va boshqariladigan qolishi uchun (Supabase Free
  tarifida cheksiz o‘sadigan log emas). **📋 Ro‘yxat** — hozir
  kuzatilayotgan barcha foydalanuvchilarni ko‘rsatadi.

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

## Ishga tushirish rejimlari

Python 3.12 va Postgres (Supabase yoki lokal) kerak bo‘ladi. Redis
umuman ishlatilmaydi.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Standalone (tavsiya etiladi — bitta process, polling + worker)

```powershell
python -m app.standalone
```

Bitta process ichida bot ham xabar qabul qiladi (polling), ham
navbatdagi yuklash vazifalarini bajaradi. Alohida webhook server yoki
Site kerak emas — production’da ham shu rejim tavsiya etiladi (qarang:
`DEPLOY_ALWAYSDATA.md`).

### Ajratilgan polling + worker

```powershell
python -m app.bot
python -m app.worker
```

Ikkita alohida process — bot faqat xabar qabul qilib navbatga qo‘yadi,
worker alohida navbatni ishlaydi. Ko‘p yuklamali sozlashlarda foydali,
lekin ikkita process’ni alohida kuzatish kerak.

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
