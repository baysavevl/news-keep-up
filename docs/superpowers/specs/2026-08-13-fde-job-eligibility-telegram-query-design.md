# FDE Job Eligibility and Telegram Query Design

**Date:** 2026-08-13
**Status:** Approved for implementation
**Profile:** `fde-jobs`

## Context

Production alerts exposed three distinct false-positive paths:

- An AIJobs listing for a hybrid Prague role inherited `Remote` from the source feed, lost its location during parsing, and was sent as `verify`/Weak.
- A Bing search result for `Home | Microsoft AI` was classified as an FDE opportunity and linked to a generic homepage rather than a vacancy.
- A Hightouch role explicitly located in `Remote (North America)` was sent because North America was not recognized as a country lock.

The shared cause is permissive uncertainty: the current workability predicate accepts every state except `no`, the pending queue ignores `should_alert`, source metadata can masquerade as job evidence, and Telegram search uses the same permissive predicate.

## Goals

1. Auto-send only concrete vacancies or credible hiring posts that can be performed from Vietnam with strong source evidence.
2. Accept Vietnam roles in any work mode and remote roles explicitly scoped to SEA, APAC, Asia, worldwide, global, or work-from-anywhere, provided no country lock conflicts.
3. Never auto-send a bare `Remote`, `verify`, Weak-signal, or explicit non-Vietnam country-locked role.
4. Reject generic homepages, search results, category pages, learning pages, and other URLs that are not a specific vacancy or hiring post.
5. Keep technically relevant but geographically uncertain concrete vacancies in a manual `/verify` queue.
6. Make Telegram commands list and query the same policy-approved data efficiently.
7. Suppress already-stored false positives immediately without requiring destructive database cleanup.

## Non-goals

- Do not auto-apply or contact recruiters.
- Do not delete historical opportunities or delivery records.
- Do not treat an APAC country location such as Singapore as proof that a Vietnam-based applicant is eligible.
- Do not add a new database or Telegram bot.
- Do not implement the broader cloud-fit plan in this change.

## Considered Approaches

### Raise the confidence threshold

Rejected. All three reported alerts received the same fallback score of 60, but a higher number would remain an indirect proxy for link validity and geographic eligibility. It would also discard useful uncertain jobs without making them queryable.

### Add only a final send-time block

Rejected as incomplete. It would stop Telegram spam but leave generic pages and country-locked records visible in `/jobs`, and source-level false assumptions would remain in classification.

### Layered deterministic gates

Selected. Validate role evidence, URL specificity, location scope, and alert eligibility at their natural boundaries. Keep uncertainty searchable but separate from the automatic queue.

## Eligibility Contract

The existing normalized states remain:

- `explicit_yes`: the source locates the role in Vietnam or explicitly permits Vietnam.
- `likely_possible`: the source explicitly describes cross-border remote scope such as Remote SEA, Remote APAC, Remote Asia, worldwide, global remote, or work from anywhere.
- `verify`: the role is concrete and relevant, but only says `Remote`, omits applicant geography, or otherwise lacks enough evidence.
- `no`: a non-Vietnam location/country lock, incompatible region, onsite foreign role, or another explicit exclusion.

Two predicates have separate meanings:

- *storable/workable candidate*: any relevant concrete vacancy that is not explicitly `no`; this includes `verify` so it can be reviewed manually.
- *auto-alertable opportunity*: only `explicit_yes` or `likely_possible` with deterministic evidence, a specific job/hiring-post URL, non-closed status, and `should_alert=true`.

Positive Vietnam evidence comes from job fields and job text, not a search-source name or a URL hostname containing the word `vietnam`. Negative geographic evidence may use the title, parsed location, remote policy, country, and a location-bearing URL slug. North America, US/Canada, EMEA/Europe, LATAM, and named foreign-country locks are evaluated before generic `Remote` wording.

Relocation or visa wording may keep a vacancy in `/verify`, but does not by itself make a role auto-alertable under this scope.

## Role and Source Evidence

