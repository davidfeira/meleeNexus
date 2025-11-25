"""
Stage Detector - Detects which stage a mod is for based on filename patterns
"""
import os
import re
import zipfile
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Set
from PIL import Image
from io import BytesIO

# Stage code to folder name mapping
STAGE_MAPPING = {
    'GrNBa': {'name': 'Battlefield', 'folder': 'battlefield'},
    'GrNLa': {'name': 'Final Destination', 'folder': 'final_destination'},
    'GrSt': {'name': "Yoshi's Story", 'folder': 'yoshis_story'},
    'GrOp': {'name': 'Dreamland', 'folder': 'dreamland'},
    'GrPs': {'name': 'Pokemon Stadium', 'folder': 'pokemon_stadium'},
    'GrIz': {'name': 'Fountain of Dreams', 'folder': 'fountain_of_dreams'}
}


def extract_stage_code_from_filename(filename: str) -> Optional[str]:
    """
    Extract stage code (GrNBa, GrPs, etc.) from a filename.

    Args:
        filename: Filename to extract from (can be full path)

    Returns:
        Stage code if found, None otherwise
    """
    basename = os.path.basename(filename).upper()

    # Try to find any stage code in the filename
    for stage_code in STAGE_MAPPING.keys():
        if stage_code.upper() in basename:
            return stage_code

    return None


def build_screenshot_indexes(zf: zipfile.ZipFile, filenames: List[str]) -> Tuple[Dict, Dict, Dict]:
    """
    Build indexes of screenshots for smart matching.

    Similar to character_detector.build_image_indexes() but for stage screenshots.

    Args:
        zf: ZipFile object
        filenames: List of filenames in ZIP

    Returns:
        Tuple of (screenshots_by_name, screenshots_by_code, screenshots_by_folder)
    """
    image_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'}

    screenshots_by_name = {}  # Cleaned basename -> (filename, aspect_ratio)
    screenshots_by_code = {}  # Stage code -> [(filename, aspect_ratio, folder)]
    screenshots_by_folder = {}  # Folder path -> [(filename, aspect_ratio)]

    for filename in filenames:
        # Skip directories
        if filename.endswith('/'):
            continue

        ext = os.path.splitext(filename)[1].lower()
        if ext not in image_extensions:
            continue

        # Get image dimensions for aspect ratio scoring
        try:
            img_data = zf.read(filename)
            img = Image.open(BytesIO(img_data))
            width, height = img.size
            aspect_ratio = width / height if height > 0 else 0
        except Exception:
            aspect_ratio = 0

        # Index by cleaned name
        basename = os.path.basename(filename)
        name_without_ext = os.path.splitext(basename)[0].lower()

        # Remove common prefixes
        for prefix in ['screenshot_', 'preview_', 'stage_', 'icon_', 'banner_']:
            if name_without_ext.startswith(prefix):
                name_without_ext = name_without_ext[len(prefix):]
                break

        screenshots_by_name[name_without_ext] = (filename, aspect_ratio)

        # Index by stage code
        stage_code = extract_stage_code_from_filename(filename)
        if stage_code:
            if stage_code not in screenshots_by_code:
                screenshots_by_code[stage_code] = []
            folder = os.path.dirname(filename)
            screenshots_by_code[stage_code].append((filename, aspect_ratio, folder))

        # Index by folder
        folder = os.path.dirname(filename)
        if folder not in screenshots_by_folder:
            screenshots_by_folder[folder] = []
        screenshots_by_folder[folder].append((filename, aspect_ratio))

    return screenshots_by_name, screenshots_by_code, screenshots_by_folder


