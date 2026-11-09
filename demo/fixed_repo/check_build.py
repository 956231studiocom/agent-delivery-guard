import os, sys
sys.exit(0 if os.path.exists(os.path.join(os.path.dirname(__file__), "dist", "bundle.js")) else 1)
