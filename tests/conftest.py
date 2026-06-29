import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Nur das headless User-Plugin (das volle plugin.py zieht Selenium nach)
pytest_plugins = ["nicegui.testing.user_plugin"]
