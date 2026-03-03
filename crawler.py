#!/usr/bin/env python3
"""
Production-ready crawler that automatically handles retries
"""

import yaml
import requests
from bs4 import BeautifulSoup, Tag
from typing import Dict, Optional, Set, List, Tuple
from urllib.parse import urljoin, urlparse
import sys
import argparse
import time
from datetime import datetime, timedelta
from database import Database
from enum import Enum


class CrawlMode(Enum):
    NORMAL = "normal"  # Crawl new URLs and retry failed ones
    RETRY_ONLY = "retry_only"  # Only retry failed URLs
    NEW_ONLY = "new_only"  # Only crawl new URLs, skip retries


def load_config(path: str = "config.yaml") -> Dict:
    """Load configuration from YAML file"""
    with open(path, "r") as f:
        return yaml.safe_load(f)


def calculate_backoff_time(
    retry_count: int, base_backoff: float = 1.0, max_backoff: float = 60.0
) -> float:
    """Calculate exponential backoff time"""
    backoff = min(base_backoff * (2**retry_count), max_backoff)
    return backoff


def should_retry_now(last_crawled: str, retry_count: int) -> bool:
    """Check if enough time has passed for retry based on backoff strategy"""
    if not last_crawled:
        return True

    last_crawled_time = datetime.fromisoformat(last_crawled)
    backoff_seconds = calculate_backoff_time(retry_count)
    next_retry_time = last_crawled_time + timedelta(seconds=backoff_seconds)

    return datetime.now() >= next_retry_time


def mark_non_retryable_error(db: Database, url: str, max_retries: int) -> None:
    """Mark a URL as permanently failed so it won't be queued again."""
    now = datetime.now().isoformat()
    with db.get_cursor() as cursor:
        cursor.execute(
            """
            UPDATE urls
            SET status = 'error',
                http_status = NULL,
                retry_count = ?,
                last_crawled = ?,
                updated_at = ?
            WHERE url = ?
        """,
            (max_retries, now, now, url),
        )


def fetch_page_with_retry(
    url: str, config: Dict, retry_count: int = 0
) -> Tuple[Optional[requests.Response], bool]:
    """
    Fetch a page with retry awareness
    Returns: (response, should_retry)
    """
    headers = {"User-Agent": config["crawler"]["user_agent"]}

    # Add delay if this is a retry
    if retry_count > 0:
        backoff_time = calculate_backoff_time(retry_count - 1)
        print(f"  ⏳ Retry {retry_count} after {backoff_time:.1f}s backoff")
        time.sleep(backoff_time)

    try:
        print(f"  Fetching: {url}")
        response = requests.get(
            url, headers=headers, timeout=config["crawler"]["timeout"]
        )
        response.raise_for_status()
        return response, False  # Success, no retry needed

    except requests.exceptions.Timeout:
        print(f"  ⏱️  Timeout error")
        return None, True

    except requests.exceptions.ConnectionError:
        print(f"  🔌 Connection error")
        return None, True

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else None

        if status_code:
            if status_code == 429:
                print(f"  🚦 Rate limited (429)")
                return None, True
            elif status_code == 503:
                print(f"  🔧 Service unavailable (503)")
                return None, True
            elif 500 <= status_code < 600:
                print(f"  💥 Server error ({status_code})")
                return None, True
            else:
                print(f"  ❌ Client error ({status_code}) - will not retry")
                return None, False
        else:
            print(f"  ❌ HTTP error: {e}")
            return None, True

    except requests.RequestException as e:
        print(f"  ❌ Request error: {e}")
        return None, True