def detect_stage_from_zip(zip_path: str) -> List[Dict]:
    """
    Detect stage mods in a ZIP file. Supports multiple stages per ZIP.

    Uses intelligent screenshot matching similar to character detection:
    - Tier 0: Exact filename match (screenshot_grnba.png -> GrNBa.dat)
    - Tier 1: Stage code match (extracts GrNBa from image filename)
    - Tier 2: Same-folder match (if only 1 stage in folder)
    - Tier 3: Global fallback (if only 1 stage in entire ZIP)

    Args:
        zip_path: Path to the ZIP file

    Returns:
        List of stage info dicts (empty list if none found):
        [{
            'stage_code': 'GrNBa',
            'stage_name': 'Battlefield',
            'folder': 'battlefield',
            'stage_file': 'GrNBa.dat',
            'screenshot': 'screenshot.png' or None,
            'extension': '.dat' or '.usd'
        }, ...]
    """
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            filenames = zf.namelist()

            # Find all stage files in the ZIP
            stage_files = []
            for filename in filenames:
                # Skip directories
                if filename.endswith('/'):
                    continue

                basename = os.path.basename(filename)
                name_upper = basename.upper()
                file_ext = os.path.splitext(basename)[1].lower()

                # Check for stage patterns
                for stage_code, stage_info in STAGE_MAPPING.items():
                    if stage_code.upper() in name_upper:
                        # Validate extension based on stage
                        # Pokemon Stadium (GrPs) uses .usd files
                        # All other stages use .dat files
                        if stage_code == 'GrPs':
                            if file_ext != '.usd':
                                continue
                        else:
                            if file_ext != '.dat':
                                continue

                        stage_files.append({
                            'filename': filename,
                            'stage_code': stage_code,
                            'stage_info': stage_info,
                            'extension': file_ext
                        })
                        break  # Found stage code, don't check other codes

            # If no stages found, return empty list
            if not stage_files:
                return []

            # Build screenshot indexes for smart matching
            screenshots_by_name, screenshots_by_code, screenshots_by_folder = build_screenshot_indexes(zf, filenames)

            # Track used screenshots to prevent double-matching
            used_screenshots: Set[str] = set()

            # Match screenshots to each stage using four-tier system
            results = []
            for stage_file_info in stage_files:
                filename = stage_file_info['filename']
                stage_code = stage_file_info['stage_code']
                stage_info = stage_file_info['stage_info']
                file_ext = stage_file_info['extension']

                screenshot = None
                match_tier = None

                # Get context for this stage file
                basename = os.path.basename(filename)
                name_without_ext = os.path.splitext(basename)[0].lower()
                folder = os.path.dirname(filename)

                # TIER 0: Exact filename match
                # e.g., "GrNBa.dat" matches with "grnba.png" or "screenshot_grnba.png"
                if name_without_ext in screenshots_by_name:
                    candidate_file, aspect_ratio = screenshots_by_name[name_without_ext]
                    if candidate_file not in used_screenshots:
                        screenshot = candidate_file
                        match_tier = 0

                # TIER 1: Stage code match
                # e.g., "screenshot_grnba.png" or "grnba_preview.png" -> GrNBa.dat
                if screenshot is None and stage_code in screenshots_by_code:
                    candidates = screenshots_by_code[stage_code]
                    # Filter out already used
                    candidates = [(f, ar, fld) for f, ar, fld in candidates if f not in used_screenshots]
                    if candidates:
                        # Prefer same folder if available
                        same_folder = [c for c in candidates if c[2] == folder]
                        if same_folder:
                            screenshot = same_folder[0][0]
                        else:
                            screenshot = candidates[0][0]
                        match_tier = 1

                # TIER 2: Same-folder match (only if single stage in folder)
                if screenshot is None and folder:
                    stages_in_folder = [sf for sf in stage_files if os.path.dirname(sf['filename']) == folder]
                    if len(stages_in_folder) == 1:
                        # Only one stage in this folder, can safely match any screenshot from folder
                        if folder in screenshots_by_folder:
                            candidates = screenshots_by_folder[folder]
                            # Filter out already used
                            candidates = [(f, ar) for f, ar in candidates if f not in used_screenshots]
                            if candidates:
                                # Pick best aspect ratio (prefer 16:9 = 1.777 for stages)
                                candidates_sorted = sorted(candidates, key=lambda x: abs(x[1] - 1.777))
                                screenshot = candidates_sorted[0][0]
                                match_tier = 2

                # TIER 3: Global fallback (only if single stage in entire ZIP)
                if screenshot is None and len(stage_files) == 1:
                    # Only one stage in entire ZIP, can use any screenshot
                    all_screenshots = []
                    for folder_path, screenshots in screenshots_by_folder.items():
                        all_screenshots.extend(screenshots)
                    # Filter out already used
                    all_screenshots = [(f, ar) for f, ar in all_screenshots if f not in used_screenshots]
                    if all_screenshots:
                        # Pick best aspect ratio
                        all_screenshots_sorted = sorted(all_screenshots, key=lambda x: abs(x[1] - 1.777))
                        screenshot = all_screenshots_sorted[0][0]
                        match_tier = 3

                # Mark screenshot as used
                if screenshot:
                    used_screenshots.add(screenshot)

                results.append({
                    'stage_code': stage_code,
                    'stage_name': stage_info['name'],
                    'folder': stage_info['folder'],
                    'stage_file': filename,
                    'screenshot': screenshot,
                    'extension': file_ext
                })

            return results

    except Exception as e:
        print(f"Error detecting stages from {zip_path}: {e}")
        import traceback
        traceback.print_exc()
        return []


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
    image_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'}
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

    # Check for stage codes and validate extension
    for stage_code in STAGE_MAPPING.keys():
        if stage_code.upper() in name_upper:
            # Pokemon Stadium (GrPs) uses .usd files
            # All other stages use .dat files
            if stage_code == 'GrPs':
                return ext == '.usd'
            else:
                return ext == '.dat'

    return False
