#!/usr/bin/env python3
"""
Huronalytics Site Builder
Parses MLB offseason transaction Excel file and generates static HTML site.
"""

import pandas as pd
import json
import os
from pathlib import Path
from datetime import datetime
import html

# Configuration
EXCEL_FILE = "data/2025_26_MLB_Offseason.xlsx"
OUTPUT_DIR = "docs"

TEAM_INFO = {
    'ARI': {'name': 'Arizona Diamondbacks', 'short': 'Diamondbacks'},
    'ATH': {'name': 'Athletics', 'short': 'Athletics'},
    'ATL': {'name': 'Atlanta Braves', 'short': 'Braves'},
    'BAL': {'name': 'Baltimore Orioles', 'short': 'Orioles'},
    'BOS': {'name': 'Boston Red Sox', 'short': 'Red Sox'},
    'CHC': {'name': 'Chicago Cubs', 'short': 'Cubs'},
    'CHW': {'name': 'Chicago White Sox', 'short': 'White Sox'},
    'CIN': {'name': 'Cincinnati Reds', 'short': 'Reds'},
    'CLE': {'name': 'Cleveland Guardians', 'short': 'Guardians'},
    'COL': {'name': 'Colorado Rockies', 'short': 'Rockies'},
    'DET': {'name': 'Detroit Tigers', 'short': 'Tigers'},
    'HOU': {'name': 'Houston Astros', 'short': 'Astros'},
    'KCR': {'name': 'Kansas City Royals', 'short': 'Royals'},
    'LAA': {'name': 'Los Angeles Angels', 'short': 'Angels'},
    'LAD': {'name': 'Los Angeles Dodgers', 'short': 'Dodgers'},
    'MIA': {'name': 'Miami Marlins', 'short': 'Marlins'},
    'MIL': {'name': 'Milwaukee Brewers', 'short': 'Brewers'},
    'MIN': {'name': 'Minnesota Twins', 'short': 'Twins'},
    'NYM': {'name': 'New York Mets', 'short': 'Mets'},
    'NYY': {'name': 'New York Yankees', 'short': 'Yankees'},
    'PHI': {'name': 'Philadelphia Phillies', 'short': 'Phillies'},
    'PIT': {'name': 'Pittsburgh Pirates', 'short': 'Pirates'},
    'SDP': {'name': 'San Diego Padres', 'short': 'Padres'},
    'SEA': {'name': 'Seattle Mariners', 'short': 'Mariners'},
    'SFG': {'name': 'San Francisco Giants', 'short': 'Giants'},
    'STL': {'name': 'St. Louis Cardinals', 'short': 'Cardinals'},
    'TBR': {'name': 'Tampa Bay Rays', 'short': 'Rays'},
    'TEX': {'name': 'Texas Rangers', 'short': 'Rangers'},
    'TOR': {'name': 'Toronto Blue Jays', 'short': 'Blue Jays'},
    'WSH': {'name': 'Washington Nationals', 'short': 'Nationals'},
}

# Columns for MLB feed
MLB_RELEVANT_COLS = ['MLB Signing', 'Extension', 'Traded For', 'Traded Away', 'Waiver Claim', 'Lost off Waivers']

# Columns to skip (paired columns)
SKIP_COLS = ['New Team']

# Accordion section ordering and grouping
ACCORDION_SECTIONS = [
    {'title': 'MLB Signings', 'columns': ['MLB Signings']},
    {'title': 'MiLB Signings', 'columns': ['MiLB Signings']},
    {'title': 'International Signings', 'columns': ['Intl Amateur Signings']},
    {'title': 'Trades', 'columns': ['Traded For', 'Traded Away'], 'subheaders': True},
    {'title': 'Extensions', 'columns': ['Extensions']},
    {'title': 'Waiver Claims', 'columns': ['Waiver Claims']},
    {'title': 'Lost off Waivers', 'columns': ['Lost off Waivers']},
    {'title': 'Outrighted', 'columns': ['Outrighted']},
    {'title': 'Added to 40-Man', 'columns': ['Added to 40-Man']},
    {'title': 'Rule-5 Draft', 'columns': ['Rule-5 Draft Additions', 'Rule-5 Draft Losses'], 'subheaders': True},
    {'title': 'MLB Free Agents / Non-tendered', 'columns': ['Elected MLB FA/Non-tendered'], 'paired_col': 'New Team'},
    {'title': 'MiLB Free Agents', 'columns': ['Elected MiLB FA'], 'paired_col': 'New Team'},
    {'title': 'Released', 'columns': ['Released'], 'paired_col': 'New Team'},
    {'title': 'Retired', 'columns': ['Retired']},
]