def extract_seo_data(html: str, url: str) -> Dict:
    """Extract basic SEO information from HTML"""
    soup = BeautifulSoup(html, "lxml")

    data = {
        "url": url,
        "title": None,
        "meta_description": None,
        "h1_tags": [],
        "h2_tags": [],
        "status": "success",
    }

    title_tag = soup.find("title")
    if title_tag:
        data["title"] = title_tag.get_text(strip=True)

    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and isinstance(meta_desc, Tag):
        content = meta_desc.get("content")
        if content and isinstance(content, str):
            data["meta_description"] = content.strip()

    # Extract canonical URL
    canonical_link = soup.find("link", attrs={"rel": "canonical"})
    if canonical_link and isinstance(canonical_link, Tag):
        href = canonical_link.get("href")
        if href and isinstance(href, str):
            data["canonical_url"] = href.strip()

    h1_tags = soup.find_all("h1")
    data["h1_tags"] = [h1.get_text(strip=True) for h1 in h1_tags]

    h2_tags = soup.find_all("h2")
    data["h2_tags"] = [h2.get_text(strip=True) for h2 in h2_tags]

    return data


# File extensions to exclude from crawling (non-HTML content)
EXCLUDED_EXTENSIONS = {
    '.zip', '.tar', '.gz', '.rar', '.7z',  # archives
    '.md', '.markdown',  # markdown
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',  # documents
    '.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.ico', '.bmp',  # images
    '.mp3', '.wav', '.ogg', '.flac',  # audio
    '.mp4', '.avi', '.mov', '.wmv', '.webm',  # video
    '.css', '.js', '.json', '.xml',  # web assets
    '.exe', '.dmg', '.apk', '.msi',  # executables
}


def normalize_hostname(hostname: Optional[str]) -> str:
    """Normalize hostname for consistent comparisons."""
    return (hostname or "").strip().lower().rstrip(".")


def get_allowed_host_rules(config: Dict) -> Tuple[str, Set[str], bool]:
    """Build hostname allow-list rules from config."""
    site_config = config.get("site", {})
    base_url = site_config.get("base_url", "")
    base_host = normalize_hostname(urlparse(base_url).hostname)

    explicit_hosts: Set[str] = set()
    if base_host:
        explicit_hosts.add(base_host)

    # Accept either a list of labels (e.g. "docs") or full hostnames.
    for value in site_config.get("allowed_subdomains", []):
        subdomain = normalize_hostname(str(value))
        if not subdomain:
            continue
        if "." in subdomain:
            explicit_hosts.add(subdomain)
        elif base_host:
            explicit_hosts.add(f"{subdomain}.{base_host}")

    allow_subdomains = bool(site_config.get("allow_subdomains", False))
    return base_host, explicit_hosts, allow_subdomains


def is_allowed_host(
    hostname: Optional[str],
    base_host: str,
    explicit_hosts: Set[str],
    allow_subdomains: bool,
) -> bool:
    """Check whether a hostname should be treated as internal."""
    candidate = normalize_hostname(hostname)
    if not candidate:
        return False

    if candidate in explicit_hosts:
        return True

    if allow_subdomains and base_host and candidate.endswith(f".{base_host}"):
        return True

    return False


def resolve_crawled_url(requested_url: str, fetched_url: Optional[str]) -> str:
    """Use final fetched URL when available, removing fragments."""
    effective_url = (fetched_url or requested_url).strip()
    return effective_url.split("#")[0]


def has_template_placeholder(url: str) -> bool:
    """Detect unresolved route placeholders such as {path} in URLs."""
    lower_url = url.lower()
    return (
        "{" in lower_url
        or "}" in lower_url
        or "%7b" in lower_url
        or "%7d" in lower_url
    )


def has_excluded_extension(url: str) -> bool:
    """Detect URLs that resolve to excluded file extensions."""
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in EXCLUDED_EXTENSIONS)


def get_invalid_url_reason(url: str) -> Optional[str]:
    """Return skip reason for URLs that should never be crawled."""
    if has_template_placeholder(url):
        return "unresolved template URL"
    if has_excluded_extension(url):
        return "excluded file extension URL"
    return None


