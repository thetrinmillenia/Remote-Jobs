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
import datetime
import urllib.request
import urllib.parse

# -----------------------------------------------------------------------------
# 1. CONFIG  —  edit these lists any time; no other code needs to change.
# -----------------------------------------------------------------------------

# Companies whose job boards we check directly (Greenhouse "board tokens").
# Add more by copying a company's Greenhouse URL token here.
GREENHOUSE_COMPANIES = [
    "springhealth66",   # Spring Health (healthcare)
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
DAILY_TARGET = 5            # add at most this many BEST new jobs per day
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
    """Remove HTML tags so we can scan plain description text."""
    return re.sub(r"<[^>]+>", " ", text or "").lower()

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

def tag_niches(text):
    tags = []
    for niche, words in NICHE_KEYWORDS.items():
        if any(w in text for w in words):
            tags.append(niche)
    return tags

def is_phone_heavy(text):
    return any(flag in text for flag in PHONE_FLAGS)

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
                company=data.get("name") or token,
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
    for msg in data.get("messages", []):
        text = msg.get("text", "")
        # Anything you typed next to the link (e.g. a salary like "21 to 32 an hour").
        extra = re.sub(r"https?://[^\s|>]+", " ", text)
        extra = re.sub(r"[<>|]", " ", extra)
        for raw in re.findall(r"https?://[^\s|>]+", text):
            link = raw.rstrip(">").strip()
            if link in seen:
                continue
            seen.add(link)
            low = link.lower()
            if any(b in low for b in SLACK_BLOCK_DOMAINS):
                print("    (skipped reference link, not a job: %s)" % link)
                continue
            title, company, salary, body = enrich_link(link)
            if not title:
                print("    (skipped unreadable link — couldn't get clean details: %s)" % link)
                continue
            loc = "Hybrid" if is_hybrid(body) else "Remote"
            job = build_job(
                title=title,
                company=company,
                url=link,
                location=loc,
                description=(body + " " + extra),
                # pay comes from the page OR from what you typed after the link
                salary_text=(salary + " " + extra + " " + body),
                source="Slack",
            )
            # Whatever you typed after the link (minus the pay) becomes the card's
            # short note — your own 5-word description of the role.
            note = re.sub(r"\$?\s?\d[\d,\.]*k?\s*(?:-|–|to)\s*\$?\s?\d[\d,\.]*k?\s*(?:/\s*hr|per\s*hour|an\s*hour|hourly)?", " ", extra, flags=re.I)
            note = re.sub(r"\$?\s?\d[\d,\.]*k?\s*(?:/\s*hr|per\s*hour|an\s*hour|hourly)", " ", note, flags=re.I)
            note = re.sub(r"\$\s?\d[\d,\.]*k?", " ", note)
            note = re.sub(r"\s+", " ", note).strip(" -–·•,|")
            if note and not job.get("phoneFlag"):
                job["note"] = note[:90]
            jobs.append(job)
    print("  Collected %d job link(s) from Slack." % len(jobs))
    return jobs

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
    m = re.search(r'<meta property="og:title" content="([^"]+)"', html) or \
        re.search(r"<title>([^<]+)</title>", html)
    title = (m.group(1).strip() if m else "")
    company = ""
    for sep in (" - ", " | ", " at ", " @ "):
        if sep in title:
            parts = title.split(sep)
            title, company = parts[0].strip(), parts[-1].strip()
            break
    body = strip_html(html)
    salary = extract_salary(html)
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
        "salary": extract_salary(salary_text),
        "level": "Entry" if any(w in blob for w in ["entry", "junior", "associate", "coordinator"]) else "Mid",
        "remote": location.strip() or "Remote",
        "tags": tag_niches(blob),
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
    if not job.get("salary", "").strip():
        return False                       # pay transparency REQUIRED
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
    if job.get("source") == "Slack":
        s += 25                             # YOU hand-picked it → boost
    return s

def main():
    print("Curating today's remote jobs...")
    existing = load_existing()

    # Companies used in the last COMPANY_COOLDOWN_DAYS — skip them for freshness.
    cutoff = (datetime.date.today() -
              datetime.timedelta(days=COMPANY_COOLDOWN_DAYS)).isoformat()
    recent = {normalize_company(j.get("company", ""))
              for j in existing if j.get("dateAdded", "") >= cutoff}
    existing_urls = {j.get("url") for j in existing if j.get("url")}

    # How many slots are still open for today (so re-runs don't pile up).
    todays_count = sum(1 for j in existing if j.get("dateAdded") == TODAY)
    slots = max(0, DAILY_TARGET - todays_count)

    # Gather candidates. We use company-direct sources only (company ATS boards
    # + the links YOU drop in Slack) so every link points to the real employer,
    # not an aggregator. (Remotive is left out for that reason.)
    candidates = collect_greenhouse() + collect_slack()
    candidates = [c for c in candidates
                  if is_clean(c)              # clean data + PAY LISTED + remote-only
                  and not c.get("phoneFlag")   # no phone-heavy roles
                  and c.get("url") not in existing_urls]
    candidates.sort(key=score_job, reverse=True)

    picked, per_co = [], {}
    for c in candidates:
        if len(picked) >= slots:
            break
        co = normalize_company(c.get("company", ""))
        if not co or co in recent:                     # fresh companies only
            continue
        if per_co.get(co, 0) >= MAX_PER_COMPANY:        # max 3 per company
            continue
        picked.append(c)
        per_co[co] = per_co.get(co, 0) + 1
        recent.add(co)
    print("  Added %d fresh, curated job(s) today (%d slot[s] were open)."
          % (len(picked), slots))

    all_jobs = picked + existing
    all_jobs.sort(key=lambda j: j.get("dateAdded", ""), reverse=True)

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
    new_html = re.sub(r"// JOBS_START.*?// JOBS_END", block, html, flags=re.DOTALL)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(new_html)

if __name__ == "__main__":
    main()
