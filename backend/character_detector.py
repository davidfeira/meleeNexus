"""
Character Detector - Detects character and costume info from DAT files
"""
import sys
import os
import re
from pathlib import Path
from typing import Optional, Dict, Tuple, List
import zipfile

# Try to import py7zr for 7z support
try:
    import py7zr
    HAS_7Z_SUPPORT = True
except ImportError:
    HAS_7Z_SUPPORT = False

# Add utility scripts to path
SCRIPT_DIR = Path(__file__).parent.parent
UTILITY_DIR = SCRIPT_DIR / "utility" / "website" / "backend" / "tools" / "processor"
sys.path.insert(0, str(UTILITY_DIR))

try:
    from detect_character import DATParser
except ImportError:
    print(f"Warning: Could not import DATParser from {UTILITY_DIR}")
    DATParser = None


def extract_costume_code_from_filename(filename: str) -> Optional[str]:
    """
    Extract Melee costume code (PlXxYy format) from a filename.

    Costume codes follow the pattern: Pl + 2 chars (character) + 2 chars (color)
    Examples: PlFxGr, PlPkBu, PlCaRd, PlMsBu, PlGwWh

    Args:
        filename: The filename to search for a costume code

    Returns:
        Costume code if found (preserves case), None otherwise
    """
    # Pattern: Pl + 2 letters + 2 letters (case-insensitive search)
    pattern = r'[Pp][Ll]([A-Za-z]{2})([A-Za-z]{2})'
    match = re.search(pattern, filename)
    if match:
        # Return the matched costume code (preserving original case from filename)
        return match.group(0)
    return None


def get_image_dimensions(archive, filename, is_7z=False):
    """
    Get dimensions of an image from an archive without fully extracting it.

    Args:
        archive: The open archive (ZipFile or SevenZipFile)
        filename: The filename inside the archive
        is_7z: Whether this is a 7z archive

    Returns:
        Tuple of (width, height) or None if unable to read
    """
    try:
        from PIL import Image
        import io

        # Read image data from archive
        if is_7z:
            file_data = archive.read([filename])
            image_bytes = file_data[filename].read()
        else:
            image_bytes = archive.read(filename)

        # Open with PIL to get dimensions
        img = Image.open(io.BytesIO(image_bytes))
        dimensions = img.size
        img.close()
        return dimensions
    except Exception as e:
        return None


