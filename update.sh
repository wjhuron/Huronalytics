#!/bin/bash

# Huronalytics Auto-Update Script
# Downloads latest Google Sheet, rebuilds site, and syncs to GitHub

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Google Sheet published URL
SHEET_URL="https://docs.google.com/spreadsheets/d/e/2PACX-1vQX9EUtMqEgxP7tjoGibR3j6Y6CUrY9p2heOxAr6kdq3CZTq979tYSSXMdTQpuY4bNMJ3IqrswiUV5I/pub?output=xlsx"

# File paths
DATA_FILE="data/2025_26_MLB_Offseason.xlsx"

# Change to script directory
cd "$(dirname "$0")"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   Huronalytics Auto-Update${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Step 1: Download latest Google Sheet
echo -e "${YELLOW}[1/3] Downloading latest data from Google Sheets...${NC}"
curl -L -o "$DATA_FILE" "$SHEET_URL"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Data downloaded successfully${NC}"
else
    echo -e "${RED}✗ Failed to download data${NC}"
    exit 1
fi
echo ""

# Step 2: Run build script
echo -e "${YELLOW}[2/3] Building site...${NC}"
python3 build.py

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Site built successfully${NC}"
else
    echo -e "${RED}✗ Build failed${NC}"
    exit 1
fi
echo ""

# Step 3: Sync to GitHub
echo -e "${YELLOW}[3/3] Syncing to GitHub...${NC}"

# Check if there are any changes
if [[ -z $(git status -s) ]]; then
    echo -e "${GREEN}✓ No changes detected. Everything is up to date!${NC}"
    exit 0
fi

# Show changes
echo -e "${BLUE}Changes detected:${NC}"
git status -s

# Add all changes
git add .

# Create commit with timestamp
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
COMMIT_MESSAGE="Auto-update: $TIMESTAMP"

git commit -m "$COMMIT_MESSAGE"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Changes committed${NC}"

    # Push to GitHub
    git push origin main

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Successfully pushed to GitHub${NC}"
    else
        echo -e "${RED}✗ Failed to push to GitHub${NC}"
        exit 1
    fi
else
    echo -e "${RED}✗ Commit failed${NC}"
    exit 1
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}   Update Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "View your site: ${YELLOW}https://github.com/wjhuron/Huronalytics${NC}"