def extract_links(html: str, base_url: str, config: Dict) -> List[str]:
    """Extract all internal links from the page"""
    soup = BeautifulSoup(html, "lxml")
    links = []
    base_host, explicit_hosts, allow_subdomains = get_allowed_host_rules(config)
    exclude_patterns = config.get("crawler", {}).get("exclude_patterns", [])

    for link in soup.find_all("a", href=True):
        href = link["href"]
        absolute_url = urljoin(base_url, href)
        parsed_url = urlparse(absolute_url)

        if not is_allowed_host(
            parsed_url.hostname, base_host, explicit_hosts, allow_subdomains
        ):
            continue

        absolute_url = absolute_url.split("#")[0]

        # Skip unresolved URL templates like /{path}
        if has_template_placeholder(absolute_url):
            continue

        # Skip non-HTML and markdown file extensions
        if has_excluded_extension(absolute_url):
            continue

        # Skip excluded URL patterns
        path = parsed_url.path.lower()
        if any(pattern in path for pattern in exclude_patterns):
            continue

        if absolute_url and absolute_url not in links:
            links.append(absolute_url)

    return links


def identify_seo_issues(data: Dict, config: Dict) -> List[Dict]:
    """Identify SEO issues from the extracted data using config rules"""
    issues = []
    
    # Get SEO config with defaults
    seo_config = config.get('seo', {})
    
    # Title rules
    title_config = seo_config.get('title', {})
    title_min = title_config.get('min_length', 30)
    title_max = title_config.get('max_length', 60)
    title_required = title_config.get('required', True)
    
    if not data['title']:
        if title_required:
            issues.append({'type': 'missing_title', 'details': 'No title tag found'})
    else:
        title_length = len(data['title'])
        if title_length < title_min:
            issues.append({
                'type': 'short_title', 
                'details': f'Title is {title_length} characters (recommended: {title_min}-{title_max})'
            })
        elif title_length > title_max:
            issues.append({
                'type': 'long_title', 
                'details': f'Title is {title_length} characters (recommended: {title_min}-{title_max})'
            })
    
    # Meta description rules
    meta_config = seo_config.get('meta_description', {})
    meta_min = meta_config.get('min_length', 120)
    meta_max = meta_config.get('max_length', 160)
    meta_required = meta_config.get('required', True)
    
    if not data['meta_description']:
        if meta_required:
            issues.append({'type': 'missing_meta_description', 'details': 'No meta description found'})
    else:
        meta_length = len(data['meta_description'])
        if meta_length < meta_min:
            issues.append({
                'type': 'short_meta_description', 
                'details': f'Meta description is {meta_length} characters (recommended: {meta_min}-{meta_max})'
            })
        elif meta_length > meta_max:
            issues.append({
                'type': 'long_meta_description', 
                'details': f'Meta description is {meta_length} characters (recommended: {meta_min}-{meta_max})'
            })
    
    # Heading rules
    heading_config = seo_config.get('headings', {})
    max_h1 = heading_config.get('max_h1_tags', 1)
    min_h1 = heading_config.get('min_h1_tags', 1)
    warn_empty = heading_config.get('warn_empty_headings', True)
    
    h1_count = len(data['h1_tags'])
    if h1_count < min_h1:
        issues.append({'type': 'missing_h1', 'details': f'No H1 tag found (recommended: {min_h1})'})
    elif h1_count > max_h1:
        issues.append({
            'type': 'multiple_h1', 
            'details': f'Found {h1_count} H1 tags (recommended: {max_h1})'
        })
    
    # Check for empty H1 tags
    if warn_empty and data['h1_tags']:
        empty_h1s = [h1 for h1 in data['h1_tags'] if not h1.strip()]
        if empty_h1s:
            issues.append({'type': 'empty_h1', 'details': f'Found {len(empty_h1s)} empty H1 tag(s)'})
    
    # Canonical URL rules
    canonical_config = seo_config.get('canonical', {})
    require_canonical = canonical_config.get('required', True)
    check_self_referencing = canonical_config.get('check_self_referencing', True)
    
    if require_canonical and not data.get('canonical_url'):
        issues.append({
            'type': 'missing_canonical', 
            'details': 'No canonical URL specified'
        })
    elif data.get('canonical_url') and check_self_referencing:
        # Normalize URLs for comparison (remove trailing slashes, fragments, etc.)
        from urllib.parse import urlparse, urlunparse
        
        def normalize_url(url):
            parsed = urlparse(url)
            # Remove fragment and normalize path
            normalized = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path.rstrip('/') if parsed.path != '/' else '/',
                parsed.params,
                parsed.query,
                ''  # remove fragment
            ))
            return normalized
        
        canonical_normalized = normalize_url(data['canonical_url'])
        actual_normalized = normalize_url(data['url'])
        
        if canonical_normalized != actual_normalized:
            issues.append({
                'type': 'canonical_mismatch',
                'details': f'Canonical URL ({data["canonical_url"]}) doesn\'t match actual URL'
            })
    
    return issues


