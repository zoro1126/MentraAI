#!/bin/bash

# Configuration
SOURCE_DIR="daic-woz/zips/sessions"
DEST_DIR="backend/data"
NUM_SESSIONS=80

# Create destination directory if it doesn't exist
mkdir -p "$DEST_DIR"

# Check if source directory exists
if [ ! -d "$SOURCE_DIR" ]; then
    echo "Error: Source directory $SOURCE_DIR does not exist."
    exit 1
fi

# Find up to 80 session zip files
echo "Finding session zip files..."
ZIPS=$(find "$SOURCE_DIR" -maxdepth 1 -type f -name "*_P.zip" | head -n "$NUM_SESSIONS")

if [ -z "$ZIPS" ]; then
    echo "Error: No session zip files found in $SOURCE_DIR."
    exit 1
fi

count=0
for zip_file in $ZIPS; do
    session_id=$(basename "$zip_file" | cut -d'_' -f1)
    echo "Extracting files from session $session_id..."
    
    # We use -j to ignore path inside the ZIP (extract flat to DEST_DIR)
    # We use -o to overwrite without prompting
    # We use -q for quiet output
    unzip -j -o -q "$zip_file" "*_CLNF_AUs.txt" "*_CLNF_pose.txt" "*_CLNF_gaze.txt" -d "$DEST_DIR"
    
    count=$((count+1))
done

echo "Successfully extracted specified files from $count sessions to $DEST_DIR."