def build_image_indexes(archive, filenames: list, is_7z=False) -> tuple:
    """
    Build dual indexes for CSPs and stocks from ZIP file list.

    Args:
        archive: The open archive (ZipFile or SevenZipFile)
        filenames: List of all filenames in ZIP
        is_7z: Whether this is a 7z archive

    Returns:
        Tuple of (csps_by_name, csps_by_path, csps_by_costume, stocks_by_name, stocks_by_path, stocks_by_costume)
        Each is a dict mapping to file info. costume indexes map costume code -> list of matching files
    """
    csps_by_name = {}
    csps_by_path = {}
    csps_by_costume = {}  # costume_code -> list of file info
    stocks_by_name = {}
    stocks_by_path = {}
    stocks_by_costume = {}  # costume_code -> list of file info

    image_extensions = {'.png', '.jpg', '.jpeg'}

    # Target aspect ratios
    CSP_ASPECT_RATIO = 136 / 188  # 0.723 (portrait)
    STOCK_ASPECT_RATIO = 1.0  # Square-ish

    for filename in filenames:
        ext = os.path.splitext(filename)[1].lower()
        if ext not in image_extensions:
            continue

        basename = os.path.splitext(os.path.basename(filename))[0].lower()
        folder = os.path.dirname(filename)

        # Extract costume code from filename (case-insensitive)
        costume_code = extract_costume_code_from_filename(filename)
        if costume_code:
            # Normalize to consistent case for indexing
            costume_code = costume_code.upper()

        # Get image dimensions and aspect ratio
        dimensions = get_image_dimensions(archive, filename, is_7z)
        aspect_ratio = None
        aspect_ratio_score_csp = float('inf')
        aspect_ratio_score_stock = float('inf')

        if dimensions:
            width, height = dimensions
            if height > 0:
                aspect_ratio = width / height
                # Calculate how close this image is to ideal CSP/stock ratios
                aspect_ratio_score_csp = abs(aspect_ratio - CSP_ASPECT_RATIO)
                aspect_ratio_score_stock = abs(aspect_ratio - STOCK_ASPECT_RATIO)

        info = {
            'filename': filename,
            'folder': folder,
            'basename': basename,
            'costume_code': costume_code,
            'dimensions': dimensions,
            'aspect_ratio': aspect_ratio,
            'aspect_ratio_score_csp': aspect_ratio_score_csp,
            'aspect_ratio_score_stock': aspect_ratio_score_stock
        }

        # Determine if CSP or stock by filename patterns
        basename_lower = basename.lower()
        if any(pattern in basename_lower for pattern in ['csp', 'portrait', 'icon']) and 'stock' not in basename_lower:
            csps_by_name[basename] = info
            csps_by_path[filename] = info
            # Add to costume index
            if costume_code:
                if costume_code not in csps_by_costume:
                    csps_by_costume[costume_code] = []
                csps_by_costume[costume_code].append(info)
        elif any(pattern in basename_lower for pattern in ['stc', 'stock']):
            stocks_by_name[basename] = info
            stocks_by_path[filename] = info
            # Add to costume index
            if costume_code:
                if costume_code not in stocks_by_costume:
                    stocks_by_costume[costume_code] = []
                stocks_by_costume[costume_code].append(info)
        else:
            # Default: Check aspect ratio to determine if CSP or stock
            # If aspect ratio is closer to CSP (portrait), treat as CSP
            # If closer to stock (square), treat as stock
            if aspect_ratio_score_csp < aspect_ratio_score_stock:
                csps_by_name[basename] = info
                csps_by_path[filename] = info
                # Add to costume index
                if costume_code:
                    if costume_code not in csps_by_costume:
                        csps_by_costume[costume_code] = []
                    csps_by_costume[costume_code].append(info)
            else:
                stocks_by_name[basename] = info
                stocks_by_path[filename] = info
                # Add to costume index
                if costume_code:
                    if costume_code not in stocks_by_costume:
                        stocks_by_costume[costume_code] = []
                    stocks_by_costume[costume_code].append(info)

    return csps_by_name, csps_by_path, csps_by_costume, stocks_by_name, stocks_by_path, stocks_by_costume


