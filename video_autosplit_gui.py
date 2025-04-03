#!/usr/bin/env python3
"""
Video AutoSplit GUI Extension
An optional GUI for Video AutoSplit allowing parameter configuration and config file management.
"""

import sys
import os
import json
import argparse
import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import threading
import queue
import re

# Import the main VideoAutoSplitter class
try:
    from video_autosplit import VideoAutoSplitter, logger
except ImportError:
    # If running standalone, try to import from current directory
    import importlib.util
    spec = importlib.util.spec_from_file_location("video_autosplit", 
                                                 os.path.join(os.path.dirname(__file__), "video-autosplit.py"))
    video_autosplit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(video_autosplit)
    VideoAutoSplitter = video_autosplit.VideoAutoSplitter
    logger = video_autosplit.logger


class RedirectText:
    """Class to redirect stdout/stderr to a tkinter Text widget"""
    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.queue = queue.Queue()
        self.update_timer = None
        
    def write(self, string):
        self.queue.put(string)
        if self.update_timer is None:
            self.update_timer = self.text_widget.after(100, self.update_text)
    
    def update_text(self):
        while not self.queue.empty():
            text = self.queue.get_nowait()
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, text)
            self.text_widget.see(tk.END)
            self.text_widget.configure(state='disabled')
        self.update_timer = None
    
    def flush(self):
        pass