def build_crawl_queue(db: Database, config: Dict, mode: CrawlMode, base_url: str, preview: bool = False) -> Tuple[List[str], int, int]:
    """
    Build the crawl queue based on mode
    Returns: (urls_to_visit, retry_count, new_count)
    """
    urls_to_visit = []
    retry_count = 0
    new_count = 0
    
    # Check if this is the very first run (database is empty)
    with db.get_cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM urls')
        result = cursor.fetchone()
        total_urls = result[0] if result else 0
        print(f"DEBUG: Total URLs in database: {total_urls}")
    
    # If database is completely empty, start with base URL
    if total_urls == 0:
        print(f"📍 Starting fresh crawl from: {base_url}")
        urls_to_visit.append(base_url)
        if not preview:
            db.save_url(base_url, status='new')
        new_count = 1
        return urls_to_visit, retry_count, new_count
    
    # Otherwise, build queue from existing data
    print(f"DEBUG: Building queue from existing {total_urls} URLs")
    
    if mode != CrawlMode.NEW_ONLY:
        # Get retry candidates that are ready
        retry_candidates = db.get_retry_candidates(config['crawler']['max_retries'])
        ready_retries = []
        skipped_invalid_retries = 0
        
        for candidate in retry_candidates:
            invalid_reason = get_invalid_url_reason(candidate["url"])
            if invalid_reason:
                skipped_invalid_retries += 1
                if not preview:
                    db.save_url(candidate["url"], status="invalid", http_status=None)
                continue

            if should_retry_now(candidate['last_crawled'], candidate['retry_count']):
                ready_retries.append(candidate['url'])
            elif not preview:
                backoff = calculate_backoff_time(candidate['retry_count'])
                print(f"⏳ Skipping retry: {candidate['url'][:50]}... (retry in {backoff:.0f}s)")
        
        if skipped_invalid_retries and not preview:
            print(
                f"🚫 Skipped {skipped_invalid_retries} invalid retry URL(s)"
            )
        
        if ready_retries and not preview:
            print(f"🔄 Found {len(ready_retries)} URLs ready for retry")
        urls_to_visit.extend(ready_retries)
        retry_count = len(ready_retries)
    
    if mode != CrawlMode.RETRY_ONLY:
        # Get ONLY new URLs (not crawled yet)
        with db.get_cursor() as cursor:
            cursor.execute('''
                SELECT url FROM urls 
                WHERE status = 'new' 
                ORDER BY created_at
            ''')
            new_urls = [row[0] for row in cursor.fetchall()]
            print(f"DEBUG: Found {len(new_urls)} URLs with status='new'")

        filtered_new_urls = []
        skipped_invalid_new = 0
        for url in new_urls:
            invalid_reason = get_invalid_url_reason(url)
            if invalid_reason:
                skipped_invalid_new += 1
                if not preview:
                    db.save_url(url, status="invalid", http_status=None)
                continue
            filtered_new_urls.append(url)

        if skipped_invalid_new and not preview:
            print(
                f"🚫 Skipped {skipped_invalid_new} invalid new URL(s)"
            )
        
        if filtered_new_urls:
            if not preview:
                print(f"🆕 Found {len(filtered_new_urls)} new URLs to crawl")
            urls_to_visit.extend(filtered_new_urls)
            new_count = len(filtered_new_urls)
    
    return urls_to_visit, retry_count, new_count


