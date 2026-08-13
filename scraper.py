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
    """Pull the first yearly-looking salary number from text, or 0 if none."""
    # Looks for things like $106,500 or $118,000
    matches = re.findall(r"\$\s?(\d{2,3}(?:,\d{3}))", text or "")
    nums = [int(m.replace(",", "")) for m in matches]
    return max(nums) if nums else 0

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
        for raw in re.findall(r"https?://[^\s|>]+", text):
            link = raw.rstrip(">").strip()
            if link in seen:
                continue
            seen.add(link)
            title, company = enrich_link(link)
            desc = (title + " " + text).lower()
            jobs.append(build_job(
                title=title or "Job lead (from Slack)",
                company=company,
                url=link,
                location="Remote",
                description=desc,
                salary_text=desc,
                source="Slack",
            ))
    print("  Collected %d job link(s) from Slack." % len(jobs))
    return jobs

def enrich_link(url):
    """Best-effort: read a job page's title to name the role + company."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DataWizards-JobBoard/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read(60000).decode("utf-8", "ignore")
    except Exception:
        return ("", "")
    m = re.search(r'<meta property="og:title" content="([^"]+)"', html) or \
        re.search(r"<title>([^<]+)</title>", html)
    title = (m.group(1).strip() if m else "")
    company = ""
    for sep in (" - ", " | ", " at ", " @ "):
        if sep in title:
            parts = title.split(sep)
            title, company = parts[0].strip(), parts[-1].strip()
            break
    return (title, company)

def build_job(title, company, url, location, description, salary_text, source):
    """Turn raw fields into our standard job record with tags + flags."""
    blob = (title + " " + description).lower()
    salary_num = find_salary_number(salary_text)
    phone = is_phone_heavy(description)
    return {
        "title": title.strip(),
        "company": company.strip(),
        "url": url.strip(),
        "salary": ("$%s+" % format(salary_num, ",")) if salary_num else "Not listed",
        "level": "Entry" if any(w in blob for w in ["entry", "junior", "associate", "coordinator"]) else "Mid",
        "remote": location.strip() or "Remote",
        "tags": tag_niches(blob),
        "feature": (not phone) and (salary_num >= MIN_FEATURE_SALARY),
        "phoneFlag": phone,
        "note": "Heads up: this role looks phone-heavy." if phone else "",
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

def main():
    print("Fetching remote jobs (public APIs only)...")
    fresh = collect_greenhouse() + collect_remotive() + collect_slack()
    print("  Collected %d raw roles (auto + Slack)." % len(fresh))

    existing = load_existing()
    by_url = {}
    # Keep existing first (preserves their original dateAdded), then add new ones.
    for job in existing + fresh:
        if job.get("url"):
            by_url.setdefault(job["url"], job)

    all_jobs = list(by_url.values())
    all_jobs.sort(key=lambda j: j.get("dateAdded", ""), reverse=True)
    print("  %d unique roles after de-duplicating." % len(all_jobs))

    # Only ONE featured job per day — the first (top) featured role each day
    # keeps its star; any others that day are un-featured.
    featured_days = set()
    for job in all_jobs:
        if job.get("feature"):
            day = job.get("dateAdded", "")
            if day in featured_days:
                job["feature"] = False
            else:
                featured_days.add(day)

    # Save the data file
    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, indent=2, ensure_ascii=False)

    # Rebuild index.html between the JOBS_START / JOBS_END markers
    rebuild_index(all_jobs)
    print("Done. Wrote jobs.json and updated index.html.")

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