Role matching may use the vacancy title, summary, content, author/company, and parsed item metadata. It must not use the configured source category or search query label as role evidence. In particular, a category such as `fde-adjacent-job-search` cannot satisfy the short `fde` title alias.

Source-level `remote_policy` is only a discovery hint. Item-level location and work-mode fields take precedence. Generic JSON parsing no longer stamps every ATS result as remote; it infers remote work only from item fields or explicit source metadata.

## Direct-Link Contract

An auto-alert or `/verify` result must point to one of:

- a specific ATS, official-career, or job-board vacancy;
- a LinkedIn Job URL;
- a specific LinkedIn hiring Post.

Root homepages and generic `/jobs`, `/careers`, `/openings`, search, category, tag, and learning pages are not opportunities. Aggregator results require a recognizable job/post path or a known direct-job host pattern. The URL check is deterministic and does not claim that an HTTP-live page is accepting applications; existing status handling remains authoritative.

## Pipeline Changes

```text
source item
  -> source filters
  -> role evidence independent of source labels
  -> specific job/hiring-post URL gate
  -> broad geographic classification
  -> classify/enrich and store
  -> strict auto-alert eligibility
       -> yes: pending Telegram queue
       -> uncertain: stored `/verify` queue
       -> explicit no / invalid link: hidden from job commands
```

`list_pending_job_alerts` must require `should_alert=1`. `run_fde_job_alerts` applies the strict predicate again so legacy rows with stale `should_alert=1` are suppressed immediately.

## Telegram Commands

The FDE jobs bot supports these primary commands:

- `/jobs [keywords]`, `/fit [keywords]`, `/list [keywords]`: latest suitable jobs only.
- `/vn [keywords]`: suitable jobs explicitly located in or open to Vietnam.
- `/sea [keywords]`: suitable regional/global remote jobs with strong cross-border evidence.
- `/remote [keywords]`: suitable remote jobs only; country-locked remote roles are excluded.
- `/high [keywords]`: suitable High-priority jobs.
- `/verify [keywords]`: concrete jobs whose Vietnam eligibility is still unknown; never auto-sent.
- `/company <name>`: suitable jobs for a company.
- `/query <keywords>` and `/search <keywords>`: aliases for suitable-job search in this bot.
- `/salary [keywords]` and `/benefits [keywords]`: suitable jobs with those fields.
- `/new [keywords]` and `/open [keywords]`: aliases for the latest suitable jobs.
- `/help` and `/commands`: the command menu.

Multiple search words use AND semantics across searchable job fields rather than requiring one exact phrase. `/high` filters the priority column directly. Every default command uses the strict suitable-job predicate; only `/verify` exposes uncertain eligibility.

Result messages show role, company, location/work mode, normalized Vietnam eligibility, evidence strength, status, confidence, and the direct link. The command help text explains that `/verify` is a manual review queue.

## Existing Data

No destructive migration is required. Runtime predicates hide the Prague, Microsoft homepage, Hightouch North America, and similar legacy rows from alerts and default commands. Valid uncertain direct vacancies remain visible only in `/verify`. Future classifications persist `should_alert=false` for these uncertain records.

## Testing

Test-first coverage includes:

- Prague/Czech URL with missing parsed location is not auto-alertable.
- `Remote (North America)` is classified `no` and omitted from alerts/search.
- `Home | Microsoft AI` and other generic aggregator URLs fail role/link validation.
- source category text cannot create an FDE match.
- bare `Remote` is stored as `verify` but not auto-alerted.
- Remote SEA/APAC/worldwide with no conflicting lock is auto-alertable.
- pending SQL requires `should_alert=1`.
- `/jobs`, `/vn`, `/sea`, `/remote`, `/high`, and `/verify` return disjoint policy-correct results.
- multi-token job queries use AND matching and `/high` reads priority correctly.
- existing command aliases and non-job Telegram profiles remain backward compatible.

## Operational Rollout

Run targeted tests, the full suite, and a production-data read-only audit that evaluates the reported rows through the new predicates. Restart the local LaunchAgent so it loads the new code, then run a dry-run preview. Commit using conventional messages and push the verified current branch as explicitly requested.
