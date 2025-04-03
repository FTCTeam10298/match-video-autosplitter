#!/usr/bin/env python3
"""
Video AutoSplit, courtesy of FTC #10298 Brain Stormz
Converted to Python from original bash script

Usage: python video-autosplit.py [url]
Example 1: python video-autosplit.py https://www.twitch.tv/videos/412843875
Example 2: python video-autosplit.py https://www.youtube.com/watch?v=7dauhDJG6tA

Requirements:
- The video has the standard FTC stream overlay (the one that shows the match timers/etc.)
- yt-dlp is installed
- ffmpeg is installed (with ffprobe)
- tesseract is installed
- imagemagick is installed (for the "convert" command)
"""

import argparse
import os
import subprocess
import uuid
import json
import time
import shutil
import re
import sys


def print_header():
    print("""----------------------------------------------------
Video AutoSplit, courtesy of FTC #10298 Brain Stormz
----------------------------------------------------
""")


def execute_command(command, capture_output=True):
    """Execute a shell command and return its output."""
    try:
        if capture_output:
            result = subprocess.run(command, shell=True, check=True, 
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True)
            return result.stdout.strip()
        else:
            subprocess.run(command, shell=True, check=True)
            return None
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {command}")
        print(f"Error message: {e.stderr}")
        return None


def live_download(stream_url, tmpdir):
    """Download the stream using yt-dlp."""
    # Download whatever there currently is to download, resuming if applicable
    command = f'yt-dlp -f b --verbose --continue --hls-prefer-native --parse-meta ":(?P<is_live>)" --fixup "never" {stream_url} -o "stream.%(ext)s" 2>&1 | tee "{tmpdir}/download-output.txt"'
    
    execute_command(command, capture_output=False)
    
    print("\n\nDownload Complete, sleeping for 5 seconds")
    time.sleep(5)
    
    # Get the last fragment number from the download output
    with open(f"{tmpdir}/download-output.txt", "r") as f:
        download_output = f.read()
    
    last_fragment = 0
    fragment_match = re.search(r'Total fragments: (\d+)', download_output)
    if fragment_match:
        last_fragment = int(fragment_match.group(1))
    
    video_filename = ""
    
    if os.path.exists("./stream.mp4.ytdl"):
        print("./stream.mp4.ytdl exists, not overwriting")
        video_filename = "stream.mp4.part"
    else:
        if last_fragment > 0:
            print(f"Using updated last fragment value: {last_fragment}")
            
            # Create ytdl state file
            ytdl_state = {
                "downloader": {
                    "current_fragment": {"index": last_fragment},
                    "extra_state": {}
                }
            }
            
            with open("./stream.mp4.ytdl", "w") as f:
                json.dump(ytdl_state, f)
            
            if os.path.exists("stream.mp4"):
                shutil.move("stream.mp4", "stream.mp4.part")
            
            video_filename = "stream.mp4.part"
        else:
            print("No new last fragment value, skipping file write")
            video_filename = "stream.mp4"
    
    print("File writes complete (if applicable)")
    print("Sleeping for 5 seconds")
    time.sleep(5)
    print("Sleep complete\n\n")
    
    return video_filename, last_fragment


