"""
CodeBot MCP Server v2 - Streamable HTTP
─────────────────────────────────────────
שרת MCP מורחב לניהול קוד, snippets, דפלוי ותפעול.
כולל: Render API, GitHub Issues, ניתוח קוד, ופרומפטים מובנים.
"""

import os
import logging
import json
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pymongo import MongoClient
from bson import ObjectId

# ── הגדרות ─────────────────────────────────────────────────
MONGO_URI = os.environ.get("MONGO_URI", "")
DB_NAME = os.environ.get("DB_NAME", "codebot")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "snippets")
PORT = int(os.environ.get("PORT", 8000))

# Render API
RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "")
RENDER_SERVICE_ID = os.environ.get("RENDER_SERVICE_ID", "")
RENDER_API_BASE = "https://api.render.com/v1"

# GitHub API
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")  # owner/repo
GITHUB_API_BASE = "https://api.github.com"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("codebot-mcp")

# ── MongoDB ─────────────────────────────────────────────────
_mongo_client: Optional[MongoClient] = None
_collection = None


def get_collection():
    global _mongo_client, _collection
    if _collection is None:
        if not MONGO_URI:
            raise RuntimeError("MONGO_URI לא הוגדר")
        _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        _collection = _mongo_client[DB_NAME][COLLECTION_NAME]
        logger.info(f"MongoDB מחובר: {DB_NAME}/{COLLECTION_NAME}")
    return _collection


def serialize_doc(doc: dict) -> dict:
    if doc is None:
        return {}
    doc["_id"] = str(doc["_id"])
    for field in ("created_at", "updated_at"):
        if field in doc and isinstance(doc[field], datetime):
            doc[field] = doc[field].isoformat()
    return doc


# ── HTTP Helpers ────────────────────────────────────────────

def render_headers() -> dict:
    return {
        "Authorization": f"Bearer {RENDER_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def github_headers() -> dict:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


# ══════════════════════════════════════════════════════════════
#  MCP Server
# ══════════════════════════════════════════════════════════════

# הגדרת אבטחת תעבורה
# בסביבת ענן (Render, Heroku וכו') האבטחה מנוהלת ברמת התשתית
# לכן משביתים את הגנת DNS Rebinding שגורמת לשגיאות 421
mcp = FastMCP(
    name="CodeBot MCP Server",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


# ┌─────────────────────────────────────────────────────────┐
# │  1. כלי Snippets - ניהול קוד                            │
# └─────────────────────────────────────────────────────────┘

@mcp.tool()
def list_snippets(
    language: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 20,
    search: Optional[str] = None,
) -> dict:
    """
    רשימת snippets מהמאגר.
    ניתן לסנן לפי שפת תכנות, תגית, או טקסט חופשי.

    Args:
        language: סינון לפי שפה (python, javascript וכו')
        tag: סינון לפי תגית
        limit: מספר תוצאות מקסימלי (ברירת מחדל: 20)
        search: חיפוש טקסט חופשי בכותרת ובתוכן
    """
    col = get_collection()
    query = {}
    if language:
        query["language"] = {"$regex": language, "$options": "i"}
    if tag:
        query["tags"] = {"$regex": tag, "$options": "i"}
    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"code": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}},
        ]
    docs = list(col.find(query).sort("created_at", -1).limit(limit))
    return {"count": len(docs), "snippets": [serialize_doc(d) for d in docs]}


@mcp.tool()
def get_snippet(snippet_id: str) -> dict:
    """
    קבלת snippet בודד לפי מזהה.

    Args:
        snippet_id: מזהה ה-snippet (MongoDB ObjectId)
    """
    col = get_collection()
    doc = col.find_one({"_id": ObjectId(snippet_id)})
    if not doc:
        return {"error": f"snippet עם מזהה {snippet_id} לא נמצא"}
    return {"snippet": serialize_doc(doc)}


