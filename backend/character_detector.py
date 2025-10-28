"""
Character Detector - Detects character and costume info from DAT files
"""
import sys
import os
from pathlib import Path
from typing import Optional, Dict, Tuple
import zipfile

# Add utility scripts to path
SCRIPT_DIR = Path(__file__).parent.parent
UTILITY_DIR = SCRIPT_DIR / "utility" / "website" / "backend" / "tools" / "processor"
sys.path.insert(0, str(UTILITY_DIR))

try:
    from detect_character import DATParser
except ImportError:
    print(f"Warning: Could not import DATParser from {UTILITY_DIR}")
    DATParser = None


def detect_character_from_zip(zip_path: str) -> Optional[Dict]:
    """
    Detect character information from a ZIP file containing a character costume.

    Args:
        zip_path: Path to the ZIP file

    Returns:
        Dict with character info if detected, None otherwise:
        {
            'character': 'Fox',
            'color': 'Green',
            'costume_code': 'PlFxGr',
            'dat_file': 'PlFxGr.dat',
            'csp_file': 'csp.png' or None,
            'stock_file': 'stc.png' or None
        }
    """
    if not DATParser:
        print("DATParser not available")
        return None

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            filenames = zf.namelist()

            # Find .dat file
            dat_files = [f for f in filenames if f.endswith('.dat')]
            if not dat_files:
                return None

            dat_filename = dat_files[0]

            # Extract DAT to temp location for parsing
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.dat', delete=False) as tmp:
                tmp.write(zf.read(dat_filename))
                tmp_path = tmp.name

            try:
                # Parse DAT file
                parser = DATParser(tmp_path)
                parser.read_dat()

                character, symbol = parser.detect_character()
                if not character:
                    return None

                # Check if it's a costume (has Ply symbol) vs data mod (only ftData)
                has_ply_symbol = any('Ply' in node['symbol'] for node in parser.root_nodes)
                if not has_ply_symbol:
                    # This is a data/effect mod, not a costume
                    return None

                color_info = parser.detect_costume_color()
                costume_code = parser.get_character_filename()

                # Find CSP and stock in ZIP
                csp_file = find_image_in_zip(filenames, ['csp', 'portrait', 'icon'])
                stock_file = find_image_in_zip(filenames, ['stc', 'stock', 'icon'], exclude=['csp'])

                # Normalize character name
                if character in ['Ice Climbers (Nana)', 'Ice Climbers (Popo)']:
                    character = 'Ice Climbers'

                return {
                    'character': character,
                    'color': color_info.get('color', 'Custom') if color_info else 'Custom',
                    'costume_code': costume_code,
                    'dat_file': dat_filename,
                    'csp_file': csp_file,
                    'stock_file': stock_file,
                    'symbol': symbol
                }

            finally:
                # Clean up temp file
                try:
                    os.unlink(tmp_path)
                except:
                    pass

    except Exception as e:
        print(f"Error detecting character from {zip_path}: {e}")
        return None


def find_image_in_zip(filenames: list, preferred_names: list, exclude: list = None) -> Optional[str]:
    """
    Find an image file in the ZIP based on preferred names.

    Args:
        filenames: List of filenames in ZIP
        preferred_names: List of preferred name patterns (e.g., ['csp', 'portrait'])
        exclude: List of patterns to exclude

    Returns:
        Filename of matched image, or None
    """
    image_extensions = {'.png', '.jpg', '.jpeg'}
    exclude = exclude or []

    # First pass: Look for preferred names
    for filename in filenames:
        basename = os.path.basename(filename).lower()
        name_without_ext = os.path.splitext(basename)[0]
        ext = os.path.splitext(basename)[1].lower()

        if ext in image_extensions:
            # Check exclusions
            if any(excl.lower() in basename for excl in exclude):
                continue

            # Check preferred names
            for preferred in preferred_names:
                if preferred.lower() in basename:
                    return filename

    # Second pass: Return first image not in exclusions
    for filename in filenames:
        ext = os.path.splitext(filename)[1].lower()
        basename = os.path.basename(filename).lower()

        if ext in image_extensions:
            if not any(excl.lower() in basename for excl in exclude):
                return filename

    return None


def is_character_costume(dat_path: str) -> bool:
    """
    Check if a DAT file is a character costume (vs data/effect mod).

    Args:
        dat_path: Path to DAT file

    Returns:
        True if it's a character costume file
    """
    if not DATParser:
        return False

    try:
        parser = DATParser(dat_path)
        parser.read_dat()

        # Check for Ply symbols (character costumes have these)
        has_ply_symbol = any('Ply' in node['symbol'] for node in parser.root_nodes)
        return has_ply_symbol

    except:
        return False
