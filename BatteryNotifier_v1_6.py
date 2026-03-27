import psutil
import os
import sys
import json
import winreg
import pythoncom
import win32com.client
from time import sleep
from playsound import playsound, PlaysoundException
import threading
from pystray import Icon, MenuItem, Menu
from PIL import Image
from plyer import notification
import tkinter as tk
import customtkinter as ctk


# ---------------- Helpers ----------------
def resource_path(filename):
    """Resolve path to a BUNDLED asset (read-only: icons, sounds, etc.)
    Works both in development and when frozen by PyInstaller."""
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, filename)


def user_data_path(filename):
    """Resolve path to a WRITABLE user-data file (settings, history).
    Stored in %APPDATA%\\BatteryNotifier so it survives across installs."""
    app_data = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                            "BatteryNotifier")
    os.makedirs(app_data, exist_ok=True)
    return os.path.join(app_data, filename)


class BatteryNotifier:
    def __init__(self):
        self.settings_file = user_data_path("settings.json")
        self.history_file  = user_data_path("history.json")
        self.load_settings()
        self.sound_file = resource_path("short_bell.mp3")
        self.running = True
        self.ALARM_REPEAT_LIMIT = 3
        self.low_play_count  = 0
        self.full_play_count = 0

        # --- Startup folder shortcut (covers sign-out / sign-in) ---
        self.startup_folder = os.path.join(
            os.environ.get("APPDATA", ""),
            r"Microsoft\Windows\Start Menu\Programs\Startup"
        )
        self.shortcut_path = os.path.join(self.startup_folder, "BatteryNotifier.lnk")

        # Hidden main root — mainloop() runs on main thread
        self.root = tk.Tk()
        self.root.withdraw()

    # ---------------- Settings ----------------
    def load_settings(self):
        try:
            with open(self.settings_file, "r") as f:
                data = json.load(f)
                self.low_value  = data.get("low_value",  15)
                self.full_value = data.get("full_value", 100)
        except Exception:
            self.low_value  = 15
            self.full_value = 100

    def save_settings(self):
        with open(self.settings_file, "w") as f:
            json.dump({"low_value": self.low_value, "full_value": self.full_value}, f)

    def open_settings(self, icon=None, item=None):
        self.root.after(0, self._open_settings_ui)

    def _open_settings_ui(self):
        def save():
            try:
                low  = int(low_entry.get())
                full = int(full_entry.get())
                if not (0 < low < full <= 100):
                    raise ValueError
                self.low_value  = low
                self.full_value = full
                self.save_settings()
                self.low_play_count  = 0
                self.full_play_count = 0
                win.destroy()
            except Exception:
                pass

        ctk.set_appearance_mode("dark")
        win = ctk.CTkToplevel(self.root)
        win.title("Settings")
        win.geometry("300x200")
        win.lift()
        win.attributes("-topmost", True)
        win.after(100, lambda: win.attributes("-topmost", False))

        ctk.CTkLabel(win, text="Low Battery %").pack(pady=5)
        low_entry = ctk.CTkEntry(win)
        low_entry.insert(0, str(self.low_value))
        low_entry.pack()

        ctk.CTkLabel(win, text="Full Battery %").pack(pady=5)
        full_entry = ctk.CTkEntry(win)
        full_entry.insert(0, str(self.full_value))
        full_entry.pack()

        ctk.CTkButton(win, text="Save", command=save).pack(pady=10)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.focus_force()

    # ---------------- History ----------------
    def log_history(self, message):
        try:
            with open(self.history_file, "r") as f:
                data = json.load(f)
        except Exception:
            data = []

        data.append(message)
        with open(self.history_file, "w") as f:
            json.dump(data, f, indent=2)

    def show_history(self, icon=None, item=None):
        self.root.after(0, self._show_history_ui)

    def _show_history_ui(self):
        try:
            with open(self.history_file, "r") as f:
                data = json.load(f)
        except Exception:
            data = []

        window = tk.Toplevel(self.root)
        window.title("Notification History")
        window.geometry("400x300")
        window.lift()
        window.attributes("-topmost", True)
        window.after(100, lambda: window.attributes("-topmost", False))

        text = tk.Text(window)
        text.pack(expand=True, fill="both")

        for entry in data:
            text.insert("end", entry + "\n")

        window.protocol("WM_DELETE_WINDOW", window.destroy)
        window.focus_force()

    # ---------------- Auto-Start (Registry + Startup Folder) ----------------
    def _get_exe_path(self):
        """Always returns the real EXE path whether frozen by PyInstaller or run as .py"""
        if getattr(sys, "frozen", False):
            return sys.executable
        return os.path.abspath(sys.argv[0])

    def _write_registry(self, exe_path):
        """Write HKCU Run key — fires on every boot and restart."""
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, "BatteryNotifier", 0, winreg.REG_SZ, exe_path)
        winreg.CloseKey(key)

    def _delete_registry(self):
        """Remove HKCU Run key."""
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE
        )
        winreg.DeleteValue(key, "BatteryNotifier")
        winreg.CloseKey(key)

    def _registry_exists(self):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run"
            )
            winreg.QueryValueEx(key, "BatteryNotifier")
            winreg.CloseKey(key)
            return True
        except Exception:
            return False

    def _write_shortcut(self, exe_path):
        """Create .lnk in Startup folder — fires after sign-out / sign-in."""
        pythoncom.CoInitialize()
        shell    = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(self.shortcut_path)
        shortcut.TargetPath       = exe_path
        shortcut.WorkingDirectory = os.path.dirname(exe_path)
        shortcut.Description      = "Battery Notifier"
        shortcut.save()

    def _delete_shortcut(self):
        if os.path.isfile(self.shortcut_path):
            os.remove(self.shortcut_path)

    def _shortcut_exists(self):
        return os.path.isfile(self.shortcut_path)

    def enable_startup(self, icon=None, item=None):
        if not self.is_startup_enabled():
            try:
                exe_path = self._get_exe_path()
                self._write_registry(exe_path)   # boot / restart
                self._write_shortcut(exe_path)   # sign-out / sign-in
                notification.notify(
                    title="Startup Enabled",
                    message="Battery Notifier will start on boot and after sign-in",
                    timeout=3
                )
            except Exception as e:
                print(f"enable_startup error: {e}")

    def disable_startup(self, icon=None, item=None):
        if self.is_startup_enabled():
            try:
                self._delete_registry()
                self._delete_shortcut()
                notification.notify(
                    title="Startup Disabled",
                    message="Battery Notifier won't start automatically",
                    timeout=3
                )
            except Exception as e:
                print(f"disable_startup error: {e}")

    def is_startup_enabled(self):
        # Both must be present — they are always written and removed together
        return self._registry_exists() and self._shortcut_exists()

    def startup_on_checked(self):
        return self.is_startup_enabled()

    def startup_off_checked(self):
        return not self.is_startup_enabled()

    # ---------------- Battery Checker ----------------
    def _play_alarm(self):
        """Fire alarm in its own daemon thread so nothing can block it."""
        def _play():
            playsound(self.sound_file)
        threading.Thread(target=_play, daemon=True).start()

    def check_battery(self):
        """
        Runs every 10 seconds.
        Alarm fires based purely on percentage — plug state is irrelevant.
        Alarm plays up to ALARM_REPEAT_LIMIT times per threshold crossing,
        then stays silent until the battery leaves the zone and returns.
        """
        while self.running:
            try:
                battery = psutil.sensors_battery()
                if battery is None:
                    sleep(10)
                    continue

                percent = battery.percent

                if percent <= self.low_value:
                    if self.low_play_count < self.ALARM_REPEAT_LIMIT:
                        self._play_alarm()
                        self.low_play_count += 1
                        if self.low_play_count == 1:
                            msg = f"Battery Low: {percent}%"
                            self.log_history(msg)
                            notification.notify(title="Battery Low!", message=msg, timeout=5)
                        self.full_play_count = 0

                elif percent >= self.full_value:
                    if self.full_play_count < self.ALARM_REPEAT_LIMIT:
                        self._play_alarm()
                        self.full_play_count += 1
                        if self.full_play_count == 1:
                            msg = f"Battery Full: {percent}%"
                            self.log_history(msg)
                            notification.notify(title="Battery Full", message=msg, timeout=5)
                        self.low_play_count = 0

                else:
                    self.low_play_count  = 0
                    self.full_play_count = 0

            except PlaysoundException:
                print("Sound error — check short_bell.mp3 exists")
            except Exception as e:
                print(f"Battery check error: {e}")

            sleep(10)

    def stop(self, icon=None, item=None):
        self.running = False
        icon.stop()
        self.root.after(0, self.root.quit)