def detect_character_from_zip(zip_path: str) -> List[Dict]:
    """
    Detect character information from a ZIP/7z file containing character costumes.
    Now supports multiple DATs in one archive and 7z files.

    Args:
        zip_path: Path to the ZIP or 7z file

    Returns:
        List of dicts with character info. Empty list if none detected.
        Each dict contains:
        {
            'character': 'Fox',
            'color': 'Green',
            'costume_code': 'PlFxGr',
            'dat_file': 'PlFxGr.dat',
            'csp_file': 'csp.png' or None,
            'stock_file': 'stc.png' or None,
            'folder': 'green_fox/' or ''
        }
    """
    if not DATParser:
        print("DATParser not available")
        return []

    # Detect archive type
    is_7z = zip_path.lower().endswith('.7z')

    if is_7z and not HAS_7Z_SUPPORT:
        print("7z file provided but py7zr not installed")
        return []

    try:
        # Open appropriate archive type
        if is_7z:
            archive = py7zr.SevenZipFile(zip_path, 'r')
            filenames = archive.getnames()
        else:
            archive = zipfile.ZipFile(zip_path, 'r')
            filenames = archive.namelist()

        # Find ALL .dat files
        dat_files = [f for f in filenames if f.endswith('.dat')]
        if not dat_files:
            if not is_7z:
                archive.close()
            return []

        # Build dual indexes for smart matching
        csps_by_name, csps_by_path, csps_by_costume, stocks_by_name, stocks_by_path, stocks_by_costume = build_image_indexes(archive, filenames, is_7z)

        results = []
        import tempfile

        # Track which images have been used to prevent double-matching
        used_csp_files = set()
        used_stock_files = set()

        # Process each DAT file
        for dat_filename in dat_files:
            # Extract DAT to temp location for parsing
            with tempfile.NamedTemporaryFile(suffix='.dat', delete=False) as tmp:
                # Read file data from appropriate archive type
                if is_7z:
                    file_data = archive.read([dat_filename])
                    tmp.write(file_data[dat_filename].read())
                else:
                    tmp.write(archive.read(dat_filename))
                tmp_path = tmp.name

            try:
                # Parse DAT file
                parser = DATParser(tmp_path)
                parser.read_dat()

                character, symbol = parser.detect_character()
                if not character:
                    continue

                # Check if it's a costume (has Ply symbol) vs data mod (only ftData)
                has_ply_symbol = any('Ply' in node['symbol'] for node in parser.root_nodes)
                if not has_ply_symbol:
                    # This is a data/effect mod, not a costume
                    continue

                color_info = parser.detect_costume_color()
                costume_code = parser.get_character_filename()

                # Get folder context for this DAT
                dat_folder = os.path.dirname(dat_filename)
                dat_basename = os.path.splitext(os.path.basename(dat_filename))[0].lower()

                # Count DATs in this folder (used by both CSP and stock matching)
                dats_in_folder = sum(1 for d in dat_files if os.path.dirname(d) == dat_folder)

                # FOUR-TIER MATCHING for CSP
                csp_file = None

                # Tier 0: Exact/similar filename match (best match)
                # Match DAT basename with CSP basename (removing csp_ prefix)
                for csp_path, csp_info in csps_by_path.items():
                    if csp_path in used_csp_files:
                        continue
                    # Remove common CSP prefixes from the basename
                    csp_basename_clean = csp_info['basename'].replace('csp_', '').replace('portrait_', '').replace('icon_', '')
                    # Check if basenames match (both already lowercased)
                    if csp_basename_clean == dat_basename:
                        csp_file = csp_info['filename']
                        break

                # Tier 1: Costume code match
                if not csp_file and costume_code:
                    costume_code_upper = costume_code.upper()
                    if costume_code_upper in csps_by_costume:
                        candidates = csps_by_costume[costume_code_upper]
                        # Filter out already-used CSPs
                        available_candidates = [c for c in candidates if c['filename'] not in used_csp_files]
                        if available_candidates:
                            # Sort by aspect ratio score (best match first)
                            available_candidates.sort(key=lambda x: x['aspect_ratio_score_csp'])

                            # If multiple CSPs match, prefer same folder with best aspect ratio
                            same_folder = [c for c in available_candidates if c['folder'] == dat_folder]
                            if same_folder:
                                csp_file = same_folder[0]['filename']
                            else:
                                # Use best aspect ratio match
                                csp_file = available_candidates[0]['filename']

                # Tier 2: Same-folder match
                if not csp_file:
                    if dats_in_folder == 1:
                        # Only 1 DAT in this folder - match CSP from same folder with best aspect ratio
                        same_folder_csps = [info for path, info in csps_by_path.items()
                                          if info['folder'] == dat_folder and path not in used_csp_files]
                        if same_folder_csps:
                            # Sort by aspect ratio score (best match first)
                            same_folder_csps.sort(key=lambda x: x['aspect_ratio_score_csp'])
                            csp_file = same_folder_csps[0]['filename']

                # Tier 3: Global fallback (single DAT in entire ZIP)
                if not csp_file and len(dat_files) == 1 and csps_by_path:
                    # Take CSP with best aspect ratio
                    available_csps = [info for path, info in csps_by_path.items() if path not in used_csp_files]
                    if available_csps:
                        # Sort by aspect ratio score (best match first)
                        available_csps.sort(key=lambda x: x['aspect_ratio_score_csp'])
                        csp_file = available_csps[0]['filename']

                # FOUR-TIER MATCHING for Stock
                stock_file = None

                # Tier 0: Exact/similar filename match (best match)
                # Match DAT basename with stock basename (removing stock_ prefix)
                for stock_path, stock_info in stocks_by_path.items():
                    if stock_path in used_stock_files:
                        continue
                    # Remove common stock prefixes from the basename
                    stock_basename_clean = stock_info['basename'].replace('stock_', '').replace('stc_', '')
                    # Check if basenames match (both already lowercased)
                    if stock_basename_clean == dat_basename:
                        stock_file = stock_info['filename']
                        break

                # Tier 1: Costume code match
                if not stock_file and costume_code:
                    costume_code_upper = costume_code.upper()
                    if costume_code_upper in stocks_by_costume:
                        candidates = stocks_by_costume[costume_code_upper]
                        # Filter out already-used stocks
                        available_candidates = [c for c in candidates if c['filename'] not in used_stock_files]
                        if available_candidates:
                            # Sort by aspect ratio score (best match first)
                            available_candidates.sort(key=lambda x: x['aspect_ratio_score_stock'])

                            # If multiple stocks match, prefer same folder with best aspect ratio
                            same_folder = [c for c in available_candidates if c['folder'] == dat_folder]
                            if same_folder:
                                stock_file = same_folder[0]['filename']
                            else:
                                # Use best aspect ratio match
                                stock_file = available_candidates[0]['filename']

                # Tier 2: Same-folder match
                if not stock_file and dats_in_folder == 1:
                    # Only 1 DAT in this folder - match stock from same folder with best aspect ratio
                    same_folder_stocks = [info for path, info in stocks_by_path.items()
                                        if info['folder'] == dat_folder and path not in used_stock_files]
                    if same_folder_stocks:
                        # Sort by aspect ratio score (best match first)
                        same_folder_stocks.sort(key=lambda x: x['aspect_ratio_score_stock'])
                        stock_file = same_folder_stocks[0]['filename']

                # Tier 3: Global fallback (single DAT in entire ZIP)
                if not stock_file and len(dat_files) == 1 and stocks_by_path:
                    # Take stock with best aspect ratio
                    available_stocks = [info for path, info in stocks_by_path.items() if path not in used_stock_files]
                    if available_stocks:
                        # Sort by aspect ratio score (best match first)
                        available_stocks.sort(key=lambda x: x['aspect_ratio_score_stock'])
                        stock_file = available_stocks[0]['filename']

                # Normalize character name
                if character in ['Ice Climbers (Nana)', 'Ice Climbers (Popo)']:
                    character = 'Ice Climbers'

                results.append({
                    'character': character,
                    'color': color_info if color_info else 'Custom',
                    'costume_code': costume_code,
                    'dat_file': dat_filename,
                    'csp_file': csp_file,
                    'stock_file': stock_file,
                    'symbol': symbol,
                    'folder': dat_folder
                })

                # Mark matched files as used to prevent double-matching
                if csp_file:
                    used_csp_files.add(csp_file)
                if stock_file:
                    used_stock_files.add(stock_file)

            finally:
                # Clean up temp file
                try:
                    os.unlink(tmp_path)
                except:
                    pass

        # Close archive before returning
        if not is_7z:
            archive.close()

        # Post-process Ice Climbers: Match Popo with Nana pairs
        processed_results = []
        ice_climbers_entries = [r for r in results if r['character'] == 'Ice Climbers']
        other_entries = [r for r in results if r['character'] != 'Ice Climbers']

        if ice_climbers_entries:
            # Separate Popo and Nana
            popo_entries = [r for r in ice_climbers_entries if 'PlPp' in r.get('costume_code', '')]
            nana_entries = [r for r in ice_climbers_entries if 'PlNn' in r.get('costume_code', '')]

            # Color mapping: Popo color -> Nana color
            POPO_TO_NANA = {
                'Default': 'Default',
                'Red': 'White',
                'Orange': 'Aqua/Light Blue',
                'Green': 'Yellow',
            }
            NANA_TO_POPO = {v: k for k, v in POPO_TO_NANA.items()}

            paired_nanas = set()

            # Match each Popo with Nana
            for popo in popo_entries:
                expected_nana_color = POPO_TO_NANA.get(popo['color'])
                matching_nana = None

                if expected_nana_color:
                    for nana in nana_entries:
                        if nana['color'] == expected_nana_color and id(nana) not in paired_nanas:
                            matching_nana = nana
                            paired_nanas.add(id(nana))
                            break

                # Only add if paired (skip unpaired)
                if matching_nana:
                    # Mark Popo entry
                    popo['is_popo'] = True
                    popo['is_nana'] = False
                    popo['pair_dat_file'] = matching_nana['dat_file']
                    popo['pair_color'] = matching_nana['color']
                    popo['pair_costume_code'] = matching_nana['costume_code']
                    processed_results.append(popo)

                    # Mark Nana entry
                    matching_nana['is_nana'] = True
                    matching_nana['is_popo'] = False
                    matching_nana['pair_dat_file'] = popo['dat_file']
                    matching_nana['pair_color'] = popo['color']
                    matching_nana['pair_costume_code'] = popo['costume_code']
                    processed_results.append(matching_nana)

        processed_results.extend(other_entries)
        return processed_results

    except Exception as e:
        print(f"Error detecting character from {zip_path}: {e}")
        return []


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
