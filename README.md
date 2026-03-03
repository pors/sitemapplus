# SitemapPlus - Sitemap Generator & SEO Monitor

A production-ready Python crawler that generates sitemaps while monitoring SEO health. Built for sites with thousands of pages, featuring incremental crawling, automatic retries, and comprehensive SEO analysis.

[Example report](https://pors.github.io/sitemapplus/seo_report_example.html)

## 🎯 Introduction

SitemapPlus is more than just a sitemap generator. It's a comprehensive SEO monitoring tool that:
- Crawls your website incrementally (no need to recrawl everything each run)
- Generates both `sitemap.txt` and `sitemap.xml` formats
- Identifies and tracks SEO issues across your entire site
- Handles failures gracefully with exponential backoff retry logic
- Produces beautiful HTML reports for SEO analysis
- Stores all data in SQLite for historical tracking

Perfect for maintaining sitemaps for dynamic sites with constantly changing content.

## ✨ Features

### Core Functionality
- **Incremental Crawling** - Only crawls new/changed pages, picks up where it left off
- **Smart Retry Logic** - Exponential backoff for failed requests (network issues, 5xx errors)
- **Redirect-Aware Storage** - Persists final resolved URL after redirects
- **SEO Analysis** - Checks title, meta descriptions, H1/H2 tags against configurable rules
- **Multiple Output Formats** - Generates sitemap.txt, sitemap.xml, and HTML reports
- **Database Storage** - SQLite backend for persistence and historical data
- **Configurable Rules** - Customize SEO requirements via YAML config

### Advanced Features
- **Rate Limiting** - Respectful crawling with configurable delays
- **Parallel Discovery** - Discovers new URLs while crawling
- **Error Recovery** - Distinguishes between temporary and permanent failures
- **Detailed Reporting** - HTML reports with filtering and expandable details
- **Status Tracking** - Monitor crawl progress and pending work
- **URL Hygiene Filters** - Skips unresolved template routes and non-HTML assets (`.md`, `.pdf`, etc.)
- **Webhook Support** - API endpoints for real-time updates (coming soon)

## 📦 Installation

### Prerequisites
- Python 3.8+
- pip

### Setup

Clone the repository:

```bash
git clone https://github.com/yourusername/sitemapplus.git
cd sitemapplus
```

Install dependencies:


```bash
pip install -r requirements.txt
```

Configure your site:


```bash
# Edit config.yaml with your site details
nano/vi/emacs config.yaml
```

### Dependencies

```txt
requests==2.31.0
beautifulsoup4==4.12.3
pyyaml==6.0.1
lxml==5.1.0
```

## 🚀 Usage

### Basic Commands

#### First-time crawl

```bash
# Crawl 50 pages starting from base URL
python crawler.py --max-pages 50
```

#### Continue crawling

```bash
# Process next batch of discovered URLs
python crawler.py --max-pages 100
```

#### Check status

```bash
# See crawl statistics
python crawler.py --stats

# Preview what would be crawled
python crawler.py --preview
```

#### Generate outputs

```bash
# Generate sitemap.txt (automatic after crawl)
python generate_sitemap.py

# Generate sitemap.xml
python generate_sitemap.py --format xml

# Generate SEO report
python seo_report.py --open
```

### Advanced Usage

#### Reset and start fresh

```bash
python crawler.py --reset --max-pages 50
```

#### Retry failed URLs

```bash
# Only process URLs that previously failed
python crawler.py --retry-only --max-pages 20
```

#### Recrawl a single URL

```bash
# Recrawl a specific page (e.g., after fixing an SEO issue)
python crawler.py --url "https://example.com/my-page"
```

#### Filter sitemap generation

```bash
# Only include specific subdirectory
python generate_sitemap.py --base-url \"https://example.com/blog/\"
```

### Configuration

Edit `config.yaml` to customize:

```yaml
# Site configuration
site:
  base_url: \"https://example.com\"
  allow_subdomains: false
  allowed_subdomains: [\"docs\"]  # optional
  sitemap_output_path: \"./sitemap.txt\"

# Crawler settings
crawler:
  user_agent: \"SitemapBot/1.0\"
  timeout: 10
  max_retries: 5
  backoff_factor: 2
  rate_limit: 0.5  # seconds between requests

# SEO Rules
seo:
  title:
    min_length: 30
    max_length: 60
    required: true
    
  meta_description:
    min_length: 120
    max_length: 160
    required: true
    
  headings:
    max_h1_tags: 1
    min_h1_tags: 1
    warn_empty_headings: true
    
  severity:
    critical:
      - missing_title
      - missing_h1
    major:
      - missing_meta_description
      - multiple_h1
    minor:
      - short_title
      - long_title
      - short_meta_description
      - long_meta_description
```

### Production Deployment

#### Using Cron

```bash
# Add to crontab for hourly crawls
0 * * * * cd /path/to/sitemapplus && python crawler.py --max-pages 100 >> crawl.log 2>&1

# Daily SEO report generation
0 2 * * * cd /path/to/sitemapplus && python seo_report.py
```

#### Using systemd

```ini
[Unit]
Description=SitemapPlus Crawler
After=network.target

[Service]
Type=oneshot
User=www-data
WorkingDirectory=/opt/sitemapplus
ExecStart=/usr/bin/python3 /opt/sitemapplus/crawler.py --max-pages 100

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

## 🏗️ Architecture

### Components

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  crawler.py │────▶│  database.py │────▶│  SQLite DB   │
└─────────────┘     └──────────────┘     └──────────────┘
       │                                          │
       ▼                                          ▼
┌─────────────┐                         ┌──────────────┐
│   Config    │                         │   Reports    │
│  (YAML)     │                         │  (HTML/TXT)  │
└─────────────┘                         └──────────────┘
```

### Database Schema

```sql
urls                          seo_data
├── id (PK)                   ├── url_id (FK)
├── url (UNIQUE)              ├── title
├── status                    ├── meta_description
├── http_status               ├── h1_tags (JSON)
├── retry_count               ├── h2_tags (JSON)
└── last_crawled              └── canonical_url

seo_issues                    custom_seo_data
├── id (PK)                   ├── id (PK)
├── url_id (FK)               ├── url_id (FK)
├── issue_type                ├── key
└── details                   └── value
```

### URL State Machine

```
   ┌─────┐      ┌──────────┐      ┌─────────┐
   │ new │─────▶│ crawling │─────▶│ crawled │
   └─────┘      └──────────┘      └─────────┘
                      │                 │
                      ▼                 ▼
                 ┌────────┐       ┌────────────┐
                 │ error  │       │ redirected │
                 └────────┘       └────────────┘
                      │
                      ▼
                 (retry with backoff)

   Invalid/disallowed URLs (for example unresolved `/{path}` routes or `.md` links)
   are marked `invalid` and excluded from future queues.
```

### Crawl Algorithm

1. **Queue Building**
   - Check for failed URLs ready for retry (respecting backoff)
   - Add all URLs with status='new'
   - If database empty, start with base_url

2. **Processing**
   - Pop URL from queue (FIFO)
   - Fetch page with timeout
   - On success: Extract SEO data, discover new links
   - On failure: Mark for retry or permanent failure

3. **Link Discovery**
   - Parse all `<a href>` tags
   - Filter for internal links only (supports `allow_subdomains` / `allowed_subdomains`)
   - Skip unresolved template URLs (`{...}`) and excluded extensions (`.md`, `.pdf`, etc.)
   - Add new URLs to database as status='new'

4. **Retry Logic**
   ```
   Backoff time = 2^retry_count seconds
   Max retries = 5 (configurable)
   Retryable: 5xx, 429, timeouts
   Non-retryable: 4xx errors
   ```
   Non-retryable failures are marked as permanent and removed from retry candidates.

## 🔧 Development

### Project Structure

```
sitemapplus/
├── crawler.py           # Main crawler logic
├── database.py          # Database operations
├── generate_sitemap.py  # Sitemap generation
├── seo_report.py        # HTML report generation
├── config.yaml          # Configuration
├── requirements.txt     # Python dependencies
├── sitemap.db          # SQLite database (generated)
├── sitemap.txt         # Output sitemap (generated)
└── seo_report.html     # SEO report (generated)
```

### Adding Custom SEO Checks

Add new checks in `crawler.py`:

```python
def identify_seo_issues(data: Dict, config: Dict) -> List[Dict]:
    issues = []
    
    # Your custom check
    if 'noindex' in data.get('robots_directives', ''):
        issues.append({
            'type': 'noindex_tag',
            'details': 'Page has noindex directive'
        })
    
    return issues
```

### Extending the Database

Add new columns in `database.py`:

```python
cursor.execute('''
    ALTER TABLE seo_data 
    ADD COLUMN canonical_url TEXT
''')
```

### API Integration (Coming Soon)

The system is designed to accept webhooks:

```python
POST /webhook/add
{
  \"url\": \"https://example.com/new-page\",
  \"template\": \"/blog/{slug}\"
}
```

## 📊 Performance

- **Memory efficient**: Processes URLs in batches, doesn't load entire site into memory
- **Resumable**: Can be interrupted and resumed without losing progress
- **Scalable**: Tested on sites with 10,000+ pages
- **Respectful**: Rate limiting prevents server overload

### Benchmarks

- ~100 pages/minute (with 0.5s rate limit)
- ~10MB database size per 1000 URLs
- Handles 500+ concurrent pending URLs efficiently

## 🐛 Troubleshooting

### Common Issues

**Database locked error**

```bash
# Close any SQLite browsers/tools accessing sitemap.db
# Or delete the lock file
rm sitemap.db-journal
```

**All URLs already crawled**

```bash
# Force rediscovery of links
python crawler.py --reset
# Or check for new URLs
python crawler.py --stats
```

**Stuck retries**

```bash
# Clear error status
sqlite3 sitemap.db \"UPDATE urls SET status='new' WHERE status='error';\"
```

**Remove invalid template/asset URLs**

```bash
sqlite3 sitemap.db "DELETE FROM urls WHERE status='invalid';"
```

**Memory issues with large sites**

```bash
# Process in smaller batches
python crawler.py --max-pages 20
```

## 🛠️ Advanced Configuration

### Custom Headers
Add custom headers in config.yaml:

```yaml
crawler:
  headers:
    Accept-Language: \"en-US,en;q=0.9\"
    Accept: \"text/html,application/xhtml+xml\"
```

### Exclude Patterns
Skip URLs containing certain patterns (useful for login pages, SPAs, etc.):

```yaml
crawler:
  exclude_patterns:
    - "/login"
    - "/admin"
    - "/api"
    - "/privacy"
    - "/terms"
```

### Subdomain Crawling
Allow crawling multiple hosts for the same site:

```yaml
site:
  base_url: "https://paperzilla.ai"
  allow_subdomains: false
  allowed_subdomains:
    - "docs"  # allows docs.paperzilla.ai
```

Set `allow_subdomains: true` to include any `*.paperzilla.ai` subdomain.

### SEO Severity Customization
Redefine issue importance:

```yaml
seo:
  severity:
    critical:
      - missing_title
      - missing_h1
    major:
      - missing_meta_description
    minor:
      - long_title
      - short_meta_description
```

## 📈 Monitoring & Alerts

### Slack Integration (Example)

```python
import requests

def send_slack_alert(message):
    webhook_url = \"YOUR_SLACK_WEBHOOK_URL\"
    requests.post(webhook_url, json={\"text\": message})

# In crawler.py
if critical_issues > 10:
    send_slack_alert(f\"⚠️ Found {critical_issues} critical SEO issues!\")
```

### Export Metrics

```bash
# Export to CSV
sqlite3 -header -csv sitemap.db \"SELECT * FROM urls;\" > urls.csv

# Get daily stats
sqlite3 sitemap.db \"SELECT DATE(last_crawled), COUNT(*) FROM urls GROUP BY DATE(last_crawled);\"
```

## 🚧 Roadmap

### Near Term
- [ ] Robots.txt compliance
- [ ] FastAPI webhook endpoints
- [ ] JavaScript rendering support
- [ ] Concurrent crawling

### Long Term
- [ ] Multi-site support
- [ ] Cloud storage backends
- [ ] Docker containerization
- [ ] Web UI dashboard
- [ ] Elasticsearch integration

## 💡 Tips & Best Practices

1. **Start small**: Begin with `--max-pages 10` to test your configuration
2. **Monitor memory**: For sites with 10,000+ pages, run in batches
3. **Regular crawls**: Schedule hourly crawls for dynamic sites
4. **Check robots.txt**: Ensure your user agent is allowed
5. **Backup database**: Regular backups of sitemap.db
6. **Rate limiting**: Be respectful - use at least 0.5s delay

## 🤝 Contributing

Contributions welcome! Key areas for improvement:
- JavaScript rendering support (Selenium/Playwright)
- Robots.txt compliance
- XML sitemap index for large sites
- Multi-threaded crawling
- CloudFlare bypass
- Custom extraction rules

### Development Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\\Scripts\\activate on Windows

# Install in development mode
pip install -r requirements.txt
pip install pytest black flake8

# Run tests
pytest tests/

# Format code
black *.py
```

## 📝 License

MIT License - free for commercial use

## 🙏 Acknowledgments

Built with:

- [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) for HTML parsing
- [Requests](https://requests.readthedocs.io/) for HTTP handling
- [SQLite](https://www.sqlite.org/) for data persistence
- [Claude AI](https://claude.ai/) for coding and documenting

Tested with:

- [Paperzilla](https://paperzilla.ai)

## 📧 Support

For issues and questions:

- Open an issue on GitHub
- Check existing issues for solutions
- Review the troubleshooting section

---

Made with ❤️ for the SEO community