@mcp.tool()
def create_snippet(
    title: str,
    code: str,
    language: str = "python",
    description: str = "",
    tags: Optional[list[str]] = None,
) -> dict:
    """
    יצירת snippet חדש במאגר.

    Args:
        title: כותרת ה-snippet
        code: קוד המקור
        language: שפת התכנות (ברירת מחדל: python)
        description: תיאור אופציונלי
        tags: רשימת תגיות אופציונלית
    """
    col = get_collection()
    now = datetime.now(timezone.utc)
    doc = {
        "title": title,
        "code": code,
        "language": language,
        "description": description,
        "tags": tags or [],
        "created_at": now,
        "updated_at": now,
        "source": "mcp",
    }
    result = col.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return {"message": "snippet נוצר בהצלחה", "snippet": serialize_doc(doc)}


@mcp.tool()
def update_snippet(
    snippet_id: str,
    title: Optional[str] = None,
    code: Optional[str] = None,
    language: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> dict:
    """
    עדכון snippet קיים.

    Args:
        snippet_id: מזהה ה-snippet
        title: כותרת חדשה (אופציונלי)
        code: קוד חדש (אופציונלי)
        language: שפה חדשה (אופציונלי)
        description: תיאור חדש (אופציונלי)
        tags: תגיות חדשות (אופציונלי)
    """
    col = get_collection()
    updates = {"updated_at": datetime.now(timezone.utc)}
    for key, val in [("title", title), ("code", code), ("language", language),
                     ("description", description), ("tags", tags)]:
        if val is not None:
            updates[key] = val

    result = col.update_one({"_id": ObjectId(snippet_id)}, {"$set": updates})
    if result.matched_count == 0:
        return {"error": f"snippet {snippet_id} לא נמצא"}

    updated = col.find_one({"_id": ObjectId(snippet_id)})
    return {"message": "snippet עודכן", "snippet": serialize_doc(updated)}


@mcp.tool()
def delete_snippet(snippet_id: str) -> dict:
    """
    מחיקת snippet מהמאגר.

    Args:
        snippet_id: מזהה ה-snippet למחיקה
    """
    col = get_collection()
    doc = col.find_one({"_id": ObjectId(snippet_id)})
    if not doc:
        return {"error": f"snippet {snippet_id} לא נמצא"}
    col.delete_one({"_id": ObjectId(snippet_id)})
    return {"message": f"snippet '{doc.get('title', '')}' נמחק"}


@mcp.tool()
def search_by_code(pattern: str, language: Optional[str] = None) -> dict:
    """
    חיפוש בתוך הקוד עצמו לפי ביטוי רגולרי או טקסט.

    Args:
        pattern: טקסט או regex לחיפוש בקוד
        language: סינון אופציונלי לפי שפה
    """
    col = get_collection()
    query = {"code": {"$regex": pattern, "$options": "i"}}
    if language:
        query["language"] = {"$regex": language, "$options": "i"}
    docs = list(col.find(query).sort("created_at", -1).limit(20))
    return {"count": len(docs), "pattern": pattern, "snippets": [serialize_doc(d) for d in docs]}


@mcp.tool()
def get_stats() -> dict:
    """
    סטטיסטיקות על המאגר - מספר snippets, שפות, תגיות נפוצות.
    """
    col = get_collection()
    total = col.count_documents({})

    lang_pipeline = [
        {"$group": {"_id": "$language", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}, {"$limit": 10},
    ]
    languages = {d["_id"]: d["count"] for d in col.aggregate(lang_pipeline) if d["_id"]}

    tag_pipeline = [
        {"$unwind": "$tags"},
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}, {"$limit": 10},
    ]
    tags = {d["_id"]: d["count"] for d in col.aggregate(tag_pipeline) if d["_id"]}

    latest = col.find_one(sort=[("created_at", -1)])
    latest_info = None
    if latest:
        ca = latest.get("created_at")
        latest_info = {
            "title": latest.get("title"),
            "language": latest.get("language"),
            "created_at": ca.isoformat() if isinstance(ca, datetime) else str(ca or ""),
        }

    return {
        "total_snippets": total,
        "languages": languages,
        "popular_tags": tags,
        "latest_snippet": latest_info,
    }


# ┌─────────────────────────────────────────────────────────┐
# │  2. Render API - תפעול ודפלוי                           │
# └─────────────────────────────────────────────────────────┘

@mcp.tool()
async def render_service_status(service_id: Optional[str] = None) -> dict:
    """
    בדיקת סטטוס שירות ב-Render.
    מחזיר מידע על מצב השירות, סוג, תאריך עדכון אחרון ועוד.

    Args:
        service_id: מזהה השירות (אם לא צוין, ישתמש בברירת מחדל)
    """
    sid = service_id or RENDER_SERVICE_ID
    if not sid or not RENDER_API_KEY:
        return {"error": "חסר RENDER_API_KEY או RENDER_SERVICE_ID"}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{RENDER_API_BASE}/services/{sid}", headers=render_headers())
        if resp.status_code != 200:
            return {"error": f"Render API שגיאה: {resp.status_code}", "detail": resp.text}
        data = resp.json()

    svc = data.get("service", data)
    return {
        "id": svc.get("id"),
        "name": svc.get("name"),
        "type": svc.get("type"),
        "status": svc.get("suspended", "unknown"),
        "url": svc.get("serviceDetails", {}).get("url", ""),
        "region": svc.get("region"),
        "created_at": svc.get("createdAt"),
        "updated_at": svc.get("updatedAt"),
        "auto_deploy": svc.get("autoDeploy"),
    }


@mcp.tool()
async def render_list_deploys(
    service_id: Optional[str] = None,
    limit: int = 5,
) -> dict:
    """
    רשימת דפלויים אחרונים של שירות ב-Render.

    Args:
        service_id: מזהה השירות (אם לא צוין, ישתמש בברירת מחדל)
        limit: מספר דפלויים להחזרה (ברירת מחדל: 5)
    """
    sid = service_id or RENDER_SERVICE_ID
    if not sid or not RENDER_API_KEY:
        return {"error": "חסר RENDER_API_KEY או RENDER_SERVICE_ID"}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{RENDER_API_BASE}/services/{sid}/deploys",
            headers=render_headers(),
            params={"limit": limit},
        )
        if resp.status_code != 200:
            return {"error": f"Render API שגיאה: {resp.status_code}"}
        data = resp.json()

    deploys = []
    for item in data:
        d = item.get("deploy", item)
        deploys.append({
            "id": d.get("id"),
            "status": d.get("status"),
            "trigger": d.get("trigger"),
            "commit_id": d.get("commit", {}).get("id", "")[:8] if isinstance(d.get("commit"), dict) else "",
            "commit_message": d.get("commit", {}).get("message", "") if isinstance(d.get("commit"), dict) else "",
            "created_at": d.get("createdAt"),
            "finished_at": d.get("finishedAt"),
        })

    return {"service_id": sid, "count": len(deploys), "deploys": deploys}


