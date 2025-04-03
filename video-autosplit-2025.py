#!/usr/bin/env python3
"""
Video AutoSplit, courtesy of FTC #10298 Brain Stormz
Converted to Python from original bash script with improvements

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
import logging
from pathlib import Path
import threading
import tempfile
import cv2
import numpy as np


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger("video-autosplit")


class VideoAutoSplitter:
    """Main class for handling video auto-splitting functionality"""
    
    def __init__(self, stream_url, output_dir=None, frame_increment=5, max_attempts=30):
        """Initialize the video splitter with parameters"""
        self.stream_url = stream_url
        self.output_dir = Path(output_dir) if output_dir else Path.cwd()
        self.frame_increment = frame_increment
        self.max_attempts = max_attempts
        
        # Create unique temp directory
        self.tmpdir = Path(tempfile.gettempdir()) / f"video-autosplit-{uuid.uuid4()}"
        self.tmpdir.mkdir(exist_ok=True)
        
        # Initialize state variables
        self.video_number = 0
        self.video_filename = ""
        self.curr_frame_time = 0
        self.last_split_frame_time = 0
        self.current_match_string = "Intro"
        self.previous_match_string = "Intro"
        self.frame_width = 0
        self.frame_height = 0
        self.stream_fps = 0
        self.stream_length = 0
        self.last_fragment = 0
        self.new_data_attempts = 0
        
        # Fix nasty slowdown of tesseract OCR when multiple processes running
        os.environ["OMP_THREAD_LIMIT"] = "1"
        
        # Track encoder processes
        self.encoder_processes = []

    def execute_command(self, command, capture_output=True, shell=False):
        """Execute a shell command and return its output."""
        try:
            if isinstance(command, str) and not shell:
                # Split command string into arguments
                command = command.split()
            
            if capture_output:
                result = subprocess.run(
                    command, 
                    shell=shell,
                    check=True, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE,
                    text=True
                )
                return result.stdout.strip()
            else:
                subprocess.run(command, shell=shell, check=True)
                return None
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if hasattr(e, 'stderr') else str(e)
            logger.error(f"Error executing command: {command}")
            logger.error(f"Error message: {error_msg}")
            return None

    def live_download(self):
        """Download the stream using yt-dlp."""
        logger.info("Downloading stream content...")
        
        # Download whatever there currently is to download, resuming if applicable
        download_output_file = self.tmpdir / "download-output.txt"
        
        # Using a list of arguments is safer than shell=True, but yt-dlp with piping
        # requires shell=True, so we need to be careful with the input
        if '|' in self.stream_url or ';' in self.stream_url or '&' in self.stream_url:
            logger.error("Invalid URL containing shell metacharacters")
            sys.exit(1)
            
        command = (
            f'yt-dlp -f b --verbose --continue --hls-prefer-native '
            f'--parse-meta ":(?P<is_live>)" --fixup "never" "{self.stream_url}" '
            f'-o "stream.%(ext)s" 2>&1 | tee "{download_output_file}"'
        )
        
        self.execute_command(command, capture_output=False, shell=True)
        
        logger.info("Download complete, processing results...")
        time.sleep(2)
        
        # Get the last fragment number from the download output
        try:
            with open(download_output_file, "r") as f:
                download_output = f.read()
            
            last_fragment = 0
            fragment_match = re.search(r'Total fragments: (\d+)', download_output)
            if fragment_match:
                last_fragment = int(fragment_match.group(1))
                self.last_fragment = last_fragment
        except Exception as e:
            logger.warning(f"Failed to read download output: {e}")
        
        video_filename = ""
        ytdl_state_file = Path("./stream.mp4.ytdl")
        
        if ytdl_state_file.exists():
            logger.info("Download state file exists, not overwriting")
            video_filename = "stream.mp4.part"
        else:
            if self.last_fragment > 0:
                logger.info(f"Using updated last fragment value: {self.last_fragment}")
                
                # Create ytdl state file
                ytdl_state = {
                    "downloader": {
                        "current_fragment": {"index": self.last_fragment},
                        "extra_state": {}
                    }
                }
                
                with open(ytdl_state_file, "w") as f:
                    json.dump(ytdl_state, f)
                
                if Path("stream.mp4").exists():
                    shutil.move("stream.mp4", "stream.mp4.part")
                
                video_filename = "stream.mp4.part"
            else:
                logger.info("No fragment value available, using default filename")
                video_filename = "stream.mp4"
        
        logger.info("File processing complete")
        return video_filename

    def analyze_frame(self, frame_time):
        """Extract and analyze a frame from the video at the given time."""
        current_frame_path = self.tmpdir / "current.png"
        
        # Extract current frame for analysis
        ffmpeg_cmd = [
            'ffmpeg', '-hide_banner', '-nostats', '-loglevel', 'warning', 
            '-y', '-ss', str(frame_time), '-i', self.video_filename, 
            '-update', '1', '-frames:v', '1', '-q:v', '2', str(current_frame_path)
        ]
        
        self.execute_command(ffmpeg_cmd)
        
        # Check if the frame extraction was successful
        if not current_frame_path.exists():
            logger.warning(f"Failed to extract frame at {frame_time}")
            return False, "", ""
            
        # Process the frame using OpenCV for better OCR results
        try:
            # Read the image
            img = cv2.imread(str(current_frame_path))
            if img is None:
                logger.warning("Failed to read frame image")
                return False, "", ""
                
            # Calculate areas for OCR
            overlay_area = self.calculate_area(0.0, 0.77, 0.1, 0.055)
            match_number_area = self.calculate_area(0.53, 0.773148148, 0.3, 0.05)
            
            # Extract regions of interest
            overlay_roi = img[
                int(overlay_area[1]):int(overlay_area[1] + overlay_area[3]), 
                int(overlay_area[0]):int(overlay_area[0] + overlay_area[2])
            ]
            
            # Save the overlay ROI for OCR
            overlay_check_image = self.tmpdir / "overlay_check.png"
            cv2.imwrite(str(overlay_check_image), overlay_roi)
            
            # Perform OCR on overlay
            overlay_text_file = self.tmpdir / "overlay_check.txt"
            if overlay_text_file.exists():
                overlay_text_file.unlink()
                
            self.execute_command(['tesseract', str(overlay_check_image), 
                                str(overlay_text_file).replace('.txt', '')])
            
            # Check if overlay contains "CH" indicating the overlay is present
            try:
                with open(overlay_text_file, "r") as f:
                    overlay_text = f.read()
                    
                overlay_text = re.sub(r'[^\x00-\x7F]+', '', overlay_text).replace('\f', '')
                
                if "CH" not in overlay_text:
                    return False, "", ""
                    
                # Overlay is present, extract match number area
                match_roi = img[
                    int(match_number_area[1]):int(match_number_area[1] + match_number_area[3]), 
                    int(match_number_area[0]):int(match_number_area[0] + match_number_area[2])
                ]
                
                # Pre-process for better OCR
                # Convert to grayscale
                gray = cv2.cvtColor(match_roi, cv2.COLOR_BGR2GRAY)
                # Apply threshold to get black and white image
                _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
                
                match_number_image = self.tmpdir / "match_number_check.png"
                cv2.imwrite(str(match_number_image), thresh)
                
                match_text_file = self.tmpdir / "match_num.txt"
                self.execute_command(['tesseract', str(match_number_image), 
                                    str(match_text_file).replace('.txt', '')])
                
                # Read and clean up the match text
                with open(match_text_file, "r") as f:
                    match_text = f.read()
                    
                match_text = re.sub(r'[^\x00-\x7F]+', '', match_text).replace('\n', '').replace('\f', '')
                match_text = match_text.strip()
                
                return True, overlay_text, match_text
                
            except Exception as e:
                logger.warning(f"Error in OCR processing: {e}")
                return False, "", ""
                
        except Exception as e:
            logger.warning(f"Error in frame analysis: {e}")
            return False, "", ""

    def calculate_area(self, x_ratio, y_ratio, width_ratio, height_ratio):
        """Calculate the area for extraction based on frame dimensions."""
        x = x_ratio * self.frame_width
        y = y_ratio * self.frame_height
        width = width_ratio * self.frame_width
        height = height_ratio * self.frame_height
        return (x, y, width, height)

    def split_video(self, start_time, duration, output_file):
        """Split the video and encode the segment."""
        logger.info(f"Encoding segment: {output_file}")
        
        cmd = [
            'ffmpeg', '-hide_banner', '-ss', str(start_time), 
            '-i', self.video_filename, '-t', str(duration),
            '-vcodec', 'copy', '-acodec', 'copy', output_file
        ]
        
        # Run encoding in a separate thread to avoid blocking
        encoder_thread = threading.Thread(
            target=self.execute_command,
            args=(cmd,),
            kwargs={'capture_output': False}
        )
        encoder_thread.start()
        self.encoder_processes.append(encoder_thread)
        
        # Clean up completed encoder processes
        self.encoder_processes = [p for p in self.encoder_processes if p.is_alive()]

    def get_video_info(self):
        """Get information about the video file."""
        try:
            # Get video dimensions
            width_cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', 
                        '-show_entries', 'stream=width', '-of', 'default=nw=1:nk=1', 
                        self.video_filename]
            height_cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', 
                        '-show_entries', 'stream=height', '-of', 'default=nw=1:nk=1', 
                        self.video_filename]
            
            self.frame_width = int(self.execute_command(width_cmd))
            self.frame_height = int(self.execute_command(height_cmd))
            logger.info(f"Frame dimensions: {self.frame_width}x{self.frame_height}")
            
            # Get stream FPS
            fps_cmd = ['ffprobe', '-hide_banner', '-show_streams', self.video_filename]
            fps_output = self.execute_command(fps_cmd)
            fps_match = re.search(r'(\d+\.?\d*) fps', fps_output)
            self.stream_fps = float(fps_match.group(1)) if fps_match else 30.0
            
            # Get stream length
            length_cmd = ['ffprobe', '-i', self.video_filename, '-show_entries', 
                        'format=duration', '-v', 'quiet', '-of', 'csv=p=0']
            self.stream_length = float(self.execute_command(length_cmd))
            
            logger.info(f"Video info - FPS: {self.stream_fps}, Length: {self.stream_length} seconds")
            return True
        except Exception as e:
            logger.error(f"Failed to get video info: {e}")
            return False

    def process(self):
        """Main processing loop."""
        try:
            # First download
            self.video_filename = self.live_download()
            if not self.video_filename:
                logger.error("Failed to download video")
                return False
                
            # Get video information
            if not self.get_video_info():
                return False
            
            # Main processing loop
            while True:
                # Inner loop for finding new matches
                while True:
                    # Increment frame time
                    self.curr_frame_time += self.frame_increment
                    
                    # Check if we need more video
                    while self.curr_frame_time > self.stream_length:
                        logger.info("Reached end of current video, checking for more content...")
                        self.video_filename = self.live_download()
                        
                        # Update stream length
                        length_cmd = ['ffprobe', '-i', self.video_filename, '-show_entries', 
                                    'format=duration', '-v', 'quiet', '-of', 'csv=p=0']
                        try:
                            self.stream_length = float(self.execute_command(length_cmd))
                        except:
                            logger.warning("Failed to get updated stream length")
                            
                        # Update number of new data attempts
                        self.new_data_attempts += 1
                        logger.info(f"Attempts to get new data: {self.new_data_attempts}")
                        
                        if self.new_data_attempts > self.max_attempts:
                            # Stream appears to have ended
                            logger.info("Stream appears to have ended, processing final clip")
                            diff_time = self.curr_frame_time - self.last_split_frame_time
                            self.video_number += 1
                            output_file = self.output_dir / f"{self.video_number} - {self.current_match_string}.mp4"
                            self.split_video(self.last_split_frame_time, diff_time, str(output_file))
                            
                            # Wait for all encoder processes to complete
                            for p in self.encoder_processes:
                                if p.is_alive():
                                    p.join()
                                    
                            logger.info("Processing complete!")
                            return True
                    
                    # Reset attempts counter
                    self.new_data_attempts = 0
                    
                    # Analyze current frame
                    logger.info(f"Analyzing frame at {self.curr_frame_time}")
                    overlay_present, overlay_text, match_text = self.analyze_frame(self.curr_frame_time)
                    
                    if overlay_present:
                        logger.info(f"Overlay present at {self.curr_frame_time}, Match: {match_text}")
                        
                        # Check if it's a new match
                        if match_text and match_text != self.current_match_string:
                            self.previous_match_string = self.current_match_string
                            self.current_match_string = match_text
                            logger.info(f"New match detected: {match_text}")
                            break
                
                # Process the video segment for the previous match
                logger.info(f"Processing segment for match: {self.previous_match_string}")
                diff_time = self.curr_frame_time - self.last_split_frame_time
                self.video_number += 1
                
                # Create output filename
                output_file = self.output_dir / f"{self.video_number} - {self.previous_match_string}.mp4"
                
                # Split video
                self.split_video(self.last_split_frame_time, diff_time, str(output_file))
                
                # Update last split time
                self.last_split_frame_time = self.curr_frame_time
                
        except KeyboardInterrupt:
            logger.info("Process interrupted by user")
            # Wait for existing encoder processes to complete
            for p in self.encoder_processes:
                if p.is_alive():
                    p.join()
            return False
        except Exception as e:
            logger.error(f"Error in main process: {e}")
            return False
        finally:
            # Clean up temp directory
            if self.tmpdir.exists():
                shutil.rmtree(self.tmpdir)


def main():
    parser = argparse.ArgumentParser(description="Video AutoSplit tool for FTC competition videos")
    parser.add_argument("url", nargs="?", help="URL of the stream to process")
    parser.add_argument("--output-dir", "-o", help="Output directory for video segments", default=".")
    parser.add_argument("--frame-increment", "-f", type=float, help="Time increment between frames to check (seconds)", default=5)
    parser.add_argument("--max-attempts", "-m", type=int, help="Maximum attempts to check for new data before quitting", default=30)
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()
    
    # Set log level
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Print header
    print("""----------------------------------------------------
Video AutoSplit, courtesy of FTC #10298 Brain Stormz
----------------------------------------------------
""")
    
    if not args.url:
        parser.print_help()
        sys.exit(1)
    
    # Check for required dependencies
    dependencies = ['yt-dlp', 'ffmpeg', 'ffprobe', 'tesseract', 'convert']
    missing_deps = []
    
    for dep in dependencies:
        try:
            subprocess.run(['which', dep], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError:
            missing_deps.append(dep)
    
    if missing_deps:
        logger.error(f"Missing dependencies: {', '.join(missing_deps)}")
        logger.error("Please install all required dependencies before running this script.")
        sys.exit(1)
    
    # Create output directory if it doesn't exist
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)
    
    # Create and run the splitter
    splitter = VideoAutoSplitter(
        args.url,
        output_dir=output_dir,
        frame_increment=args.frame_increment,
        max_attempts=args.max_attempts
    )
    
    success = splitter.process()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()