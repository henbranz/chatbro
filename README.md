# Chat Bro

Chat Bro הוא MVP לצ'אט מודרני עם Streamlit, FastAPI ו-SQLite.

הארכיטקטורה נשארת מופרדת:

```text
User -> Streamlit frontend -> FastAPI backend -> SQLite database
```

ה-frontend אינו ניגש למסד הנתונים ישירות. כל הפעולות עוברות דרך HTTP JSON אל ה-backend, ורק FastAPI קורא וכותב ל-SQLite.

המערכת כוללת הרשמה/התחברות, רשימת שיחות, בחירת שיחה, שליחת הודעות, רענון הודעות באמצעות polling, וחיפוש חופשי בתוכן ההודעות.

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
python run_local.py
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

אם הפורטים תפוסים:

Mac/Linux:

```bash
CHAT_BRO_BACKEND_PORT=8005 CHAT_BRO_FRONTEND_PORT=8505 python run_local.py
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

לפי דרישת ה-PRD לפרויקט הדמו, משתמשים חדשים נשמרים גם עם סיסמה גלויה בשדה `password`. זה מתאים לפרויקט לימודי בלבד ולא מתאים לפרודקשן.

הודעות חדשות נשמרות עם `user_id`, `role`, `message_content`, ו-`conversation_id`, כדי לתמוך בצ'אטים נפרדים לכל משתמש. טבלת `conversations` מוסיפה מזהה מספרי לשיחות עבור ה-API החדש, תוך שמירה על תאימות לשיחות קיימות.

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