@mcp.tool()
async def render_trigger_deploy(
    service_id: Optional[str] = None,
    clear_cache: bool = False,
) -> dict:
    """
    הפעלת דפלוי חדש לשירות ב-Render.
    ⚠️ פעולה זו מבצעת דפלוי בפועל!

    Args:
        service_id: מזהה השירות
        clear_cache: האם לנקות cache לפני הבנייה
    """
    sid = service_id or RENDER_SERVICE_ID
    if not sid or not RENDER_API_KEY:
        return {"error": "חסר RENDER_API_KEY או RENDER_SERVICE_ID"}

    body = {}
    if clear_cache:
        body["clearCache"] = "clear"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{RENDER_API_BASE}/services/{sid}/deploys",
            headers=render_headers(),
            json=body,
        )
        if resp.status_code not in (200, 201):
            return {"error": f"שגיאת דפלוי: {resp.status_code}", "detail": resp.text}
        data = resp.json()

    d = data.get("deploy", data)
    return {
        "message": "דפלוי הופעל בהצלחה",
        "deploy_id": d.get("id"),
        "status": d.get("status"),
    }


@mcp.tool()
async def render_restart_service(service_id: Optional[str] = None) -> dict:
    """
    ריסטארט לשירות ב-Render (ללא בנייה מחדש).
    ⚠️ פעולה זו מפעילה מחדש את השירות בפועל!

    Args:
        service_id: מזהה השירות
    """
    sid = service_id or RENDER_SERVICE_ID
    if not sid or not RENDER_API_KEY:
        return {"error": "חסר RENDER_API_KEY או RENDER_SERVICE_ID"}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{RENDER_API_BASE}/services/{sid}/restart",
            headers=render_headers(),
        )
        if resp.status_code not in (200, 204):
            return {"error": f"שגיאת restart: {resp.status_code}", "detail": resp.text}

    return {"message": f"שירות {sid} הופעל מחדש בהצלחה"}


