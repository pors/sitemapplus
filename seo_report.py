#!/usr/bin/env python3
"""
Generate HTML report of SEO issues from crawled URLs
"""

import argparse
from datetime import datetime
from database import Database
import json
from collections import defaultdict, Counter
from typing import Dict, List, Tuple

def get_seo_data_with_issues(db: Database) -> List[Dict]:
    """Get all URLs with their SEO data and issues"""
    with db.get_cursor() as cursor:
        cursor.execute('''
            SELECT 
                u.url,
                u.status,
                u.http_status,
                u.last_crawled,
                s.title,
                s.meta_description,
                s.h1_tags,
                s.h2_tags
            FROM urls u
            LEFT JOIN seo_data s ON u.id = s.url_id
            WHERE u.status = 'crawled'
            ORDER BY u.url
        ''')
        
        urls_data = []
        for row in cursor.fetchall():
            url_data = {
                'url': row['url'],
                'status': row['status'],
                'http_status': row['http_status'],
                'last_crawled': row['last_crawled'],
                'title': row['title'],
                'meta_description': row['meta_description'],
                'h1_tags': json.loads(row['h1_tags']) if row['h1_tags'] else [],
                'h2_tags': json.loads(row['h2_tags']) if row['h2_tags'] else [],
                'issues': []
            }
            
            # Get issues for this URL
            cursor.execute('''
                SELECT issue_type, details
                FROM seo_issues
                WHERE url_id = (SELECT id FROM urls WHERE url = ?)
            ''', (row['url'],))
            
            for issue_row in cursor.fetchall():
                url_data['issues'].append({
                    'type': issue_row['issue_type'],
                    'details': issue_row['details']
                })
            
            urls_data.append(url_data)
    
    return urls_data