class VideoAutoSplitGUI(tk.Tk):
    """GUI for Video AutoSplit tool"""
    
    DEFAULT_CONFIG = {
        "url": "",
        "output_dir": ".",
        "frame_increment": 5.0,
        "max_attempts": 30,
        "template": "",
        "search_string": "CH",
        "overlay_area": "0.0,0.77,0.1,0.055",
        "match_area": "0.53,0.773148148,0.3,0.05"
    }
    
    def __init__(self):
        super().__init__()
        
        self.title("Video AutoSplit GUI")
        self.geometry("800x600")
        self.minsize(700, 500)
        
        # Set up the main frame with padding
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create a style
        style = ttk.Style()
        style.configure("TLabel", padding=(0, 5))
        style.configure("TButton", padding=5)
        style.configure("TEntry", padding=3)
        
        # Initialize configuration
        self.config = self.DEFAULT_CONFIG.copy()
        self.config_file_path = None
        self.running = False
        self.splitter_thread = None
        
        # Create widgets
        self.create_widgets(main_frame)
        
        # Load default values into GUI
        self.load_config_to_gui()
        
        # Set up protocol for window closing
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
    def create_widgets(self, parent):
        """Create all GUI widgets"""
        # Create notebook (tabbed interface)
        notebook = ttk.Notebook(parent)
        
        # Config tab
        config_frame = ttk.Frame(notebook, padding="10")
        notebook.add(config_frame, text="Configuration")
        
        # Console tab
        console_frame = ttk.Frame(notebook, padding="10")
        notebook.add(console_frame, text="Console")
        
        # Help tab
        help_frame = ttk.Frame(notebook, padding="10")
        notebook.add(help_frame, text="Help")
        
        notebook.pack(fill=tk.BOTH, expand=True)
        
        # Configuration tab
        self.create_config_widgets(config_frame)
        
        # Console tab
        self.create_console_widgets(console_frame)
        
        # Help tab
        self.create_help_widgets(help_frame)
        
    def create_config_widgets(self, parent):
        """Create configuration widgets"""
        # Create frames for organization
        url_frame = ttk.Frame(parent)
        url_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(url_frame, text="Stream URL:").pack(side=tk.LEFT)
        self.url_entry = ttk.Entry(url_frame)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Output directory
        output_frame = ttk.Frame(parent)
        output_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(output_frame, text="Output Directory:").pack(side=tk.LEFT)
        self.output_entry = ttk.Entry(output_frame)
        self.output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        ttk.Button(output_frame, text="Browse...", command=self.browse_output).pack(side=tk.LEFT, padx=(5, 0))
        
        # Frame increment and max attempts
        timing_frame = ttk.Frame(parent)
        timing_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(timing_frame, text="Frame Increment (seconds):").pack(side=tk.LEFT)
        self.frame_increment_var = tk.StringVar()
        self.frame_increment_entry = ttk.Entry(timing_frame, width=10, textvariable=self.frame_increment_var)
        self.frame_increment_entry.pack(side=tk.LEFT, padx=(5, 20))
        
        ttk.Label(timing_frame, text="Max Attempts:").pack(side=tk.LEFT)
        self.max_attempts_var = tk.StringVar()
        self.max_attempts_entry = ttk.Entry(timing_frame, width=10, textvariable=self.max_attempts_var)
        self.max_attempts_entry.pack(side=tk.LEFT, padx=(5, 0))
        
        # Template and search string
        detection_frame = ttk.Frame(parent)
        detection_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(detection_frame, text="Template Image:").pack(side=tk.LEFT)
        self.template_entry = ttk.Entry(detection_frame)
        self.template_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        ttk.Button(detection_frame, text="Browse...", command=self.browse_template).pack(side=tk.LEFT, padx=(5, 0))
        
        search_frame = ttk.Frame(parent)
        search_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(search_frame, text="Fallback Search String:").pack(side=tk.LEFT)
        self.search_string_var = tk.StringVar()
        self.search_string_entry = ttk.Entry(search_frame, textvariable=self.search_string_var)
        self.search_string_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Area coordinates
        ttk.Label(parent, text="Overlay Area (x,y,width,height):").pack(anchor=tk.W, pady=(10, 0))
        self.overlay_area_var = tk.StringVar()
        self.overlay_area_entry = ttk.Entry(parent, textvariable=self.overlay_area_var)
        self.overlay_area_entry.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(parent, text="Match Number Area (x,y,width,height):").pack(anchor=tk.W, pady=(5, 0))
        self.match_area_var = tk.StringVar()
        self.match_area_entry = ttk.Entry(parent, textvariable=self.match_area_var)
        self.match_area_entry.pack(fill=tk.X, pady=(0, 5))
        
        # Config buttons
        config_buttons_frame = ttk.Frame(parent)
        config_buttons_frame.pack(fill=tk.X, pady=10)
        
        ttk.Button(config_buttons_frame, text="Load Config", command=self.load_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(config_buttons_frame, text="Save Config", command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(config_buttons_frame, text="Reset to Default", command=self.reset_to_default).pack(side=tk.LEFT, padx=5)
        
        # Bottom buttons
        bottom_frame = ttk.Frame(parent)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=10)
        
        self.start_button = ttk.Button(bottom_frame, text="Start Processing", command=self.start_processing)
        self.start_button.pack(side=tk.RIGHT, padx=5)
        
        self.stop_button = ttk.Button(bottom_frame, text="Stop", command=self.stop_processing, state=tk.DISABLED)
        self.stop_button.pack(side=tk.RIGHT, padx=5)
        
    def create_console_widgets(self, parent):
        """Create console output widgets"""
        # Console output
        ttk.Label(parent, text="Console Output:").pack(anchor=tk.W)
        
        # Create text widget with scrollbar
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.console_text = tk.Text(frame, wrap=tk.WORD, yscrollcommand=scrollbar.set, height=20)
        self.console_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.console_text.configure(state='disabled')
        
        scrollbar.config(command=self.console_text.yview)
        
        # Redirect standard output and error
        self.redirect = RedirectText(self.console_text)
        
    def create_help_widgets(self, parent):
        """Create help information widgets"""
        help_text = """
Video AutoSplit Tool - Help

This tool automatically splits FTC competition video streams into separate match videos.

Requirements:
- The video has the standard FTC stream overlay (showing match timers)
- yt-dlp is installed
- ffmpeg is installed (with ffprobe)
- tesseract is installed
- imagemagick is installed (for the "convert" command)

Parameters:
- Stream URL: URL of the Twitch or YouTube video to process
- Output Directory: Where the split videos will be saved
- Frame Increment: Time between frame checks (in seconds)
- Max Attempts: Maximum attempts to check for new data before quitting
- Template Image: Optional template image for overlay detection
- Fallback Search String: Text to search for in the overlay (default: "CH")
- Overlay Area: Coordinates to check for overlay presence (x,y,width,height as ratios)
- Match Number Area: Coordinates to extract match number (x,y,width,height as ratios)

Config Files:
You can save your settings to a config file for future use. These config files
can also be used with the command-line version using the --config parameter.

Example: python video-autosplit.py --config my_config.json
        """
        
        # Create text widget with scrollbar for help text
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        help_text_widget = tk.Text(frame, wrap=tk.WORD, yscrollcommand=scrollbar.set)
        help_text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        help_text_widget.insert(tk.END, help_text)
        help_text_widget.configure(state='disabled')
        
        scrollbar.config(command=help_text_widget.yview)
        
    def browse_output(self):
        """Open file dialog to select output directory"""
        directory = filedialog.askdirectory(
            initialdir=self.output_entry.get() if self.output_entry.get() else ".",
            title="Select Output Directory"
        )
        if directory:
            self.output_entry.delete(0, tk.END)
            self.output_entry.insert(0, directory)
            
    def browse_template(self):
        """Open file dialog to select template image"""
        filetypes = [
            ("Image files", "*.png *.jpg *.jpeg *.bmp"),
            ("All files", "*.*")
        ]
        file = filedialog.askopenfilename(
            initialdir=os.path.dirname(self.template_entry.get()) if self.template_entry.get() else ".",
            title="Select Template Image",
            filetypes=filetypes
        )
        if file:
            self.template_entry.delete(0, tk.END)
            self.template_entry.insert(0, file)
            
    def load_config(self):
        """Load configuration from a JSON file"""
        filetypes = [
            ("JSON files", "*.json"),
            ("All files", "*.*")
        ]
        file = filedialog.askopenfilename(
            initialdir="." if not self.config_file_path else os.path.dirname(self.config_file_path),
            title="Load Configuration",
            filetypes=filetypes
        )
        if file:
            try:
                with open(file, 'r') as f:
                    config = json.load(f)
                    
                # Validate the loaded config
                required_keys = set(self.DEFAULT_CONFIG.keys())
                if not all(key in config for key in required_keys):
                    messagebox.showerror("Invalid Config", 
                                        "The selected file is missing required configuration parameters.")
                    return
                    
                self.config = config
                self.config_file_path = file
                self.load_config_to_gui()
                messagebox.showinfo("Config Loaded", f"Configuration loaded from {file}")
                
            except (json.JSONDecodeError, IOError) as e:
                messagebox.showerror("Error Loading Config", f"Failed to load configuration: {str(e)}")
                
    def save_config(self):
        """Save current configuration to a JSON file"""
        # Update config from GUI
        self.update_config_from_gui()
        
        filetypes = [
            ("JSON files", "*.json"),
            ("All files", "*.*")
        ]
        file = filedialog.asksaveasfilename(
            initialdir="." if not self.config_file_path else os.path.dirname(self.config_file_path),
            title="Save Configuration",
            filetypes=filetypes,
            defaultextension=".json"
        )
        if file:
            try:
                with open(file, 'w') as f:
                    json.dump(self.config, f, indent=4)
                    
                self.config_file_path = file
                messagebox.showinfo("Config Saved", f"Configuration saved to {file}")
                
            except IOError as e:
                messagebox.showerror("Error Saving Config", f"Failed to save configuration: {str(e)}")
                
    def reset_to_default(self):
        """Reset configuration to default values"""
        if messagebox.askyesno("Confirm Reset", "Are you sure you want to reset to default values?"):
            self.config = self.DEFAULT_CONFIG.copy()
            self.load_config_to_gui()
            
    def load_config_to_gui(self):
        """Load configuration values into GUI widgets"""
        self.url_entry.delete(0, tk.END)
        self.url_entry.insert(0, self.config["url"])
        
        self.output_entry.delete(0, tk.END)
        self.output_entry.insert(0, self.config["output_dir"])
        
        self.frame_increment_var.set(str(self.config["frame_increment"]))
        self.max_attempts_var.set(str(self.config["max_attempts"]))
        
        self.template_entry.delete(0, tk.END)
        self.template_entry.insert(0, self.config["template"])
        
        self.search_string_var.set(self.config["search_string"])
        self.overlay_area_var.set(self.config["overlay_area"])
        self.match_area_var.set(self.config["match_area"])
        
    def update_config_from_gui(self):
        """Update configuration from GUI widgets"""
        # Validate numeric inputs
        try:
            frame_increment = float(self.frame_increment_var.get())
            max_attempts = int(self.max_attempts_var.get())
            
            # Validate coordinate formats
            overlay_area = self.overlay_area_var.get()
            match_area = self.match_area_var.get()
            
            for area in [overlay_area, match_area]:
                coords = area.split(',')
                if len(coords) != 4:
                    raise ValueError(f"Area coordinates must be exactly 4 values: {area}")
                for coord in coords:
                    float(coord)  # Validate as float
                    
        except ValueError as e:
            messagebox.showerror("Invalid Input", f"Invalid value detected: {str(e)}")
            return False
            
        # Update config
        self.config["url"] = self.url_entry.get()
        self.config["output_dir"] = self.output_entry.get()
        self.config["frame_increment"] = frame_increment
        self.config["max_attempts"] = max_attempts
        self.config["template"] = self.template_entry.get()
        self.config["search_string"] = self.search_string_var.get()
        self.config["overlay_area"] = self.overlay_area_var.get()
        self.config["match_area"] = self.match_area_var.get()
        
        return True
        
    def start_processing(self):
        """Start video processing"""
        # Update config from GUI
        if not self.update_config_from_gui():
            return
            
        # Validate URL
        if not self.config["url"]:
            messagebox.showerror("Missing URL", "Please enter a stream URL")
            return
            
        # Confirm output directory exists
        output_dir = Path(self.config["output_dir"])
        output_dir.mkdir(exist_ok=True, parents=True)
        
        # Prepare for processing
        self.console_text.configure(state='normal')
        self.console_text.delete(1.0, tk.END)
        self.console_text.configure(state='disabled')
        
        # Redirect stdout and stderr
        self.old_stdout = sys.stdout
        self.old_stderr = sys.stderr
        sys.stdout = self.redirect
        sys.stderr = self.redirect
        
        # Make sure logging also outputs to our redirected stdout
        log_handler = logging.StreamHandler(sys.stdout)
        log_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        logger.addHandler(log_handler)
        # logger.setLevel(logging.INFO)
        
        # Update UI state
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.running = True
        
        # Parse area coordinates
        overlay_area_coords = tuple(float(x) for x in self.config["overlay_area"].split(','))
        match_area_coords = tuple(float(x) for x in self.config["match_area"].split(','))
        
        # Create and run the splitter in a separate thread
        self.splitter = VideoAutoSplitter(
            self.config["url"],
            output_dir=self.config["output_dir"],
            frame_increment=self.config["frame_increment"],
            max_attempts=self.config["max_attempts"],
            template_path=self.config["template"] if self.config["template"] else None,
            fallback_search_string=self.config["search_string"],
            overlay_area_coords=overlay_area_coords,
            match_number_area_coords=match_area_coords
        )
        
        self.splitter_thread = threading.Thread(target=self.run_processing)
        self.splitter_thread.daemon = True
        self.splitter_thread.start()
        
    def run_processing(self):
        """Run video processing in thread"""
        try:
            success = self.splitter.process()
            if success:
                print("\nProcessing completed successfully!")
            else:
                print("\nProcessing completed with errors or was stopped.")
        except Exception as e:
            print(f"\nError during processing: {e}")
        finally:
            self.after(100, self.processing_completed)
        
    def processing_completed(self):
        """Handle completion of processing"""
        # Restore stdout and stderr
        sys.stdout = self.old_stdout
        sys.stderr = self.old_stderr
        
        # Remove the added logging handler
        for handler in logger.handlers[:]:
            if isinstance(handler, logging.StreamHandler) and handler.stream == self.redirect:
                logger.removeHandler(handler)
        
        # Update UI state
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.running = False
        
    def stop_processing(self):
        """Stop video processing"""
        if self.running and self.splitter:
            logger.info("User requested to stop processing")
            self.splitter.new_data_attempts = self.splitter.max_attempts + 1  # Force exit
            
            # Update UI state
            self.stop_button.configure(state=tk.DISABLED)
            
    def on_close(self):
        """Handle window closing"""
        if self.running:
            if messagebox.askyesno("Confirm Exit", "Processing is still running. Are you sure you want to exit?"):
                self.stop_processing()
                self.after(500, self.destroy)  # Give some time for cleanup
        else:
            self.destroy()


# Function to modify the main file's argument parser to accept config file
def update_argument_parser(original_parser):
    """Add config file option to the original argument parser"""
    original_parser.add_argument("--config", "-c", help="Path to configuration JSON file")
    return original_parser


def load_config_from_file(config_file):
    """Load configuration from JSON file"""
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load config file: {e}")
        return None


def main():
    """Main function for GUI mode"""
    # If no arguments, launch GUI
    if len(sys.argv) == 1:
        app = VideoAutoSplitGUI()
        app.mainloop()
    else:
        # In CLI mode, add support for config file
        parser = argparse.ArgumentParser(description="Video AutoSplit tool for FTC competition videos")
        parser.add_argument("url", nargs="?", help="URL of the stream to process")
        parser.add_argument("--config", "-c", help="Path to configuration JSON file")
        parser.add_argument("--output-dir", "-o", help="Output directory for video segments", default=".")
        parser.add_argument("--frame-increment", "-f", type=float, help="Time increment between frames to check (seconds)", default=5)
        parser.add_argument("--max-attempts", "-m", type=int, help="Maximum attempts to check for new data before quitting", default=30)
        parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
        parser.add_argument("--template", "-t", help="Path to overlay template image", default=None)
        parser.add_argument("--search-string", "-s", help="Fallback search string for OCR detection", default="CH")
        parser.add_argument("--overlay-area", help="Overlay area coordinates as x,y,width,height ratios", default="0.0,0.77,0.1,0.055")
        parser.add_argument("--match-area", help="Match number area coordinates as x,y,width,height ratios", default="0.53,0.773148148,0.3,0.05")
        parser.add_argument("--gui", action="store_true", help="Launch GUI mode")

        args = parser.parse_args()
        
        # Launch GUI if requested
        if args.gui:
            app = VideoAutoSplitGUI()
            app.mainloop()
            return
            
        # Handle config file
        if args.config:
            config = load_config_from_file(args.config)
            if not config:
                logger.error("Failed to load config file. Exiting.")
                sys.exit(1)
                
            # Use config values but allow command line arguments to override
            for key, value in config.items():
                if key == "url" and not args.url:
                    args.url = value
                elif key == "output_dir" and args.output_dir == ".":
                    args.output_dir = value
                elif key == "frame_increment" and args.frame_increment == 5:
                    args.frame_increment = value
                elif key == "max_attempts" and args.max_attempts == 30:
                    args.max_attempts = value
                elif key == "template" and args.template is None:
                    args.template = value
                elif key == "search_string" and args.search_string == "CH":
                    args.search_string = value
                elif key == "overlay_area" and args.overlay_area == "0.0,0.77,0.1,0.055":
                    args.overlay_area = value
                elif key == "match_area" and args.match_area == "0.53,0.773148148,0.3,0.05":
                    args.match_area = value
        
        # Call the original main function from video_autosplit with updated args
        # This requires modifying the original main or re-implementing it here
        
        # For now, we'll just print the effective configuration
        logger.info("Effective configuration:")
        logger.info(f"URL: {args.url}")
        logger.info(f"Output directory: {args.output_dir}")
        logger.info(f"Frame increment: {args.frame_increment}")
        logger.info(f"Max attempts: {args.max_attempts}")
        logger.info(f"Template: {args.template}")
        logger.info(f"Search string: {args.search_string}")
        logger.info(f"Overlay area: {args.overlay_area}")
        logger.info(f"Match area: {args.match_area}")
        
        # Call video_autosplit.main() with the parsed args
        # This would normally be the entry point to the original functionality
        video_autosplit.main()


if __name__ == "__main__":
    main()