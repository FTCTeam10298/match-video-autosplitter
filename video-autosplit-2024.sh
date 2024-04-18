#!/bin/bash
# Video AutoSplit, courtesy of FTC #10298 Brain Stormz
# Usage: ./video-autosplit.sh [url]
# Example 1: ./video-autosplit.sh https://www.twitch.tv/videos/412843875
# Example 2: ./video-autosplit.sh https://www.youtube.com/watch?v=7dauhDJG6tA
# Requirements:
# - The video has the standard FTC stream overlay (the one that shows the match timers/etc.)
# - yt-dlp is installed
# - ffmpeg is installed
# - tesseract is installed (package may be called tesseract-ocr)
# - imagemagick is installed (needed for the "convert" command)

echo -e "----------------------------------------------------
Video AutoSplit, courtesy of FTC #10298 Brain Stormz
----------------------------------------------------\n"
if [ -z "$1" ]; then
    echo -e "Error: No stream passed!

Usage: ./video-autosplit.sh [url]

Example 1: ./video-autosplit.sh https://www.twitch.tv/videos/412843875
Example 2: ./video-autosplit.sh https://www.youtube.com/watch?v=7dauhDJG6tA

Requirements:
 - The video has the standard FTC stream overlay (the one that shows the match timers/etc.)
 - yt-dlp is installed
 - ffmpeg is installed
 - tesseract is installed (package may be called tesseract-ocr)
 - imagemagick is installed (needed for the 'convert' command)"
    exit
fi

declare -i LAST_SPLIT_FRAMENUM
#CURRVIDNUM=1

declare -i VIDEO_NUMBER
VIDEO_NUMBER=0

VIDEO_FILENAME=""

CURRFRAMETIME=0
LAST_SPLIT_FRAMETIME=0
DIFFTIME=0

UUID=$(uuidgen)
TMPDIR="/tmp/video-autosplit-$UUID"

CURRENT_MATCH_STRING="Intro"
PREVIOUS_MATCH_STRING="Intro"

declare -i FRAME_WIDTH
declare -i FRAME_HEIGHT
FRAME_WIDTH=0
FRAME_HEIGHT=0

STREAM_FPS=0
STREAM_LENGTH=0

STREAM_URL=$1

#-------------------------------------------------------------------------------

declare -i LAST_FRAGMENT
LAST_FRAGMENT=0

declare -i NEW_DATA_ATTEMPTS
NEW_DATA_ATTEMPTS=0

# Using the method from https://www.reddit.com/r/youtubedl/comments/115etx6/switching_to_ytdlp_for_incrementally_downloading/
live_download() {
    # Download whatever there currently is to download, resuming if applicable
    # Add `--live-from-start ` to commands if downloading a currently-live YouTube stream
    yt-dlp -f b --verbose --continue --hls-prefer-native --parse-meta ":(?P<is_live>)" --fixup "never" $STREAM_URL -o "stream.%(ext)s" 2>&1 | tee "$TMPDIR/download-output.txt"
    
    echo -e "\n\nDownload Complete, sleeping for 5 seconds"
    sleep 5
    
    LAST_FRAGMENT_FROM_CURRENT_OUTPUT="$(cat $TMPDIR/download-output.txt | grep 'Total fragments' | tr -dc '0123456789')"
    
    if [ -f ./stream.mp4.ytdl ]; then
        echo "./stream.mp4.ytdl exists, not overwriting"
        VIDEO_FILENAME="stream.mp4.part"
    else
        # Check if LAST_FRAGMENT_FROM_CURRENT_OUTPUT is non-empty
        if [ -n "$LAST_FRAGMENT_FROM_CURRENT_OUTPUT" ]; then
        
            LAST_FRAGMENT=$LAST_FRAGMENT_FROM_CURRENT_OUTPUT
            echo "Using updated last fragment value: "$LAST_FRAGMENT
            
            echo '{"downloader": {"current_fragment": {"index": '$LAST_FRAGMENT'}, "extra_state": {}}}' | tr -d '\n\f' > ./stream.mp4.ytdl
            mv stream.mp4 stream.mp4.part
            VIDEO_FILENAME="stream.mp4.part"
            
        elif [ "$LAST_FRAGMENT" -ne 0 ]; then
        
            echo "No new last fragment value, using old value "$LAST_FRAGMENT
            
            echo '{"downloader": {"current_fragment": {"index": '$LAST_FRAGMENT'}, "extra_state": {}}}' | tr -d '\n\f' > ./stream.mp4.ytdl
            mv stream.mp4 stream.mp4.part
            VIDEO_FILENAME="stream.mp4.part"
            
        else
            echo "No new last fragment value nor old value, skipping file write"
            VIDEO_FILENAME="stream.mp4"
        fi
        
        echo "File writes complete (if applicable)"
    fi
    
    echo "Sleeping for 5 seconds"
    sleep 5
    echo -e "Sleep complete\n\n"
}

#-------------------------------------------------------------------------------

# Delete and re-create temp dir to avoid leftover state messing with things
rm -r $TMPDIR/
mkdir $TMPDIR/ > /dev/null 2>&1

echo "Downloading stream..."
#yt-dlp $STREAM_URL -o "stream.%(ext)s" --remux-video mp4
live_download
echo "Download complete."

FRAME_WIDTH="$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of default=nw=1:nk=1 $VIDEO_FILENAME | head -n1)"
FRAME_HEIGHT="$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of default=nw=1:nk=1 $VIDEO_FILENAME | head -n1)"
echo "Frame width: $FRAME_WIDTH"
echo "Frame height: $FRAME_HEIGHT"

