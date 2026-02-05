# 🤖 CodeBot MCP Server v2

שרת MCP מורחב לניהול קוד, דפלוי ותפעול — מותאם לחיבור ל-Claude.

---

## ✨ יכולות

### 📝 ניהול Snippets
| כלי | תיאור |
|------|--------|
| `list_snippets` | רשימה עם סינון לפי שפה / תגית / חיפוש |
| `get_snippet` | קבלת snippet בודד |
| `create_snippet` | יצירת snippet חדש |
| `update_snippet` | עדכון snippet קיים |
| `delete_snippet` | מחיקת snippet |
| `search_by_code` | חיפוש regex בתוך הקוד |
| `get_stats` | סטטיסטיקות על המאגר |

### 🔍 ניתוח קוד
| כלי | תיאור |
|------|--------|
| `analyze_snippet` | ניתוח מטריקות, דפוסים בעייתיים והצעות |
| `bulk_tag_snippets` | עדכון תגיות על מספר snippets בבת אחת |

### 🚀 Render API (תפעול)
| כלי | תיאור |
|------|--------|
| `render_service_status` | מצב השירות הנוכחי |
| `render_list_deploys` | דפלויים אחרונים |
| `render_trigger_deploy` | ⚠️ הפעלת דפלוי חדש |
| `render_restart_service` | ⚠️ ריסטארט לשירות |
| `render_get_env_vars` | הצגת משתני סביבה (ערכים רגישים מוסתרים) |

### 🐙 GitHub Issues
| כלי | תיאור |
|------|--------|
| `github_create_issue` | יצירת Issue חדש (תומך Markdown) |
| `github_list_issues` | רשימת Issues עם סינון |

### 📋 Prompts מובנים (בעברית)
| פרומפט | תיאור |
|---------|--------|
| `code_review` | סקירת קוד מקצועית |
| `debug_help` | ניתוח שגיאה והצעת פתרונות |
| `create_github_issue_prompt` | תבנית Issue (bug / enhancement) |
| `deploy_check` | בדיקות בטיחות לפני דפלוי |
| `summarize_logs` | ניתוח לוגים וזיהוי שגיאות |
| `optimize_snippet` | הצעות אופטימיזציה |

---

## 🚀 התקנה

### הרצה מקומית

```bash
git clone https://github.com/YOUR_USERNAME/codebot-mcp-server.git
cd codebot-mcp-server

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# ערוך את .env

python server.py
```

השרת עולה על `http://localhost:8000/mcp`

### דפלוי ל-Render

1. העלה ל-GitHub
2. ב-Render: **New → Web Service → Docker**
3. הגדר משתני סביבה:

| משתנה | חובה? | תיאור |
|--------|-------|--------|
| `MONGO_URI` | ✅ | Connection string ל-MongoDB |
| `RENDER_API_KEY` | ⬜ | Render API token (ל-deploy/restart) |
| `RENDER_SERVICE_ID` | ⬜ | מזהה השירות ב-Render |
| `GITHUB_TOKEN` | ⬜ | GitHub PAT (ל-Issues) |
| `GITHUB_REPO` | ⬜ | `owner/repo` |

> **💡 טיפ**: רק `MONGO_URI` חובה. שאר האינטגרציות עובדות כשהמשתנים שלהן מוגדרים.

---

## 🔌 חיבור ל-Claude

### Claude.ai (Pro / Max / Team / Enterprise)

**Settings → Integrations → Add custom connector**

```
URL: https://YOUR-APP.onrender.com/mcp
```

### Claude Desktop

הוסף ל-`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "codebot": {
      "type": "streamable-http",
      "url": "https://YOUR-APP.onrender.com/mcp"
    }
  }
}
```

### Claude Code

```bash
claude mcp add-json codebot '{"type":"streamable-http","url":"https://YOUR-APP.onrender.com/mcp"}'
```

---

## 💬 דוגמאות שימוש ב-Claude

### ניהול קוד
> *"הראה לי את כל ה-snippets שלי ב-Python שקשורים ל-async"*
>
> *"צור snippet חדש עם פונקציה למיון מהיר"*
>
> *"חפש בקוד שלי שימוש ב-try/except"*

### ניתוח קוד
> *"תעשה code review על ה-snippet הזה"* (מפעיל את הפרומפט code_review)
>
> *"יש לי שגיאה: ModuleNotFoundError: No module named 'redis'"*

### דפלוי ותפעול
> *"מה הסטטוס של השירות שלי ב-Render?"*
>
> *"תעשה דפלוי חדש"* (מפעיל deploy_check לבדיקת בטיחות)
>
> *"תפתח Issue על הבאג שמצאנו"*

### לוגים
> *"נתח לי את הלוגים האלה ותגיד מה לא תקין"*

---

## 📁 מבנה

```
codebot-mcp-server/
├── server.py          # שרת MCP (כל הכלים, prompts, resources)
├── requirements.txt   # תלויות
├── Dockerfile         # Docker image
├── render.yaml        # Render Blueprint
├── .env.example       # דוגמה למשתנים
├── .gitignore
└── README.md
```

---

## 🔒 אבטחה

- **Stateless mode** — מתאים ל-horizontal scaling
- **ערכים רגישים** מוסתרים ב-`render_get_env_vars`
- **אישור נדרש** לפני deploy/restart (דרך הפרומפט `deploy_check`)
- **אין secrets בקוד** — הכל דרך משתני סביבה

---

## 📄 רישיון

MIT