# Subheader labels for sections that need them
SUBHEADER_LABELS = {
    'Traded For': 'Acquired',
    'Traded Away': 'Traded Away',
    'Rule-5 Draft Additions': 'Additions',
    'Rule-5 Draft Losses': 'Losses',
}


def parse_date(entry):
    """Extract date from entry if present (MM/DD: format)
    Also handles entries wrapped in ~~ strikethrough notation"""
    
    # Check if entire entry is wrapped in strikethrough
    is_strikethrough = False
    working_entry = entry
    if entry.startswith('~~') and entry.endswith('~~'):
        is_strikethrough = True
        working_entry = entry[2:-2]  # Remove ~~ from both ends
    
    # Check if entire entry is wrapped in italic
    is_italic = False
    if working_entry.startswith('_') and working_entry.endswith('_') and not working_entry.startswith('__'):
        is_italic = True
        working_entry = working_entry[1:-1]  # Remove _ from both ends
    
    # Now try to extract date
    if ': ' in working_entry:
        potential_date = working_entry.split(': ')[0]
        if '/' in potential_date and len(potential_date) <= 5:
            try:
                parts = potential_date.split('/')
                month = int(parts[0])
                day = int(parts[1])
                if 1 <= month <= 12 and 1 <= day <= 31:
                    # Found valid date
                    remaining_text = ': '.join(working_entry.split(': ')[1:])
                    # Re-add notation to remaining text
                    if is_italic:
                        remaining_text = f'_{remaining_text}_'
                    if is_strikethrough:
                        remaining_text = f'~~{remaining_text}~~'
                    return potential_date, remaining_text
            except:
                pass
    
    # No date found, return original entry
    return None, entry


def date_sort_key(t):
    """Sort key for transactions by date (oldest first - chronological)"""
    if t['date'] is None:
        # Check if re-signed (has asterisk) - these go to the top (return very early date)
        if '*' in t.get('entry', '') or '*' in t.get('raw', ''):
            return (1900, 1, 1)
        # No date and not re-signed - goes to the bottom (return very late date)
        return (2099, 12, 31)
    try:
        parts = t['date'].split('/')
        month = int(parts[0])
        day = int(parts[1])
        # Offseason: Sep-Dec = 2025, Jan-Mar = 2026
        year = 2025 if month >= 9 else 2026
        return (year, month, day)
    except:
        return (2099, 12, 31)


def parse_excel(filepath):
    """Parse the Excel file and return structured data"""
    xlsx = pd.ExcelFile(filepath)
    
    all_transactions = []
    team_data = {}
    
    for team_abbr in xlsx.sheet_names:
        if team_abbr == 'Indy Ball' or team_abbr not in TEAM_INFO:
            continue
        
        df = pd.read_excel(xlsx, sheet_name=team_abbr, header=None)
        
        # Build header mapping by name
        headers = {}
        header_positions = {}  # Track position for paired columns
        for i, val in enumerate(df.iloc[1]):
            if pd.notna(val):
                col_name = str(val).strip()
                headers[i] = col_name
                if col_name not in header_positions:
                    header_positions[col_name] = []
                header_positions[col_name].append(i)
        
        # Initialize team data structure
        team_data[team_abbr] = {col: [] for col in headers.values() if col not in SKIP_COLS}
        team_data[team_abbr]['_paired'] = {}  # Store paired column data
        
        # Parse each cell
        for col_idx, col_name in headers.items():
            if col_name in SKIP_COLS or not col_name:
                continue
            
            # Find paired "New Team" column if exists (it's the next column)
            paired_col_idx = None
            if col_name in ['Elected MLB FA/Non-tendered', 'Elected MiLB FA', 'Released']:
                if col_idx + 1 in headers and headers[col_idx + 1] == 'New Team':
                    paired_col_idx = col_idx + 1
            
            for row_idx in range(2, len(df)):
                cell = df.iloc[row_idx, col_idx]
                if pd.notna(cell) and str(cell).strip():
                    raw_entry = str(cell).strip()
                    date, entry_text = parse_date(raw_entry)
                    
                    # Get paired value if exists
                    paired_value = None
                    if paired_col_idx is not None:
                        paired_cell = df.iloc[row_idx, paired_col_idx]
                        if pd.notna(paired_cell) and str(paired_cell).strip():
                            paired_value = str(paired_cell).strip()
                    
                    is_mlb = col_name in MLB_RELEVANT_COLS
                    
                    txn = {
                        'team_abbr': team_abbr,
                        'team': TEAM_INFO[team_abbr]['name'],
                        'category': col_name,
                        'date': date,
                        'entry': entry_text,
                        'raw': raw_entry,
                        'is_mlb': is_mlb,
                        'paired_value': paired_value,
                    }
                    
                    all_transactions.append(txn)
                    team_data[team_abbr][col_name].append(txn)
    
    # Sort all transactions by date (chronological - oldest first)
    all_transactions.sort(key=date_sort_key)
    
    return all_transactions, team_data


