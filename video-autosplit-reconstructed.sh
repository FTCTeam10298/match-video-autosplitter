#!/bin/bash
# Video AutoSplit, courtesy of FTC #10298 Brain Stormz
# Usage: ./video-autosplit.sh https://example.com/video/123456
# Example 1: ./video-autosplit.sh https://www.twitch.tv/videos/412843875
# Example 2: ./video-autosplit.sh https://www.youtube.com/watch?v=7dauhDJG6tA
# Requirements:
# - The video has the standard FTC stream overlay (the one that shows the match timers/etc.)
# - youtube-dl is installed
# - ffmpeg is installed
# - tesseract is installed (package may be called tesseract-ocr)

declare -i LAST_SPLIT_FRAMENUM
CURRVIDNUM=1
CURRFRAMETIME=0
LAST_SPLIT_FRAMETIME=0
DIFFTIME=0

CURRENT_MATCH_STRING="Intro"
PREVIOUS_MATCH_STRING="Intro"

declare -i FRAME_WIDTH
declare -i FRAME_HEIGHT
FRAME_WIDTH=0
FRAME_HEIGHT=0

OVERLAY_CHECK_AREA=0x0+0+0

MATCH_NUMBER_CHECK_AREA=0x0+0+0

STREAM_FPS=0
STREAM_LENGTH=0

#-------------------------------------------------------------------------------

echo "Downloading stream..."
youtube-dl $1 -o "stream.%(ext)s"
echo "Download complete."

FRAME_WIDTH="$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of default=nw=1:nk=1 stream.mp4)"
FRAME_HEIGHT="$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of default=nw=1:nk=1 stream.mp4)"

OVERLAY_CHECK_AREA=$(bc -l <<< "0.143229167*$FRAME_WIDTH")x$(bc -l <<< "0.055555556*$FRAME_HEIGHT")+$(bc -l <<< "0.0078125*$FRAME_WIDTH")+$(bc -l <<< "0.773148148*$FRAME_HEIGHT")

MATCH_NUMBER_CHECK_AREA=$(bc -l <<< "0.356770833*$FRAME_WIDTH")x$(bc -l <<< "0.055555556*$FRAME_HEIGHT")+$(bc -l <<< "0.151041667*$FRAME_WIDTH")+$(bc -l <<< "0.773148148*$FRAME_HEIGHT")

# Store the FPS of the stream for use later
STREAM_FPS=$(ffprobe -hide_banner -show_streams stream.mp4 2>&1 | grep fps | awk '{split($0,a,"fps")}END{print a[1]}' | awk '{print $NF}')
STREAM_LENGTH=$(ffprobe -i stream.mp4 -show_entries format=duration -v quiet -of csv="p=0")

echo "OVERLAY_CHECK_AREA: $OVERLAY_CHECK_AREA"
echo "MATCH_NUMBER_CHECK_AREA: $MATCH_NUMBER_CHECK_AREA"

mkdir ./tmp > /dev/null 2>&1

# Start main loop --------------------------------------------------------------

while true
do
    while true
    do
        # The "2" is the increment between each frame that is grabbed and checked.
        # Decrease the 2 for better accuracy, increase for better performance.
        CURRFRAMETIME=$(echo "$CURRFRAMETIME + 2" | bc -l)

        if (( $(echo "$CURRFRAMETIME > $STREAM_LENGTH" | bc -l) )); then
            # We have reahced the end of the source file, so encode the last clip and exit.
            DIFFTIME=$(echo "$CURRFRAMETIME - $LAST_SPLIT_FRAMETIME" | bc -l)
            ffmpeg -hide_banner -ss $LAST_SPLIT_FRAMETIME -i stream.mp4 -t $DIFFTIME -vcodec copy -acodec copy "$CURRENT_MATCH_STRING.mp4" &
            exit
        fi

        fn="stream.mp4"
        of="tmp/current.png"
        ffmpeg -hide_banner -nostats -loglevel warning -y -ss $CURRFRAMETIME -i $fn -vframes 1 -q:v 2 $of

        # Check if overlay is present
        convert tmp/current.png -crop $OVERLAY_CHECK_AREA tmp/overlay_check.png
        rm tmp/out.txt > /dev/null 2>&1
        tesseract tmp/overlay_check.png tmp/overlay_check > /dev/null 2>&1
        tr -dc '\0-\177' <tmp/overlay_check.txt | tr -d '\f' >tmp/tmp && mv tmp/tmp tmp/overlay_check.txt
        grep FIRST tmp/overlay_check.txt > /dev/null 2>&1
        if [ $? -lt 1 ]
        then
            # Overlay is present, let's check if it's a new match
            #echo "Overlay present at time $CURRFRAMETIME"
            convert tmp/current.png -crop $MATCH_NUMBER_CHECK_AREA tmp/current.png

            tesseract tmp/current.png tmp/match_num > /dev/null 2>&1
            tr -dc '\0-\177' <tmp/match_num.txt | tr -d '\f' >tmp/tmp && mv tmp/tmp tmp/match_num.txt

            PREVIOUS_MATCH_STRING="$CURRENT_MATCH_STRING"
            CURRENT_MATCH_STRING="$(cat tmp/match_num.txt)"

            # Compare the two frames to see if it's a new match
            if [ "$CURRENT_MATCH_STRING" != "$PREVIOUS_MATCH_STRING" ]; then
                break
            fi
        fi
    done
    echo "New match at time $CURRFRAMETIME: $CURRENT_MATCH_STRING"

    DIFFTIME=$(echo "$CURRFRAMETIME - $LAST_SPLIT_FRAMETIME" | bc -l)
    ffmpeg -hide_banner -ss $LAST_SPLIT_FRAMETIME -i stream.mp4 -t $DIFFTIME -vcodec copy -acodec copy "$PREVIOUS_MATCH_STRING.mp4" &
    LAST_SPLIT_FRAMETIME=$CURRFRAMETIME
done
