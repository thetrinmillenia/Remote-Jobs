#!/usr/bin/env python3
# =============================================================================
#  Remote Jobs Scraper  ·  Data Wizards
# =============================================================================
#  WHAT THIS DOES (in plain English):
#    1. Downloads PUBLIC job listings from free, public job APIs.
#    2. Keeps only REMOTE roles, tags your niches, and flags phone-heavy / low-pay.
#    3. Saves the results to  jobs.json  and rebuilds  index.html.
#
#  WHAT THIS DOES *NOT* DO (your safety review):
#    - It uses ONLY Python's built-in libraries. No third-party packages,
#      nothing to install, nothing hidden.
#    - It never reads your personal files.
#    - It never touches your passwords, email, or accounts.
#    - It never sends your data anywhere. It only DOWNLOADS from the job sites
#      listed below and WRITES two files in its own folder.
#
#  You can read every line. The only web addresses it ever contacts are the
#  ones in the CONFIG section directly below.
# =============================================================================

import os
import json
import re
import html
import datetime
import urllib.request
import urllib.parse

# -----------------------------------------------------------------------------
# 1. CONFIG  —  edit these lists any time; no other code needs to change.
# -----------------------------------------------------------------------------

# Companies whose job boards we check directly (Greenhouse "board tokens").
# Add more by copying a company's Greenhouse URL token here.
GREENHOUSE_COMPANIES = [
    "springhealth66",   # Spring Health (mental health)
    "pairteam",         # Pair Team (community health / care management)
    "cadencehealth",    # Cadence Health (remote cardiac care)
    "perfectserve",     # PerfectServe (healthcare communications)
    "garnerhealth",     # Garner Health (health navigation — lots of remote roles)
    "omadahealth",      # Omada Health (virtual care — all-remote roles)
    # Add more anytime: grab the slug from any job-boards.greenhouse.io/SLUG link.
]

# Keyword searches run against the free Remotive API (general remote board).
REMOTIVE_SEARCHES = [
    "customer support",
    "data analyst",
    "healthcare",
    "finance",
    "operations",
]

# If a role's title/description contains these, we TAG it as your niche.
NICHE_KEYWORDS = {
    "healthcare":       ["health", "clinical", "patient", "care", "medical"],
    "finance":          ["finance", "financial", "accounting", "fintech", "analyst"],
    "tech/startup":     ["engineer", "developer", "product", "startup", "saas"],
    "customer service": ["customer", "support", "success", "help desk", "client"],
    "sales":            ["sales", "account executive", "business development"],
}

# If a role's description contains these, we FLAG it as phone-heavy (you avoid these).
PHONE_FLAGS = [
    "call center", "cold call", "cold-call", "dialer", "outbound call",
    "inbound call", "phone support", "telephonic", "hours on the phone",
    "high call volume", "make calls",
]

# A role is "Featured" (★) if it is NOT phone-heavy AND pays at least this much.
MIN_FEATURE_SALARY = 80000

# How many results to pull per Remotive search (keeps things fast + tidy).
REMOTIVE_LIMIT = 25

# ---- Curation rules (the "keep it tight, keep it fresh" settings) ----
DAILY_TARGET = 5            # top out at this many BEST new jobs per day
MIN_PER_DAY = 3             # aim for at least this many jobs on every weekday
MIN_HOURLY = 18             # skip anything paying less than this per hour (or yearly equiv)
BACKFILL_DAYS = 4           # if you miss weekdays, fill up to this many recent empty ones first
WEEKLY_CHECK_DAY = 0        # 0=Monday: the day the "is this job still open?" check runs
MAX_PER_COMPANY = 3         # never more than this many roles from one company
COMPANY_COOLDOWN_DAYS = 14  # don't post the same company again within this window

# Links from these domains are NOT jobs — ignore them if pasted in Slack
# (so a TikTok or reference link never lands on the board).
SLACK_BLOCK_DOMAINS = [
    "tiktok.com", "instagram.com", "youtube.com", "youtu.be", "twitter.com",
    "x.com", "facebook.com", "linkedin.com/feed", "beacons.ai", "linktr.ee",
    "stan.store", "pinterest.", "reddit.com", "t.me", "bit.ly", "amazon.com",
]

# -----------------------------------------------------------------------------
#  BOARDS TO INTEGRATE — backlog (from TikTok list, Aug 2026)
# -----------------------------------------------------------------------------
#  Our scraper needs a FREE structured feed (RSS/JSON) for each board.
#  Status of each requested board:
#
#  ALREADY IN:
#    - Remotive (jobs.remotive.com) ..... covered by REMOTIVE_SEARCHES above
#
#  QUICK WINS (likely have a free RSS feed — verify, then add):
#    - SkipTheDrive ..................... skipthedrive.com  (WordPress RSS)
#    - Jobspresso ....................... jobspresso.co     (WordPress RSS)
#
#  EXIST BUT NO FREE FEED (use Slack catcher or paid Apify actor):
#    - Remote Rocketship ................ remoterocketship.com
#    - Career Hound ..................... careerhound.io
#    - EuropeRemotely ................... europeremotely.com
#    - Dynamite Jobs .................... dynamitejobs.com
#    - Pangian .......................... pangian.com
#
#  LOCKED / PAID (manual only):
#    - Outsourcely ...................... outsourcely.com   (login-gated)
#    - Virtual Vocations ................ virtualvocations.com (paid)
#
#  DEAD — do not add:
#    - GitHub Jobs (shut down 2021), CloudPeeps (closed)
#
#  IGNORED per request: RezPass.com
# -----------------------------------------------------------------------------

