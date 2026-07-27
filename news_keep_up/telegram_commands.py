from __future__ import annotations

from collections import Counter
from html import escape

from .config import load_sources
from .db import (
    connect_database,
    init_db,
    mark_delivered,
    row_value,
    search_job_opportunities,
    upsert_profile_setting,
)
from .digest import run_digest
from .interview import run_fde_interview_guideline
from .job_filters import is_workable_from_vietnam_opportunity
from .job_alerts import run_fde_job_alerts
from .models import JobOpportunity, Settings
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
    "jobs": "jobsearch",
    "job": "jobsearch",
    "opps": "jobsearch",
    "opportunities": "jobsearch",
    "open": "jobsearch",
    "alerts": "jobsearch",
    "company": "jobsearch",
    "remote": "jobsearch",
    "high": "jobsearch",
    "salary": "salarysearch",
    "comp": "salarysearch",
    "package": "salarysearch",
    "benefits": "benefitsearch",
    "benefit": "benefitsearch",
    "analyze": "analyze",
    "why": "analyze",
    "chatid": "chatid",
    "id": "chatid",
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
    "fde": "twice daily at 08:00 and 14:00 ICT",
    "engineer": "twice daily at 09:15 and 16:00 ICT",
    "fde-interview": "hourly at :35, 07:35-22:35 ICT",
    "fde-jobs": "every 30 minutes; only sends when matching jobs exist",
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

    command_name, args = _parse_command(text)
    command = COMMAND_ALIASES.get(command_name, "help")
    if command != "chatid" and settings.telegram_chat_id and chat_id != settings.telegram_chat_id:
        return {"ok": True, "ignored": True, "reason": "unauthorized_chat"}

    if command == "chatid":
        saved = _maybe_save_fde_jobs_chat_id(settings, slot, chat)
        response = _chatid_text(chat, saved=saved)
    elif command == "help":
        response = _help_text(slot)
    elif command == "latest":
        if slot == "fde-jobs":
            response = run_fde_job_alerts(settings, dry_run=True, sources_path=sources_path) or "No pending FDE job alerts."
        else:
            response = run_digest(settings, slot, dry_run=True, sources_path=sources_path)
    elif command == "search":
        response = _job_search_text(settings, args) if slot == "fde-jobs" else _search_text(settings, args)
    elif command == "jobsearch":
        response = _job_search_text(settings, _job_search_query(command_name, args))
    elif command == "salarysearch":
        response = _job_search_text(settings, args, only_compensation=True)
    elif command == "benefitsearch":
        response = _job_search_text(settings, args, only_benefits=True)
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
    if slot == "fde-jobs":
        return "\n".join([
            "<b>FDE jobs bot commands</b>",
            "/latest - scan now and preview pending job alerts",
            "/jobs keyword - search stored FDE opportunities",
            "/jobs - show latest stored Vietnam-workable opportunities",
            "/open - show latest stored Vietnam-workable opportunities",
            "/salary - show stored jobs with salary/package",
            "/benefits - show stored jobs with benefits",
            "/company name - search by company",
            "/remote - show remote/hybrid opportunities",
            "/high - show high-priority opportunities",
            "/search keyword - alias for /jobs keyword in this group",
            "/sources - show job source coverage",
            "/status - show schedule and delivery config",
            "/chatid - show this Telegram chat id",
            "/help - show this menu",
        ])
    title = "FDE" if slot == "fde" else "Engineer"
    return "\n".join([
        f"<b>{title} news bot commands</b>",
        "/latest - build a fresh digest preview now",
        "/digest - alias for /latest",
        "/today - alias for /latest",
        "/chatid - show this Telegram chat id",
        "/search keyword - search stored news",
        "/analyze keyword - analyze stored matches through this profile lens",
        "/markread id|keyword|all - mark stored news as read so it will not be sent again",
        "/interview - show the next FDE interview guideline",
        "/sources - show source coverage",
        "/status - show schedule and config status",
        "/focus - show what this bot considers relevant",
        "/help - show this menu",
    ])


def _chatid_text(chat: dict, saved: bool = False) -> str:
    chat_id = str(chat.get("id") or "")
    title = escape(str(chat.get("title") or chat.get("username") or "this chat"))
    lines = [
        "<b>Telegram chat id</b>",
        f"Chat: {title}",
        f"ID: <code>{escape(chat_id)}</code>",
    ]
    if saved:
        lines.append("Saved for fde-jobs delivery.")
    else:
        lines.append("Use this value for FDE_JOBS_TELEGRAM_CHAT_ID.")
    return "\n".join(lines)


