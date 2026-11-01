"""Build the current geometry and visual report."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.report_core_geometry import main

if __name__ == "__main__":
    main()
