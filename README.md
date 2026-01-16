# Huronalytics - MLB Offseason Tracker

Up to date transaction log for all 30 MLB teams. Every transaction that are in the official MLB and MiLB transaction logs. Reported transactions included as well without a date.

## Automated Workflow

### One Command Update (Recommended)

Update everything automatically - download latest data, rebuild site, and push to GitHub:

```bash
./update.sh
```

This script will:
1. Download the latest data from your published Google Sheet
2. Run the build script to regenerate all HTML files
3. Commit and push all changes to GitHub

### Manual Steps (if needed)

If you prefer to run steps individually:

```bash
# 1. Download latest data
curl -L -o data/2025_26_MLB_Offseason.xlsx "YOUR_GOOGLE_SHEET_URL"

# 2. Build the site
python3 build.py

# 3. Sync to GitHub
./sync.sh
```

## Automation Options

### Schedule automatic updates

Run updates automatically using cron:

```bash
# Edit crontab
crontab -e

# Update every hour
0 * * * * cd /Users/wallyhuron/Downloads/huronalytics && ./update.sh >> update.log 2>&1

# Update every 6 hours
0 */6 * * * cd /Users/wallyhuron/Downloads/huronalytics && ./update.sh >> update.log 2>&1

# Update daily at 9 AM
0 9 * * * cd /Users/wallyhuron/Downloads/huronalytics && ./update.sh >> update.log 2>&1
```

## Files

- `update.sh` - Complete automation: download, build, and sync
- `build.py` - Build script that generates HTML from Excel data
- `sync.sh` - Git commit and push helper
- `data/` - Downloaded Excel data
- `output/` - Generated HTML files

## Repository

https://github.com/wjhuron/Huronalytics
