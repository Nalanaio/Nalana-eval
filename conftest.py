import sys
from pathlib import Path

# Ensure the project root is on sys.path so `nalana_eval` is importable
sys.path.insert(0, str(Path(__file__).parent))

# Prevent pytest from importing the v2.0 root __init__.py as a package init.
# That file uses relative imports which break when executed outside a package.
collect_ignore = ["__init__.py"]
