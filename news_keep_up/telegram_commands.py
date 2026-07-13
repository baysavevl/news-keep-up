from __future__ import annotations

from collections import Counter
from html import escape

from .config import load_sources
from .db import connect_database, init_db, mark_delivered
from .digest import run_digest
from .interview import run_fde_interview_guideline
from .models import Settings
from .telegram import send_telegram_message

COMMAND_ALIASES = {
    "start": "help",
    "help": "help",
    "latest": "latest",
    "digest": "latest",
    "today": "latest",
    "run": "latest",
    "search": "search",
    "find": "search",
    "analyze": "analyze",
    "why": "analyze",
    "sources": "sources",
    "status": "status",
    "focus": "focus",
    "interview": "interview",
    "prep": "interview",
    "markread": "markread",
    "read": "markread",
    "skip": "markread",
}

SCHEDULE_LABELS = {
    "fde": "hourly at :20, 08:20-22:20 ICT",
    "engineer": "hourly at :40, 08:40-22:40 ICT",
    "fde-interview": "every 2 hours at :35, 07:35-21:35 ICT",
}


def handle_telegram_update(
    update: dict,
    *,
    slot: str,
    sources_path: str,
    settings: Settings,
) -> dict:
    message = update.get("message") or update.get("edited_message") or {}
    text = str(message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    message_id = message.get("message_id")

    if not text.startswith("/") or not chat_id:
        return {"ok": True, "ignored": True, "reason": "not_a_command"}
    if settings.telegram_chat_id and chat_id != settings.telegram_chat_id:
        return {"ok": True, "ignored": True, "reason": "unauthorized_chat"}

    command_name, args = _parse_command(text)
    command = COMMAND_ALIASES.get(command_name, "help")
    if command == "help":
        response = _help_text(slot)
    elif command == "latest":
        response = run_digest(settings, slot, dry_run=True, sources_path=sources_path)
    elif command == "search":
        response = _search_text(settings, args)
    elif command == "analyze":
        response = _analysis_text(settings, slot, args)
    elif command == "sources":
        response = _sources_text(sources_path)
    elif command == "status":
        response = _status_text(settings, slot, sources_path)
    elif command == "focus":
        response = _focus_text(slot)
    elif command == "interview":
        response = _interview_text(settings, slot)
    elif command == "markread":
        response = _markread_text(settings, slot, args)
    else:
        response = _help_text(slot)

    send_telegram_message(
        response,
        settings,
        chat_id=chat_id,
        reply_to_message_id=int(message_id) if message_id is not None else None,
    )
    return {"ok": True, "command": command, "chat_id": chat_id}


def _parse_command(text: str) -> tuple[str, str]:
    first, _, rest = text.partition(" ")
    command = first[1:].split("@", 1)[0].lower()
    return command, rest.strip()


def _help_text(slot: str) -> str:
    title = "FDE" if slot == "fde" else "Engineer"
    return "\n".join([
        f"<b>{title} news bot commands</b>",
        "/latest - build a fresh digest preview now",
        "/digest - alias for /latest",
        "/today - alias for /latest",
        "/search keyword - search stored news",
        "/analyze keyword - analyze stored matches through this profile lens",
        "/markread id|keyword|all - mark stored news as read so it will not be sent again",
        "/interview - show the next FDE interview guideline",
        "/sources - show source coverage",
        "/status - show schedule and config status",
        "/focus - show what this bot considers relevant",
        "/help - show this menu",
    ])


def _focus_text(slot: str) -> str:
    if slot == "fde":
        return "\n".join([
            "<b>FDE focus</b>",
            "Send only Forward Deployed Engineering signals:",
            "• customer rollout and production adoption",
            "• field delivery and solution/customer engineering",
            "• enterprise implementation and workflow integration",
            "• evals, guardrails, governance, observability, and rollout risk",
            "• product feedback loops from real customer deployments",
            "",
            "Reject generic AI: model announcements, API launches, cloud roundups, and coding-agent tools unless they change customer-facing enterprise delivery.",
        ])
    return "\n".join([
        "<b>Engineer focus</b>",
        "Send practical software engineering signals:",
        "• agentic engineering and developer tools",
        "• architecture, systems, data, security, and reliability",
        "• AI engineering practices with concrete delivery impact",
        "• product/engineering strategy useful for builders",
    ])


def _sources_text(sources_path: str) -> str:
    sources = load_sources(sources_path)
    categories = Counter(source.category for source in sources)
    lines = [f"<b>Sources</b>: {len(sources)} enabled"]
    for category, count in sorted(categories.items(), key=lambda item: (-item[1], item[0]))[:10]:
        lines.append(f"• {escape(category)}: {count}")
    return "\n".join(lines)


def _status_text(settings: Settings, slot: str, sources_path: str) -> str:
    sources = load_sources(sources_path)
    gemini_status = "configured" if settings.gemini_api_key else "fallback summaries"
    return "\n".join([
        f"<b>Status: {escape(slot)}</b>",
        f"Schedule: {escape(SCHEDULE_LABELS.get(slot, 'manual or legacy schedule'))}",
        f"Sources: {len(sources)} enabled",
        f"Gemini: {gemini_status}",
        f"Chat restricted: {'yes' if settings.telegram_chat_id else 'no'}",
    ])


def _search_text(settings: Settings, query: str) -> str:
    if not query:
        return "Usage: /search keyword"
    rows = _search_rows(settings, query)
    if not rows:
        return f"No stored news found for: {escape(query)}"
    lines = [f"<b>Search: {escape(query)}</b>"]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. <b>#{int(row['id'])} {escape(row['title'])}</b>\n"
            f"Source: {escape(row['source_name'])} | Score: {int(row['relevance_score'])}/100\n"
            f"Read: <a href=\"{escape(row['url'], quote=True)}\">Read</a>"
        )
    return "\n\n".join(lines)


