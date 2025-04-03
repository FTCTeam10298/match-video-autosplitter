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
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
import threading
import queue

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
        
        # Initialize configuration
        self.config = self.DEFAULT_CONFIG.copy()
        self.config_file_path = None
        self.running = False
        self.splitter_thread = None
        
        # Create widgets
        self.create_widgets()
        
        # Load default values into GUI
        self.load_config_to_gui()
        
        # Set up protocol for window closing
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
    def create_widgets(self):
        """Create all GUI widgets"""
        # Main frame with padding
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create notebook with tabs (like FTCSwitcherGUI)
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Configuration Settings tab
        config_frame = ttk.Frame(notebook, padding="10")
        notebook.add(config_frame, text="Configuration Settings")
        self.create_config_widgets(config_frame)
        
        # Visual Settings tab
        visual_frame = ttk.Frame(notebook, padding="10")
        notebook.add(visual_frame, text="Visual Settings")
        self.create_visual_settings_widgets(visual_frame)
        
        # Help tab
        help_frame = ttk.Frame(notebook, padding="10")
        notebook.add(help_frame, text="Help")
        self.create_help_widgets(help_frame)
        
        # Control & Log Frame (below notebook like in FTCSwitcherGUI)
        control_frame = ttk.Frame(main_frame, padding="10")
        control_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Control buttons
        button_frame = ttk.Frame(control_frame)
        button_frame.pack(fill=tk.X)
        
        self.start_button = ttk.Button(button_frame, text="Start Processing", command=self.start_processing)
        self.start_button.pack(side=tk.LEFT, padx=5)
        
        self.stop_button = ttk.Button(button_frame, text="Stop", command=self.stop_processing, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(button_frame, text="Save Config", command=self.save_config).pack(side=tk.LEFT, padx=5)
        
        # Status indicator (like in FTCSwitcherGUI)
        self.status_var = tk.StringVar(value="Status: Not Running 🔴")
        status_label = ttk.Label(button_frame, textvariable=self.status_var)
        status_label.pack(side=tk.RIGHT, padx=5)
        
        # Log area
        ttk.Label(control_frame, text="Log", font=("", 10, "bold")).pack(anchor=tk.W, pady=(10, 5))
        
        # Create scrolled text for log output
        self.console_text = scrolledtext.ScrolledText(control_frame, height=10)
        self.console_text.pack(fill=tk.BOTH, expand=True)
        self.console_text.config(state=tk.DISABLED)
        
        # Redirect standard output and error
        self.redirect = RedirectText(self.console_text)
        
    def create_config_widgets(self, parent):
        """Create configuration widgets"""
        # Source Settings
        ttk.Label(parent, text="Source Settings", font=("", 12, "bold")).grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))
        
        ttk.Label(parent, text="Stream URL:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.url_entry = ttk.Entry(parent, width=30)
        self.url_entry.grid(row=1, column=1, sticky=tk.W+tk.E, pady=2)
        
        ttk.Label(parent, text="Output Directory:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.output_entry = ttk.Entry(parent, width=30)
        self.output_entry.grid(row=2, column=1, sticky=tk.W+tk.E, pady=2)
        ttk.Button(parent, text="Browse...", command=self.browse_output).grid(row=2, column=2, sticky=tk.W, pady=2)
        
        # Process Settings
        ttk.Label(parent, text="Process Settings", font=("", 12, "bold")).grid(
            row=3, column=0, columnspan=2, sticky=tk.W, pady=(10, 5))
        
        ttk.Label(parent, text="Frame Increment (seconds):").grid(row=4, column=0, sticky=tk.W, pady=2)
        self.frame_increment_var = tk.StringVar()
        self.frame_increment_entry = ttk.Entry(parent, width=10, textvariable=self.frame_increment_var)
        self.frame_increment_entry.grid(row=4, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(parent, text="Max Attempts:").grid(row=5, column=0, sticky=tk.W, pady=2)
        self.max_attempts_var = tk.StringVar()
        self.max_attempts_entry = ttk.Entry(parent, width=10, textvariable=self.max_attempts_var)
        self.max_attempts_entry.grid(row=5, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(parent, text="Template Image:").grid(row=6, column=0, sticky=tk.W, pady=2)
        self.template_entry = ttk.Entry(parent, width=30)
        self.template_entry.grid(row=6, column=1, sticky=tk.W+tk.E, pady=2)
        ttk.Button(parent, text="Browse...", command=self.browse_template).grid(row=6, column=2, sticky=tk.W, pady=2)
        
        ttk.Label(parent, text="Fallback Search String:").grid(row=7, column=0, sticky=tk.W, pady=2)
        self.search_string_var = tk.StringVar()
        self.search_string_entry = ttk.Entry(parent, textvariable=self.search_string_var, width=30)
        self.search_string_entry.grid(row=7, column=1, sticky=tk.W, pady=2)
        
        # Config file buttons
        buttons_frame = ttk.Frame(parent)
        buttons_frame.grid(row=8, column=0, columnspan=3, sticky=tk.W, pady=10)
        
        ttk.Button(buttons_frame, text="Load Config", command=self.load_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Save Config As...", command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Reset to Default", command=self.reset_to_default).pack(side=tk.LEFT, padx=5)
        
    def create_visual_settings_widgets(self, parent):
        """Create visual settings widgets (separate tab like FTCSwitcherGUI)"""
        # Video Area Settings
        ttk.Label(parent, text="Video Area Settings", font=("", 12, "bold")).grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        # Area coordinates
        ttk.Label(parent, text="Overlay Area (x,y,width,height):").grid(
            row=1, column=0, sticky=tk.W, pady=2)
        self.overlay_area_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.overlay_area_var, width=30).grid(
            row=1, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(parent, text="Match Number Area (x,y,width,height):").grid(
            row=2, column=0, sticky=tk.W, pady=2)
        self.match_area_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.match_area_var, width=30).grid(
            row=2, column=1, sticky=tk.W, pady=2)
        
        # Visual preview (placeholder)
        preview_frame = ttk.LabelFrame(parent, text="Preview (Not Implemented)")
        preview_frame.grid(row=3, column=0, columnspan=2, sticky=tk.W+tk.E+tk.N+tk.S, pady=10)
        
        ttk.Label(preview_frame, text="A visual preview would show overlay\nand match number detection areas").pack(
            padx=20, pady=20)
        
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
        
        # Create scrolled text for help text
        help_text_widget = scrolledtext.ScrolledText(parent)
        help_text_widget.pack(fill=tk.BOTH, expand=True)
        help_text_widget.insert(tk.END, help_text)
        help_text_widget.configure(state='disabled')
        
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
                logger.info(f"Configuration loaded from {file}")
                
            except (json.JSONDecodeError, IOError) as e:
                messagebox.showerror("Error Loading Config", f"Failed to load configuration: {str(e)}")
                
    def save_config(self):
        """Save current configuration to a JSON file"""
        # Update config from GUI
        if not self.update_config_from_gui():
            return
        
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
                logger.info(f"Configuration saved to {file}")
                
            except IOError as e:
                messagebox.showerror("Error Saving Config", f"Failed to save configuration: {str(e)}")
                
    def reset_to_default(self):
        """Reset configuration to default values"""
        if messagebox.askyesno("Confirm Reset", "Are you sure you want to reset to default values?"):
            self.config = self.DEFAULT_CONFIG.copy()
            self.load_config_to_gui()
            logger.info("Configuration reset to defaults")
            
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
        
        # Clear log area
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
        
        # Update UI state
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.status_var.set("Status: Running 🟢")
        self.running = True
        
        logger.info("Processing started")
        
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
                logger.info("Processing completed successfully!")
            else:
                logger.warning("Processing completed with errors or was stopped.")
        except Exception as e:
            logger.error(f"Error during processing: {e}")
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
        self.status_var.set("Status: Not Running 🔴")
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