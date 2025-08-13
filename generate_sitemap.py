#!/usr/bin/env python3
"""
Generate sitemap.txt from crawled URLs in database
"""

import argparse
from datetime import datetime
from typing import Optional, List
from database import Database
import yaml


def load_config(path: str = "config.yaml") -> dict:
    """Load configuration from YAML file"""
    with open(path, "r") as f:
        return yaml.safe_load(f)


def generate_sitemap(
    db: Database,
    output_file: str = "sitemap.txt",
    include_errors: bool = False,
    base_url: Optional[str] = None,
) -> int:
    """
    Generate sitemap.txt from database

    Args:
        db: Database connection
        output_file: Output filename
        include_errors: Include URLs with error status
        base_url: Optional base URL to filter by

    Returns:
        Number of URLs written
    """

    # Build query based on options
    query = """
        SELECT DISTINCT url 
        FROM urls 
        WHERE 1=1
    """
    params = []

    # Filter by status
    if include_errors:
        query += ' AND status IN ("crawled", "error")'
    else:
        query += ' AND status = "crawled" AND (http_status IS NULL OR http_status BETWEEN 200 AND 299)'

    # Filter by base URL if provided
    if base_url:
        query += " AND url LIKE ?"
        params.append(f"{base_url}%")

    query += " ORDER BY url"

    # Get URLs from database
    with db.get_cursor() as cursor:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        urls = [row[0] for row in cursor.fetchall()]

    # Write sitemap file
    with open(output_file, "w") as f:
        for url in urls:
            f.write(f"{url}\n")

    return len(urls)


def generate_sitemap_xml(
    db: Database, output_file: str = "sitemap.xml", base_url: Optional[str] = None
) -> int:
    """
    Generate sitemap.xml with additional metadata
    """
    # Get URLs with metadata
    query = """
        SELECT url, last_crawled, http_status
        FROM urls 
        WHERE status = "crawled" 
        AND (http_status IS NULL OR http_status BETWEEN 200 AND 299)
        ORDER BY url
    """

    with db.get_cursor() as cursor:
        cursor.execute(query)
        urls = cursor.fetchall()

    # Write XML sitemap
    with open(output_file, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')

        for row in urls:
            url, last_crawled, status = row
            f.write("  <url>\n")
            f.write(f"    <loc>{url}</loc>\n")

            if last_crawled:
                # Format date as W3C datetime
                dt = datetime.fromisoformat(last_crawled)
                f.write(f'    <lastmod>{dt.strftime("%Y-%m-%d")}</lastmod>\n')

            # Could add priority and changefreq based on URL patterns
            if url.endswith("/"):
                f.write("    <priority>1.0</priority>\n")
            elif "/blog/" in url or "/news/" in url:
                f.write("    <changefreq>weekly</changefreq>\n")
                f.write("    <priority>0.8</priority>\n")
            else:
                f.write("    <priority>0.5</priority>\n")

            f.write("  </url>\n")

        f.write("</urlset>\n")

    return len(urls)


def print_stats(db: Database):
    """Print sitemap generation statistics"""
    with db.get_cursor() as cursor:
        # Get counts by status
        cursor.execute(
            """
            SELECT 
                COUNT(CASE WHEN status = "crawled" AND (http_status BETWEEN 200 AND 299 OR http_status IS NULL) THEN 1 END) as successful,
                COUNT(CASE WHEN status = "crawled" AND http_status >= 300 THEN 1 END) as redirects_or_errors,
                COUNT(CASE WHEN status = "error" THEN 1 END) as failed,
                COUNT(CASE WHEN status = "new" THEN 1 END) as pending
            FROM urls
        """
        )
        stats = cursor.fetchone()

        print("\n" + "=" * 50)
        print("SITEMAP GENERATION STATS")
        print("=" * 50)
        print(f"✅ Successful URLs (in sitemap): {stats[0]}")
        print(f"⚠️  Redirects/Client errors (excluded): {stats[1]}")
        print(f"❌ Failed crawls (excluded): {stats[2]}")
        print(f"⏳ Pending crawls (not in sitemap): {stats[3]}")
        print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Generate sitemap from crawled URLs")
    parser.add_argument("--output", "-o", default="sitemap.txt", help="Output filename")
    parser.add_argument(
        "--format",
        choices=["txt", "xml", "both"],
        default="txt",
        help="Sitemap format (default: txt)",
    )
    parser.add_argument(
        "--include-errors", action="store_true", help="Include URLs that had errors"
    )
    parser.add_argument("--stats", action="store_true", help="Show statistics only")
    parser.add_argument("--base-url", help="Filter URLs by base URL")

    args = parser.parse_args()

    # Load config for output path
    config = load_config()
    output_path = config.get("site", {}).get("sitemap_output_path", args.output)

    with Database() as db:
        if args.stats:
            print_stats(db)
            return

        # Generate sitemap(s)
        if args.format in ["txt", "both"]:
            txt_file = output_path if args.format == "txt" else "sitemap.txt"
            count = generate_sitemap(db, txt_file, args.include_errors, args.base_url)
            print(f"✅ Generated {txt_file} with {count} URLs")

        if args.format in ["xml", "both"]:
            xml_file = (
                output_path.replace(".txt", ".xml")
                if args.format == "xml"
                else "sitemap.xml"
            )
            count = generate_sitemap_xml(db, xml_file, args.base_url)
            print(f"✅ Generated {xml_file} with {count} URLs")

        # Show stats
        if not args.stats:
            print_stats(db)


if __name__ == "__main__":
    main()