@mcp.tool()
async def render_get_env_vars(service_id: Optional[str] = None) -> dict:
    """
    הצגת משתני הסביבה של שירות ב-Render.
    ⚠️ ערכים רגישים מוצגים מוסתרים.

    Args:
        service_id: מזהה השירות
    """
    sid = service_id or RENDER_SERVICE_ID
    if not sid or not RENDER_API_KEY:
        return {"error": "חסר RENDER_API_KEY או RENDER_SERVICE_ID"}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{RENDER_API_BASE}/services/{sid}/env-vars",
            headers=render_headers(),
        )
        if resp.status_code != 200:
            return {"error": f"שגיאה: {resp.status_code}"}
        data = resp.json()

    env_vars = []
    sensitive_patterns = ("KEY", "SECRET", "TOKEN", "PASSWORD", "URI", "URL", "MONGO")
    for item in data:
        ev = item.get("envVar", item)
        key = ev.get("key", "")
        value = ev.get("value", "")
        is_sensitive = any(p in key.upper() for p in sensitive_patterns)
        env_vars.append({
            "key": key,
            "value": value[:4] + "****" if is_sensitive and len(value) > 4 else value,
            "sensitive": is_sensitive,
        })

    return {"service_id": sid, "count": len(env_vars), "env_vars": env_vars}


# ┌─────────────────────────────────────────────────────────┐
# │  3. GitHub - Issues ופעולות                             │
# └─────────────────────────────────────────────────────────┘

@mcp.tool()
async def github_create_issue(
    title: str,
    body: str,
    labels: Optional[list[str]] = None,
    repo: Optional[str] = None,
) -> dict:
    """
    יצירת Issue חדש ב-GitHub.

    Args:
        title: כותרת ה-Issue
        body: תוכן ה-Issue (תומך Markdown)
        labels: רשימת תגיות (bug, enhancement, וכו')
        repo: ריפו בפורמט owner/repo (אופציונלי, ברירת מחדל מ-env)
    """
    target_repo = repo or GITHUB_REPO
    if not target_repo or not GITHUB_TOKEN:
        return {"error": "חסר GITHUB_TOKEN או GITHUB_REPO"}

    payload = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GITHUB_API_BASE}/repos/{target_repo}/issues",
            headers=github_headers(),
            json=payload,
        )
        if resp.status_code != 201:
            return {"error": f"GitHub שגיאה: {resp.status_code}", "detail": resp.text}
        data = resp.json()

    return {
        "message": "Issue נוצר בהצלחה",
        "number": data.get("number"),
        "url": data.get("html_url"),
        "title": data.get("title"),
    }


