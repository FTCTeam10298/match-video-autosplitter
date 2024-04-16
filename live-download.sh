#!/bin/bash
# Video AutoSplit continuous live downloader component, courtesy of FTC #10298 Brain Stormz
# Using the method from https://www.reddit.com/r/youtubedl/comments/115etx6/switching_to_ytdlp_for_incrementally_downloading/
# Usage: ./live-download.sh [url]
# Example 1: ./live-download.sh https://www.twitch.tv/videos/412843875
# Example 2: ./live-download.sh https://www.youtube.com/watch?v=7dauhDJG6tA
# Requirements:
# - yt-dlp is installed

STREAM_URL=$1

declare -i LAST_FRAGMENT
LAST_FRAGMENT=0

UUID=$(uuidgen)
TMPDIR="/tmp/video-autosplit-live-downloader-$UUID"

# Delete and re-create temp dir to avoid leftover state messing with things
rm -r /tmp/video-autosplit-live-downloader-$UUID
mkdir /tmp/video-autosplit-live-downloader-$UUID > /dev/null 2>&1

while true
do
    # Download whatever there currently is to download, resuming if applicable
    yt-dlp -f b --verbose --continue --hls-prefer-native --live-from-start --parse-meta ":(?P<is_live>)" --fixup "never" $STREAM_URL -o "stream.%(ext)s" 2>&1 | tee "$TMPDIR/download-output.txt"
    
    echo -e "\n\nDownload Complete, sleeping for 10 seconds"
    sleep 10
    
    LAST_FRAGMENT_FROM_CURRENT_OUTPUT="$(cat $TMPDIR/download-output.txt | grep 'Total fragments' | tr -dc '0123456789')"
    
    if [ -f ./stream.mp4.ytdl ]; then
        echo "./stream.mp4.ytdl exists, not overwriting"
        echo "Sleeping for 10 seconds"
    else
        # Check if LAST_FRAGMENT_FROM_CURRENT_OUTPUT is non-empty
        if [ -n "$LAST_FRAGMENT_FROM_CURRENT_OUTPUT" ]; then
            LAST_FRAGMENT=$LAST_FRAGMENT_FROM_CURRENT_OUTPUT
            echo "Using updated last fragment value: "$LAST_FRAGMENT
        elif [ "$LAST_FRAGMENT" -ne 0 ]; then
            echo "No new last fragment value, using old value "$LAST_FRAGMENT
            echo '{"downloader": {"current_fragment": {"index": '$LAST_FRAGMENT'}, "extra_state": {}}}' | tr -d '\n\f' > ./stream.mp4.ytdl
            mv stream.mp4 stream.mp4.part
        else
            echo "No new last fragment value nor old value, skipping file write"
        fi
        
        echo "File writes complete (if applicable), sleeping for 10 seconds"
    fi
    
    sleep 10
    echo -e "Sleep complete\n\n"
done