def escape(s):
    """HTML escape"""
    return html.escape(str(s)) if s else ''


def format_entry(s):
    """HTML escape and convert ~~text~~ to strikethrough, _text_ to italic"""
    if not s:
        return ''
    
    text = html.escape(str(s))
    
    # Convert ~~text~~ to strikethrough
    import re
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)
    
    # Convert _text_ to italic (but not __text__ which would be double underscore)
    # Match _text_ but not when preceded or followed by another underscore
    text = re.sub(r'(?<!_)_([^_]+?)_(?!_)', r'<em>\1</em>', text)
    
    return text


def get_category_class(category):
    """Get CSS class for category color coding"""
    if 'Signing' in category or 'Extension' in category:
        return 'signing'
    elif 'Trade' in category:
        return 'trade'
    elif 'Waiver' in category and 'Lost' not in category:
        return 'waiver'
    elif 'Lost' in category:
        return 'lost'
    return ''


def generate_feed_html(transactions, limit=25):
    """Generate HTML for a transaction feed"""
    items = []
    for t in transactions[:limit]:
        date_str = t['date'] if t['date'] else '—'
        entry = format_entry(t['entry'])
        category = escape(t['category'])
        cat_class = get_category_class(t['category'])
        
        items.append(f'''                <div class="feed-item">
                    <span class="feed-team">{t['team_abbr']}</span>
                    <span class="feed-date">{date_str}</span>
                    <div class="feed-content">
                        <span class="feed-player">{entry}</span>
                        <span class="feed-category {cat_class}">{category}</span>
                    </div>
                </div>''')
    
    return '\n'.join(items)


def generate_accordion_section(title, transactions_by_col, is_open=False, use_subheaders=False):
    """Generate HTML for an accordion section"""
    # Flatten transactions for count
    all_transactions = []
    for col, txns in transactions_by_col.items():
        all_transactions.extend(txns)
    
    if not all_transactions:
        return ''
    
    open_class = ' open' if is_open else ''
    count = len(all_transactions)
    
    # Build items HTML
    if use_subheaders and len(transactions_by_col) > 1:
        # Multiple columns with subheaders
        items_parts = []
        for col, txns in transactions_by_col.items():
            if not txns:
                continue
            subheader_label = SUBHEADER_LABELS.get(col, col)
            items_parts.append(f'                    <li class="subheader">{escape(subheader_label)}</li>')
            # Sort within each subheader group
            txns_sorted = sorted(txns, key=date_sort_key)
            for t in txns_sorted:
                date_str = t['date'] if t['date'] else '—'
                entry = format_entry(t['entry'])
                paired = ''
                if t.get('paired_value'):
                    paired = f' → {escape(t["paired_value"])}'
                items_parts.append(f'''                    <li class="transaction-item">
                        <span class="tx-date">{date_str}</span>
                        <span class="tx-player">{entry}{paired}</span>
                    </li>''')
        items_html = '\n'.join(items_parts)
    else:
        # Single column or no subheaders needed
        items = []
        all_txns_sorted = sorted(all_transactions, key=date_sort_key)
        for t in all_txns_sorted:
            date_str = t['date'] if t['date'] else '—'
            entry = format_entry(t['entry'])
            paired = ''
            if t.get('paired_value'):
                paired = f' → {escape(t["paired_value"])}'
            items.append(f'''                    <li class="transaction-item">
                        <span class="tx-date">{date_str}</span>
                        <span class="tx-player">{entry}{paired}</span>
                    </li>''')
        items_html = '\n'.join(items)
    
    return f'''        <div class="accordion-section{open_class}">
            <div class="accordion-header" onclick="toggleAccordion(this)">
                <div class="accordion-title">
                    {escape(title)}
                    <span class="accordion-count">{count}</span>
                </div>
                <span class="accordion-icon">▼</span>
            </div>
            <div class="accordion-content">
                <ul class="transaction-list">
{items_html}
                </ul>
            </div>
        </div>
'''


