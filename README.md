# Chat Bro

Chat Bro הוא MVP לצ'אט מודרני עם Streamlit, FastAPI ו-SQLite.

הארכיטקטורה נשארת מופרדת:

```text
User -> Streamlit frontend -> FastAPI backend -> SQLite database
```

ה-frontend אינו ניגש למסד הנתונים ישירות. כל הפעולות עוברות דרך HTTP JSON אל ה-backend, ורק FastAPI קורא וכותב ל-SQLite.

המערכת כוללת הרשמה/התחברות, רשימת שיחות, בחירת שיחה, שליחת הודעות, רענון הודעות באמצעות polling, חיפוש חופשי בתוכן ההודעות, וצ'אטים קבוצתיים עם Chat Bro.

## מבנה תיקיות

```text
simplechat/
├── requirements.txt
├── README.md
├── backend/
│   ├── __init__.py
│   ├── database.py
│   └── main.py
└── frontend/
    └── app.py
```

## יצירת סביבה וירטואלית

Mac/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell:

```powershell
py -m venv .venv
```

אם PowerShell חוסם הפעלת scripts, אפשר להריץ את הפקודות דרך Python של הסביבה בלי להפעיל `Activate.ps1`.

## התקנת תלויות

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## הרצה מקומית מהירה

אחרי התקנת התלויות, אפשר להריץ את ה-backend וה-frontend יחד מכל מערכת הפעלה:

Mac/Linux:

```bash
python3 run_local.py
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe run_local.py
```

ברירת המחדל:

```text
Backend:  http://127.0.0.1:8000
Frontend: http://127.0.0.1:8501
```

אם אחד הפורטים תפוס, `run_local.py` יבחר אוטומטית את הפורט הפנוי הבא וידפיס את הכתובת הנכונה לפתיחה בדפדפן.

אפשר גם לבחור פורטים ידנית:

Mac/Linux:

```bash
CHAT_BRO_BACKEND_PORT=8005 CHAT_BRO_FRONTEND_PORT=8505 python3 run_local.py
```

Windows PowerShell:

```powershell
$env:CHAT_BRO_BACKEND_PORT="8005"
$env:CHAT_BRO_FRONTEND_PORT="8505"
.\.venv\Scripts\python.exe run_local.py
```

## Gemini API

אין להכניס מפתח API לקוד.

ה-backend קורא את המפתח ממשתנה סביבה:

```powershell
$env:GEMINI_API_KEY="your-gemini-api-key"
```

אפשר להחליף מודל דרך:

```powershell
$env:GEMINI_MODEL="gemini-2.5-flash"
```

אם `GEMINI_API_KEY` לא מוגדר, Chat Bro משתמש בתשובות rule-based מקומיות.

## הרצת ה-backend

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

ה-API ירוץ בכתובת:

```text
http://127.0.0.1:8000
```

## הרצת ה-frontend

פתחו טרמינל נוסף:

```powershell
.\.venv\Scripts\python.exe -m streamlit run frontend/app.py
```

ה-UI ירוץ בדרך כלל בכתובת:

```text
http://localhost:8501
```

אם ה-backend רץ בפורט אחר, אפשר להגדיר ל-frontend את כתובת ה-API:

```powershell
$env:CHAT_BRO_API_BASE_URL="http://127.0.0.1:8003"
```

## בדיקה ידנית

1. הפעילו את ה-backend.
2. הפעילו את Streamlit.
3. צרו משתמש חדש.
4. ודאו שמופיעה רשימת שיחות בצד.
5. בחרו שיחה ושלחו הודעה.
6. ודאו שמופיע typing indicator.
7. המתינו לתשובת הבוט וודאו שהיא מופיעה אוטומטית באמצעות polling.
8. השתמשו בכפתור Search וחפשו טקסט מתוך הודעה קיימת.
9. רעננו את הדף וודאו שהשיחות וההודעות נשארות.
10. התחברו עם משתמש אחר וודאו שהוא לא רואה את ההודעות של המשתמש הראשון.

## בדיקת צ'אט קבוצתי