@mcp.tool()
async def github_list_issues(
    state: str = "open",
    labels: Optional[str] = None,
    limit: int = 10,
    repo: Optional[str] = None,
) -> dict:
    """
    רשימת Issues מ-GitHub.

    Args:
        state: סטטוס (open, closed, all)
        labels: סינון לפי תגיות (מופרדות בפסיקים)
        limit: מספר תוצאות מקסימלי
        repo: ריפו בפורמט owner/repo
    """
    target_repo = repo or GITHUB_REPO
    if not target_repo or not GITHUB_TOKEN:
        return {"error": "חסר GITHUB_TOKEN או GITHUB_REPO"}

    params = {"state": state, "per_page": limit, "sort": "updated", "direction": "desc"}
    if labels:
        params["labels"] = labels

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{target_repo}/issues",
            headers=github_headers(),
            params=params,
        )
        if resp.status_code != 200:
            return {"error": f"GitHub שגיאה: {resp.status_code}"}
        data = resp.json()

    issues = []
    for issue in data:
        if issue.get("pull_request"):
            continue
        issues.append({
            "number": issue["number"],
            "title": issue["title"],
            "state": issue["state"],
            "labels": [l["name"] for l in issue.get("labels", [])],
            "created_at": issue.get("created_at"),
            "url": issue.get("html_url"),
        })

    return {"repo": target_repo, "count": len(issues), "issues": issues}


# ┌─────────────────────────────────────────────────────────┐
# │  4. ניתוח קוד                                          │
# └─────────────────────────────────────────────────────────┘

@mcp.tool()
def analyze_snippet(snippet_id: str) -> dict:
    """
    ניתוח בסיסי של snippet - שורות, מורכבות, דפוסים בעייתיים.
    מחזיר מידע שמסייע ל-Claude לבצע code review מעמיק.

    Args:
        snippet_id: מזהה ה-snippet לניתוח
    """
    col = get_collection()
    doc = col.find_one({"_id": ObjectId(snippet_id)})
    if not doc:
        return {"error": f"snippet {snippet_id} לא נמצא"}

    code = doc.get("code", "")
    lines = code.split("\n")
    lang = doc.get("language", "unknown").lower()

    analysis = {
        "snippet_id": snippet_id,
        "title": doc.get("title", ""),
        "language": lang,
        "metrics": {
            "total_lines": len(lines),
            "code_lines": len([l for l in lines if l.strip() and not l.strip().startswith("#")
                                and not l.strip().startswith("//")
                                and not l.strip().startswith("/*")]),
            "empty_lines": len([l for l in lines if not l.strip()]),
            "comment_lines": len([l for l in lines if l.strip().startswith("#")
                                   or l.strip().startswith("//")]),
            "max_line_length": max((len(l) for l in lines), default=0),
            "avg_line_length": round(sum(len(l) for l in lines) / max(len(lines), 1), 1),
        },
        "patterns_found": [],
        "suggestions": [],
    }

    # זיהוי דפוסים בעייתיים
    problem_patterns = {
        "TODO/FIXME": r"(?i)(todo|fixme|hack|xxx)",
        "print_debug": r"(?i)\b(print\(|console\.log|debugger)",
        "bare_except": r"except\s*:",
        "hardcoded_secrets": r"(?i)(password|secret|api_key|token)\s*=\s*['\"][^'\"]+['\"]",
        "long_function": None,  # נבדק בנפרד
        "nested_loops": r"(for|while).*\n\s+(for|while)",
    }

    for name, pattern in problem_patterns.items():
        if pattern:
            matches = re.findall(pattern, code)
            if matches:
                analysis["patterns_found"].append({
                    "pattern": name,
                    "count": len(matches),
                })

    # בדיקת פונקציות ארוכות (Python)
    if lang == "python":
        func_lengths = []
        current_func = None
        current_lines = 0
        for line in lines:
            if re.match(r"^(async\s+)?def\s+", line):
                if current_func and current_lines > 30:
                    analysis["patterns_found"].append({
                        "pattern": "long_function",
                        "detail": f"{current_func}: {current_lines} שורות",
                    })
                current_func = line.strip().split("(")[0].replace("def ", "").replace("async ", "")
                current_lines = 0
            elif current_func:
                current_lines += 1

        if current_func and current_lines > 30:
            analysis["patterns_found"].append({
                "pattern": "long_function",
                "detail": f"{current_func}: {current_lines} שורות",
            })

    # הצעות
    m = analysis["metrics"]
    if m["max_line_length"] > 120:
        analysis["suggestions"].append("יש שורות ארוכות מ-120 תווים — שקול לפצל")
    if m["comment_lines"] == 0 and m["code_lines"] > 20:
        analysis["suggestions"].append("אין הערות בקוד — שקול להוסיף תיעוד")
    if not analysis["patterns_found"]:
        analysis["suggestions"].append("לא נמצאו דפוסים בעייתיים — הקוד נראה נקי")

    return analysis


