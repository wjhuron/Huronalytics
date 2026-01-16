#!/bin/bash

# GitHub Auto-Sync Script for huronalytics
# This script automatically commits and pushes all changes to GitHub

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting GitHub sync...${NC}"

# Change to the script's directory
cd "$(dirname "$0")"

# Check if there are any changes
if [[ -z $(git status -s) ]]; then
    echo -e "${GREEN}No changes to commit. Everything is up to date!${NC}"
    exit 0
fi

# Show what will be committed
echo -e "${YELLOW}Changes to be committed:${NC}"
git status -s

# Add all changes
git add .

# Create commit with timestamp
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
COMMIT_MESSAGE="Auto-sync: $TIMESTAMP"

git commit -m "$COMMIT_MESSAGE"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}Changes committed successfully!${NC}"

    # Push to GitHub
    echo -e "${YELLOW}Pushing to GitHub...${NC}"
    git push origin main

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Successfully pushed to GitHub!${NC}"
    else
        echo -e "${RED}Failed to push to GitHub. Check your internet connection and credentials.${NC}"
        exit 1
    fi
else
    echo -e "${RED}Commit failed!${NC}"
    exit 1
fi