def generate_html_report(urls_data: List[Dict], output_file: str = "seo_report.html"):
    """Generate HTML report from SEO data"""
    
    # Calculate statistics
    total_urls = len(urls_data)
    urls_with_issues = sum(1 for u in urls_data if u['issues'])
    
    # Count issues by type
    issue_counts = Counter()
    for url_data in urls_data:
        for issue in url_data['issues']:
            issue_counts[issue['type']] += 1
    
    # Categorize URLs by severity
    for url_data in urls_data:
        issue_types = [i['type'] for i in url_data['issues']]
        if 'missing_title' in issue_types or 'missing_h1' in issue_types:
            url_data['severity'] = 'critical'
        elif 'missing_meta_description' in issue_types or 'multiple_h1' in issue_types:
            url_data['severity'] = 'major'
        elif url_data['issues']:
            url_data['severity'] = 'minor'
        else:
            url_data['severity'] = 'clean'
    
    critical_count = sum(1 for u in urls_data if u['severity'] == 'critical')
    major_count = sum(1 for u in urls_data if u['severity'] == 'major')
    minor_count = sum(1 for u in urls_data if u['severity'] == 'minor')
    clean_count = sum(1 for u in urls_data if u['severity'] == 'clean')
    
    # Generate HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SEO Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1600px;
            margin: 0 auto;
            padding: 20px;
        }}
        header {{
            background: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            margin-bottom: 20px;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .stat-number {{
            font-size: 2em;
            font-weight: bold;
            color: #3498db;
        }}
        .stat-label {{
            color: #7f8c8d;
            margin-top: 5px;
        }}
        .filter-buttons {{
            margin-bottom: 20px;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .filter-btn {{
            padding: 8px 16px;
            border: 1px solid #3498db;
            background: white;
            color: #3498db;
            border-radius: 5px;
            cursor: pointer;
            transition: all 0.3s;
            position: relative;
        }}
        .filter-btn:hover, .filter-btn.active {{
            background: #3498db;
            color: white;
        }}
        .filter-count {{
            display: inline-block;
            margin-left: 5px;
            padding: 2px 6px;
            background: #ecf0f1;
            border-radius: 10px;
            font-size: 0.85em;
            font-weight: bold;
        }}
        .filter-btn.active .filter-count {{
            background: rgba(255,255,255,0.3);
        }}
        .table-container {{
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        thead {{
            background: #f8f9fa;
            position: sticky;
            top: 0;
            z-index: 10;
        }}
        th {{
            padding: 15px;
            text-align: left;
            font-weight: 600;
            color: #2c3e50;
            border-bottom: 2px solid #dee2e6;
        }}
        tbody tr {{
            cursor: pointer;
            transition: background 0.2s;
            border-bottom: 1px solid #ecf0f1;
        }}
        tbody tr:hover {{
            background: #f8f9fa;
        }}
        tbody tr.expanded {{
            background: #e8f4fd;
        }}
        td {{
            padding: 12px 15px;
        }}
        .url-cell {{
            color: #2c3e50;
            max-width: 600px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .issues-cell {{
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
        }}
        .issue-badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 0.75em;
            font-weight: 500;
            white-space: nowrap;
        }}
        .issue-badge.critical {{
            background: #ffe5e5;
            color: #c0392b;
        }}
        .issue-badge.major {{
            background: #fff3cd;
            color: #856404;
        }}
        .issue-badge.minor {{
            background: #e3f2fd;
            color: #1565c0;
        }}
        .severity-indicator {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 10px;
        }}
        .severity-indicator.critical {{
            background: #e74c3c;
        }}
        .severity-indicator.major {{
            background: #f39c12;
        }}
        .severity-indicator.minor {{
            background: #95a5a6;
        }}
        .severity-indicator.clean {{
            background: #27ae60;
        }}
        .details-row {{
            display: none;
        }}
        .details-row.show {{
            display: table-row;
        }}
        .details-content {{
            padding: 20px;
            background: #f8f9fa;
            border-left: 4px solid #3498db;
        }}
        .detail-section {{
            margin-bottom: 15px;
        }}
        .detail-label {{
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 5px;
        }}
        .detail-value {{
            color: #5a6c7d;
            margin-left: 20px;
        }}
        .expand-icon {{
            display: inline-block;
            margin-right: 10px;
            transition: transform 0.3s;
            color: #7f8c8d;
        }}
        tr.expanded .expand-icon {{
            transform: rotate(90deg);
        }}
        .hidden {{
            display: none !important;
        }}
        .no-issues {{
            color: #27ae60;
            font-style: italic;
        }}
        @media (max-width: 768px) {{
            .url-cell {{
                max-width: 200px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🔍 SEO Report</h1>
            <p style="color: #7f8c8d;">Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </header>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-number">{total_urls}</div>
                <div class="stat-label">Total Pages Crawled</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{urls_with_issues}</div>
                <div class="stat-label">Pages with Issues</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{sum(issue_counts.values())}</div>
                <div class="stat-label">Total Issues Found</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{critical_count}</div>
                <div class="stat-label">Critical Issues</div>
            </div>
        </div>
        
        <div class="filter-buttons">
            <button class="filter-btn active" onclick="filterBySeverity('all')">
                All Pages <span class="filter-count">{total_urls}</span>
            </button>
            <button class="filter-btn" onclick="filterBySeverity('critical')">
                Critical <span class="filter-count">{critical_count}</span>
            </button>
            <button class="filter-btn" onclick="filterBySeverity('major')">
                Major <span class="filter-count">{major_count}</span>
            </button>
            <button class="filter-btn" onclick="filterBySeverity('minor')">
                Minor <span class="filter-count">{minor_count}</span>
            </button>
            <button class="filter-btn" onclick="filterBySeverity('clean')">
                Clean <span class="filter-count">{clean_count}</span>
            </button>
        </div>
        
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th style="width: 50%;">URL</th>
                        <th style="width: 50%;">Issues</th>
                    </tr>
                </thead>
                <tbody>
    """
    
    # Add table rows
    for i, url_data in enumerate(urls_data):
        severity = url_data['severity']
        
        # Main row
        html += f"""
                    <tr class="data-row" data-severity="{severity}" onclick="toggleDetails({i})">
                        <td class="url-cell">
                            <span class="expand-icon">▶</span>
                            <span class="severity-indicator {severity}"></span>
                            {url_data['url']}
                        </td>
                        <td>
                            <div class="issues-cell">
        """
        
        if url_data['issues']:
            for issue in url_data['issues']:
                issue_severity = 'critical' if issue['type'] in ['missing_title', 'missing_h1'] else 'major' if issue['type'] in ['missing_meta_description', 'multiple_h1'] else 'minor'
                readable_type = issue['type'].replace('_', ' ').title()
                html += f'<span class="issue-badge {issue_severity}">{readable_type}</span>'
        else:
            html += '<span class="no-issues">No issues</span>'
        
        html += """
                            </div>
                        </td>
                    </tr>
        """
        
        # Details row
        html += f"""
                    <tr class="details-row" id="details-{i}">
                        <td colspan="2">
                            <div class="details-content">
        """
        
        # Add URL info
        html += f"""
                                <div class="detail-section">
                                    <div class="detail-label">URL:</div>
                                    <div class="detail-value"><a href="{url_data['url']}" target="_blank">{url_data['url']}</a></div>
                                </div>
        """
        
        # Add title
        if url_data['title']:
            html += f"""
                                <div class="detail-section">
                                    <div class="detail-label">Title ({len(url_data['title'])} chars):</div>
                                    <div class="detail-value">{url_data['title']}</div>
                                </div>
            """
        
        # Add meta description
        if url_data['meta_description']:
            html += f"""
                                <div class="detail-section">
                                    <div class="detail-label">Meta Description ({len(url_data['meta_description'])} chars):</div>
                                    <div class="detail-value">{url_data['meta_description']}</div>
                                </div>
            """
        
        # Add H1 tags
        if url_data['h1_tags']:
            html += f"""
                                <div class="detail-section">
                                    <div class="detail-label">H1 Tags ({len(url_data['h1_tags'])}):</div>
            """
            for h1 in url_data['h1_tags']:
                html += f'<div class="detail-value">• {h1}</div>'
            html += '</div>'
        
        # Add H2 tags if present
        if url_data['h2_tags']:
            html += f"""
                                <div class="detail-section">
                                    <div class="detail-label">H2 Tags ({len(url_data['h2_tags'])}):</div>
            """
            for h2 in url_data['h2_tags'][:5]:  # Show first 5
                html += f'<div class="detail-value">• {h2}</div>'
            if len(url_data['h2_tags']) > 5:
                html += f'<div class="detail-value">... and {len(url_data["h2_tags"]) - 5} more</div>'
            html += '</div>'
        
        # Add issues details
        if url_data['issues']:
            html += """
                                <div class="detail-section">
                                    <div class="detail-label">Issue Details:</div>
            """
            for issue in url_data['issues']:
                html += f'<div class="detail-value">• {issue["details"]}</div>'
            html += '</div>'
        
        # Add crawl info
        html += f"""
                                <div class="detail-section">
                                    <div class="detail-label">HTTP Status:</div>
                                    <div class="detail-value">{url_data['http_status']}</div>
                                </div>
                                <div class="detail-section">
                                    <div class="detail-label">Last Crawled:</div>
                                    <div class="detail-value">{url_data['last_crawled']}</div>
                                </div>
        """
        
        html += """
                            </div>
                        </td>
                    </tr>
        """
    
    html += """
                </tbody>
            </table>
        </div>
    </div>
    
    <script>
        function toggleDetails(index) {
            const detailsRow = document.getElementById('details-' + index);
            const dataRow = detailsRow.previousElementSibling;
            
            detailsRow.classList.toggle('show');
            dataRow.classList.toggle('expanded');
        }
        
        function filterBySeverity(severity) {
            // Update button states
            document.querySelectorAll('.filter-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            event.target.classList.add('active');
            
            // Show/hide rows
            document.querySelectorAll('.data-row').forEach(row => {
                const nextRow = row.nextElementSibling; // details row
                if (severity === 'all' || row.dataset.severity === severity) {
                    row.classList.remove('hidden');
                } else {
                    row.classList.add('hidden');
                    nextRow.classList.remove('show'); // hide details if main row is hidden
                    row.classList.remove('expanded');
                }
            });
        }
    </script>
</body>
</html>
    """
    
    with open(output_file, 'w') as f:
        f.write(html)
    
    return total_urls, urls_with_issues, sum(issue_counts.values())

def main():
    parser = argparse.ArgumentParser(description='Generate SEO report from crawled data')
    parser.add_argument('--output', '-o', default='seo_report.html', help='Output HTML file')
    parser.add_argument('--open', action='store_true', help='Open report in browser after generation')
    
    args = parser.parse_args()
    
    with Database() as db:
        urls_data = get_seo_data_with_issues(db)
        
        if not urls_data:
            print("No crawled URLs found. Run the crawler first.")
            return
        
        total, with_issues, total_issues = generate_html_report(urls_data, args.output)
        
        print(f"✅ Generated {args.output}")
        print(f"   - {total} pages analyzed")
        print(f"   - {with_issues} pages with issues")
        print(f"   - {total_issues} total issues found")
        
        if args.open:
            import webbrowser
            webbrowser.open(f"file://{args.output}")

if __name__ == "__main__":
    main()