@mcp.tool()
def bulk_tag_snippets(
    language: Optional[str] = None,
    search: Optional[str] = None,
    add_tags: Optional[list[str]] = None,
    remove_tags: Optional[list[str]] = None,
) -> dict:
    """
    עדכון תגיות בכמות (bulk) על snippets מסוננים.

    Args:
        language: סינון לפי שפה
        search: סינון לפי טקסט
        add_tags: תגיות להוספה
        remove_tags: תגיות להסרה
    """
    col = get_collection()
    query = {}
    if language:
        query["language"] = {"$regex": language, "$options": "i"}
    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"code": {"$regex": search, "$options": "i"}},
        ]

    count = col.count_documents(query)
    if count == 0:
        return {"error": "לא נמצאו snippets תואמים"}

    operations = {}
    if add_tags:
        operations["$addToSet"] = {"tags": {"$each": add_tags}}
    if remove_tags:
        operations["$pull"] = {"tags": {"$in": remove_tags}}

    if not operations:
        return {"error": "לא צוינו תגיות להוספה או הסרה"}

    result = col.update_many(query, operations)
    return {
        "message": f"עודכנו {result.modified_count} snippets מתוך {count}",
        "matched": count,
        "modified": result.modified_count,
    }


# ┌─────────────────────────────────────────────────────────┐
# │  5. Prompts - תבניות מובנות בעברית                      │
# └─────────────────────────────────────────────────────────┘

@mcp.prompt()
def code_review(snippet_id: str) -> str:
    """
    ביצוע code review מקצועי על snippet.
    מחזיר פרומפט מובנה לניתוח מעמיק.
    """
    return (
        f"אתה מבצע code review מקצועי.\n"
        f"קודם, הפעל את הכלי analyze_snippet עם snippet_id={snippet_id} כדי לקבל מידע בסיסי.\n"
        f"לאחר מכן, הפעל את get_snippet עם אותו מזהה כדי לראות את הקוד עצמו.\n\n"
        f"בצע סקירה מקצועית שכוללת:\n"
        f"- **קריאות**: האם הקוד קריא ומובן?\n"
        f"- **ביצועים**: האם יש מקום לשיפור?\n"
        f"- **אבטחה**: האם יש בעיות אבטחה פוטנציאליות?\n"
        f"- **תחזוקה**: האם הקוד קל לתחזוקה?\n"
        f"- **דפוסים**: האם יש שימוש בדפוסי עיצוב מתאימים?\n\n"
        f"כתוב בעברית. היה ספציפי עם מספרי שורות והצעות קוד."
    )


@mcp.prompt()
def debug_help(error_message: str, context: str = "") -> str:
    """
    עזרה בדיבאג - ניתוח שגיאה והצעת פתרונות.
    """
    return (
        f"אתה מומחה דיבאג.\n"
        f"המשתמש נתקל בשגיאה הבאה:\n\n"
        f"```\n{error_message}\n```\n\n"
        f"{'הקשר נוסף: ' + context if context else ''}\n\n"
        f"נתח את השגיאה וספק:\n"
        f"1. **סיבה**: מה כנראה גורם לשגיאה\n"
        f"2. **פתרון מהיר**: איך לתקן עכשיו\n"
        f"3. **פתרון מעמיק**: איך למנוע בעתיד\n"
        f"4. **בדיקות**: איזה בדיקות להוסיף\n\n"
        f"אם רלוונטי, חפש snippets קשורים במאגר עם search_by_code.\n"
        f"כתוב בעברית. היה ספציפי."
    )