def generate_team_page(team_abbr, team_data, all_transactions, css_content):
    """Generate HTML for a team page"""
    team_info = TEAM_INFO[team_abbr]
    team_name = team_info['name']
    
    # Build accordion sections
    accordion_html = ''

    for section in ACCORDION_SECTIONS:
        # Build dict of column -> transactions for this section
        transactions_by_col = {}
        for col in section['columns']:
            if col in team_data:
                transactions_by_col[col] = team_data[col]
            else:
                transactions_by_col[col] = []

        # Check if any transactions exist
        has_transactions = any(len(txns) > 0 for txns in transactions_by_col.values())

        if has_transactions:
            use_subheaders = section.get('subheaders', False)
            accordion_html += generate_accordion_section(
                section['title'],
                transactions_by_col,
                is_open=False,  # All sections closed by default
                use_subheaders=use_subheaders
            )
    
    # Generate team grid for navigation
    team_grid = generate_team_grid(team_abbr)
    
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{team_name} - Huronalytics</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Space+Grotesk:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
{css_content}
    </style>
</head>
<body>
    <header class="header">
        <a href="index.html" class="logo">huron<span>alytics</span></a>
        <nav class="nav">
            <a href="index.html">Home</a>
            <div class="search-container">
                <span class="search-icon">⌕</span>
                <input type="text" class="search-input" placeholder="Search players..." id="searchInput">
            </div>
        </nav>
    </header>

    <div class="team-header">
        <h1 class="team-name">{team_name}</h1>
        <p class="team-subtitle">2025-26 Offseason Transactions</p>
    </div>

    <div class="accordion-container">
{accordion_html}
    </div>

    <section class="teams-section">
        <div class="section-header">
            <h2 class="section-title">Other Teams</h2>
        </div>
{team_grid}
    </section>

    <footer class="footer">
        <p>Built by <a href="#">@huronalytics</a> | Data updated daily during the offseason</p>
    </footer>

    <script src="search.js"></script>
    <script>
        function toggleAccordion(header) {{
            const section = header.parentElement;
            section.classList.toggle('open');
        }}
    </script>