OVERLAY_CHECK_AREA=$(bc -l <<< "0.1*$FRAME_WIDTH")x$(bc -l <<< "0.055000000*$FRAME_HEIGHT")+$(bc -l <<< "0.0*$FRAME_WIDTH")+$(bc -l <<< "0.77*$FRAME_HEIGHT")

MATCH_NUMBER_CHECK_AREA=$(bc -l <<< "0.3*$FRAME_WIDTH")x$(bc -l <<< "0.050000000*$FRAME_HEIGHT")+$(bc -l <<< "0.53*$FRAME_WIDTH")+$(bc -l <<< "0.773148148*$FRAME_HEIGHT")

# Store the FPS of the stream for use later
STREAM_FPS=$(ffprobe -hide_banner -show_streams $VIDEO_FILENAME 2>&1 | grep fps | awk '{split($0,a,"fps")}END{print a[1]}' | awk '{print $NF}')
STREAM_LENGTH=$(ffprobe -i $VIDEO_FILENAME -show_entries format=duration -v quiet -of csv="p=0")

echo "OVERLAY_CHECK_AREA: $OVERLAY_CHECK_AREA"
echo "MATCH_NUMBER_CHECK_AREA: $MATCH_NUMBER_CHECK_AREA"

# Start main loop --------------------------------------------------------------

while true
do
    while true
    do
        # The "1" is the increment between each frame that is grabbed and checked.
        # Decrease the 1 for better accuracy, increase for better performance.
        CURRFRAMETIME=$(echo "$CURRFRAMETIME + 1" | bc -l)

        while (( $(echo "$CURRFRAMETIME > $STREAM_LENGTH" | bc -l) )); do
            # Start by continually checking for more video
            live_download
            # Update stream length
            STREAM_LENGTH=$(ffprobe -i $VIDEO_FILENAME -show_entries format=duration -v quiet -of csv="p=0")
            # Update number of new data attempts
            NEW_DATA_ATTEMPTS=$NEW_DATA_ATTEMPTS+1
            echo "Attempts to get new data: $NEW_DATA_ATTEMPTS"
            if [ $NEW_DATA_ATTEMPTS -gt 30 ]; then
                # We have reached the end of the source file, and the stream does not
                # appear to still be going, so encode the last clip and exit.
                echo e "Stream appears to have ended, encoding last clip\n"
                DIFFTIME=$(echo "$CURRFRAMETIME - $LAST_SPLIT_FRAMETIME" | bc -l)
                VIDEO_NUMBER=$VIDEO_NUMBER+1
                ffmpeg -hide_banner -ss $LAST_SPLIT_FRAMETIME -i $VIDEO_FILENAME -t $DIFFTIME -vcodec copy -acodec copy "$VIDEO_NUMBER - $CURRENT_MATCH_STRING.mp4"
                echo "\nStream appears to have ended, last clip has been encoded, everything is complete!"
                exit
            fi
        done
        
        NEW_DATA_ATTEMPTS=0

        fn=$VIDEO_FILENAME
        of="$TMPDIR/current.png"
        ffmpeg -hide_banner -nostats -loglevel warning -y -ss $CURRFRAMETIME -i $fn -update 1 -frames:v 1 -q:v 2 $of

        # Check if overlay is present
        convert $TMPDIR/current.png -crop $OVERLAY_CHECK_AREA $TMPDIR/overlay_check.png
        rm $TMPDIR/out.txt > /dev/null 2>&1
        tesseract $TMPDIR/overlay_check.png $TMPDIR/overlay_check > /dev/null 2>&1
        tr -dc '\0-\177' <$TMPDIR/overlay_check.txt | tr -d '\f' >$TMPDIR/tmp && mv $TMPDIR/tmp $TMPDIR/overlay_check.txt
        echo "Checking for overlay at time $CURRFRAMETIME"
        grep PION $TMPDIR/overlay_check.txt > /dev/null 2>&1
        if [ $? -lt 1 ]
        then
            # Overlay is present, let's check if it's a new match
            echo "Overlay present at time $CURRFRAMETIME"
            convert $TMPDIR/current.png -crop $MATCH_NUMBER_CHECK_AREA $TMPDIR/match_number_check.png

            tesseract $TMPDIR/match_number_check.png $TMPDIR/match_num > /dev/null 2>&1
            tr -dc '\0-\177' <$TMPDIR/match_num.txt | tr -d '\n\f' >$TMPDIR/tmp && mv $TMPDIR/tmp $TMPDIR/match_num.txt

            PREVIOUS_MATCH_STRING="$CURRENT_MATCH_STRING"
            CURRENT_MATCH_STRING="$(cat $TMPDIR/match_num.txt)"

            # Compare the two frames to see if it's a new match
            if [ "$CURRENT_MATCH_STRING" != "$PREVIOUS_MATCH_STRING" ]; then
                break
            fi
        fi
    done
    echo "New match at time $CURRFRAMETIME: $CURRENT_MATCH_STRING"

    DIFFTIME=$(echo "$CURRFRAMETIME - $LAST_SPLIT_FRAMETIME" | bc -l)
    VIDEO_NUMBER=$VIDEO_NUMBER+1
    ffmpeg -hide_banner -ss $LAST_SPLIT_FRAMETIME -i $VIDEO_FILENAME -t $DIFFTIME -vcodec copy -acodec copy "$VIDEO_NUMBER - $PREVIOUS_MATCH_STRING.mp4" &
    LAST_SPLIT_FRAMETIME=$CURRFRAMETIME
done