def _maybe_save_fde_jobs_chat_id(settings: Settings, slot: str, chat: dict) -> bool:
    if slot != "fde-jobs":
        return False
    chat_id = str(chat.get("id") or "").strip()
    title = str(chat.get("title") or "")
    if not chat_id or _normalize_group_title(title) != "fdejobs":
        return False

    conn = connect_database(settings)
    init_db(conn)
    try:
        upsert_profile_setting(conn, slot, "telegram_chat_id", chat_id)
    finally:
        conn.close()
    return True


def _normalize_group_title(title: str) -> str:
    return "".join(char for char in title.lower() if char.isalnum())


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
    db_status = "durable" if settings.turso_database_url else f"local sqlite ({settings.db_path})"
    return "\n".join([
        f"<b>Status: {escape(slot)}</b>",
        f"Schedule: {escape(SCHEDULE_LABELS.get(slot, 'manual or legacy schedule'))}",
        f"Sources: {len(sources)} enabled",
        f"Gemini: {gemini_status}",
        f"Database: {escape(db_status)}",
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
            f"{index}. <b>#{int(row_value(row, 'id', 0))} {escape(row_value(row, 'title', 1))}</b>\n"
            f"Source: {escape(row_value(row, 'source_name', 3))} | Score: {int(row_value(row, 'relevance_score', 5))}/100\n"
            f"Read: <a href=\"{escape(row_value(row, 'url', 2), quote=True)}\">Read</a>"
        )
    return "\n\n".join(lines)


def _job_search_query(command_name: str, args: str) -> str:
    if args.strip():
        return args
    defaults = {
        "remote": "remote",
        "high": "High",
    }
    return defaults.get(command_name, args)


def _job_search_text(
    settings: Settings,
    query: str,
    limit: int = 5,
    only_compensation: bool = False,
    only_benefits: bool = False,
) -> str:
    conn = connect_database(settings)
    init_db(conn)
    try:
        opportunities = [
            opportunity
            for opportunity in search_job_opportunities(conn, query, limit=limit * 8)
            if is_workable_from_vietnam_opportunity(opportunity)
        ]
    finally:
        conn.close()
    if only_compensation:
        opportunities = [
            opportunity
            for opportunity in opportunities
            if opportunity.compensation or opportunity.package
        ]
    if only_benefits:
        opportunities = [
            opportunity
            for opportunity in opportunities
            if opportunity.benefits
        ]
    opportunities = opportunities[:limit]

    label = query.strip() or "latest"
    if only_compensation:
        label = query.strip() or "salary/package"
    if only_benefits:
        label = query.strip() or "benefits"
    if not opportunities:
        return f"No stored FDE jobs found for: {escape(label)}"

    lines = [f"<b>FDE job search: {escape(label)}</b>"]
    for index, opportunity in enumerate(opportunities, start=1):
        lines.append(_job_search_result_text(index, opportunity))
    return "\n\n".join(lines)


def _job_search_result_text(index: int, opportunity: JobOpportunity) -> str:
    source = opportunity.apply_url or opportunity.source_url
    compensation = _join_known([opportunity.compensation, opportunity.package])
    footprint = _join_known([opportunity.company_size, opportunity.company_coverage])
    extra_lines = []
    if compensation:
        extra_lines.append(f"💰 {escape(compensation)}")
    if opportunity.benefits:
        extra_lines.append(f"🎁 {escape(opportunity.benefits)}")
    if footprint:
        extra_lines.append(f"🏬 {escape(footprint)}")
    return "\n".join([
        f"{index}. <b>{escape(opportunity.role_title)}</b>",
        f"🏢 {escape(opportunity.company)}",
        f"📍 {escape(opportunity.location or 'Verify location')} · {escape(opportunity.remote_policy or 'Verify remote')}",
        *extra_lines,
        f"🏷 {escape(opportunity.category)} · {escape(_pretty_label(opportunity.status))} · {opportunity.confidence_score}/100",
        f"🇻🇳 {escape(opportunity.vietnam_eligibility)} · {escape(opportunity.evidence_type)} signal",
        f'🔗 <a href="{escape(source, quote=True)}">{escape(source)}</a>',
    ])


def _pretty_label(value: str) -> str:
    return " ".join(str(value or "").replace("_", " ").split()) or "verify"


def _join_known(parts: list[str]) -> str:
    return " · ".join(part for part in parts if part)


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
            lines.append(
                f"{index}. {escape(row_value(row, 'title', 1))} "
                f"({escape(row_value(row, 'source_name', 3))}, {int(row_value(row, 'relevance_score', 5))}/100)"
            )
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
        item_ids = [int(row_value(row, "id", 0)) for row in rows]
        mark_delivered(conn, item_ids, slot, set())
    finally:
        conn.close()

    preview = ", ".join(f"#{int(row_value(row, 'id', 0))}" for row in rows[:8])
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