</body>
</html>'''


def generate_team_grid(current_team=None):
    """Generate team grid HTML"""
    cards = []
    for abbr in sorted(TEAM_INFO.keys()):
        info = TEAM_INFO[abbr]
        active = ' current' if abbr == current_team else ''
        cards.append(f'            <a href="{abbr.lower()}.html" class="team-card{active}"><span class="team-abbr">{abbr}</span><span class="team-name">{info["short"]}</span></a>')
    
    return f'''        <div class="teams-grid">
{chr(10).join(cards)}
        </div>'''


def generate_homepage(all_transactions, css_content, search_js):
    """Generate the homepage HTML"""
    # COMMENTED OUT: Transaction feed generation - can be re-enabled later
    # Filter out "Lost off Waivers" and "Traded Away" since they duplicate info
    # (Waiver Claims shows where player came from, Traded For shows where player came from)
    # excluded_categories = ['Lost off Waivers', 'Traded Away']
    # filtered_transactions = [t for t in all_transactions if t['category'] not in excluded_categories]
    #
    # # Sort for homepage feeds: newest first (reverse chronological)
    # # Need a different sort key that puts newest first
    # def homepage_sort_key(t):
    #     if t['date'] is None:
    #         return (0, 0, 0)  # No date goes to end
    #     try:
    #         parts = t['date'].split('/')
    #         month = int(parts[0])
    #         day = int(parts[1])
    #         year = 2025 if month >= 9 else 2026
    #         return (year, month, day)
    #     except:
    #         return (0, 0, 0)
    #
    # filtered_sorted = sorted(filtered_transactions, key=homepage_sort_key, reverse=True)
    # mlb_transactions = [t for t in filtered_sorted if t['is_mlb']]
    #
    # mlb_feed = generate_feed_html(mlb_transactions, limit=25)
    # all_feed = generate_feed_html(filtered_sorted, limit=25)

    team_grid = generate_team_grid()
    
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Huronalytics - 2025-26 MLB Offseason Tracker</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Space+Grotesk:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
{css_content}
    </style>
</head>
<body>
    <header class="header">
        <a href="index.html" class="logo">huron<span>alytics</span></a>
        <nav class="nav">
            <a href="index.html" class="active">Home</a>
            <div class="search-container">
                <span class="search-icon">⌕</span>
                <input type="text" class="search-input" placeholder="Search players..." id="searchInput">
                <div class="search-results" id="searchResults"></div>
            </div>
        </nav>
    </header>

    <section class="hero">
        <h1>2025-26 MLB Offseason Tracker</h1>
        <p>Comprehensive transaction tracking across all 30 MLB organizations</p>
    </section>

    <section class="teams-section">
        <div class="section-header">
            <h2 class="section-title">Teams</h2>
        </div>
{team_grid}
    </section>

    <section class="key-section">
        <div class="section-header">
            <h2 class="section-title">Key</h2>
        </div>
        <div class="key-content">
            <div class="key-group">
                <h3 class="key-heading">General Notation</h3>
                <ul class="key-list">
                    <li><strong>*</strong> = Re-signed (MLB Signings, MiLB Signings)</li>
                    <li><strong>(Team)</strong> = Last team played for</li>
                    <li><strong>(Team, Level)</strong> = Last team and highest level reached (MiLB Signings, trades, waivers)</li>
                    <li><strong><em>Italics</em></strong> = MLB portion of Rule-5 Draft, or player subsequently outrighted (Waiver Claims)</li>
                    <li><strong><s>Strikethrough</s></strong> = No longer in organization (except if lost off waivers then re-joined)</li>
                    <li><strong>No date</strong> = Transaction not yet official (MLB/MiLB Signings), except re-signed players at top (*), who are MiLB players who re-signed before reaching MiLB Free Agency</li>
                </ul>
            </div>
            <div class="key-group">
                <h3 class="key-heading">Position Designations</h3>
                <ul class="key-list">
                    <li><strong>RHSP/LHSP</strong> = Right/Left-handed Starting Pitcher</li>
                    <li><strong>RHRP/LHRP</strong> = Right/Left-handed Relief Pitcher</li>
                    <li>Pitchers listed as SP if more starts than relief appearances in most recent season</li>
                    <li>Position players listed by most-played position in most recent season</li>
                </ul>
            </div>
            <div class="key-group">
                <h3 class="key-heading">Free Agents & Released Players</h3>
                <ul class="key-list">
                    <li><strong>New Team (Contract Type)</strong> = Where player signed and contract level</li>
                    <li>Example: "TBR (MiLB)" = Signed with Rays on Minor League contract</li>
                    <li>Example: "Rakuten (NPB)" = Signed with team in foreign league</li>
                </ul>
            </div>
            <div class="key-group">
                <h3 class="key-heading">International Amateur Signings</h3>
                <ul class="key-list">
                    <li><strong>(Three-letter code)</strong> = Player's country using ISO Alpha-3 codes</li>
                    <li>Example: "DOM" = Dominican Republic, "VEN" = Venezuela, "CUB" = Cuba</li>
                </ul>
            </div>
        </div>
    </section>

    <footer class="footer">
        <p>Built by <a href="#">@huronalytics</a> | Data updated daily during the offseason</p>
    </footer>

    <script>
{search_js}
    </script>
</body>
</html>'''