def main():
    parser = argparse.ArgumentParser(description="Video AutoSplit tool for FTC competition videos")
    parser.add_argument("url", nargs="?", help="URL of the stream to process")
    args = parser.parse_args()
    
    print_header()
    
    if not args.url:
        print("""Error: No stream passed!

Usage: python video-autosplit.py [url]

Example 1: python video-autosplit.py https://www.twitch.tv/videos/412843875
Example 2: python video-autosplit.py https://www.youtube.com/watch?v=7dauhDJG6tA

Requirements:
 - The video has the standard FTC stream overlay (the one that shows the match timers/etc.)
 - yt-dlp is installed
 - ffmpeg is installed
 - tesseract is installed
 - imagemagick is installed (needed for the 'convert' command)""")
        sys.exit(1)
    
    # Fix nasty slowdown of tesseract OCR when multiple processes running
    os.environ["OMP_THREAD_LIMIT"] = "1"
    
    # Initialize variables
    last_split_framenum = 0
    video_number = 0
    video_filename = ""
    
    curr_frame_time = 0
    last_split_frame_time = 0
    diff_time = 0
    
    # Create unique temp directory
    uuid_str = str(uuid.uuid4())
    tmpdir = f"/tmp/video-autosplit-{uuid_str}"
    
    current_match_string = "Intro"
    previous_match_string = "Intro"
    
    frame_width = 0
    frame_height = 0
    
    stream_fps = 0
    stream_length = 0
    
    stream_url = args.url
    
    last_fragment = 0
    new_data_attempts = 0
    
    # Delete and re-create temp dir to avoid leftover state
    if os.path.exists(tmpdir):
        shutil.rmtree(tmpdir)
    os.makedirs(tmpdir, exist_ok=True)
    
    print("Downloading stream...")
    video_filename, last_fragment = live_download(stream_url, tmpdir)
    print("Download complete.")
    
    # Get video dimensions
    frame_width = int(execute_command(f"ffprobe -v error -select_streams v:0 -show_entries stream=width -of default=nw=1:nk=1 {video_filename} | head -n1"))
    frame_height = int(execute_command(f"ffprobe -v error -select_streams v:0 -show_entries stream=height -of default=nw=1:nk=1 {video_filename} | head -n1"))
    print(f"Frame width: {frame_width}")
    print(f"Frame height: {frame_height}")
    
    # Calculate areas for OCR
    overlay_check_area = f"{0.1*frame_width}x{0.055*frame_height}+{0.0*frame_width}+{0.77*frame_height}"
    match_number_check_area = f"{0.3*frame_width}x{0.05*frame_height}+{0.53*frame_width}+{0.773148148*frame_height}"
    
    # Get stream FPS and length
    fps_output = execute_command(f"ffprobe -hide_banner -show_streams {video_filename} 2>&1 | grep fps")
    stream_fps = float(re.search(r'(\d+\.?\d*) fps', fps_output).group(1))
    stream_length = float(execute_command(f"ffprobe -i {video_filename} -show_entries format=duration -v quiet -of csv=\"p=0\""))
    
    print(f"OVERLAY_CHECK_AREA: {overlay_check_area}")
    print(f"MATCH_NUMBER_CHECK_AREA: {match_number_check_area}")
    
    # Start main loop
    while True:
        while True:
            # The "5" is the increment between each frame that is grabbed and checked.
            # Decrease for better accuracy, increase for better performance.
            curr_frame_time += 5
            
            while curr_frame_time > stream_length:
                # Start by continually checking for more video
                video_filename, last_fragment = live_download(stream_url, tmpdir)
                # Update stream length
                stream_length = float(execute_command(f"ffprobe -i {video_filename} -show_entries format=duration -v quiet -of csv=\"p=0\""))
                # Update number of new data attempts
                new_data_attempts += 1
                print(f"Attempts to get new data: {new_data_attempts}")
                
                if new_data_attempts > 30:
                    # We have reached the end of the source file, and the stream does not
                    # appear to still be going, so encode the last clip and exit.
                    print("Stream appears to have ended, encoding last clip\n")
                    diff_time = curr_frame_time - last_split_frame_time
                    video_number += 1
                    execute_command(f'ffmpeg -hide_banner -ss {last_split_frame_time} -i {video_filename} -t {diff_time} -vcodec copy -acodec copy "{video_number} - {current_match_string}.mp4"')
                    print("\nStream appears to have ended, last clip has been encoded, everything is complete!")
                    sys.exit(0)
            
            new_data_attempts = 0
            
            # Extract current frame for analysis
            current_frame = f"{tmpdir}/current.png"
            execute_command(f'ffmpeg -hide_banner -nostats -loglevel warning -y -ss {curr_frame_time} -i {video_filename} -update 1 -frames:v 1 -q:v 2 {current_frame}')
            
            # Check if overlay is present
            print(f"Checking for overlay at time {curr_frame_time}")
            overlay_check_image = f"{tmpdir}/overlay_check.png"
            execute_command(f'convert {current_frame} -crop {overlay_check_area} {overlay_check_image}')
            
            if os.path.exists(f"{tmpdir}/overlay_check.txt"):
                os.remove(f"{tmpdir}/overlay_check.txt")
                
            execute_command(f'tesseract {overlay_check_image} {tmpdir}/overlay_check > /dev/null 2>&1')
            
            # Clean up the OCR output
            with open(f"{tmpdir}/overlay_check.txt", "r") as f:
                overlay_text = f.read()
                
            overlay_text = re.sub(r'[^\x00-\x7F]+', '', overlay_text).replace('\f', '')
            
            with open(f"{tmpdir}/overlay_check.txt", "w") as f:
                f.write(overlay_text)
            
            # Check if "CH" is in the overlay text (indicating overlay is present)
            if "CH" in overlay_text:
                # Overlay is present, let's check if it's a new match
                print(f"Overlay present at time {curr_frame_time}")
                match_number_image = f"{tmpdir}/match_number_check.png"
                execute_command(f'convert {current_frame} -crop {match_number_check_area} {match_number_image}')
                
                execute_command(f'tesseract {match_number_image} {tmpdir}/match_num > /dev/null 2>&1')
                
                # Clean up the OCR output
                with open(f"{tmpdir}/match_num.txt", "r") as f:
                    match_text = f.read()
                    
                match_text = re.sub(r'[^\x00-\x7F]+', '', match_text).replace('\n', '').replace('\f', '')
                
                with open(f"{tmpdir}/match_num.txt", "w") as f:
                    f.write(match_text)
                
                previous_match_string = current_match_string
                
                with open(f"{tmpdir}/match_num.txt", "r") as f:
                    current_match_string = f.read().strip()
                
                print(f"Current match: {current_match_string}")
                
                # Compare the two frames to see if it's a new match
                if current_match_string != previous_match_string:
                    break
        
        print(f"New match at time {curr_frame_time}: {current_match_string}")
        
        diff_time = curr_frame_time - last_split_frame_time
        video_number += 1
        
        # Start a background process to encode the video segment
        subprocess.Popen(
            f'ffmpeg -hide_banner -ss {last_split_frame_time} -i {video_filename} -t {diff_time} -vcodec copy -acodec copy "{video_number} - {previous_match_string}.mp4"',
            shell=True
        )
        
        last_split_frame_time = curr_frame_time


if __name__ == "__main__":
    main()