def create_tray_icon(notifier):
    image = Image.open(resource_path("battery_icon.ico"))

    startup_submenu = Menu(
        MenuItem(
            "On",
            notifier.enable_startup,
            checked=lambda item: notifier.startup_on_checked(),
            radio=True
        ),
        MenuItem(
            "Off",
            notifier.disable_startup,
            checked=lambda item: notifier.startup_off_checked(),
            radio=True
        ),
    )

    menu = Menu(
        MenuItem("Settings",     notifier.open_settings),
        MenuItem("Auto Start",   startup_submenu),
        MenuItem("View History", notifier.show_history),
        MenuItem("Exit",         notifier.stop),
    )

    return Icon("BatteryNotifier", image, "Battery Notifier", menu)


# ---------------- MAIN ----------------
if __name__ == "__main__":
    notifier  = BatteryNotifier()
    tray_icon = create_tray_icon(notifier)

    # Battery checker in its own background thread
    battery_thread = threading.Thread(
        target=notifier.check_battery,
        daemon=True
    )
    battery_thread.start()

    # Tray icon in background thread
    tray_thread = threading.Thread(target=tray_icon.run, daemon=True)
    tray_thread.start()

    # Tkinter mainloop on the MAIN thread (required by Windows)
    notifier.root.mainloop()