def generate_css():
    """Generate the main CSS file"""
    return '''/* Huronalytics Styles */
:root {
    --bg-primary: #0a0a0a;
    --bg-secondary: #111;
    --bg-tertiary: #1a1a1a;
    --text-primary: #f0f0f0;
    --text-secondary: #888;
    --text-muted: #555;
    --accent: #c41e3a;
    --accent-light: #e63757;
    --accent-dim: #8b1528;
    --border: #2a2a2a;
    --green: #3d9942;
    --red: #c73e4d;
    --blue: #3b7dd8;
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: 'Space Grotesk', sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    min-height: 100vh;
}

/* Header */
.header {
    padding: 1.5rem 3rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
    position: sticky;
    top: 0;
    background: var(--bg-primary);
    z-index: 100;
}

.logo {
    font-size: 1.5rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    text-decoration: none;
    color: var(--text-primary);
}

.logo span {
    color: var(--accent-light);
}

.nav {
    display: flex;
    gap: 2rem;
    align-items: center;
}

.nav a {
    color: var(--text-secondary);
    text-decoration: none;
    font-size: 0.9rem;
    transition: color 0.2s;
}

.nav a:hover, .nav a.active {
    color: var(--text-primary);
}

/* Search */
.search-container {
    position: relative;
}

.search-input {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.5rem 1rem 0.5rem 2.5rem;
    color: var(--text-primary);
    font-family: 'Space Grotesk', sans-serif;
    font-size: 0.85rem;
    width: 250px;
    transition: border-color 0.2s, width 0.2s;
}

.search-input:focus {
    outline: none;
    border-color: var(--accent);
    width: 300px;
}

.search-icon {
    position: absolute;
    left: 0.75rem;
    top: 50%;
    transform: translateY(-50%);
    color: var(--text-muted);
    font-size: 0.9rem;
}

.search-results {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
    margin-top: 0.5rem;
    max-height: 400px;
    overflow-y: auto;
    display: none;
    z-index: 200;
}

.search-results.active {
    display: block;
}

.search-result-item {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    transition: background 0.2s;
}

.search-result-item:hover {
    background: var(--bg-tertiary);
}

.search-result-item:last-child {
    border-bottom: none;
}

.search-result-player {
    font-weight: 600;
    margin-bottom: 0.25rem;
}

.search-result-detail {
    font-size: 0.75rem;
    color: var(--text-secondary);
    font-family: 'JetBrains Mono', monospace;
}

/* Hero */
.hero {
    padding: 3rem;
    background: linear-gradient(135deg, var(--accent-dim) 0%, var(--bg-primary) 60%);
    border-bottom: 1px solid var(--border);
}

.hero h1 {
    font-size: 2.5rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    margin-bottom: 0.5rem;
}

.hero p {
    color: var(--text-secondary);
    font-size: 1.1rem;
}

/* Team Header (for team pages) */
.team-header {
    padding: 3rem;
    background: linear-gradient(135deg, var(--accent) 0%, #1a0a0a 100%);
    border-bottom: 3px solid var(--accent-light);
}

.team-name {
    font-size: 3rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    margin-bottom: 0.5rem;
}

.team-subtitle {
    color: rgba(255,255,255,0.7);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}

/* Teams Grid */
.teams-section {
    padding: 2rem 3rem;
    border-bottom: 1px solid var(--border);
}

.section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
}

.section-title {
    font-size: 1.25rem;
    font-weight: 600;
}

/* Key Section */
.key-section {
    padding: 2rem 3rem;
    border-bottom: 1px solid var(--border);
    background: var(--bg-secondary);
}

.key-content {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 2rem;
}

.key-group {
    background: var(--bg-primary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 1.5rem;
}

.key-heading {
    font-size: 1rem;
    font-weight: 600;
    color: var(--accent-light);
    margin-bottom: 1rem;
    font-family: 'JetBrains Mono', monospace;
}

.key-list {
    list-style: none;
    padding: 0;
    margin: 0;
}

.key-list li {
    font-size: 0.85rem;
    line-height: 1.8;
    color: var(--text-secondary);
    padding: 0.25rem 0;
}

.key-list li strong {
    color: var(--text-primary);
    font-family: 'JetBrains Mono', monospace;
}

.teams-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 0.75rem;
}

.team-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.75rem 1rem;
    text-decoration: none;
    color: var(--text-primary);
    transition: border-color 0.2s, transform 0.2s;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.team-card:hover {
    border-color: var(--accent);
    transform: translateY(-2px);
}

.team-card.current {
    border-color: var(--accent-light);
    background: var(--accent-dim);
}

.team-abbr {
    font-family: 'JetBrains Mono', monospace;
    font-weight: 600;
    font-size: 0.9rem;
    color: var(--accent-light);
}

.team-name {
    font-size: 0.8rem;
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* Feeds */
.feeds-container {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 2rem;
    padding: 2rem 3rem;
}

@media (max-width: 1200px) {
    .feeds-container {
        grid-template-columns: 1fr;
    }
}

.feed {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
}

.feed-header {
    padding: 1rem 1.25rem;
    background: var(--bg-tertiary);
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.feed-title {
    font-weight: 600;
    font-size: 1rem;
}

.feed-body {
    max-height: 700px;
    overflow-y: auto;
}

.feed-item {
    display: grid;
    grid-template-columns: 50px 55px 1fr;
    gap: 0.75rem;
    padding: 0.75rem 1.25rem;
    border-bottom: 1px solid var(--border);
    font-size: 0.85rem;
    align-items: baseline;
    transition: background 0.2s;
}

.feed-item:hover {
    background: var(--bg-tertiary);
}

.feed-item:last-child {
    border-bottom: none;
}

.feed-team {
    font-family: 'JetBrains Mono', monospace;
    font-weight: 600;
    color: var(--accent-light);
    font-size: 0.8rem;
}

.feed-date {
    font-family: 'JetBrains Mono', monospace;
    color: var(--text-muted);
    font-size: 0.75rem;
}

.feed-content {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
}

.feed-player {
    color: var(--text-primary);
}

.feed-category {
    font-size: 0.7rem;
    color: var(--text-muted);
    font-family: 'JetBrains Mono', monospace;
}

.feed-category.signing { color: var(--green); }
.feed-category.trade { color: var(--blue); }
.feed-category.waiver { color: #9b59b6; }
.feed-category.lost { color: var(--red); }

.load-more {
    padding: 1rem;
    text-align: center;
    border-top: 1px solid var(--border);
}

.load-more-btn {
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    padding: 0.5rem 1.5rem;
    border-radius: 4px;
    cursor: pointer;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 0.85rem;
    transition: all 0.2s;
}

.load-more-btn:hover {
    border-color: var(--accent);
    color: var(--text-primary);
}

/* Accordion */
.accordion-container {
    max-width: 900px;
    margin: 0 auto;
    padding: 2rem;
}

.accordion-section {
    border: 1px solid var(--border);
    margin-bottom: 0.5rem;
    border-radius: 4px;
    overflow: hidden;
}

.accordion-header {
    background: var(--bg-secondary);
    padding: 1rem 1.5rem;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    align-items: center;
    transition: background 0.2s;
}

.accordion-header:hover {
    background: var(--bg-tertiary);
}

.accordion-title {
    font-weight: 600;
    font-size: 0.95rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.accordion-count {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    color: var(--text-muted);
    background: var(--bg-primary);
    padding: 0.2rem 0.5rem;
    border-radius: 3px;
}

.accordion-icon {
    font-size: 1.25rem;
    color: var(--text-muted);
    transition: transform 0.3s;
}

.accordion-section.open .accordion-icon {
    transform: rotate(180deg);
}

.accordion-content {
    display: none;
    background: var(--bg-primary);
    border-top: 1px solid var(--border);
}

.accordion-section.open .accordion-content {
    display: block;
}

.transaction-list {
    padding: 0;
    list-style: none;
}

.transaction-item {
    display: grid;
    grid-template-columns: 60px 1fr;
    gap: 1rem;
    padding: 0.75rem 1.5rem;
    border-bottom: 1px solid var(--border);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    align-items: baseline;
}

.transaction-item:last-child {
    border-bottom: none;
}

.transaction-item:hover {
    background: var(--bg-secondary);
}

.transaction-list .subheader {
    padding: 0.5rem 1.5rem;
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-family: 'JetBrains Mono', monospace;
    border-bottom: 1px solid var(--border);
    list-style: none;
}

.tx-date {
    color: var(--text-muted);
    font-size: 0.75rem;
}

.tx-player {
    color: var(--text-primary);
}

/* Footer */
.footer {
    padding: 2rem 3rem;
    border-top: 1px solid var(--border);
    text-align: center;
    color: var(--text-muted);
    font-size: 0.8rem;
}

.footer a {
    color: var(--accent-light);
    text-decoration: none;
}

/* Scrollbars */
.feed-body::-webkit-scrollbar,
.accordion-content::-webkit-scrollbar {
    width: 6px;
}

.feed-body::-webkit-scrollbar-track,
.accordion-content::-webkit-scrollbar-track {
    background: var(--bg-secondary);
}

.feed-body::-webkit-scrollbar-thumb,
.accordion-content::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 3px;
}

/* Responsive */
@media (max-width: 768px) {
    .header {
        padding: 1rem 1.5rem;
        flex-wrap: wrap;
        gap: 1rem;
    }
    
    .nav {
        gap: 1rem;
    }
    
    .search-input {
        width: 180px;
    }
    
    .search-input:focus {
        width: 200px;
    }
    
    .hero, .teams-section, .feeds-container {
        padding: 1.5rem;
    }
    
    .hero h1 {
        font-size: 1.75rem;
    }
    
    .team-header {
        padding: 2rem 1.5rem;
    }
    
    .team-header .team-name {
        font-size: 2rem;
    }
    
    .accordion-container {
        padding: 1rem;
    }
}
'''