1. צרו שני משתמשים שונים, למשל `parent1` ו-`parent2`, עם כתובות אימייל שונות.
2. התחברו כ-`parent1`.
3. באזור `MyGroups`, צרו קבוצה חדשה עם שם ברור.
4. ודאו שהקבוצה מופיעה ברשימת הקבוצות וש-`parent1` יכול לשלוח הודעה.
5. הזמינו את `parent2` דרך שדה ההזמנה בתוך הקבוצה באמצעות כתובת האימייל שאיתה הוא נרשם.
6. התחברו כ-`parent2` במחשב או דפדפן אחר.
7. ודאו שההזמנה מופיעה באזור `Invitations` בתוך `MyGroups`.
8. לחצו `Accept` וודאו שהקבוצה מופיעה לרשימת הקבוצות של `parent2`.
9. שלחו הודעה כ-`parent2` וודאו שההודעה מופיעה גם אצל `parent1`.
10. ודאו שהבוט עונה בתוך אותה קבוצה.
11. שלחו הודעה נוספת והמתינו ל-polling; ודאו שאין שכפול הודעות.
12. נסו לפתוח הודעות קבוצה עם משתמש שאינו חבר דרך ה-API; ה-backend אמור להחזיר 403.

## בדיקות אוטומטיות

יש בדיקת backend בסיסית לצ'אטים קבוצתיים:

```bash
python -m unittest tests.test_group_api
```

הבדיקה משתמשת במסד SQLite זמני, ולכן היא לא נוגעת ב-`messages.db` המקומי.

## מסד נתונים

SQLite נשמר מקומית בקובץ:

```text
messages.db
```

אפשר לשנות את מיקום מסד הנתונים דרך משתנה סביבה:

```text
DATABASE_URL=sqlite:///./messages.db
```

המערכת כוללת טבלאות `users`, `conversations`, `conversation_participants`, ו-`messages`.

לצ'אטים קבוצתיים נוספו טבלאות נפרדות כדי לא לשבור את זרימת הצ'אט הרגילה:

```text
group_chats
group_members
group_invitations
group_messages
```

לפי דרישת ה-PRD לפרויקט הדמו, משתמשים חדשים נשמרים גם עם סיסמה גלויה בשדה `password`. זה מתאים לפרויקט לימודי בלבד ולא מתאים לפרודקשן.

טבלת `users` כוללת גם שדה `email` ייחודי למשתמשים חדשים, כדי שאפשר יהיה להזמין משתמשים לקבוצות לפי כתובת אימייל רשומה.

הודעות חדשות נשמרות עם `user_id`, `role`, `message_content`, ו-`conversation_id`, כדי לתמוך בצ'אטים נפרדים לכל משתמש. טבלת `conversations` מוסיפה מזהה מספרי לשיחות עבור ה-API החדש, תוך שמירה על תאימות לשיחות קיימות.

## API לצ'אטים קבוצתיים

```text
POST /groups/create
GET  /groups/my
POST /groups/{group_id}/invite
GET  /invitations/my
POST /invitations/{invitation_id}/accept
POST /invitations/{invitation_id}/decline
GET  /groups/{group_id}/messages
GET  /groups/{group_id}/messages/new?after_id=...
POST /groups/{group_id}/messages
```

כל קריאה שמחזירה או שומרת הודעות קבוצה מאמתת שהמשתמש חבר בקבוצה. הזמנות אפשר לקבל או לדחות רק על ידי המשתמש שהוזמן.

## Deployment ל-Render

הפרויקט כולל `render.yaml` עם שני שירותים:

```text
chat-bro-api  -> FastAPI + SQLite persistent disk
chat-bro-web  -> Streamlit frontend
```

ב-Render, צרו Blueprint מה-repository. אם שיניתם את שם שירות ה-API, עדכנו את `CHAT_BRO_API_BASE_URL` בשירות `chat-bro-web` לכתובת ה-Render של ה-API.

ה-backend מוגדר עם persistent disk כדי שה-SQLite לא יימחק בריסטארט. ב-Render זה דורש plan שתומך בדיסק.

לפרודקשן עם Gemini, הגדירו ב-Render את:

```text
GEMINI_API_KEY
```
