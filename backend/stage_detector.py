"""
Stage Detector - Detects which stage a mod is for based on filename patterns
"""
import os
import zipfile
from pathlib import Path
from typing import Optional, Dict, List, Tuple

# Stage code to folder name mapping
STAGE_MAPPING = {
    'GrNBa': {'name': 'Battlefield', 'folder': 'battlefield'},
    'GrNLa': {'name': 'Final Destination', 'folder': 'final_destination'},
    'GrSt': {'name': "Yoshi's Story", 'folder': 'yoshis_story'},
    'GrOp': {'name': 'Dreamland', 'folder': 'dreamland'},
    'GrPs': {'name': 'Pokemon Stadium', 'folder': 'pokemon_stadium'},
    'GrIz': {'name': 'Fountain of Dreams', 'folder': 'fountain_of_dreams'}
}


def detect_stage_from_zip(zip_path: str) -> Optional[Dict]:
    """
    Detect which stage this mod is for by scanning the ZIP contents.

    Args:
        zip_path: Path to the ZIP file

    Returns:
        Dict with stage info if detected, None otherwise:
        {
            'stage_code': 'GrNBa',
            'stage_name': 'Battlefield',
            'folder': 'battlefield',
            'stage_file': 'GrNBa.dat',
            'screenshot': 'screenshot.png' or None,
            'extension': '.dat' or '.usd'
        }
    """
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            filenames = zf.namelist()

            # Search for stage files
            for filename in filenames:
                basename = os.path.basename(filename)
                name_upper = basename.upper()

                # Check for stage patterns
                for stage_code, stage_info in STAGE_MAPPING.items():
                    if stage_code.upper() in name_upper:
                        # Found a matching stage code
                        file_ext = os.path.splitext(basename)[1].lower()

                        # Validate extension (.dat or .usd)
                        if file_ext in ['.dat', '.usd']:
                            # Pokemon Stadium can be .usd or .dat
                            if stage_code == 'GrPs' and file_ext not in ['.dat', '.usd']:
                                continue
                            # All other stages must be .dat
                            elif stage_code != 'GrPs' and file_ext != '.dat':
                                continue

                            # Find screenshot
                            screenshot = find_screenshot_in_zip(zf, filenames)

                            return {
                                'stage_code': stage_code,
                                'stage_name': stage_info['name'],
                                'folder': stage_info['folder'],
                                'stage_file': filename,
                                'screenshot': screenshot,
                                'extension': file_ext
                            }

        return None

    except Exception as e:
        print(f"Error detecting stage from {zip_path}: {e}")
        return None


def find_screenshot_in_zip(zf: zipfile.ZipFile, filenames: List[str]) -> Optional[str]:
    """
    Find a screenshot image in the ZIP file.

    Priority:
    1. Files named screenshot/preview/stage/icon
    2. First image file found

    Args:
        zf: ZipFile object
        filenames: List of filenames in the ZIP

    Returns:
        Filename of screenshot, or None
    """
    image_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
    priority_names = ['screenshot', 'preview', 'stage', 'icon', 'banner']

    # First pass: Look for priority names
    for filename in filenames:
        basename = os.path.basename(filename).lower()
        name_without_ext = os.path.splitext(basename)[0]
        ext = os.path.splitext(basename)[1].lower()

        if ext in image_extensions:
            if name_without_ext in priority_names:
                return filename

    # Second pass: Return first image found
    for filename in filenames:
        ext = os.path.splitext(filename)[1].lower()
        if ext in image_extensions:
            return filename

    return None


def extract_stage_files(zip_path: str, stage_info: Dict, output_dir: Path) -> Tuple[Path, Optional[Path]]:
    """
    Extract stage file and screenshot from ZIP.

    Args:
        zip_path: Path to ZIP file
        stage_info: Stage detection info from detect_stage_from_zip()
        output_dir: Directory to extract to

    Returns:
        Tuple of (stage_file_path, screenshot_path)
        screenshot_path can be None if no screenshot found
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as zf:
        # Extract stage file
        stage_file_data = zf.read(stage_info['stage_file'])
        stage_file_path = output_dir / os.path.basename(stage_info['stage_file'])
        stage_file_path.write_bytes(stage_file_data)

        # Extract screenshot if available
        screenshot_path = None
        if stage_info['screenshot']:
            screenshot_data = zf.read(stage_info['screenshot'])
            # Save with standardized name
            screenshot_ext = os.path.splitext(stage_info['screenshot'])[1]
            screenshot_path = output_dir / f"screenshot{screenshot_ext}"
            screenshot_path.write_bytes(screenshot_data)

    return stage_file_path, screenshot_path


def get_stage_code_from_name(stage_name: str) -> Optional[str]:
    """
    Get stage code from friendly name.

    Args:
        stage_name: Friendly name like "Battlefield"

    Returns:
        Stage code like "GrNBa", or None
    """
    for code, info in STAGE_MAPPING.items():
        if info['name'].lower() == stage_name.lower():
            return code
    return None


def is_stage_file(filename: str) -> bool:
    """
    Check if a filename appears to be a stage file.

    Args:
        filename: Filename to check

    Returns:
        True if looks like a stage file
    """
    name_upper = filename.upper()
    ext = os.path.splitext(filename)[1].lower()

    # Check extension
    if ext not in ['.dat', '.usd']:
        return False

    # Check for stage codes
    for stage_code in STAGE_MAPPING.keys():
        if stage_code.upper() in name_upper:
            return True

    return False