def generate_search_js(all_transactions):
    """Generate search JavaScript with transaction data"""
    # Create searchable data
    search_data = []
    for t in all_transactions:
        search_data.append({
            'entry': t['entry'],
            'team': t['team_abbr'],
            'category': t['category'],
            'date': t['date'],
            'team_page': f"{t['team_abbr'].lower()}.html"
        })

    return f'''// Search functionality
const searchData = {json.dumps(search_data)};  // All transactions searchable

const searchInput = document.getElementById('searchInput');
const searchResults = document.getElementById('searchResults');

if (searchInput && searchResults) {{
    searchInput.addEventListener('input', function() {{
        const query = this.value.toLowerCase().trim();
        
        if (query.length < 2) {{
            searchResults.classList.remove('active');
            return;
        }}
        
        const matches = searchData.filter(t => 
            t.entry.toLowerCase().includes(query)
        ).slice(0, 10);
        
        if (matches.length === 0) {{
            searchResults.innerHTML = '<div class="search-result-item"><div class="search-result-detail">No results found</div></div>';
        }} else {{
            searchResults.innerHTML = matches.map(t => `
                <a href="${{t.team_page}}" class="search-result-item">
                    <div class="search-result-player">${{t.entry}}</div>
                    <div class="search-result-detail">${{t.team}} - ${{t.category}}${{t.date ? ' (' + t.date + ')' : ''}}</div>
                </a>
            `).join('');
        }}
        
        searchResults.classList.add('active');
    }});
    
    searchInput.addEventListener('blur', function() {{
        setTimeout(() => searchResults.classList.remove('active'), 200);
    }});
    
    searchInput.addEventListener('focus', function() {{
        if (this.value.length >= 2) {{
            searchResults.classList.add('active');
        }}
    }});
}}

// Load more functionality (placeholder)
function loadMore(type) {{
    console.log('Load more:', type);
    // In a real implementation, this would fetch more data
    alert('Load more functionality coming soon!');
}}
'''


def build_site(excel_path, output_dir):
    """Main build function"""
    print(f"Parsing {excel_path}...")
    all_transactions, team_data = parse_excel(excel_path)
    print(f"Found {len(all_transactions)} transactions across {len(team_data)} teams")
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate CSS content
    css_content = generate_css()
    
    # Generate search JS content
    search_js = generate_search_js(all_transactions)
    
    # Generate homepage
    print("Generating index.html...")
    with open(os.path.join(output_dir, 'index.html'), 'w') as f:
        f.write(generate_homepage(all_transactions, css_content, search_js))
    
    # Generate team pages
    for team_abbr in team_data:
        print(f"Generating {team_abbr.lower()}.html...")
        with open(os.path.join(output_dir, f'{team_abbr.lower()}.html'), 'w') as f:
            f.write(generate_team_page(team_abbr, team_data[team_abbr], all_transactions, css_content))
    
    print(f"\nBuild complete! Output in {output_dir}/")
    print(f"Open {output_dir}/index.html to view the site")


if __name__ == '__main__':
    build_site(EXCEL_FILE, OUTPUT_DIR)
