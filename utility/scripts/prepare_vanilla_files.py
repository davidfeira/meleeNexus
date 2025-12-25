#!/usr/bin/env python3
"""
Copy vanilla costume DAT files from build/files/ to utility/assets/vanilla/{Character}/{CostumeCode}/
"""

import os
import shutil
import re
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent

BUILD_FILES = PROJECT_ROOT / "build" / "files"
VANILLA_DIR = PROJECT_ROOT / "utility" / "assets" / "vanilla"

# Character code to name mapping (reverse of what's in mex_api.py)
CODE_TO_CHARACTER = {
    # Original cast
    "Ca": "C. Falcon",
    "Fc": "Falco",
    "Fx": "Fox",
    "Ms": "Marth",
    "Fe": "Roy",
    "Kp": "Bowser",
    "Dk": "DK",
    "Gn": "Ganondorf",
    "Pr": "Jigglypuff",
    "Kb": "Kirby",
    "Lk": "Link",
    "Lg": "Luigi",
    "Mr": "Mario",
    "Mt": "Mewtwo",
    "Ns": "Ness",
    "Pe": "Peach",
    "Pc": "Pichu",
    "Pk": "Pikachu",
    "Pp": "Ice Climbers",
    "Ss": "Samus",
    "Sk": "Sheik",
    "Ys": "Yoshi",
    "Cl": "Young Link",
    "Zd": "Zelda",
    "Dr": "Dr. Mario",
    "Gw": "G&W",
    # M-ex / additional characters
    "Bo": "Giga Bowser",
    "Ch": "Charizard",
    "Db": "Diddy Kong",
    "Dd": "King Dedede",
    "Gk": "Giga Bowser",
    "Lc": "Lucas",
    "Mh": "Master Hand",
    "Sb": "Sandbag",
    "Sn": "Sonic",
    "Ts": "Tails",
    "Wf": "Wolf",
}

# Pattern: PlXxYy.dat where Xx is char code, Yy is costume code
COSTUME_PATTERN = re.compile(r'^Pl([A-Z][a-z])([A-Z][a-z])\.dat$')

def main():
    if not BUILD_FILES.exists():
        print(f"Error: Build files directory not found: {BUILD_FILES}")
        return

    if not VANILLA_DIR.exists():
        print(f"Error: Vanilla directory not found: {VANILLA_DIR}")
        return

    copied = 0
    skipped = 0
    errors = []

    # Find all Pl*.dat files
    for dat_file in BUILD_FILES.glob("Pl*.dat"):
        filename = dat_file.name

        # Skip animation files (PlXxAJ.dat)
        if "AJ" in filename:
            continue

        # Match costume pattern
        match = COSTUME_PATTERN.match(filename)
        if not match:
            continue

        char_code = match.group(1)
        costume_code = match.group(2)

        # Get character name
        char_name = CODE_TO_CHARACTER.get(char_code)
        if not char_name:
            errors.append(f"Unknown character code: {char_code} ({filename})")
            continue

        # Build destination path
        costume_folder = f"Pl{char_code}{costume_code}"
        dest_dir = VANILLA_DIR / char_name / costume_folder
        dest_file = dest_dir / filename

        # Create directory if needed
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Copy if doesn't exist
        if dest_file.exists():
            skipped += 1
        else:
            shutil.copy2(dat_file, dest_file)
            print(f"Copied: {filename} -> {char_name}/{costume_folder}/")
            copied += 1

    print(f"\nDone! Copied: {copied}, Skipped (already exists): {skipped}")
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for err in errors:
            print(f"  - {err}")

if __name__ == "__main__":
    main()