def _analysis_text(settings: Settings, slot: str, query: str) -> str:
    if not query:
        return _focus_text(slot)
    rows = _search_rows(settings, query, limit=3)
    lines = [f"<b>{escape(slot.upper())} analysis: {escape(query)}</b>"]
    if slot == "fde":
        lines.extend([
            "Lens: prioritize customer rollout, enterprise implementation, field delivery, governance/evals, and production risk.",
            "Ignore generic AI news unless it changes deployment work with real customers.",
        ])
    else:
        lines.append("Lens: prioritize practical engineering impact, architecture, reliability, and developer workflow leverage.")
    if rows:
        lines.append("")
        lines.append("Recent stored matches:")
        for index, row in enumerate(rows, start=1):
            lines.append(f"{index}. {escape(row['title'])} ({escape(row['source_name'])}, {int(row['relevance_score'])}/100)")
    else:
        lines.append("")
        lines.append("No stored matches yet. Use /latest first to fetch and enrich current sources.")
    return "\n".join(lines)


def _interview_text(settings: Settings, slot: str) -> str:
    if slot != "fde":
        return "FDE interview guidelines are available in the FDE group."
    return run_fde_interview_guideline(settings, dry_run=True)


def _markread_text(settings: Settings, slot: str, query: str) -> str:
    if not query:
        return "Usage: /markread #id, /markread keyword, or /markread all"

    conn = connect_database(settings)
    init_db(conn)
    try:
        rows = _markread_rows(conn, query)
        if not rows:
            return f"No unread stored news found for: {escape(query)}"
        item_ids = [int(row["id"]) for row in rows]
        mark_delivered(conn, item_ids, slot, set())
    finally:
        conn.close()

    preview = ", ".join(f"#{int(row['id'])}" for row in rows[:8])
    suffix = "" if len(rows) <= 8 else f" +{len(rows) - 8} more"
    return f"Marked read: {len(rows)} item(s) for {escape(slot)}. {escape(preview + suffix)}"


def _markread_rows(conn, query: str) -> list:
    normalized = query.strip().lstrip("#")
    if normalized.lower() == "all":
        return conn.execute(
            """SELECT i.id, i.title
               FROM items i
               JOIN enrichments e ON e.item_id = i.id
               WHERE e.should_send = 1
                 AND NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.item_id = i.id)
               ORDER BY e.relevance_score DESC, i.published_at DESC, i.fetched_at DESC
               LIMIT 50"""
        ).fetchall()
    if normalized.isdigit():
        return conn.execute(
            """SELECT i.id, i.title
               FROM items i
               JOIN enrichments e ON e.item_id = i.id
               WHERE i.id = ?
                 AND NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.item_id = i.id)
               LIMIT 1""",
            (int(normalized),),
        ).fetchall()

    pattern = f"%{normalized.lower()}%"
    return conn.execute(
        """SELECT i.id, i.title
           FROM items i
           JOIN enrichments e ON e.item_id = i.id
           WHERE NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.item_id = i.id)
             AND (
                lower(i.title) LIKE ?
                OR lower(i.summary) LIKE ?
                OR lower(i.source_name) LIKE ?
                OR lower(e.topic) LIKE ?
                OR lower(e.category) LIKE ?
             )
           ORDER BY e.relevance_score DESC, i.published_at DESC, i.fetched_at DESC
           LIMIT 5""",
        (pattern, pattern, pattern, pattern, pattern),
    ).fetchall()


def _search_rows(settings: Settings, query: str, limit: int = 5) -> list:
    pattern = f"%{query.lower()}%"
    conn = connect_database(settings)
    init_db(conn)
    try:
        return conn.execute(
            """SELECT i.id, i.title, i.url, i.source_name, i.source_category,
                      e.relevance_score, e.topic, e.category
               FROM items i
               JOIN enrichments e ON e.item_id = i.id
               WHERE lower(i.title) LIKE ?
                  OR lower(i.summary) LIKE ?
                  OR lower(i.source_name) LIKE ?
                  OR lower(e.topic) LIKE ?
                  OR lower(e.category) LIKE ?
               ORDER BY e.relevance_score DESC, i.published_at DESC, i.fetched_at DESC
               LIMIT ?""",
            (pattern, pattern, pattern, pattern, pattern, limit),
        ).fetchall()
    finally:
        conn.close()