# Your Slack #remote-jobs channel — links you paste there get added to the board.
# The scraper reads it ONLY if a SLACK_TOKEN is provided (as a GitHub secret).
# Without a token, it simply skips Slack and does the auto-scrape only.
SLACK_CHANNEL_ID = "C0BNT644UHK"

# The bot posts its OWN finds here so you can review/fix them — #ai-remote-jobs.
# Fixes (company:/salary:/title:) are read from this channel too.
BOT_LOG_CHANNEL_ID = "C0BRW4C7FGW"

# A SEPARATE channel just for whole company boards / careers pages. The robot
# harvests EVERY remote job off each link you drop there (backup supply).
# Leave "" until you make the channel, then paste its channel ID here.
BOARDS_CHANNEL_ID = ""

# -----------------------------------------------------------------------------
# 2. Small helpers
# -----------------------------------------------------------------------------

TODAY = datetime.date.today().isoformat()

def fetch_json(url):
    """Download a URL and parse it as JSON. Times out after 20 seconds."""
    req = urllib.request.Request(url, headers={"User-Agent": "DataWizards-JobBoard/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)

def strip_html(text):
    """Turn HTML (or HTML-escaped text) into clean, readable plain text.
    Decodes entities first (&lt;p&gt; -> <p>, &amp; -> &), then removes tags.
    Keeps original casing so auto-written notes read normally."""
    t = html.unescape(text or "")
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[ \t\r\f\v]+", " ", t).strip()

def is_remote(text):
    t = (text or "").lower()
    return any(w in t for w in ["remote", "anywhere", "worldwide", "work from home"])

def find_salary_number(text):
    """Pull the highest yearly-looking salary number from text, or 0 if none."""
    matches = re.findall(r"\$\s?(\d{2,3}(?:,\d{3}))", text or "")
    nums = [int(m.replace(",", "")) for m in matches]
    return max(nums) if nums else 0

def _hr(a, b=None):
    return ("$%s – $%s / hr" % (a, b)) if b else ("$%s / hr" % a)

def extract_salary(text):
    """Find a clean, displayable pay range/rate in the text (from the job page
    OR from what you typed after the link in Slack). Returns '' if none found."""
    t = re.sub(r"[–—]", "-", text or "")   # normalize en/em dashes
    t = re.sub(r"\s+", " ", t)
    U = r"(?:/\s*hr|/\s*hour|per\s*hour|an\s*hour|hourly)"   # hourly unit

    # Yearly $ range: $80,000 - $100,000  or  $80k - $100k  (must have comma or k)
    m = re.search(r"\$\s?(\d{2,3},\d{3}|\d{2,3}k)\s*(?:-|to)\s*\$?\s?(\d{2,3},\d{3}|\d{2,3}k)", t, re.I)
    if m:
        return "$%s – $%s" % (m.group(1), m.group(2))
    # Hourly $ range: $20 - $27 /hr
    m = re.search(r"\$\s?(\d{1,3}(?:\.\d{1,2})?)\s*(?:-|to)\s*\$?\s?(\d{1,3}(?:\.\d{1,2})?)\s*" + U, t, re.I)
    if m:
        return _hr(m.group(1), m.group(2))
    # Hourly range WITHOUT $: 21 to 32 an hour  |  21-32/hr
    m = re.search(r"\b(\d{1,3}(?:\.\d{1,2})?)\s*(?:-|to)\s*(\d{1,3}(?:\.\d{1,2})?)\s*" + U, t, re.I)
    if m:
        return _hr(m.group(1), m.group(2))
    # Single hourly with $: $22 per hour
    m = re.search(r"\$\s?(\d{1,3}(?:\.\d{1,2})?)\s*" + U, t, re.I)
    if m:
        return _hr(m.group(1))
    # Single hourly WITHOUT $: 22 an hour
    m = re.search(r"\b(\d{1,3}(?:\.\d{1,2})?)\s*" + U, t, re.I)
    if m:
        return _hr(m.group(1))
    # Single yearly $ (needs comma or k so we don't grab small bonus numbers)
    m = re.search(r"\$\s?(\d{2,3}k|\d{2,3},\d{3})", t, re.I)
    if m:
        return "$" + m.group(1)
    return ""

def is_hybrid(text):
    return "hybrid" in (text or "").lower()

def clean_company(name):
    """Make company names tidy and consistent: real words, capitalized,
    no URL-slug leftovers (springhealth66) and no trailing US/Inc/LLC."""
    n = (name or "").strip()
    if not n:
        return ""
    # URL-slug style (no spaces, all lowercase or has digits) -> prettify
    if " " not in n and (n.islower() or any(c.isdigit() for c in n)):
        n = re.sub(r"\d+$", "", n)                     # drop trailing digits
        n = n.replace("-", " ").replace("_", " ")
    n = re.sub(r"[\s,]+(?:us|usa|inc\.?|llc|ltd\.?|corp\.?|co\.?)$", "", n, flags=re.I).strip()
    n = re.sub(r"\s*\((?:us|usa|remote|inc)\)$", "", n, flags=re.I).strip()
    if n.islower() or n.isupper():
        n = n.title()
    return n[:45].strip()

def slack_post(text, channel=None):
    """Post a message into a Slack channel (needs the bot's chat:write scope)."""
    token = os.environ.get("SLACK_TOKEN", "").strip()
    if not token:
        return
    payload = json.dumps({"channel": channel or SLACK_CHANNEL_ID, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=payload,
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json; charset=utf-8"})
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print("  ! couldn't post Slack flag: %s" % e)

def load_flagged():
    try:
        with open("flagged.json", "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_flagged(urls):
    with open("flagged.json", "w", encoding="utf-8") as f:
        json.dump(sorted(urls), f, indent=2)

def _field(text, keys):
    """Pull `keys: value` from a message, value runs until the next marker/end."""
    pat = r"\b(?:%s)\s*[:=]\s*(.+?)(?=\s+(?:company|co|salary|pay|title)\s*[:=]|$)" % keys
    m = re.search(pat, text, re.I)
    return m.group(1).strip() if m else ""

def slack_field_overrides():
    """Read #remote-jobs for `company:` / `salary:` / `title:` typed next to a link.
    Returns {url: {field: value}} so you can FIX any card — even a bot-found one."""
    token = os.environ.get("SLACK_TOKEN", "").strip()
    if not token:
        return {}
    overrides = {}
    for chan in (SLACK_CHANNEL_ID, BOT_LOG_CHANNEL_ID):   # read both channels
        if not chan:
            continue
        api = "https://slack.com/api/conversations.history?channel=%s&limit=100" % chan
        req = urllib.request.Request(api, headers={"Authorization": "Bearer " + token})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
        except Exception:
            continue
        if not data.get("ok"):
            continue
        for msg in data.get("messages", []):
            if msg.get("bot_id"):        # ignore the bot's own posts
                continue
            text = msg.get("text", "")
            fix = {}
            co = clean_company(_field(text, "company|co"))
            sal = normalize_salary(_field(text, "salary|pay"))
            ttl = _field(text, "title")
            if co:
                fix["company"] = co
            if sal:
                fix["salary"] = sal
            if ttl:
                fix["title"] = ttl[:100]
            if not fix:
                continue
            for raw in re.findall(r"https?://[^\s|>]+", text):
                overrides[raw.rstrip(">").strip()] = fix
    return overrides

def load_posted():
    try:
        with open("posted.json", "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_posted(urls):
    with open("posted.json", "w", encoding="utf-8") as f:
        json.dump(sorted(urls), f, indent=2)

def post_bot_finds(jobs):
    """Post the bot's OWN finds into #ai-remote-jobs so you have a record and can
    correct them. Each job is posted only once."""
    if not (os.environ.get("SLACK_TOKEN", "").strip() and BOT_LOG_CHANNEL_ID):
        return
    posted = load_posted()
    for j in jobs:
        u = j.get("url", "")
        if not u or u in posted:
            continue
        slack_post(":robot_face: Added *%s* — %s\n%s\nFix it? Post the link here with `company:` / `salary:` / `title:`"
                   % (j.get("title", ""), j.get("company", ""), u), channel=BOT_LOG_CHANNEL_ID)
        posted.add(u)
    save_posted(posted)

def normalize_salary(s):
    """Force every pay value into a consistent look:
    yearly  -> $100,000 – $150,000     hourly -> $20 – $24 / hr"""
    s = (s or "").strip()
    if not s:
        return s
    hourly = ("hr" in s.lower()) or ("hour" in s.lower())
    vals = []
    for n in re.findall(r"\d[\d,\.]*k?", s, re.I):
        n = n.replace(",", "")
        try:
            vals.append(float(n[:-1]) * 1000 if n.lower().endswith("k") else float(n))
        except Exception:
            pass
    if not vals:
        return s

    def fmt(v):
        if hourly:
            return ("%.2f" % v).rstrip("0").rstrip(".") if v % 1 else "%d" % v
        return "{:,}".format(int(round(v)))

    body = ("$%s – $%s" % (fmt(vals[0]), fmt(vals[1]))) if len(vals) >= 2 else ("$%s" % fmt(vals[0]))
    return body + (" / hr" if hourly else "")

CLOSED_SIGNALS = (
    "no longer accepting applications", "no longer accepting application",
    "no longer available", "position has been filled", "position is filled",
    "this position has been closed", "position has been closed",
    "this job is closed", "applications are closed", "posting has expired",
    "job posting has expired", "this job is no longer active",
    "we are no longer accepting", "job not found", "posting is closed",
    "role has been filled", "we've filled this role", "this opening is closed",
)

def is_closed(text):
    """True if the job page says the role is filled/closed/expired."""
    t = (text or "").lower()
    return any(sig in t for sig in CLOSED_SIGNALS)

def meets_min_pay(salary):
    """True if the pay is at least MIN_HOURLY/hr (or the yearly equivalent)."""
    s = (salary or "")
    nums = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", s)]
    if not nums:
        return False
    lo = min(nums)
    if "hr" in s.lower() or "hour" in s.lower():
        return lo >= MIN_HOURLY
    if "k" in s.lower():
        lo *= 1000
    return lo >= MIN_HOURLY * 2080   # yearly equivalent of the hourly floor

VAGUE_TITLES = ("opportunit", "talent community", "talent network",
                "general application", "future opening", "expression of interest",
                "candidate pool", "join our team")

def parse_jsonld_job(html):
    """Read the page's structured JobPosting data for an EXACT job title,
    company, and salary. This is what fixes 'company and job are backwards'."""
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and "@graph" in data:
            items = data["@graph"]
        for it in items:
            if not isinstance(it, dict):
                continue
            t = it.get("@type")
            is_job = t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t)
            if not is_job:
                continue
            title = (it.get("title") or "").strip()
            org = it.get("hiringOrganization")
            company = ""
            if isinstance(org, dict):
                company = (org.get("name") or "").strip()
            elif isinstance(org, str):
                company = org.strip()
            salary = ""
            bs = it.get("baseSalary")
            if isinstance(bs, dict):
                v = bs.get("value")
                unit = (bs.get("unitText") or (v.get("unitText") if isinstance(v, dict) else "") or "").upper()
                if isinstance(v, dict):
                    mn, mx = v.get("minValue"), v.get("maxValue")
                    if mn and mx:
                        if "HOUR" in unit:
                            salary = "$%s – $%s / hr" % (_num(mn), _num(mx))
                        else:
                            salary = "$%s – $%s" % (_num(mn, True), _num(mx, True))
                    elif mn:
                        salary = ("$%s / hr" % _num(mn)) if "HOUR" in unit else ("$" + _num(mn, True))
            return title, company, salary
    return "", "", ""

def _num(x, comma=False):
    try:
        n = float(x)
        n = int(n) if n == int(n) else n
    except Exception:
        return str(x)
    return "{:,}".format(n) if comma else str(n)

def tag_niches(text):
    tags = []
    for niche, words in NICHE_KEYWORDS.items():
        if any(w in text for w in words):
            tags.append(niche)
    return tags

def is_phone_heavy(text):
    low = (text or "").lower()
    return any(flag in low for flag in PHONE_FLAGS)

# -----------------------------------------------------------------------------
# 3. Collect jobs from each source into one common shape
# -----------------------------------------------------------------------------

def collect_greenhouse():
    jobs = []
    for token in GREENHOUSE_COMPANIES:
        url = "https://boards-api.greenhouse.io/v1/boards/%s/jobs?content=true" % token
        try:
            data = fetch_json(url)
        except Exception as e:
            print("  ! Greenhouse '%s' failed: %s" % (token, e))
            continue
        for j in data.get("jobs", []):
            location = (j.get("location") or {}).get("name", "")
            if not is_remote(location) and not is_remote(j.get("content", "")):
                continue
            desc = strip_html(j.get("content", ""))
            jobs.append(build_job(
                title=j.get("title", ""),
                company=clean_company(j.get("company_name") or data.get("name") or token),
                url=j.get("absolute_url", ""),
                location=location or "Remote",
                description=desc,
                salary_text=desc,
                source="Greenhouse",
            ))
    return jobs

def collect_remotive():
    jobs = []
    for term in REMOTIVE_SEARCHES:
        url = "https://remotive.com/api/remote-jobs?search=%s&limit=%d" % (
            urllib.parse.quote(term), REMOTIVE_LIMIT)
        try:
            data = fetch_json(url)
        except Exception as e:
            print("  ! Remotive '%s' failed: %s" % (term, e))
            continue
        for j in data.get("jobs", []):
            desc = strip_html(j.get("description", ""))
            jobs.append(build_job(
                title=j.get("title", ""),
                company=j.get("company_name", ""),
                url=j.get("url", ""),
                location=j.get("candidate_required_location", "Remote"),
                description=desc,
                salary_text=(j.get("salary", "") + " " + desc),
                source="Remotive",
            ))
    return jobs

def _board_root(url):
    """If the link is a company's whole job board, return (kind, slug)."""
    for kind, pat in (("greenhouse", r"https?://(?:job-boards|boards)\.greenhouse\.io/([^/?#]+)/?$"),
                      ("lever",      r"https?://jobs\.lever\.co/([^/?#]+)/?$"),
                      ("ashby",      r"https?://jobs\.ashbyhq\.com/([^/?#]+)/?$")):
        m = re.match(pat, url, re.I)
        if m:
            return (kind, m.group(1))
    return None

def _is_single_job(url):
    """True if the link points to one specific job posting (not a board/page)."""
    pats = (r"greenhouse\.io/[^/]+/jobs/\d+", r"lever\.co/[^/]+/[0-9a-f\-]{18,}",
            r"ashbyhq\.com/[^/]+/[0-9a-f\-]{18,}", r"workable\.com/.+/j/",
            r"myworkdayjobs\.com/.+/job/", r"icims\.com/jobs/\d+",
            r"/careers/jobs/\d+", r"/job/\d+")
    return any(re.search(p, url, re.I) for p in pats)

def board_job_urls(kind, slug, cap=20):
    """Pull all REMOTE job URLs from a company's board via its public API."""
    urls = []
    try:
        if kind == "greenhouse":
            data = fetch_json("https://boards-api.greenhouse.io/v1/boards/%s/jobs?content=true" % slug)
            for j in data.get("jobs", []):
                loc = (j.get("location") or {}).get("name", "")
                if is_remote(loc) or is_remote(j.get("content", "")):
                    urls.append(j.get("absolute_url", ""))
        elif kind == "lever":
            data = fetch_json("https://api.lever.co/v0/postings/%s?mode=json" % slug)
            for j in data:
                blob = ((j.get("categories") or {}).get("location", "") + " " +
                        (j.get("workplaceType") or ""))
                if is_remote(blob):
                    urls.append(j.get("hostedUrl", ""))
        elif kind == "ashby":
            data = fetch_json("https://api.ashbyhq.com/posting-api/job-board/%s" % slug)
            for j in data.get("jobs", []):
                if j.get("isRemote") or is_remote(j.get("location", "")):
                    urls.append(j.get("jobUrl", ""))
    except Exception as e:
        print("  ! couldn't read %s board '%s': %s" % (kind, slug, e))
    return [u for u in urls if u][:cap]

def harvest_generic(url, cap=15):
    """Grab individual job-application links off a listings/careers page."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DataWizards-JobBoard/1.0"})
        with urllib.request.urlopen(req, timeout=18) as r:
            html = r.read(400000).decode("utf-8", "ignore")
    except Exception:
        return []
    pats = (r"https?://[a-z0-9.\-]*greenhouse\.io/[^\"'<>\s]+/jobs/\d+",
            r"https?://jobs\.lever\.co/[^\"'<>\s]+/[0-9a-f\-]{18,}",
            r"https?://jobs\.ashbyhq\.com/[^\"'<>\s]+/[0-9a-f\-]{18,}",
            r"https?://[a-z0-9.\-]*workable\.com/[^\"'<>\s]*/j/[A-Za-z0-9]+",
            r"https?://[a-z0-9.\-]*myworkdayjobs\.com/[^\"'<>\s]+/job/[^\"'<>\s]+",
            r"https?://[a-z0-9.\-]*icims\.com/jobs/\d+[^\"'<>\s]*")
    found = []
    for p in pats:
        for m in re.findall(p, html, re.I):
            u = m.rstrip(".,);\"'")
            if u not in found:
                found.append(u)
    return found[:cap]

def expand_slack_link(link):
    """Turn one pasted link into the list of job links to actually process:
    a board page -> all its remote jobs; a listings page -> the jobs found on it;
    a single posting -> just itself."""
    board = _board_root(link)
    if board:
        found = board_job_urls(*board)
        if found:
            print("  Found %d remote job(s) on the %s board: %s" % (len(found), board[0], link))
            return found
    if _is_single_job(link):
        return [link]
    found = harvest_generic(link)
    if found:
        print("  Harvested %d job link(s) from page: %s" % (len(found), link))
        return found
    return [link]

def collect_slack():
    """Read job links YOU pasted into #remote-jobs and add them to the board.
    Runs only if a SLACK_TOKEN is provided; otherwise skips quietly."""
    token = os.environ.get("SLACK_TOKEN", "").strip()
    if not token:
        print("  (No SLACK_TOKEN — skipping Slack; auto-scrape only.)")
        return []
    api = "https://slack.com/api/conversations.history?channel=%s&limit=100" % SLACK_CHANNEL_ID
    req = urllib.request.Request(api, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    except Exception as e:
        print("  ! Slack read failed: %s" % e)
        return []
    if not data.get("ok"):
        print("  ! Slack API error: %s" % data.get("error"))
        return []
    jobs, seen = [], set()
    flagged = load_flagged()
    for msg in data.get("messages", []):
        if msg.get("bot_id"):          # ignore the bot's own posts, only read YOURS
            continue
        text = msg.get("text", "")
        # Anything you typed next to the link: pay ("21 to 32 an hour"), a short
        # note, and/or an explicit company ("company: Acme Health").
        extra = re.sub(r"https?://[^\s|>]+", " ", text)
        extra = re.sub(r"[<>|*]", " ", extra)          # also drop Slack *bold* stars
        # Trust what YOU type: title / company / pay markers win over the page.
        typed_company = clean_company(_field(extra, "company|co"))
        typed_title = _field(extra, "title").strip(" -–·").strip()
        typed_salary = extract_salary(extra)
        for raw in re.findall(r"https?://[^\s|>]+", text):
            posted = raw.rstrip(">").strip()
            if any(b in posted.lower() for b in SLACK_BLOCK_DOMAINS):
                print("    (skipped reference link, not a job: %s)" % posted)
                continue
            if posted in seen:
                continue
            seen.add(posted)
            title, company, salary, body = enrich_link(posted)
            if not (typed_title or title):
                print("    (skipped unreadable link — couldn't get details: %s)" % posted)
                continue
            if is_closed(body):
                continue
            title = typed_title or title
            company = typed_company or clean_company(company)
            if not company:
                if posted not in flagged:
                    slack_post(":label: I couldn't detect the *company* for this job:\n%s\n"
                               "Post the link with `company: Company Name` and I'll add it." % posted)
                    flagged.add(posted)
                continue
            loc = "Hybrid" if is_hybrid(body) else "Remote"
            job = build_job(
                title=title,
                company=company,
                url=posted,
                location=loc,
                description=body,
                salary_text=(typed_salary + " " + salary + " " + body),   # YOUR pay first
                source="Slack",
            )
            job["srcMsg"] = posted     # remember the message that created it (delete-sync)
            jobs.append(job)
    save_flagged(flagged)
    print("  Collected %d job link(s) from Slack." % len(jobs))
    return jobs

def collect_boards():
    """Read the SEPARATE boards channel and harvest every remote job off each
    board/careers page you drop there. Marked 'Slack-board' = backup supply."""
    if not BOARDS_CHANNEL_ID:
        return []
    token = os.environ.get("SLACK_TOKEN", "").strip()
    if not token:
        return []
    api = "https://slack.com/api/conversations.history?channel=%s&limit=100" % BOARDS_CHANNEL_ID
    req = urllib.request.Request(api, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    except Exception as e:
        print("  ! boards channel read failed: %s" % e)
        return []
    if not data.get("ok"):
        print("  ! boards channel error: %s" % data.get("error"))
        return []
    jobs, seen = [], set()
    for msg in data.get("messages", []):
        if msg.get("bot_id"):
            continue
        for raw in re.findall(r"https?://[^\s|>]+", msg.get("text", "")):
            posted = raw.rstrip(">").strip()
            if any(b in posted.lower() for b in SLACK_BLOCK_DOMAINS):
                continue
            for link in expand_slack_link(posted):
                if link in seen:
                    continue
                seen.add(link)
                title, company, salary, body = enrich_link(link)
                if not title or is_closed(body):
                    continue
                company = clean_company(company)
                if not company:
                    continue
                loc = "Hybrid" if is_hybrid(body) else "Remote"
                job = build_job(
                    title=title, company=company, url=link, location=loc,
                    description=body, salary_text=(salary + " " + body),
                    source="Slack-board")
                job["srcMsg"] = posted     # the board link you posted (delete-sync)
                jobs.append(job)
    print("  Collected %d job(s) from the boards channel." % len(jobs))
    return jobs

def slack_live_links():
    """Every job/board link still present in your Slack channels right now, plus a
    flag for whether we read them fully (so we NEVER prune on a partial read)."""
    token = os.environ.get("SLACK_TOKEN", "").strip()
    if not token:
        return set(), False
    links, ok = set(), True
    for chan in (SLACK_CHANNEL_ID, BOT_LOG_CHANNEL_ID, BOARDS_CHANNEL_ID):
        if not chan:
            continue
        api = "https://slack.com/api/conversations.history?channel=%s&limit=200" % chan
        req = urllib.request.Request(api, headers={"Authorization": "Bearer " + token})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
        except Exception:
            ok = False
            continue
        if not data.get("ok") or data.get("has_more"):
            ok = False
        for msg in data.get("messages", []):
            if msg.get("bot_id"):
                continue
            for raw in re.findall(r"https?://[^\s|>]+", msg.get("text", "")):
                links.add(raw.rstrip(">").strip())
    return links, ok

def enrich_link(url):
    """Read a job page thoroughly: pull title, company, listed salary, and the
    full page text (so we can also detect phone-heavy / hybrid). Returns
    (title, company, salary, body_text) — empties if the page can't be read."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DataWizards-JobBoard/1.0"})
        with urllib.request.urlopen(req, timeout=18) as r:
            html = r.read(200000).decode("utf-8", "ignore")
    except Exception:
        return ("", "", "", "")
    body = strip_html(html)
    # 1) Best source: structured JobPosting data → exact job title + company + pay.
    jt, jc, js = parse_jsonld_job(html)
    # 2) Fallback: the page/browser title (prefer "Job @ Company" style).
    ot = re.search(r'<meta property="og:title" content="([^"]+)"', html) or \
         re.search(r"<title>([^<]+)</title>", html)
    otitle = (ot.group(1).strip() if ot else "")
    ocompany = ""
    for sep in (" @ ", " | ", " - ", " at "):
        if sep in otitle:
            parts = otitle.split(sep)
            otitle, ocompany = parts[0].strip(), parts[-1].strip()
            break
    title = jt or otitle
    company = jc or ocompany
    salary = js or extract_salary(html)
    return (title, company, salary, body)

def summarize(text, title=""):
    """Auto-write a short descriptor by pulling the sentence that best describes
    the role from the job text, then trimming it. No AI, no typing needed."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", t)
    keys = ["you will", "you'll", "you’ll", "as a ", "as an ", "we are hiring",
            "we're hiring", "we are looking", "we're looking", "responsible for",
            "in this role", "this role"]
    skip = ("our mission", "about ", "we believe", "we partner", "we are ",
            "founded", "headquartered", "backed by")
    pick = ""
    for s in sentences:
        sl = s.lower()
        if any(k in sl for k in keys) and 25 < len(s) < 170:
            pick = s
            break
    if not pick:
        for s in sentences:
            if 30 < len(s) < 170 and not s.lower().startswith(skip):
                pick = s
                break
    if not pick:
        return ""
    words = pick.split()
    if len(words) > 13:
        pick = " ".join(words[:13]).rstrip(",;:") + "…"
    return pick.strip()

def build_job(title, company, url, location, description, salary_text, source):
    """Turn raw fields into our standard job record with tags + flags."""
    blob = (title + " " + description).lower()
    salary_num = find_salary_number(salary_text)
    phone = is_phone_heavy(description)
    return {
        "title": title.strip(),
        "company": company.strip(),
        "url": url.strip(),
        "salary": normalize_salary(extract_salary(salary_text)),
        "level": "Entry" if any(w in blob for w in ["entry", "junior", "associate", "coordinator"]) else "Mid",
        "remote": location.strip() or "Remote",
        "tags": tag_niches(blob)[:4],
        "feature": (not phone) and (salary_num >= MIN_FEATURE_SALARY),
        "phoneFlag": phone,
        "note": ("Heads up: this role looks phone-heavy." if phone else summarize(description, title)),
        "source": source,
        "datePosted": "",
        "dateAdded": TODAY,
    }

# -----------------------------------------------------------------------------
# 4. Merge, de-duplicate, and save
# -----------------------------------------------------------------------------

def load_existing():
    """Read jobs already on the board so old days are preserved."""
    try:
        with open("jobs.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def normalize_company(name):
    """Turn 'Spring Health / Alma' and 'Spring Health, Inc.' into one key."""
    n = (name or "").lower().strip()
    n = re.sub(r"\s*/.*$", "", n)          # text before a slash
    n = re.sub(r"[^a-z0-9 ]", "", n)       # drop punctuation
    return n.strip()

def is_clean(job):
    """Only keep cards that will look complete and tidy on the board."""
    t = job.get("title", "").strip()
    c = job.get("company", "").strip()
    u = job.get("url", "").strip()
    if not t or not c or not u:
        return False
    if len(t) < 3 or t.lower().startswith("job lead"):
        return False
    if any(v in t.lower() for v in VAGUE_TITLES):
        return False                       # skip vague "Future Opportunities" posts
    if not job.get("salary", "").strip():
        return False                       # pay transparency REQUIRED
    if not meets_min_pay(job.get("salary", "")):
        return False                       # below the $18/hr floor
    if is_hybrid(job.get("remote", "")):
        return False                       # remote only — no hybrid
    return True

def score_job(job):
    """Higher = stronger pick. Rewards real pay, niche fit, and your Slack picks."""
    s = 0
    sal = find_salary_number(job.get("salary", ""))
    if sal >= 100000:
        s += 40
    elif sal >= 80000:
        s += 30
    elif sal > 0:
        s += 15
    elif job.get("salary") not in ("", "Not listed"):
        s += 8                              # hourly rate is listed
    s += 6 * len(job.get("tags", []))       # niche matches
    src = job.get("source")
    if src == "Slack":
        s += 40                             # YOU hand-picked this exact link → first
    elif src == "Slack-board":
        s += 15                             # from a page/board you added → next
    # (Greenhouse watchlist gets no boost → it's the backup filler)
    return s

def mark_closed(jobs):
    """Once a week (on WEEKLY_CHECK_DAY), re-check every posted job and label any
    that are filled/closed with a CLOSED badge — instead of deleting them.
    Conservative: only changes a job's status when its page actually loads, so a
    temporary network glitch never mislabels the board."""
    if datetime.date.today().weekday() != WEEKLY_CHECK_DAY:
        return jobs                          # only runs on the weekly check day
    print("  Weekly check: verifying which posted jobs are still open...")
    for j in jobs:
        try:
            body = enrich_link(j.get("url", ""))[3]
        except Exception:
            body = ""
        if body:                             # only update when the page loaded
            was = j.get("closed", False)
            j["closed"] = is_closed(body)
            if j["closed"] and not was:
                print("  (marked CLOSED: %s)" % j.get("title", ""))
    return jobs

def main():
    print("Curating today's remote jobs...")
    existing = mark_closed(load_existing())

    # FIX command: apply any `company:` / `salary:` / `title:` you typed in Slack
    # to jobs already on the board (correct any card without editing files).
    overrides = slack_field_overrides()
    for j in existing:
        fix = overrides.get(j.get("url"))
        if fix:
            j.update(fix)

    # Delete-sync: if you removed a Slack message, drop the job(s) it created.
    # Guarded — if Slack can't be read fully, nothing is removed.
    live_links, links_ok = slack_live_links()
    if links_ok:
        def _keep(j):
            src = j.get("source")
            if src not in ("Slack", "Slack-board"):
                return True                       # watchlist jobs are never pruned
            key = j.get("srcMsg") or (j.get("url") if src == "Slack" else "")
            if not key:
                return True                       # can't tell (older board job) -> keep
            return key in live_links
        before = len(existing)
        existing = [j for j in existing if _keep(j)]
        if before - len(existing):
            print("  Removed %d job(s) whose Slack message was deleted." % (before - len(existing)))

    # Companies used in the last COMPANY_COOLDOWN_DAYS — skip them for freshness.
    cutoff = (datetime.date.today() -
              datetime.timedelta(days=COMPANY_COOLDOWN_DAYS)).isoformat()
    recent = {normalize_company(j.get("company", ""))
              for j in existing if j.get("dateAdded", "") >= cutoff}
    existing_urls = {j.get("url") for j in existing if j.get("url")}

    # Recent weekdays (oldest -> today) and how many jobs each has right now.
    # We'll fill every one up to at least MIN_PER_DAY, then top up toward DAILY_TARGET.
    today = datetime.date.today()
    day_counts = []
    for i in range(BACKFILL_DAYS, -1, -1):               # include today (i = 0)
        d = today - datetime.timedelta(days=i)
        if d.weekday() >= 5:                              # weekdays only (Mon–Fri)
            continue
        cnt = sum(1 for j in existing if j.get("dateAdded") == d.isoformat())
        day_counts.append([d.isoformat(), cnt])
    total_slots = sum(max(0, DAILY_TARGET - c) for _, c in day_counts)

    # Gather candidates. Company-direct sources only (company ATS boards + your
    # Slack links) so every link points to the real employer.
    candidates = collect_greenhouse() + collect_slack() + collect_boards()
    candidates = [c for c in candidates
                  if is_clean(c)              # clean data + PAY LISTED + remote-only
                  and not c.get("phoneFlag")   # no phone-heavy roles
                  and c.get("url") not in existing_urls]
    candidates.sort(key=score_job, reverse=True)

    picked, per_co, seen_urls = [], {}, set()
    for c in candidates:
        if len(picked) >= total_slots:
            break
        u = c.get("url", "")
        if u in seen_urls:                             # same job from two sources
            continue
        co = normalize_company(c.get("company", ""))
        if not co or co in recent:                     # fresh companies only
            continue
        if per_co.get(co, 0) >= MAX_PER_COMPANY:        # max 3 per company
            continue
        picked.append(c)
        seen_urls.add(u)
        per_co[co] = per_co.get(co, 0) + 1
        recent.add(co)

    # Assign picks to days in two passes: first bring EVERY weekday up to the
    # required minimum (oldest first), then top up toward the daily target.
    for target in (MIN_PER_DAY, DAILY_TARGET):
        for c in picked:
            if c.get("_day"):
                continue
            for day in day_counts:
                if day[1] < target:
                    c["_day"] = day[0]
                    day[1] += 1
                    break
    for c in picked:
        c["dateAdded"] = c.pop("_day", today.isoformat())
    short = [d for d, c in day_counts if c < MIN_PER_DAY]
    msg = "  Added %d curated job(s) (target %d–%d/day)." % (len(picked), MIN_PER_DAY, DAILY_TARGET)
    if short:
        msg += " Still under %d on: %s — needs more links." % (MIN_PER_DAY, ", ".join(short))
    print(msg)

    # Post the bot's OWN finds into Slack so you can review / fix them.
    post_bot_finds([c for c in picked if c.get("source") in ("Greenhouse", "Slack-board")])

    all_jobs = picked + existing
    all_jobs.sort(key=lambda j: j.get("dateAdded", ""), reverse=True)

    # Consistency pass: cap tags at 4 and standardize every salary format
    # (applies to older jobs too, so the whole board looks uniform).
    for j in all_jobs:
        j["tags"] = (j.get("tags") or [])[:4]
        j["salary"] = normalize_salary(j.get("salary", ""))
        j["company"] = clean_company(j.get("company", ""))

    # One featured job per day.
    featured_days = set()
    for job in all_jobs:
        if job.get("feature"):
            day = job.get("dateAdded", "")
            if day in featured_days:
                job["feature"] = False
            else:
                featured_days.add(day)

    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, indent=2, ensure_ascii=False)
    rebuild_index(all_jobs)
    print("Done. Board now shows %d jobs total." % len(all_jobs))

def rebuild_index(jobs):
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()
    except Exception:
        print("  ! index.html not found — skipping page rebuild.")
        return
    block = "// JOBS_START\nconst JOBS = %s;\n// JOBS_END" % json.dumps(jobs, indent=2, ensure_ascii=False)
    # Use a replacement FUNCTION so backslashes/$-signs in job text are never
    # mistaken for regex backreferences (which would corrupt or crash the write).
    new_html = re.sub(r"// JOBS_START.*?// JOBS_END", lambda _m: block, html, flags=re.DOTALL)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(new_html)

if __name__ == "__main__":
    main()
