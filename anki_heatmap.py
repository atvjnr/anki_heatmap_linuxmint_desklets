#!/usr/bin/env python3
import os
import json
import sqlite3
import datetime
import subprocess
import gi

# Specify GTK version before importing
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango
import cairo

class AnkiHeatmapWidget:
    def __init__(self):
        # Create window WITH decorations for minimize and maximize
        self.window = Gtk.Window(title="Anki Heatmap")
        self.window.set_default_size(400, 200)
        self.window.set_decorated(True)  # Enable window decorations (minimize, maximize, close)
        self.window.set_keep_above(False)  # Do not keep widget above other windows (run in background)
        self.window.set_skip_taskbar_hint(False)  # Show in taskbar
        self.window.connect("destroy", Gtk.main_quit)
        
        # Make window movable by dragging
        self.window.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | 
                              Gdk.EventMask.BUTTON_RELEASE_MASK |
                              Gdk.EventMask.POINTER_MOTION_MASK)
        self.window.connect("button-press-event", self.on_press)
        self.window.connect("button-release-event", self.on_release)
        self.window.connect("motion-notify-event", self.on_motion)
        self.dragging = False
        
        # For tooltip handling
        self.tooltip_window = None
        self.hover_date = None
        self.hover_count = None
        
        # Set up UI
        self.setup_ui()
        
        # Initial data load
        self.load_anki_data()
        
        # Set up auto-refresh (every hour)
        GLib.timeout_add_seconds(3600, self.refresh_data)
        
        # Show all elements
        self.window.show_all()
    
    def on_press(self, widget, event):
        """Handle mouse button press for dragging the window"""
        if event.button == 1:  # Left mouse button
            self.dragging = True
            self.drag_x, self.drag_y = event.x, event.y
            
            # Hide tooltip if it exists
            self.hide_tooltip()
        return True
        
    def on_release(self, widget, event):
        """Handle mouse button release for dragging"""
        self.dragging = False
        return True
        
    def on_motion(self, widget, event):
        """Handle mouse motion for dragging the window"""
        if self.dragging:
            window_x, window_y = self.window.get_position()
            new_x = window_x + int(event.x - self.drag_x)
            new_y = window_y + int(event.y - self.drag_y)
            self.window.move(new_x, new_y)
        return True
    
    def setup_ui(self):
        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_box.set_margin_top(10)
        main_box.set_margin_bottom(10)
        main_box.set_margin_start(10)
        main_box.set_margin_end(10)
        self.window.add(main_box)
        
        # Header bar with title (removed close button since we have window decorations now)
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        
        # Title
        title_label = Gtk.Label()
        title_label.set_markup("<b>Anki Study Heatmap 2025</b>")
        title_label.set_halign(Gtk.Align.START)
        title_label.set_hexpand(True)
        header_box.pack_start(title_label, True, True, 0)
        
        main_box.pack_start(header_box, False, False, 0)
        
        # Date range label
        self.date_range_label = Gtk.Label()
        self.date_range_label.set_markup("<i>Loading date range...</i>")
        self.date_range_label.set_halign(Gtk.Align.START)
        main_box.pack_start(self.date_range_label, False, False, 0)
        
        # Heatmap drawing area
        self.heatmap_area = Gtk.DrawingArea()
        self.heatmap_area.set_size_request(380, 140)
        self.heatmap_area.connect("draw", self.draw_heatmap)
        
        # Add mouse motion event for tooltips
        self.heatmap_area.add_events(Gdk.EventMask.POINTER_MOTION_MASK | 
                                     Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.heatmap_area.connect("motion-notify-event", self.on_heatmap_motion)
        self.heatmap_area.connect("leave-notify-event", self.on_heatmap_leave)
        
        main_box.pack_start(self.heatmap_area, True, True, 0)
        
        # Stats label
        self.stats_label = Gtk.Label()
        self.stats_label.set_markup("<i>Loading statistics...</i>")
        main_box.pack_start(self.stats_label, False, False, 0)
        
        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        
        refresh_button = Gtk.Button.new_with_label("Refresh")
        refresh_button.connect("clicked", self.on_refresh_clicked)
        button_box.pack_start(refresh_button, True, True, 0)
        
        launch_button = Gtk.Button.new_with_label("Open Anki")
        launch_button.connect("clicked", self.on_launch_clicked)
        button_box.pack_start(launch_button, True, True, 0)
        
        # Add minimize to tray button
        minimize_button = Gtk.Button.new_with_label("Run in Background")
        minimize_button.connect("clicked", self.on_minimize_clicked)
        button_box.pack_start(minimize_button, True, True, 0)
        
        main_box.pack_start(button_box, False, False, 0)
    
    def on_minimize_clicked(self, button):
        """Handle minimize to background button click"""
        self.window.iconify()  # Minimize window
    
    def find_anki_collection(self):
        """Find the Anki collection file path"""
        home_dir = os.path.expanduser("~")
        
        # Common Anki collection paths
        possible_paths = [
            os.path.join(home_dir, ".local/share/Anki2/User 1/collection.anki2"),
            os.path.join(home_dir, "Documents/Anki/User 1/collection.anki2"),
            os.path.join(home_dir, "Anki/User 1/collection.anki2")
        ]
        
        # Try to find profile directories
        anki2_dir = os.path.join(home_dir, ".local/share/Anki2")
        if os.path.exists(anki2_dir):
            for profile_dir in os.listdir(anki2_dir):
                if os.path.isdir(os.path.join(anki2_dir, profile_dir)):
                    possible_paths.append(os.path.join(anki2_dir, profile_dir, "collection.anki2"))
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def load_anki_data(self):
        """Load review data from Anki database"""
        self.review_counts = {}
        
        collection_path = self.find_anki_collection()
        if not collection_path:
            self.stats_label.set_markup("<span color='red'>Anki collection not found</span>")
            return
        
        try:
            # Connect to Anki database
            conn = sqlite3.connect(f"file:{collection_path}?mode=ro", uri=True)  # Read-only mode
            cursor = conn.cursor()
            
            # Debug: Check if revlog table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='revlog'")
            if not cursor.fetchone():
                self.stats_label.set_markup("<span color='red'>Revlog table not found in Anki database</span>")
                conn.close()
                return
            
            # Get column info from revlog
            cursor.execute("PRAGMA table_info(revlog)")
            column_info = cursor.fetchall()
            column_names = [col[1] for col in column_info]
            
            # Get review history (last 365 days)
            today = int(datetime.datetime.now().strftime("%Y%m%d"))
            one_year_ago = today - 366
            
            # Anki 2.1.x uses 'id' column for timestamp
            if 'id' in column_names:
                cursor.execute("""
                    SELECT 
                        CAST(id/1000 AS INTEGER)/86400 AS day,
                        COUNT(*)
                    FROM revlog 
                    GROUP BY day
                    ORDER BY day
                """)
            else:
                # Fallback for other versions
                cursor.execute("""
                    SELECT 
                        day,
                        COUNT(*)
                    FROM revlog 
                    GROUP BY day
                    ORDER BY day
                """)
            
            # Process results
            for day_timestamp, count in cursor.fetchall():
                try:
                    # Convert from Anki epoch (seconds since 1970-01-01) to date string
                    date_obj = datetime.datetime.fromtimestamp(day_timestamp * 86400)
                    date_str = date_obj.strftime("%Y-%m-%d")
                    
                    # Filter for 2025 dates only
                    if date_str.startswith("2025-"):
                        self.review_counts[date_str] = count
                except (ValueError, OverflowError):
                    # Skip invalid timestamps
                    continue
            
            # Get streak information
            self.current_streak = self.calculate_current_streak()
            self.longest_streak = self.calculate_longest_streak()
            self.total_reviews = sum(self.review_counts.values())
            
            # Update stats label
            self.update_stats_label()
            # Update date range label
            self.update_date_range_label()
            
            conn.close()
            
        except Exception as e:
            self.stats_label.set_markup(f"<span color='red'>Error: {str(e)}</span>")
            import traceback
            traceback.print_exc()
    
    def calculate_current_streak(self):
        """Calculate current streak of consecutive study days"""
        if not self.review_counts:
            return 0
        
        streak = 0
        today = datetime.datetime.now().date()
        
        for i in range(0, 30):  # Check up to 30 days back
            check_date = today - datetime.timedelta(days=i)
            date_str = check_date.strftime("%Y-%m-%d")
            
            if date_str in self.review_counts and self.review_counts[date_str] > 0:
                streak += 1
            else:
                break
                
        return streak
    
    def calculate_longest_streak(self):
        """Calculate longest streak of consecutive study days"""
        if not self.review_counts:
            return 0
        
        # Sort dates
        dates = sorted(self.review_counts.keys())
        if not dates:
            return 0
            
        max_streak = 0
        current_streak = 1
        
        for i in range(1, len(dates)):
            date1 = datetime.datetime.strptime(dates[i-1], "%Y-%m-%d").date()
            date2 = datetime.datetime.strptime(dates[i], "%Y-%m-%d").date()
            
            if (date2 - date1).days == 1:
                current_streak += 1
            else:
                max_streak = max(max_streak, current_streak)
                current_streak = 1
                
        max_streak = max(max_streak, current_streak)
        return max_streak
    
    def update_date_range_label(self):
        """Update the date range label to show the current display period"""
        today = datetime.datetime.now().date()
        start_date = datetime.datetime(2025, 1, 1).date()  # Start from January 1, 2025
        
        # If today is not in 2025, use February 26, 2025 as "today" for display purposes
        if today.year != 2025:
            today = datetime.datetime(2025, 2, 26).date()
        
        formatted_start = start_date.strftime("%b %d, %Y")
        formatted_today = today.strftime("%b %d, %Y")
        
        self.date_range_label.set_markup(
            f"<small>Displaying: <b>{formatted_start}</b> to <b>{formatted_today}</b></small>"
        )
    
    def update_stats_label(self):
        """Update the statistics label with current data"""
        today = datetime.datetime.now().date()
        # If today is not in 2025, use February 26, 2025 as "today" for display purposes
        if today.year != 2025:
            today = datetime.datetime(2025, 2, 26).date()
            
        today_str = today.strftime("%Y-%m-%d")
        today_reviews = self.review_counts.get(today_str, 0)
        
        if self.total_reviews > 0:
            self.stats_label.set_markup(
                f"Today: <b>{today_reviews}</b> reviews | "
                f"Current streak: <b>{self.current_streak}</b> days | "
                f"Longest streak: <b>{self.longest_streak}</b> days | "
                f"Total: <b>{self.total_reviews}</b> reviews"
            )
        else:
            self.stats_label.set_markup(
                "<span color='orange'>No 2025 review data found. If you use Anki, try clicking Refresh.</span>"
            )
    
    def on_heatmap_motion(self, widget, event):
        """Handle mouse motion over the heatmap to show tooltips"""
        # Get cell under mouse pointer
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        days_to_show = min(self.get_days_in_2025(), 105)  # Show only available days in 2025
        cols = min(days_to_show // 7, width // 20)
        rows = 7
        
        cell_width = min(18, width / cols)
        cell_height = min(18, height / rows)
        
        h_padding = (width - (cell_width * cols)) / 2
        v_padding = (height - (cell_height * rows)) / 2
        
        # Find which cell the mouse is over
        if event.x < h_padding or event.x > width - h_padding:
            self.hide_tooltip()
            return
        
        if event.y < v_padding or event.y > height - v_padding:
            self.hide_tooltip()
            return
        
        col = int((event.x - h_padding) / cell_width)
        row = int((event.y - v_padding) / cell_height)
        
        if col >= cols or row >= rows:
            self.hide_tooltip()
            return
        
        # Calculate date for this cell
        start_date = datetime.datetime(2025, 1, 1).date()
        today = datetime.datetime.now().date()
        
        # If today is not in 2025, use February 26, 2025 as "today" for display purposes
        if today.year != 2025:
            today = datetime.datetime(2025, 2, 26).date()
        
        week_number = cols - 1 - col
        day_of_week = row
        days_from_start = week_number * 7 + day_of_week
        
        cell_date = start_date + datetime.timedelta(days=days_from_start)
        
        # Ensure we don't exceed today's date
        if cell_date > today:
            self.hide_tooltip()
            return
            
        date_str = cell_date.strftime("%Y-%m-%d")
        
        # Get review count
        count = self.review_counts.get(date_str, 0)
        
        # Show tooltip if this is a different cell than before
        formatted_date = cell_date.strftime("%A, %b %d, %Y")  # Full day name, month, day, year
        if self.hover_date != formatted_date or self.hover_count != count:
            self.hover_date = formatted_date
            self.hover_count = count
            self.show_tooltip(event, formatted_date, count)
    
    def get_days_in_2025(self):
        """Calculate how many days are available in 2025 up to today"""
        today = datetime.datetime.now().date()
        start_date = datetime.datetime(2025, 1, 1).date()
        
        # If today is not in 2025, use February 26, 2025 as "today"
        if today.year != 2025:
            today = datetime.datetime(2025, 2, 26).date()
            
        days = (today - start_date).days + 1
        return days
    
    def on_heatmap_leave(self, widget, event):
        """Handle mouse leaving the heatmap area"""
        self.hide_tooltip()
    
    def show_tooltip(self, event, date_str, count):
        """Show tooltip with date and review count"""
        self.hide_tooltip()  # Hide any existing tooltip
        
        # Create tooltip window
        self.tooltip_window = Gtk.Window(type=Gtk.WindowType.POPUP)
        self.tooltip_window.set_decorated(False)
        
        # Add content
        tooltip_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        tooltip_box.set_margin_top(5)
        tooltip_box.set_margin_bottom(5)
        tooltip_box.set_margin_start(8)
        tooltip_box.set_margin_end(8)
        
        date_label = Gtk.Label()
        date_label.set_markup(f"<b>{date_str}</b>")
        tooltip_box.pack_start(date_label, False, False, 0)
        
        count_label = Gtk.Label()
        if count > 0:
            count_label.set_markup(f"<b>{count}</b> {'reviews' if count > 1 else 'review'}")
        else:
            count_label.set_markup("<i>No reviews</i>")
        tooltip_box.pack_start(count_label, False, False, 0)
        
        self.tooltip_window.add(tooltip_box)
        
        # Position tooltip near mouse
        x, y = self.window.get_position()
        win_x = x + int(event.x) + 10
        win_y = y + int(event.y) + 20
        
        self.tooltip_window.move(win_x, win_y)
        self.tooltip_window.show_all()
    
    def hide_tooltip(self):
        """Hide the tooltip window if it exists"""
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None
            self.hover_date = None
            self.hover_count = None
    
    def draw_heatmap(self, widget, context):
        """Draw the heatmap visualization"""
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        
        # Draw background
        context.set_source_rgb(0.95, 0.95, 0.95)
        context.rectangle(0, 0, width, height)
        context.fill()
        
        # Calculate cell size and layout
        days_to_show = min(self.get_days_in_2025(), 105)  # Show only available days in 2025
        cols = min(days_to_show // 7 + 1, width // 20)  # Add 1 to ensure we have enough columns
        rows = 7  # Days of week
        
        cell_width = min(18, width / cols)
        cell_height = min(18, height / rows)
        
        h_padding = (width - (cell_width * cols)) / 2
        v_padding = (height - (cell_height * rows)) / 2
        
        # Get date range to display
        start_date = datetime.datetime(2025, 1, 1).date()
        today = datetime.datetime.now().date()
        
        # If today is not in 2025, use February 26, 2025 as "today"
        if today.year != 2025:
            today = datetime.datetime(2025, 2, 26).date()
        
        # Find max count for color scaling
        max_count = 1
        if self.review_counts:
            max_count = max(self.review_counts.values())
        
        # Draw cells
        for i in range(days_to_show):
            current_date = start_date + datetime.timedelta(days=i)
            
            # Skip if we've gone beyond today
            if current_date > today:
                continue
                
            date_str = current_date.strftime("%Y-%m-%d")
            
            # Calculate position
            days_since_start = (current_date - start_date).days
            week_number = days_since_start // 7
            day_of_week = current_date.weekday()  # 0=Monday, 6=Sunday
            
            col = week_number
            row = day_of_week
            
            x = h_padding + col * cell_width
            y = v_padding + row * cell_height
            
            # Get review count for this date
            count = self.review_counts.get(date_str, 0)
            
            # Set color based on count (green with varying intensity)
            intensity = min(1.0, count / max_count) if count > 0 else 0
            if count > 0:
                r, g, b = 0.15, 0.4 + (intensity * 0.5), 0.15
            else:
                r, g, b = 0.9, 0.9, 0.9  # Light gray for no reviews
            
            # Draw cell
            context.set_source_rgb(r, g, b)
            context.rectangle(x, y, cell_width - 2, cell_height - 2)
            context.fill()
            
            # Highlight today's cell
            if current_date == today:
                context.set_source_rgb(0.8, 0.3, 0.3)  # Red outline
                context.set_line_width(2)
                context.rectangle(x, y, cell_width - 2, cell_height - 2)
                context.stroke()
        
        # Draw month labels with year
        context.set_source_rgb(0.3, 0.3, 0.3)
        context.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        context.set_font_size(9)
        
        # Get distinct months to display
        current_month = None
        for month in range(1, 13):  # All months
            if month > today.month and today.year == 2025:
                break
                
            date = datetime.datetime(2025, month, 1).date()
            month_name = date.strftime("%b")  # Abbreviated month name
            
            if month_name != current_month:
                current_month = month_name
                days_since_start = (date - start_date).days
                week_number = days_since_start // 7
                
                # Only show months that are visible
                if 0 <= week_number < cols:
                    # Draw month name (all are 2025)
                    x = h_padding + week_number * cell_width
                    y = v_padding - 5
                    context.move_to(x, y)
                    context.show_text(f"{month_name} '25")
        
        # Draw day indicators (Mon, Wed, Fri)
        context.set_font_size(8)
        day_labels = {0: "Mon", 2: "Wed", 4: "Fri", 6: "Sun"}
        for day, label in day_labels.items():
            x = h_padding - 22
            y = v_padding + day * cell_height + 12
            context.move_to(x, y)
            context.show_text(label)
    
    def refresh_data(self):
        """Reload Anki data and refresh the display"""
        self.load_anki_data()
        self.heatmap_area.queue_draw()
        return True  # Continue the timeout
    
    def on_refresh_clicked(self, button):
        """Handle refresh button click"""
        self.refresh_data()
    
    def on_launch_clicked(self, button):
        """Handle launch Anki button click"""
        try:
            subprocess.Popen(["anki"])
        except Exception as e:
            self.stats_label.set_markup(f"<span color='red'>Failed to launch Anki: {str(e)}</span>")

def setup_desktop_file():
    """Create a .desktop file for autostart"""
    desktop_dir = os.path.expanduser("~/.config/autostart")
    os.makedirs(desktop_dir, exist_ok=True)
    
    desktop_path = os.path.join(desktop_dir, "anki-heatmap.desktop")
    desktop_content = f"""[Desktop Entry]
Type=Application
Exec={os.path.abspath(__file__)}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=Anki Heatmap Widget 2025
Comment=Display Anki study history for 2025
"""
    
    with open(desktop_path, "w") as f:
        f.write(desktop_content)
    
    os.chmod(desktop_path, 0o755)
    print(f"Created autostart entry at {desktop_path}")

def install_as_desklet():
    """Create files needed to install as a Cinnamon desklet"""
    # Create desklet directory
    desklet_dir = os.path.expanduser("~/.local/share/cinnamon/desklets/anki-heatmap@user")
    os.makedirs(desklet_dir, exist_ok=True)
    
    # Create metadata.json
    metadata = {
        "uuid": "anki-heatmap@user",
        "name": "Anki Heatmap 2025",
        "description": "Shows your Anki study activity for 2025 as a heatmap",
        "version": "1.0",
        "last-edited": int(datetime.datetime.now().timestamp())
    }
    
    with open(os.path.join(desklet_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)
    
    # Create desklet.js
    desklet_js = """const Desklet = imports.ui.desklet;
const GLib = imports.gi.GLib;
const Gio = imports.gi.Gio;
const Util = imports.misc.util;
const Lang = imports.lang;

function AnkiHeatmapDesklet(metadata, desklet_id) {
    this._init(metadata, desklet_id);
}

AnkiHeatmapDesklet.prototype = {
    __proto__: Desklet.Desklet.prototype,

    _init: function(metadata, desklet_id) {
        Desklet.Desklet.prototype._init.call(this, metadata, desklet_id);
        
        // Launch the Python script
        this._launchScript();
    },
    
    _launchScript: function() {
        let scriptPath = GLib.get_home_dir() + 
            "/.local/share/cinnamon/desklets/anki-heatmap@user/anki_heatmap.py";
        Util.spawnCommandLine("python3 " + scriptPath);
    },
    
    on_desklet_removed: function() {
        // Cleanup when desklet is removed
        Util.spawnCommandLine("pkill -f anki_heatmap.py");
    }
};

function main(metadata, desklet_id) {
    return new AnkiHeatmapDesklet(metadata, desklet_id);
}
"""
    
    with open(os.path.join(desklet_dir, "desklet.js"), "w") as f:
        f.write(desklet_js)
    
    # Copy this script as anki_heatmap.py
    with open(__file__, "r") as src:
        with open(os.path.join(desklet_dir, "anki_heatmap.py"), "w") as dst:
            dst.write(src.read())
    
    # Make executable
    os.chmod(os.path.join(desklet_dir, "anki_heatmap.py"), 0o755)
    
    print(f"Desklet installed to {desklet_dir}")
    print("You can now add it from the Cinnamon desklets settings")

if __name__ == "__main__":
    # Check if we should install as desklet or autostart
    if len(os.sys.argv) > 1:
        if os.sys.argv[1] == "--install":
            install_as_desklet()
        elif os.sys.argv[1] == "--autostart":
            setup_desktop_file()
    else:
        # Run as standalone app
        app = AnkiHeatmapWidget()
        Gtk.main()