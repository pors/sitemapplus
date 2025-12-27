# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SitemapPlus is a Python-based incremental web crawler and SEO monitor. It crawls websites, generates sitemaps (txt/xml), and produces HTML reports identifying SEO issues.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Crawl pages (incremental - picks up where it left off)
python crawler.py --max-pages 50

# Continue crawling pending URLs
python crawler.py --max-pages 100

# Check crawl status
python crawler.py --stats

# Preview what would be crawled without actually crawling
python crawler.py --preview

# Reset database and start fresh
python crawler.py --reset --max-pages 50

# Retry only failed URLs
python crawler.py --retry-only --max-pages 20

# Recrawl a single URL (e.g., after fixing an SEO issue)
python crawler.py --url "https://example.com/my-page"

# Generate sitemap.txt (also auto-generated after crawl)
python generate_sitemap.py

# Generate sitemap.xml
python generate_sitemap.py --format xml

# Generate SEO report
python seo_report.py

# Generate and open SEO report in browser
python seo_report.py --open
```

## Architecture

The system uses SQLite for persistence with four main tables:
- `urls` - URL queue with status (new/crawled/error), retry tracking, HTTP status
- `seo_data` - Extracted SEO metadata (title, meta description, h1/h2 tags, canonical URL)
- `seo_issues` - Identified SEO problems per URL (issue type + details)
- Indexes on `urls.status` and `seo_issues.url_id`

**Data Flow:**
1. `crawler.py` fetches pages, extracts SEO data, discovers new links, manages retry queue
2. `database.py` handles all SQLite operations via context-managed cursors
3. `generate_sitemap.py` exports crawled URLs to txt/xml formats
4. `seo_report.py` generates interactive HTML reports with severity filtering

**URL State Machine:**
- `new` → `crawled` (success) or `error` (failure with retry potential)
- Error URLs retry with exponential backoff: `2^retry_count` seconds, max 5 retries
- 5xx/429/timeouts are retryable; 4xx errors are permanent failures

**Configuration:** `config.yaml` defines:
- Site base URL and output paths
- Crawler settings (user agent, timeout, rate limit, max retries)
- SEO rules (title/meta length ranges, H1 requirements, canonical checks)
- Issue severity classifications (critical/major/minor)

## Key Implementation Details

- BeautifulSoup with lxml parser for HTML extraction
- Requests library with timeout and retry handling
- All DB operations use context managers for safe commits/rollbacks
- SEO issues are classified by severity based on config rules
- Link discovery filters for same-domain internal links only