def main():
    parser = argparse.ArgumentParser(description="SEO Crawler")
    parser.add_argument(
        "--reset", action="store_true", help="Reset database before crawling"
    )
    parser.add_argument("--stats", action="store_true", help="Show statistics only")
    parser.add_argument(
        "--retry-only",
        action="store_true",
        help="Only retry failed URLs, skip new ones",
    )
    parser.add_argument(
        "--new-only", action="store_true", help="Only crawl new URLs, skip retries"
    )
    parser.add_argument(
        "--max-pages", type=int, default=0, help="Maximum pages to crawl (0 = unlimited)"
    )
    parser.add_argument(
        "--preview", action="store_true", help="Preview what would be crawled"
    )
    parser.add_argument("--debug", action="store_true", help="Show debug information")
    parser.add_argument("--url", type=str, help="Recrawl a specific URL")
    args = parser.parse_args()

    # Determine crawl mode
    if args.retry_only:
        mode = CrawlMode.RETRY_ONLY
    elif args.new_only:
        mode = CrawlMode.NEW_ONLY
    else:
        mode = CrawlMode.NORMAL

    config = load_config()

    if "max_retries" not in config.get("crawler", {}):
        config["crawler"]["max_retries"] = 5
    if "backoff_factor" not in config.get("crawler", {}):
        config["crawler"]["backoff_factor"] = 2

    with Database() as db:
        # Handle stats-only mode
        if args.stats:
            stats = db.get_crawl_stats()
            print("\n" + "=" * 50)
            print("CRAWL STATISTICS")
            print("=" * 50)
            print(f"Total URLs: {stats['total_urls']}")
            print(f"Crawled: {stats['crawled']}")
            print(f"Pending: {stats['new']}")
            print(f"Errors: {stats['errors']}")
            print(f"URLs with SEO issues: {stats['urls_with_issues']}")

            retry_candidates = db.get_retry_candidates(config["crawler"]["max_retries"])
            if retry_candidates:
                print(f"\nRetry candidates: {len(retry_candidates)}")
                ready_now = sum(
                    1
                    for c in retry_candidates
                    if should_retry_now(c["last_crawled"], c["retry_count"])
                )
                print(f"Ready for retry now: {ready_now}")
                print(f"Waiting for backoff: {len(retry_candidates) - ready_now}")
            print("=" * 50)
            return

        # Handle single URL recrawl
        if args.url:
            invalid_reason = get_invalid_url_reason(args.url)
            if invalid_reason:
                db.save_url(args.url, status="invalid", http_status=None)
                print(f"\n🚫 Skipping {invalid_reason}: {args.url}")
                return

            print(f"\n🔄 Recrawling: {args.url}")
            response, should_retry = fetch_page_with_retry(args.url, config, 0)

            if not response:
                if not should_retry:
                    db.save_url(args.url, status="error", http_status=None)
                    mark_non_retryable_error(
                        db, args.url, config["crawler"]["max_retries"]
                    )
                print(f"  ❌ Failed to fetch URL")
                return

            print(f"  ✅ Status: {response.status_code}")

            resolved_url = resolve_crawled_url(args.url, response.url)
            if resolved_url != args.url:
                redirect_status = (
                    response.history[0].status_code
                    if response.history
                    else response.status_code
                )
                db.save_url(args.url, status="redirected", http_status=redirect_status)
                print(f"  ↪ Redirected to: {resolved_url}")

            # Save/update URL (use final URL after redirects)
            url_id = db.save_url(
                resolved_url, status="crawled", http_status=response.status_code
            )

            # Extract and save SEO data
            seo_data = extract_seo_data(response.text, resolved_url)
            db.save_seo_data(url_id, seo_data)

            # Identify and save SEO issues
            issues = identify_seo_issues(seo_data, config)
            if issues:
                print(f"  ⚠️  Found {len(issues)} SEO issues:")
                for issue in issues:
                    print(f"      - {issue['type']}: {issue['details']}")
                db.save_seo_issues(url_id, issues)
            else:
                # Clear any existing issues
                with db.get_cursor() as cursor:
                    cursor.execute("DELETE FROM seo_issues WHERE url_id = ?", (url_id,))
                print(f"  ✅ No SEO issues")

            # Discover new links
            found_links = extract_links(response.text, resolved_url, config)
            new_links_added = 0
            for link in found_links:
                with db.get_cursor() as cursor:
                    cursor.execute("SELECT id FROM urls WHERE url = ?", (link,))
                    if not cursor.fetchone():
                        db.save_url(link, status="new")
                        new_links_added += 1

            if new_links_added:
                print(f"  📎 Discovered {new_links_added} new URLs")

            print(f"\n✅ Done")
            return

        # Handle preview mode
        if args.preview:
            base_url = config["site"]["base_url"]
            urls_to_visit, retry_count, new_count = build_crawl_queue(
                db, config, mode, base_url, preview=True
            )

            print("\n" + "=" * 50)
            print("CRAWL PREVIEW")
            print("=" * 50)

            if not urls_to_visit:
                print("No URLs would be crawled")
            else:
                print(f"Would crawl {len(urls_to_visit)} URLs:")
                print(f"  - {retry_count} retries")
                print(f"  - {new_count} new URLs")
                print("\nFirst 10 URLs that would be crawled:")
                for url in urls_to_visit[:10]:
                    retry_count_url = db.get_url_retry_count(
                        url
                    )  # Renamed variable to avoid conflict
                    prefix = "🔄" if retry_count_url > 0 else "🆕"
                    print(f"  {prefix} {url}")
                if len(urls_to_visit) > 10:
                    print(f"  ... and {len(urls_to_visit) - 10} more")

            print("=" * 50)
            return

        # Handle reset
        if args.reset:
            db.reset_database()
            print()

        # Initialize tracking
        base_url = config["site"]["base_url"]
        visited_urls: Set[str] = set()
        max_pages = args.max_pages

        print(f"\n" + "=" * 50)
        print(f"CRAWL MODE: {mode.value.replace('_', ' ').title()}")
        print(f"Max pages: {'unlimited' if max_pages == 0 else max_pages}")
        print(f"Max retries per URL: {config['crawler']['max_retries']}")
        print("=" * 50 + "\n")

        page_count = 0
        successful_crawls = 0
        failed_permanently = 0
        discovered_urls = 0

        while True:
            urls_to_visit, retry_count, new_count = build_crawl_queue(
                db, config, mode, base_url, preview=False
            )
            urls_to_visit = [u for u in urls_to_visit if u not in visited_urls]

            if not urls_to_visit:
                if page_count == 0:
                    print("No URLs to crawl")
                break

            print(f"Queue: {retry_count} retries, {new_count} new URLs\n")

            while urls_to_visit and (max_pages == 0 or page_count < max_pages):
                current_url = urls_to_visit.pop(0)

                if current_url in visited_urls:
                    continue

                visited_urls.add(current_url)
                page_count += 1

                # Get retry count from database
                retry_count = db.get_url_retry_count(current_url)

                page_label = f"{page_count}" if max_pages == 0 else f"{page_count}/{max_pages}"
                status_text = f"[{page_label}]"
                if retry_count > 0:
                    status_text += (
                        f" [Retry {retry_count}/{config['crawler']['max_retries']}]"
                    )
                print(f"{status_text} Processing: {current_url}")

                invalid_reason = get_invalid_url_reason(current_url)
                if invalid_reason:
                    db.save_url(current_url, status="invalid", http_status=None)
                    print(f"  🚫 Skipping {invalid_reason}")
                    continue

                # Fetch the page
                response, should_retry = fetch_page_with_retry(
                    current_url, config, retry_count
                )

                if not response:
                    if should_retry and retry_count < config["crawler"]["max_retries"]:
                        new_retry_count = db.increment_retry_count(current_url)
                        db.save_url(current_url, status="error", http_status=None)
                        print(
                            f"  🔄 Will retry later (attempt {new_retry_count}/{config['crawler']['max_retries']})"
                        )
                    else:
                        if should_retry:
                            db.save_url(current_url, status="error", http_status=None)
                        else:
                            mark_non_retryable_error(
                                db, current_url, config["crawler"]["max_retries"]
                            )
                        failed_permanently += 1
                        print(f"  ❌ Failed permanently")
                    continue

                print(f"  ✅ Status: {response.status_code}")

                resolved_url = resolve_crawled_url(current_url, response.url)
                if resolved_url != current_url:
                    redirect_status = (
                        response.history[0].status_code
                        if response.history
                        else response.status_code
                    )
                    db.save_url(
                        current_url, status="redirected", http_status=redirect_status
                    )
                    print(f"  ↪ Redirected to: {resolved_url}")

                # Save successful crawl using final URL
                url_id = db.save_url(
                    resolved_url, status="crawled", http_status=response.status_code
                )

                # Extract and save SEO data
                seo_data = extract_seo_data(response.text, resolved_url)
                db.save_seo_data(url_id, seo_data)

                # Identify and save SEO issues
                issues = identify_seo_issues(seo_data, config)
                if issues:
                    print(f"  ⚠️  Found {len(issues)} SEO issues")
                    db.save_seo_issues(url_id, issues)
                else:
                    print(f"  ✅ No SEO issues")

                successful_crawls += 1

                # Extract and queue new links from every page
                if mode != CrawlMode.RETRY_ONLY:
                    found_links = extract_links(response.text, resolved_url, config)
                    new_links_added = 0
                    already_known = 0

                    for link in found_links:
                        # Check if URL already exists in database
                        with db.get_cursor() as cursor:
                            cursor.execute("SELECT id FROM urls WHERE url = ?", (link,))
                            exists = cursor.fetchone()

                        if not exists:
                            db.save_url(link, status="new")
                            new_links_added += 1
                            discovered_urls += 1
                            if args.debug:  # Debug mode shows each new URL
                                print(f"    + New: {link}")
                        else:
                            already_known += 1

                    # Better reporting
                    print(
                        f"  📎 Found {len(found_links)} links: {new_links_added} new, {already_known} already known"
                    )

            if max_pages > 0 and page_count >= max_pages:
                break

        # Summary
        print("\n" + "=" * 50)
        print("CRAWL COMPLETE")
        print("=" * 50)

        stats = db.get_crawl_stats()
        print(f"Pages processed: {page_count}")
        print(f"Successful: {successful_crawls}")
        if discovered_urls > 0:
            print(f"New URLs discovered: {discovered_urls}")
        print(f"Failed (will retry): {stats['errors'] - failed_permanently}")
        print(f"Failed permanently: {failed_permanently}")
        print(f"Total URLs in database: {stats['total_urls']}")

        # Show what's pending (only relevant if we stopped due to max_pages)
        if max_pages > 0 and page_count >= max_pages:
            retry_candidates = db.get_retry_candidates(config["crawler"]["max_retries"])
            with db.get_cursor() as cursor:
                cursor.execute('SELECT COUNT(*) FROM urls WHERE status = "new"')
                pending_new = cursor.fetchone()[0]

            if retry_candidates or pending_new:
                print(f"\n📋 Pending work:")
                if retry_candidates:
                    ready_now = sum(
                        1
                        for c in retry_candidates
                        if should_retry_now(c["last_crawled"], c["retry_count"])
                    )
                    print(f"  - {ready_now} URLs ready for retry")
                    print(
                        f"  - {len(retry_candidates) - ready_now} URLs waiting for backoff"
                    )
                if pending_new:
                    print(f"  - {pending_new} new URLs to crawl")
                print("\n💡 Run crawler again to process pending URLs")

        if successful_crawls > 0 and not args.stats and not args.preview:
            print("\n" + "=" * 50)
            print("GENERATING SITEMAP")
            print("=" * 50)

            # Generate sitemap.txt
            output_path = config.get("site", {}).get("sitemap_output_path", "sitemap.txt")
            with db.get_cursor() as cursor:
                cursor.execute(
                    """
                        SELECT url FROM urls 
                        WHERE status = "crawled" 
                        AND (http_status IS NULL OR http_status BETWEEN 200 AND 299)
                        ORDER BY url
                    """
                )
                urls = [row[0] for row in cursor.fetchall()]

            with open(output_path, "w") as f:
                for url in urls:
                    f.write(f"{url}\n")

            print(f"✅ Updated {output_path} with {len(urls)} URLs")

    print("\n✅ Data saved to sitemap.db")

if __name__ == "__main__":
    main()