@mcp.prompt()
def create_github_issue_prompt(
    issue_type: str = "bug",
    description: str = "",
) -> str:
    """
    יצירת Issue מקצועי ב-GitHub עם תבנית מובנית.
    """
    templates = {
        "bug": (
            f"צור Issue מסוג באג ב-GitHub.\n\n"
            f"תיאור הבעיה: {description}\n\n"
            f"השתמש בכלי github_create_issue עם המבנה הבא:\n\n"
            f"**כותרת**: [קצר וממוקד, בעברית]\n\n"
            f"**תוכן** (Markdown):\n"
            f"## תיאור הבאג\n"
            f"[תיאור ברור של הבעיה]\n\n"
            f"## צעדים לשחזור\n"
            f"1. ...\n2. ...\n\n"
            f"## התנהגות צפויה\n"
            f"[מה היה אמור לקרות]\n\n"
            f"## התנהגות בפועל\n"
            f"[מה קורה בפועל]\n\n"
            f"## סביבה\n"
            f"- Python / Node.js גרסה\n"
            f"- מערכת הפעלה\n\n"
            f"labels: ['bug']"
        ),
        "enhancement": (
            f"צור Issue מסוג שיפור ב-GitHub.\n\n"
            f"תיאור: {description}\n\n"
            f"השתמש בכלי github_create_issue עם המבנה הבא:\n\n"
            f"**כותרת**: [feat: תיאור קצר בעברית]\n\n"
            f"**תוכן** (Markdown):\n"
            f"## תיאור הפיצ'ר\n"
            f"[מה הפיצ'ר עושה ולמה צריך אותו]\n\n"
            f"## פתרון מוצע\n"
            f"[איך לממש]\n\n"
            f"## חלופות שנשקלו\n"
            f"[אם רלוונטי]\n\n"
            f"## משימות\n"
            f"- [ ] משימה 1\n- [ ] משימה 2\n\n"
            f"labels: ['enhancement']"
        ),
    }

    return templates.get(issue_type, templates["bug"])


@mcp.prompt()
def deploy_check() -> str:
    """
    בדיקה לפני דפלוי - אישור בטיחות.
    """
    return (
        "אתה עומד לבצע דפלוי.\n"
        "קודם כל, בצע את הבדיקות הבאות:\n\n"
        "1. **הפעל** render_service_status כדי לבדוק את מצב השירות הנוכחי\n"
        "2. **הפעל** render_list_deploys כדי לראות את הדפלוי האחרון\n"
        "3. **הפעל** github_list_issues עם labels='bug' כדי לבדוק באגים פתוחים\n\n"
        "לאחר מכן, הצג למשתמש:\n"
        "- מצב השירות הנוכחי\n"
        "- תוצאת הדפלוי האחרון\n"
        "- באגים פתוחים שעלולים להשפיע\n\n"
        "שאל את המשתמש אם להמשיך עם הדפלוי.\n"
        "אם הוא מאשר, השתמש ב-render_trigger_deploy.\n\n"
        "⚠️ אל תבצע דפלוי ללא אישור מפורש!"
    )


@mcp.prompt()
def summarize_logs(logs: str) -> str:
    """
    סיכום לוגים - ניתוח שגיאות והתרעות.
    """
    return (
        f"אתה מנתח לוגים טכניים.\n"
        f"הלוגים הבאים דורשים ניתוח:\n\n"
        f"```\n{logs}\n```\n\n"
        f"ספק ניתוח שכולל:\n\n"
        f"### שגיאות (Errors)\n"
        f"פרט כל שגיאה: שורה, סוג, חומרה, והשפעה.\n\n"
        f"### אזהרות (Warnings)\n"
        f"פרט אזהרות שדורשות תשומת לב.\n\n"
        f"### דפוסים\n"
        f"האם יש דפוסים חוזרים? שגיאות שמתרחשות בתדירות?\n\n"
        f"### המלצות\n"
        f"מה לתקן קודם ואיך.\n\n"
        f"היה טכני ומדויק. ציין מספרי שורות."
    )


