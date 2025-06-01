import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import requests
import subprocess
import os
import json
import sys
import ctypes
from collections import defaultdict, OrderedDict

# Load apps from JSON
with open("apps.json", "r") as f:
    raw_json = json.load(f)

# Group apps by the 'category' field inside each app, keep categories in original order, sort apps alphabetically
apps_by_category = defaultdict(dict)
category_order = []
for top_level in raw_json.values():
    for app_name, app_data in top_level.items():
        cat = app_data.get("category", "Other")
        if cat not in apps_by_category:
            category_order.append(cat)
        apps_by_category[cat][app_name] = app_data
# Only sort apps alphabetically, not categories
apps_by_category = OrderedDict((cat, OrderedDict(sorted(apps.items()))) for cat, apps in apps_by_category.items() if cat in category_order)
# Move 'Other' to the end
if 'Other' in category_order:
    category_order = [c for c in category_order if c != 'Other'] + ['Other']
apps_by_category = OrderedDict((cat, apps_by_category[cat]) for cat in category_order if cat in apps_by_category)

os.makedirs("installers", exist_ok=True)

def run_as_admin(exe, params=''):
    # exe: path to the executable
    # params: command line arguments as a single string or None
    print(f"Running as admin: {exe}")
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)

class AppInstallerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Bore's App Installer")
        self.root.geometry("1200x700")
        self.root.configure(bg="#f4f4f4")
        self.root.minsize(800, 400)

        self.check_vars = {}
        self.install_mode = tk.StringVar(value="auto")  # 'auto', 'skip', 'manual'
        self.next_button = None
        self.pending_apps = []
        self.current_app_index = 0
        self.custom_app_fields = {}
        self.app_widgets = {}  # (category, app_name): frame
        self.edit_mode = tk.StringVar(value="add")  # 'add', 'edit', 'remove'
        self.icon_preview_img = None
        self.icon_file_path = None
        self.category_labels = {}  # category: label widget
        self.category_trash_icons = {}  # category: trash button widget

        # Load default JSON for revert
        import copy
        with open("apps.json", "r") as f:
            self.default_json = copy.deepcopy(f.read())

        # Top options
        options_frame = tk.Frame(root, bg="#f4f4f4")
        options_frame.pack(pady=(8, 0))
        auto_rb = ttk.Radiobutton(options_frame, text="Auto Install (unsafe)", variable=self.install_mode, value="auto", command=self.update_mode_explanation)
        auto_rb.pack(side="left", padx=10)
        skip_rb = ttk.Radiobutton(options_frame, text="Skip Auto Install", variable=self.install_mode, value="skip", command=self.update_mode_explanation)
        skip_rb.pack(side="left", padx=10)
        manual_rb = ttk.Radiobutton(options_frame, text="Manual Step-Through", variable=self.install_mode, value="manual", command=self.update_mode_explanation)
        manual_rb.pack(side="left", padx=10)

        self.mode_explanation = tk.Label(root, text="", font=("Helvetica", 10), bg="#f4f4f4", fg="#444444")
        self.mode_explanation.pack(pady=(0, 8))
        self.update_mode_explanation()

        # Next App button placeholder (will be packed here)
        self.next_button_frame = tk.Frame(root, bg="#f4f4f4")
        self.next_button_frame.pack()
        self.next_button = None

        self.notification_label = tk.Label(root, text="", font=("Helvetica", 10), bg="#f4f4f4", fg="green")
        self.notification_label.pack(pady=2)

        title = tk.Label(root, text="Select Apps to Install", font=("Helvetica", 18), bg="#f4f4f4")
        title.pack(pady=10)

        install_button = ttk.Button(root, text="Install Selected", command=self.install_selected)
        install_button.pack(pady=(0, 10))

        # Responsive canvas with horizontal and vertical scrollbars using grid
        self.canvas_frame = tk.Frame(root)
        self.canvas_frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.canvas_frame, bg="#f4f4f4", highlightthickness=0)
        self.scroll_y = ttk.Scrollbar(self.canvas_frame, orient="vertical", command=self.canvas.yview)
        self.scroll_x = ttk.Scrollbar(self.canvas_frame, orient="horizontal", command=self.canvas.xview)
        self.scroll_frame = ttk.Frame(self.canvas)

        self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scroll_y.set, xscrollcommand=self.scroll_x.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scroll_y.grid(row=0, column=1, sticky="ns")
        self.scroll_x.grid(row=1, column=0, sticky="ew")
        self.canvas_frame.grid_rowconfigure(0, weight=1)
        self.canvas_frame.grid_columnconfigure(0, weight=1)
        self.scroll_frame.grid_rowconfigure(0, weight=1)
        for i in range(21):  # allow up to 20 app columns + 1 for trash
            self.scroll_frame.grid_columnconfigure(i, weight=1)

        def on_canvas_configure(event):
            self.canvas.itemconfig("all", width=event.width)
        self.canvas.bind("<Configure>", on_canvas_configure)
        self.scroll_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        self.render_app_grid()

        # Custom Apper Maker section (vertically stacked) - now at the bottom
        edit_frame = tk.LabelFrame(root, text="Custom Apper Maker", bg="#f4f4f4")
        edit_frame.pack(side="bottom", pady=8, fill="x", padx=10)
        # Mode selection
        mode_frame = tk.Frame(edit_frame, bg="#f4f4f4")
        mode_frame.pack(anchor="w", pady=(4, 8))
        add_rb = ttk.Radiobutton(mode_frame, text="Add", variable=self.edit_mode, value="add", command=self.update_edit_mode)
        add_rb.pack(side="left", padx=6)
        edit_rb = ttk.Radiobutton(mode_frame, text="Edit", variable=self.edit_mode, value="edit", command=self.update_edit_mode)
        edit_rb.pack(side="left", padx=6)
        remove_rb = ttk.Radiobutton(mode_frame, text="Remove", variable=self.edit_mode, value="remove", command=self.update_edit_mode)
        remove_rb.pack(side="left", padx=6)
        self.disclaimer = tk.Label(mode_frame, text="If you don't see the trash icons, try adjusting the window size.", font=("Helvetica", 8), bg="#f4f4f4", fg="#a00")
        self.disclaimer.pack(side="left", padx=(12, 0))
        self.disclaimer.pack_forget()
        # Name field with icon preview
        name_row = tk.Frame(edit_frame, bg="#f4f4f4")
        name_row.pack(fill="x", pady=2)
        name_label = tk.Label(name_row, text="Name", bg="#f4f4f4")
        name_label.pack(side="left", padx=(2, 8))
        name_entry = ttk.Entry(name_row, width=24)
        name_entry.pack(side="left")
        self.custom_app_fields["name"] = name_entry
        icon_preview = tk.Label(name_row, bg="#f4f4f4")
        icon_preview.pack(side="left", padx=8)
        self.icon_preview = icon_preview
        name_entry.bind("<KeyRelease>", self.update_edit_fields)

        # Icon field (file picker)
        icon_row = tk.Frame(edit_frame, bg="#f4f4f4")
        icon_row.pack(fill="x", pady=2)
        icon_label = tk.Label(icon_row, text="Icon", bg="#f4f4f4")
        icon_label.pack(side="left", padx=(2, 8))
        icon_entry = ttk.Entry(icon_row, width=24)
        icon_entry.pack(side="left")
        self.custom_app_fields["icon"] = icon_entry
        icon_btn = ttk.Button(icon_row, text="Choose Image", command=self.choose_icon_file)
        icon_btn.pack(side="left", padx=4)
        self.icon_field_preview = tk.Label(icon_row, bg="#f4f4f4")
        self.icon_field_preview.pack(side="left", padx=8)

        # Download Link field
        url_row = tk.Frame(edit_frame, bg="#f4f4f4")
        url_row.pack(fill="x", pady=2)
        url_label = tk.Label(url_row, text="Download Link", bg="#f4f4f4")
        url_label.pack(side="left", padx=(2, 8))
        url_entry = ttk.Entry(url_row, width=40)
        url_entry.pack(side="left")
        self.custom_app_fields["url"] = url_entry

        # Category field (combobox with add/delete)
        cat_row = tk.Frame(edit_frame, bg="#f4f4f4")
        cat_row.pack(fill="x", pady=2)
        cat_label = tk.Label(cat_row, text="Category", bg="#f4f4f4")
        cat_label.pack(side="left", padx=(2, 8))
        from tkinter import ttk as ttk2
        self.cat_var = tk.StringVar()
        self.cat_combo = ttk2.Combobox(cat_row, textvariable=self.cat_var, state="readonly", width=22)
        self.cat_combo.pack(side="left")
        cat_add_btn = ttk.Button(cat_row, text="New Category", command=self.add_new_category)
        cat_add_btn.pack(side="left", padx=4)
        self.custom_app_fields["category"] = self.cat_combo

        submit_btn = ttk.Button(edit_frame, text="Submit", command=self.handle_edit_submit)
        submit_btn.pack(pady=6)
        revert_btn = ttk.Button(edit_frame, text="Revert to Default", command=self.revert_to_default_json)
        revert_btn.pack(pady=2)

        self.update_edit_fields()

    def render_app_grid(self):
        # Remove all app widgets and category labels/trash icons
        for frame in self.app_widgets.values():
            frame.destroy()
        self.app_widgets.clear()
        for label in getattr(self, 'category_labels', {}).values():
            label.destroy()
        for btn in getattr(self, 'category_trash_icons', {}).values():
            btn.destroy()
        self.category_labels = {}
        self.category_trash_icons = {}
        # Display all categories as columns in a single horizontal row
        categories = list(apps_by_category.keys())
        remove_mode = self.edit_mode.get() == 'remove'
        edit_mode = self.edit_mode.get() == 'edit'
        for col, category in enumerate(categories):
            cat_frame = tk.Frame(self.scroll_frame, bg="#f4f4f4")
            cat_frame.grid(row=0, column=col, padx=16, pady=(8, 16), sticky="nwe")
            cat_label = tk.Label(cat_frame, text=category, font=("Helvetica", 14, "bold"), bg="#f4f4f4")
            cat_label.pack(side="left")
            self.category_labels[category] = cat_label
            if remove_mode:
                trash_btn = tk.Button(cat_frame, text="🗑️", command=lambda c=category: self.delete_category_gui(c), relief="flat", bg="#f4f4f4", bd=0, padx=2, cursor="hand2")
                trash_btn.pack(side="left", padx=(6, 0))
                self.category_trash_icons[category] = trash_btn
        # Place apps under each category
        for col, category in enumerate(categories):
            apps = apps_by_category[category]
            for row_offset, (name, data) in enumerate(apps.items()):
                frame = self.add_app(name, data, parent=self.scroll_frame, grid_row=row_offset+1, grid_col=col, return_widget=True, category=category, show_remove=remove_mode)
                self.app_widgets[(category, name)] = frame

    def add_custom_app(self):
        name = self.custom_app_fields["name"].get().strip()
        icon = self.custom_app_fields["icon"].get().strip()
        url = self.custom_app_fields["url"].get().strip()
        category = self.custom_app_fields["category"].get().strip() or "Other"
        if not name or not icon or not url:
            self.show_notification("Please fill in all fields.", error=True)
            return
        # Add to apps_by_category
        if category not in apps_by_category:
            from collections import OrderedDict
            apps_by_category[category] = OrderedDict()
        apps_by_category[category][name] = {"url": url, "icon": icon, "category": category}
        self.render_app_grid()
        self.save_json()
        self.show_notification(f"Added {name} to {category}.")
        for entry in self.custom_app_fields.values():
            entry.delete(0, tk.END)

    def save_json(self):
        # Save the current apps_by_category to apps.json
        import json
        # Rebuild the original structure for saving
        out = {}
        for cat, apps in apps_by_category.items():
            for name, data in apps.items():
                if cat not in out:
                    out[cat] = {}
                out[cat][name] = data
        with open("apps.json", "w") as f:
            json.dump(out, f, indent=2)

    def revert_to_default_json(self):
        import json
        with open("apps.json", "w") as f:
            f.write(self.default_json)
        # Reload apps_by_category
        global apps_by_category
        with open("apps.json", "r") as f:
            raw_json = json.load(f)
        from collections import defaultdict, OrderedDict
        apps_by_category = defaultdict(dict)
        category_order = []
        for top_level in raw_json.values():
            for app_name, app_data in top_level.items():
                cat = app_data.get("category", "Other")
                if cat not in apps_by_category:
                    category_order.append(cat)
                apps_by_category[cat][app_name] = app_data
        apps_by_category = OrderedDict((cat, OrderedDict(sorted(apps.items()))) for cat, apps in apps_by_category.items() if cat in category_order)
        if 'Other' in category_order:
            category_order = [c for c in category_order if c != 'Other'] + ['Other']
        apps_by_category = OrderedDict((cat, apps_by_category[cat]) for cat in category_order if cat in apps_by_category)
        self.render_app_grid()
        self.show_notification("Reverted to default app list.")

    def add_app(self, name, data, parent=None, grid_row=None, grid_col=None, return_widget=False, category=None, show_remove=False):
        if parent is None:
            parent = self.scroll_frame
        frame = ttk.Frame(parent)
        if grid_row is not None and grid_col is not None:
            frame.grid(row=grid_row, column=grid_col, padx=8, pady=4, sticky="nsew")
        else:
            frame.pack(fill="x", pady=5)

        try:
            img = Image.open(os.path.join("icons", data["icon"]))
            img = img.resize((20, 20), Image.LANCZOS)
            icon = ImageTk.PhotoImage(img)
        except Exception as e:
            print(f"Failed to load icon for {name}: {e}")
            icon = None

        var = self.check_vars.get(name) or tk.BooleanVar()
        self.check_vars[name] = var

        check = ttk.Checkbutton(frame, variable=var)
        check.grid(row=0, column=0, padx=(0, 2), sticky="w")

        if icon:
            icon_label = tk.Label(frame, image=icon)
            icon_label.image = icon
            icon_label.grid(row=0, column=1, padx=(0, 2), sticky="w")
        else:
            icon_label = tk.Label(frame, width=20)
            icon_label.grid(row=0, column=1, padx=(0, 2), sticky="w")

        def toggle_var(event=None, v=var):
            v.set(not v.get())
        name_label = tk.Label(frame, text=name, anchor="w", justify="left", width=18, cursor="hand2")
        name_label.grid(row=0, column=2, sticky="w")
        name_label.bind("<Button-1>", toggle_var)

        col_idx = 3
        if show_remove:
            def remove_app():
                if category and name in apps_by_category.get(category, {}):
                    del apps_by_category[category][name]
                    if not apps_by_category[category]:
                        del apps_by_category[category]
                    self.render_app_grid()
                    self.save_json()
                    self.show_notification(f"Removed {name} from {category}.")
            remove_btn = tk.Button(frame, text="🗑️", command=remove_app, relief="flat", bg="#f4f4f4", bd=0, padx=2, cursor="hand2")
            remove_btn.grid(row=0, column=col_idx, padx=(4, 0), sticky="ns")

        if return_widget:
            return frame

    def install_selected(self):
        selected = [name for name, var in self.check_vars.items() if var.get()]
        if not selected:
            self.show_notification("Please select at least one app to install.", error=True)
            return

        mode = self.install_mode.get()
        if mode == "skip":
            # Just download installers, do not run them
            for app_name in selected:
                self.download_and_install(app_name, run_installer=False)
            self.show_notification("Installers downloaded. Opening folder...")
            import subprocess, os
            subprocess.Popen(f'explorer "{os.path.abspath("installers")}"')
            return

        if mode == "manual":
            self.pending_apps = selected
            self.current_app_index = 0
            self.show_notification(f"Ready to install: {self.pending_apps[self.current_app_index]}")
            self.install_next_manual()
            return

        # Default: download and install all
        for app_name in selected:
            self.download_and_install(app_name)
        self.show_notification("All selected apps have been installed.")

    def install_next_manual(self):
        if self.current_app_index >= len(self.pending_apps):
            self.show_notification("All selected apps have been installed.")
            if self.next_button:
                self.next_button.destroy()
                self.next_button = None
            return
        app_name = self.pending_apps[self.current_app_index]
        self.download_and_install(app_name, after_manual=True)

    def after_manual_install(self):
        self.current_app_index += 1
        if self.current_app_index < len(self.pending_apps):
            self.show_notification(f"Ready to install: {self.pending_apps[self.current_app_index]}")
            if not self.next_button:
                self.next_button = ttk.Button(self.next_button_frame, text="Next App", command=self.install_next_manual)
                self.next_button.pack(pady=10)
        else:
            self.show_notification("All selected apps have been installed.")
            if self.next_button:
                self.next_button.destroy()
                self.next_button = None

    def download_and_install(self, app_name, run_installer=True, after_manual=False):
        # Find the app data by searching all categories
        data = None
        for apps in apps_by_category.values():
            if app_name in apps:
                data = apps[app_name]
                break
        if not data:
            self.show_notification(f"App data not found for {app_name}", error=True)
            return
        url = data["url"]
        path = os.path.join("installers", f"{app_name}.exe")

        try:
            print(f"Downloading {app_name}...")
            with requests.get(url, stream=True) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            if run_installer:
                print(f"Installing {app_name}...")
                run_as_admin(path)
            if after_manual:
                self.after_manual_install()
        except Exception as e:
            self.show_notification(f"Failed to install {app_name}: {e}", error=True)
            if after_manual and self.next_button:
                self.next_button.destroy()
                self.next_button = None

    def show_notification(self, message, error=False):
        self.notification_label.config(text=message, fg="red" if error else "green")
        self.root.after(4000, lambda: self.notification_label.config(text=""))

    def update_mode_explanation(self):
        mode = self.install_mode.get()
        if mode == "auto":
            text = "Auto Install (unsafe): Downloads and installs all selected apps automatically at the same time. You may not see installer windows."
        elif mode == "skip":
            text = "Skip Auto Install: Only downloads the installers and opens the folder. You install them manually."
        elif mode == "manual":
            text = "Manual Step-Through: Installs one app at a time. After each, click 'Next App' to continue."
        else:
            text = ""
        self.mode_explanation.config(text=text)

    def update_edit_mode(self):
        self.update_edit_fields()
        # Show/hide disclaimer based on mode
        if self.edit_mode.get() == 'remove':
            self.disclaimer.pack(side="left", padx=(12, 0))
        else:
            self.disclaimer.pack_forget()
        self.render_app_grid()

    def update_edit_fields(self, event=None):
        mode = self.edit_mode.get()
        name = self.custom_app_fields["name"].get().strip()
        icon_entry = self.custom_app_fields["icon"]
        url_entry = self.custom_app_fields["url"]
        cat_combo = self.custom_app_fields["category"]
        # Only autofill in edit/remove mode if name matches, and don't clear fields in other cases
        found = None
        for cat, apps in apps_by_category.items():
            if name in apps:
                found = (cat, apps[name])
                break
        # Icon preview (next to name)
        icon_path = None
        if found:
            icon_file = found[1].get("icon")
            if icon_file:
                icon_path = os.path.join("icons", icon_file)
        if icon_path and os.path.exists(icon_path):
            from PIL import Image, ImageTk
            img = Image.open(icon_path)
            img = img.resize((20, 20), Image.LANCZOS)
            self.icon_preview_img = ImageTk.PhotoImage(img)
            self.icon_preview.config(image=self.icon_preview_img)
        else:
            self.icon_preview.config(image="")
        # Icon preview (next to icon field)
        icon_field_val = icon_entry.get().strip()
        icon_field_path = os.path.join("icons", icon_field_val) if icon_field_val else None
        if icon_field_path and os.path.exists(icon_field_path):
            from PIL import Image, ImageTk
            img = Image.open(icon_field_path)
            img = img.resize((20, 20), Image.LANCZOS)
            self.icon_preview_img2 = ImageTk.PhotoImage(img)
            self.icon_field_preview.config(image=self.icon_preview_img2)
        else:
            self.icon_field_preview.config(image="")
        if mode == "add":
            icon_entry.config(state="normal")
            url_entry.config(state="normal")
            cat_combo.config(state="readonly")
            self.update_category_combo()
            # Do not clear fields if user is typing name
        elif mode == "edit":
            icon_entry.config(state="normal")
            url_entry.config(state="normal")
            cat_combo.config(state="readonly")
            if found:
                icon_entry.delete(0, tk.END)
                icon_entry.insert(0, found[1].get("icon", ""))
                url_entry.delete(0, tk.END)
                url_entry.insert(0, found[1].get("url", ""))
                self.update_category_combo()
                self.cat_var.set(found[0])
        elif mode == "remove":
            icon_entry.config(state="disabled")
            url_entry.config(state="disabled")
            cat_combo.config(state="disabled")
            if found:
                icon_entry.config(state="normal")
                icon_entry.delete(0, tk.END)
                icon_entry.insert(0, found[1].get("icon", ""))
                icon_entry.config(state="disabled")
                url_entry.config(state="normal")
                url_entry.delete(0, tk.END)
                url_entry.insert(0, found[1].get("url", ""))
                url_entry.config(state="disabled")
                self.update_category_combo()
                self.cat_var.set(found[0])
                cat_combo.config(state="disabled")

    def handle_edit_submit(self):
        mode = self.edit_mode.get()
        name = self.custom_app_fields["name"].get().strip()
        icon = self.custom_app_fields["icon"].get().strip()
        url = self.custom_app_fields["url"].get().strip()
        category = self.cat_var.get().strip() or "Other"
        if not name:
            self.show_notification("Please enter a name.", error=True)
            return
        if mode == "add":
            if not icon or not url or not category:
                self.show_notification("Please fill in all fields.", error=True)
                return
            if category not in apps_by_category:
                from collections import OrderedDict
                apps_by_category[category] = OrderedDict()
            apps_by_category[category][name] = {"url": url, "icon": icon, "category": category}
            self.render_app_grid()
            self.save_json()
            self.show_notification(f"Added {name} to {category}.")
        elif mode == "edit":
            found = None
            for cat, apps in apps_by_category.items():
                if name in apps:
                    found = (cat, apps[name])
                    break
            if not found:
                self.show_notification("App not found to edit.", error=True)
                return
            # Remove from old category if changed
            if found[0] != category:
                del apps_by_category[found[0]][name]
                if not apps_by_category[found[0]]:
                    del apps_by_category[found[0]]
                if category not in apps_by_category:
                    from collections import OrderedDict
                    apps_by_category[category] = OrderedDict()
            apps_by_category[category][name] = {"url": url, "icon": icon, "category": category}
            self.render_app_grid()
            self.save_json()
            self.show_notification(f"Edited {name} in {category}.")
        elif mode == "remove":
            found = None
            for cat, apps in apps_by_category.items():
                if name in apps:
                    found = (cat, apps[name])
                    break
            if not found:
                self.show_notification("App not found to remove.", error=True)
                return
            del apps_by_category[found[0]][name]
            if not apps_by_category[found[0]]:
                del apps_by_category[found[0]]
            self.render_app_grid()
            self.save_json()
            self.show_notification(f"Removed {name} from {found[0]}.")
        # Clear fields after action
        self.custom_app_fields["name"].delete(0, tk.END)
        self.custom_app_fields["icon"].delete(0, tk.END)
        self.custom_app_fields["url"].delete(0, tk.END)
        self.cat_var.set("")
        self.update_edit_fields()

    def choose_icon_file(self):
        from tkinter import filedialog
        file_path = filedialog.askopenfilename(filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.gif;*.bmp")])
        if file_path:
            import shutil, os
            icon_name = os.path.basename(file_path)
            dest_path = os.path.join("icons", icon_name)
            try:
                shutil.copy(file_path, dest_path)
            except Exception:
                pass  # If already exists, ignore
            # Set the icon filename in the icon entry (do not clear other fields)
            self.custom_app_fields["icon"].delete(0, tk.END)
            self.custom_app_fields["icon"].insert(0, icon_name)
            self.icon_file_path = dest_path
            # Show a preview of the image next to the icon field
            from PIL import Image, ImageTk
            img = Image.open(dest_path)
            img = img.resize((20, 20), Image.LANCZOS)
            self.icon_preview_img = ImageTk.PhotoImage(img)
            self.icon_preview.config(image=self.icon_preview_img)

    def add_new_category(self):
        import tkinter.simpledialog
        new_cat = tkinter.simpledialog.askstring("New Category", "Enter new category name:")
        if new_cat:
            cats = list(apps_by_category.keys())
            if new_cat not in cats:
                apps_by_category[new_cat] = {}
            self.update_category_combo()
            self.cat_var.set(new_cat)

    def delete_category_gui(self, cat):
        # Move all apps to 'Uncategorized' instead of deleting them
        uncategorized = 'Uncategorized'
        if uncategorized not in apps_by_category:
            from collections import OrderedDict
            apps_by_category[uncategorized] = OrderedDict()
        for app_name, app_data in list(apps_by_category[cat].items()):
            app_data['category'] = uncategorized
            apps_by_category[uncategorized][app_name] = app_data
        del apps_by_category[cat]
        self.update_category_combo()
        self.cat_var.set(uncategorized)
        self.render_app_grid()
        self.save_json()
        self.show_notification(f"Deleted category: {cat}. Apps moved to 'Uncategorized'.")

    def update_category_combo(self):
        cats = list(apps_by_category.keys())
        self.cat_combo["values"] = cats

if __name__ == "__main__":
    root = tk.Tk()
    root.iconbitmap("boreicon.ico")
    app = AppInstallerGUI(root)
    root.mainloop()
