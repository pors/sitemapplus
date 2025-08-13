"""
Database management for the crawler
"""

import sqlite3
from typing import Dict, List, Optional
from datetime import datetime
import json
from contextlib import contextmanager


class Database:
    def __init__(self, db_path: str = "sitemap.db"):
        self.db_path = db_path
        # Initialize connection immediately
        self.conn: sqlite3.Connection = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # Enable column access by name
        self.init_database()

    @contextmanager
    def get_cursor(self):
        """Context manager for database cursor"""
        cursor = self.conn.cursor()
        try:
            yield cursor
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise e
        finally:
            cursor.close()

    def init_database(self) -> None:
        """Initialize database with tables"""
        with self.get_cursor() as cursor:
            # Create tables
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS urls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    http_status INTEGER,
                    last_crawled TIMESTAMP,
                    retry_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS seo_data (
                    url_id INTEGER PRIMARY KEY,
                    title TEXT,
                    meta_description TEXT,
                    h1_tags TEXT,
                    h2_tags TEXT,
                    canonical_url TEXT,
                    og_title TEXT,
                    og_description TEXT,
                    og_image TEXT,
                    robots_directives TEXT,
                    FOREIGN KEY (url_id) REFERENCES urls(id)
                )
            """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS seo_issues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url_id INTEGER,
                    issue_type TEXT,
                    details TEXT,
                    FOREIGN KEY (url_id) REFERENCES urls(id)
                )
            """
            )

            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_urls_status ON urls(status)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_seo_issues_url_id ON seo_issues(url_id)"
            )

    def reset_database(self) -> None:
        """Clear all data from database"""
        with self.get_cursor() as cursor:
            cursor.execute("DELETE FROM seo_issues")
            cursor.execute("DELETE FROM seo_data")
            cursor.execute("DELETE FROM urls")
        print("✅ Database reset complete")

    def save_url(
        self, url: str, status: str = "new", http_status: Optional[int] = None
    ) -> int:
        """Save or update a URL in the database"""
        now = datetime.now().isoformat()

        with self.get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO urls (url, status, http_status, last_crawled, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    status = ?,
                    http_status = ?,
                    last_crawled = ?,
                    updated_at = ?
            """,
                (url, status, http_status, now, now, status, http_status, now, now),
            )

            # Get the URL ID
            cursor.execute("SELECT id FROM urls WHERE url = ?", (url,))
            result = cursor.fetchone()
            if result:
                return result[0]
            else:
                raise ValueError(f"Failed to get ID for URL: {url}")

    def save_seo_data(self, url_id: int, seo_data: Dict) -> None:
        """Save SEO data for a URL"""
        # Convert lists to JSON strings
        h1_json = json.dumps(seo_data.get("h1_tags", []))
        h2_json = json.dumps(seo_data.get("h2_tags", []))

        with self.get_cursor() as cursor:
            cursor.execute(
                """
                INSERT OR REPLACE INTO seo_data 
                (url_id, title, meta_description, h1_tags, h2_tags)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    url_id,
                    seo_data.get("title"),
                    seo_data.get("meta_description"),
                    h1_json,
                    h2_json,
                ),
            )

    def save_seo_issues(self, url_id: int, issues: List[Dict]) -> None:
        """Save SEO issues for a URL"""
        with self.get_cursor() as cursor:
            # Clear existing issues for this URL
            cursor.execute("DELETE FROM seo_issues WHERE url_id = ?", (url_id,))

            # Insert new issues
            for issue in issues:
                cursor.execute(
                    """
                    INSERT INTO seo_issues (url_id, issue_type, details)
                    VALUES (?, ?, ?)
                """,
                    (url_id, issue["type"], issue.get("details", "")),
                )

    def get_all_urls(self) -> List[Dict]:
        """Get all URLs with their status"""
        with self.get_cursor() as cursor:
            cursor.execute(
                """
                SELECT u.url, u.status, u.http_status, u.last_crawled,
                       s.title, s.meta_description, s.h1_tags
                FROM urls u
                LEFT JOIN seo_data s ON u.id = s.url_id
                ORDER BY u.url
            """
            )

            results = []
            for row in cursor.fetchall():
                results.append(
                    {
                        "url": row["url"],
                        "status": row["status"],
                        "http_status": row["http_status"],
                        "last_crawled": row["last_crawled"],
                        "title": row["title"],
                        "meta_description": row["meta_description"],
                        "h1_tags": json.loads(row["h1_tags"]) if row["h1_tags"] else [],
                    }
                )

            return results

    def get_crawl_stats(self) -> Dict:
        """Get crawl statistics"""
        with self.get_cursor() as cursor:
            cursor.execute(
                """
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'crawled' THEN 1 ELSE 0 END) as crawled,
                    SUM(CASE WHEN status = 'new' THEN 1 ELSE 0 END) as new,
                    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors
                FROM urls
            """
            )

            row = cursor.fetchone()

            # Count SEO issues
            cursor.execute(
                "SELECT COUNT(DISTINCT url_id) as urls_with_issues FROM seo_issues"
            )
            issues_row = cursor.fetchone()

            return {
                "total_urls": row["total"] or 0,
                "crawled": row["crawled"] or 0,
                "new": row["new"] or 0,
                "errors": row["errors"] or 0,
                "urls_with_issues": issues_row["urls_with_issues"] or 0,
            }

    def get_retry_candidates(self, max_retries: int = 5) -> List[Dict]:
        """Get URLs that should be retried"""
        with self.get_cursor() as cursor:
            cursor.execute('''
                SELECT id, url, retry_count, last_crawled
                FROM urls
                WHERE status = 'error' 
                AND retry_count < ?
                ORDER BY retry_count ASC, last_crawled ASC
            ''', (max_retries,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'id': row['id'],
                    'url': row['url'],
                    'retry_count': row['retry_count'],
                    'last_crawled': row['last_crawled']
                })
            
            return results

    def increment_retry_count(self, url: str) -> int:
        """Increment retry count for a URL and return new count"""
        with self.get_cursor() as cursor:
            cursor.execute('''
                UPDATE urls 
                SET retry_count = retry_count + 1,
                    updated_at = ?
                WHERE url = ?
            ''', (datetime.now().isoformat(), url))
            
            cursor.execute('SELECT retry_count FROM urls WHERE url = ?', (url,))
            result = cursor.fetchone()
            return result[0] if result else 0

    def get_url_retry_count(self, url: str) -> int:
        """Get current retry count for a URL"""
        with self.get_cursor() as cursor:
            cursor.execute('SELECT retry_count FROM urls WHERE url = ?', (url,))
            result = cursor.fetchone()
            return result[0] if result else 0

    def close(self) -> None:
        """Close database connection"""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure connection is closed"""
        self.close()