@mcp.prompt()
def optimize_snippet(snippet_id: str) -> str:
    """
    הצעות אופטימיזציה ל-snippet.
    """
    return (
        f"אתה מומחה אופטימיזציה.\n"
        f"הפעל get_snippet עם snippet_id={snippet_id} ו-analyze_snippet עם אותו מזהה.\n\n"
        f"לאחר מכן, הצע אופטימיזציות:\n\n"
        f"1. **ביצועים**: Big-O, לולאות מיותרות, caching\n"
        f"2. **זיכרון**: אובייקטים מיותרים, generators vs lists\n"
        f"3. **קריאות**: שמות, מבנה, הפרדת אחריות\n"
        f"4. **פייתוני**: שימוש ב-idioms של השפה\n\n"
        f"לכל הצעה, הראה את הקוד הנוכחי לעומת הקוד המוצע.\n"
        f"אם ההצעות משמעותיות, הצע למשתמש לעדכן את ה-snippet עם update_snippet.\n\n"
        f"כתוב בעברית."
    )


# ┌─────────────────────────────────────────────────────────┐
# │  6. Resources                                          │
# └─────────────────────────────────────────────────────────┘

@mcp.resource("codebot://stats")
def stats_resource() -> str:
    """סטטיסטיקות כלליות על המאגר"""
    stats = get_stats()
    return (
        f"מאגר CodeBot:\n"
        f"סה\"כ snippets: {stats['total_snippets']}\n"
        f"שפות: {', '.join(f'{k} ({v})' for k, v in stats['languages'].items())}\n"
        f"תגיות נפוצות: {', '.join(f'{k} ({v})' for k, v in stats['popular_tags'].items())}"
    )


@mcp.resource("codebot://tools-guide")
def tools_guide_resource() -> str:
    """מדריך לכלים הזמינים בשרת"""
    return """# כלים זמינים ב-CodeBot MCP Server

## ניהול קוד
- `list_snippets` - רשימת snippets עם סינון
- `get_snippet` - קבלת snippet בודד
- `create_snippet` - יצירת snippet חדש
- `update_snippet` - עדכון snippet
- `delete_snippet` - מחיקת snippet
- `search_by_code` - חיפוש בתוך הקוד
- `get_stats` - סטטיסטיקות

## ניתוח קוד
- `analyze_snippet` - ניתוח מטריקות ודפוסים
- `bulk_tag_snippets` - עדכון תגיות בכמות

## Render (תפעול)
- `render_service_status` - מצב השירות
- `render_list_deploys` - דפלויים אחרונים
- `render_trigger_deploy` - הפעלת דפלוי
- `render_restart_service` - ריסטארט
- `render_get_env_vars` - משתני סביבה

## GitHub
- `github_create_issue` - יצירת Issue
- `github_list_issues` - רשימת Issues
"""


# ┌─────────────────────────────────────────────────────────┐
# │  7. Health Check                                       │
# └─────────────────────────────────────────────────────────┘

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    from starlette.responses import JSONResponse

    health = {
        "status": "ok",
        "server": "CodeBot MCP v2",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "integrations": {},
    }

    # MongoDB
    try:
        col = get_collection()
        col.find_one()
        health["integrations"]["mongodb"] = "connected"
    except Exception as e:
        health["integrations"]["mongodb"] = f"error: {str(e)}"
        health["status"] = "degraded"

    # Render API
    health["integrations"]["render"] = "configured" if RENDER_API_KEY else "not configured"

    # GitHub API
    health["integrations"]["github"] = "configured" if GITHUB_TOKEN else "not configured"

    return JSONResponse(health)


# ── Entrypoint ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    logger.info(f"מפעיל CodeBot MCP Server v2 על פורט {PORT}")
    uvicorn.run(
        mcp.streamable_http_app(),
        host="0.0.0.0",
        port=PORT,
    )
