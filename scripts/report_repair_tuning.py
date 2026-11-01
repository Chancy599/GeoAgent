"""Build the current geometry result report."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.report_geometry_best import main

if __name__=="__main__":
    main()
