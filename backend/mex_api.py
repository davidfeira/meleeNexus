"""
MEX API Backend - Flask server for MexManager operations

Provides REST API endpoints for costume import and ISO export operations.
"""

from flask import Flask, jsonify, request, send_file, after_this_request
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import os
import sys
import time
from pathlib import Path
import json
import threading
import subprocess
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import tempfile
import shutil
import zipfile
import re
from werkzeug.utils import secure_filename
import signal
import atexit

# Add scripts/tools to path for mex_bridge import
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "tools"))
from mex_bridge import MexManager, MexManagerError

# Configuration
if getattr(sys, 'frozen', False):
    # Running as bundled exe
    # When installed: C:\Users\...\AppData\Local\Programs\Melee Nexus\resources\backend\mex_backend.exe
    EXE_PATH = Path(sys.executable)
    RESOURCES_DIR = EXE_PATH.parent.parent  # resources/

    # For user data, detect if running in AppImage (Linux read-only mount)
    if os.name != 'nt' and '/tmp/.mount_' in str(EXE_PATH):
        # AppImage: Use home directory for writable data
        PROJECT_ROOT = Path.home() / '.melee-nexus'
        PROJECT_ROOT.mkdir(exist_ok=True)
    else:
        # Windows installer: Use the app's installation root
        PROJECT_ROOT = RESOURCES_DIR.parent  # Melee Nexus/
else:
    # Running as Python script
    PROJECT_ROOT = Path(__file__).parent.parent

# Add backend directory to path for detectors
BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKEND_DIR))
from character_detector import detect_character_from_zip, DATParser
from stage_detector import detect_stage_from_zip, extract_stage_files

# Add processor tools to path for CSP generation and slippi validation
if getattr(sys, 'frozen', False):
    # Running as bundled exe - modules are bundled in the exe
    PROCESSOR_DIR = Path(sys._MEIPASS) / "utility" / "website" / "backend" / "tools" / "processor"
    SERVICES_DIR = Path(sys._MEIPASS) / "utility" / "website" / "backend" / "app" / "services"
else:
    # Running as Python script
    PROCESSOR_DIR = PROJECT_ROOT / "utility" / "website" / "backend" / "tools" / "processor"
    SERVICES_DIR = PROJECT_ROOT / "utility" / "website" / "backend" / "app" / "services"

sys.path.insert(0, str(PROCESSOR_DIR))
from generate_csp import generate_csp

sys.path.insert(0, str(SERVICES_DIR))
from dat_processor import validate_for_slippi

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Configure SocketIO - let it auto-detect the best mode
# Threading mode works in both dev and bundled
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Determine if running from PyInstaller bundle
if getattr(sys, 'frozen', False):
    # Running as compiled exe bundled with Electron
    # Use resources directory for bundled tools
    BASE_PATH = RESOURCES_DIR
    # Platform-aware executable naming and paths
    if os.name == 'nt':
        MEXCLI_PATH = RESOURCES_DIR / "utility/mex/mexcli.exe"
    else:
        # Linux: Check mex-linux first (production), then mex (fallback)
        linux_path = RESOURCES_DIR / "utility/mex-linux/mexcli"
        fallback_path = RESOURCES_DIR / "utility/mex/mexcli"
        MEXCLI_PATH = linux_path if linux_path.exists() else fallback_path
else:
    # Running as Python script (development)
    BASE_PATH = PROJECT_ROOT
    if os.name == 'nt':
        MEXCLI_PATH = PROJECT_ROOT / "utility/MexManager/MexCLI/bin/Release/net6.0/mexcli.exe"
    else:
        # On Linux in dev mode, look for linux-x64 build
        MEXCLI_PATH = PROJECT_ROOT / "utility/MexManager/MexCLI/bin/Release/net6.0/linux-x64/mexcli"

# HSDRawViewer path for 3D model streaming
if getattr(sys, 'frozen', False):
    HSDRAW_EXE = RESOURCES_DIR / "utility/HSDRawViewer/HSDRawViewer.exe"
else:
    HSDRAW_EXE = PROJECT_ROOT / "utility/website/backend/tools/HSDLib/HSDRawViewer/bin/Release/net6.0-windows/HSDRawViewer.exe"

# User data paths (writable locations)
MEX_PROJECT_PATH = PROJECT_ROOT / "build/project.mexproj"
STORAGE_PATH = PROJECT_ROOT / "storage"
OUTPUT_PATH = PROJECT_ROOT / "output"
LOGS_PATH = PROJECT_ROOT / "logs"

# Asset paths (bundled resources)
VANILLA_ASSETS_DIR = BASE_PATH / "utility" / "assets" / "vanilla"

# Ensure directories exist
STORAGE_PATH.mkdir(exist_ok=True)
OUTPUT_PATH.mkdir(exist_ok=True)
LOGS_PATH.mkdir(exist_ok=True)
MEX_PROJECT_PATH.parent.mkdir(exist_ok=True)  # Create build/ directory

def migrate_legacy_character_names():
    """
    Migrate old character names to MEX format.
    Renames:
    - "Captain Falcon" -> "C. Falcon"
    - "Donkey Kong" -> "DK"

    This affects both metadata.json and storage folder names.
    """
    migrations = {
        "Captain Falcon": "C. Falcon",
        "Donkey Kong": "DK"
    }

    metadata_file = STORAGE_PATH / 'metadata.json'
    if not metadata_file.exists():
        return

    try:
        # Load metadata
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        # Track if any changes were made
        changes_made = False

        # Migrate character names in metadata
        if 'characters' in metadata:
            old_chars = list(metadata['characters'].keys())
            for old_name, new_name in migrations.items():
                if old_name in old_chars:
                    logger.info(f"Migrating character metadata: {old_name} -> {new_name}")
                    metadata['characters'][new_name] = metadata['characters'].pop(old_name)
                    changes_made = True

        # Save updated metadata if changes were made
        if changes_made:
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            logger.info("Updated metadata.json with migrated character names")

        # Rename storage folders
        for old_name, new_name in migrations.items():
            old_folder = STORAGE_PATH / old_name
            new_folder = STORAGE_PATH / new_name

            if old_folder.exists() and old_folder.is_dir():
                logger.info(f"Migrating storage folder: {old_name}/ -> {new_name}/")
                # If new folder already exists, we need to merge
                if new_folder.exists():
                    logger.warning(f"Target folder {new_name}/ already exists, skipping folder rename")
                else:
                    old_folder.rename(new_folder)
                    logger.info(f"Renamed storage folder: {old_name}/ -> {new_name}/")

    except Exception as e:
        logger.error(f"Error during character name migration: {e}", exc_info=True)

# Configure logging
log_file = LOGS_PATH / f"mex_api_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Global MEX manager instance and current project path
mex_manager = None
current_project_path = None

# Global 3D viewer process
viewer_process = None
viewer_port = None

def get_mex_manager():
    """Get or initialize MEX manager instance"""
    global mex_manager, current_project_path

    if current_project_path is None:
        raise Exception("No MEX project loaded. Please open a project first.")

    if mex_manager is None:
        try:
            mex_manager = MexManager(
                cli_path=str(MEXCLI_PATH),
                project_path=str(current_project_path)
            )
        except MexManagerError as e:
            raise Exception(f"Failed to initialize MexManager: {e}")
    return mex_manager

def set_project_path(path):
    """Set the current project path and reset manager"""
    global mex_manager, current_project_path
    current_project_path = Path(path)
    mex_manager = None  # Reset manager so it reinitializes with new path

def reload_mex_manager():
    """Force reload of MEX manager to pick up file changes"""
    global mex_manager
    mex_manager = None

def get_project_files_dir():
    """Get the files/ directory for the currently loaded project"""
    if current_project_path is None:
        raise Exception("No MEX project loaded. Please open a project first.")
    return current_project_path.parent / "files"


@app.route('/api/mex/status', methods=['GET'])
def get_status():
    """Get MEX project status"""
    global current_project_path

    # Check if a project is loaded
    if current_project_path is None:
        return jsonify({
            'success': True,
            'connected': True,
            'projectLoaded': False,
            'message': 'No project loaded'
        })

    try:
        mex = get_mex_manager()
        info = mex.get_info()

        return jsonify({
            'success': True,
            'connected': True,
            'projectLoaded': True,
            'project': {
                'name': info['build']['name'],
                'version': f"{info['build']['majorVersion']}.{info['build']['minorVersion']}.{info['build']['patchVersion']}",
                'path': str(current_project_path)
            },
            'counts': info['counts']
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'connected': False,
            'projectLoaded': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/project/open', methods=['POST'])
def open_project():
    """Open a MEX project from a given path"""
    try:
        data = request.json
        project_path = data.get('projectPath')

        if not project_path:
            return jsonify({
                'success': False,
                'error': 'No project path provided'
            }), 400

        project_file = Path(project_path)

        # Validate the path
        if not project_file.exists():
            return jsonify({
                'success': False,
                'error': f'Project file not found: {project_path}'
            }), 404

        if not project_file.suffix == '.mexproj':
            return jsonify({
                'success': False,
                'error': 'File must be a .mexproj file'
            }), 400

        # Set the project path
        set_project_path(project_path)

        # Try to get project info to verify it works
        mex = get_mex_manager()
        info = mex.get_info()

        logger.info(f"[OK] Opened MEX project: {project_path}")

        return jsonify({
            'success': True,
            'message': 'Project opened successfully',
            'project': {
                'name': info['build']['name'],
                'version': f"{info['build']['majorVersion']}.{info['build']['minorVersion']}.{info['build']['patchVersion']}",
                'path': str(project_path)
            }
        })
    except Exception as e:
        logger.error(f"Failed to open project: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/project/create', methods=['POST'])
def create_project():
    """Create a new MEX project from a vanilla ISO"""
    try:
        data = request.json
        iso_path = data.get('isoPath')
        project_dir = data.get('projectDir')
        project_name = data.get('projectName', 'MexProject')

        logger.info(f"=== CREATE PROJECT REQUEST ===")
        logger.info(f"ISO Path: {iso_path}")
        logger.info(f"Project Dir: {project_dir}")
        logger.info(f"Project Name: {project_name}")

        if not iso_path or not project_dir:
            return jsonify({
                'success': False,
                'error': 'Missing isoPath or projectDir parameter'
            }), 400

        # Validate ISO exists
        iso_file = Path(iso_path)
        if not iso_file.exists():
            return jsonify({
                'success': False,
                'error': f'ISO file not found: {iso_path}'
            }), 404

        # Validate project directory exists
        proj_dir = Path(project_dir)
        if not proj_dir.exists():
            return jsonify({
                'success': False,
                'error': f'Project directory not found: {project_dir}'
            }), 404

        # Call MexCLI create command
        mexcli_path = str(MEXCLI_PATH)
        cmd = [mexcli_path, 'create', str(iso_file), str(proj_dir), project_name]

        logger.info(f"Running command: {' '.join(cmd)}")

        # Hide CMD window on Windows
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            creationflags=creation_flags
        )

        logger.info(f"MexCLI stdout:\n{result.stdout}")
        logger.info(f"MexCLI stderr:\n{result.stderr}")
        logger.info(f"MexCLI return code: {result.returncode}")

        if result.returncode != 0:
            error_message = result.stderr or result.stdout or 'Unknown error'
            logger.error(f"MexCLI create failed: {error_message}")
            return jsonify({
                'success': False,
                'error': f'Failed to create project: {error_message}'
            }), 500

        # The created project file should be at projectDir/project.mexproj
        created_project_path = proj_dir / "project.mexproj"

        if not created_project_path.exists():
            logger.error(f"Project file not found after creation: {created_project_path}")
            return jsonify({
                'success': False,
                'error': 'Project was created but .mexproj file not found'
            }), 500

        logger.info(f"[OK] Project created successfully: {created_project_path}")
        logger.info(f"=== CREATE PROJECT COMPLETE ===")

        return jsonify({
            'success': True,
            'message': 'Project created successfully',
            'projectPath': str(created_project_path)
        })

    except Exception as e:
        logger.error(f"Create project error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/fighters', methods=['GET'])
def list_fighters():
    """List all fighters in MEX project"""
    try:
        mex = get_mex_manager()
        fighters = mex.list_fighters()

        # Add default stock icon URL for each fighter
        for fighter in fighters:
            name = fighter['name']
            # Find the Normal costume folder (ends with 'Nr') in vanilla assets
            vanilla_dir = VANILLA_ASSETS_DIR / name
            if vanilla_dir.exists():
                for folder in vanilla_dir.iterdir():
                    if folder.is_dir() and folder.name.endswith('Nr'):
                        fighter['defaultStockUrl'] = f"/vanilla/{name}/{folder.name}/stock.png"
                        break

        return jsonify({
            'success': True,
            'fighters': fighters
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/fighters/<fighter_name>/costumes', methods=['GET'])
def get_fighter_costumes(fighter_name):
    """Get costumes for a specific fighter"""
    try:
        mex = get_mex_manager()
        result = mex._run_command("get-costumes", str(mex.project_path), fighter_name)

        # Add asset URLs to each costume (relative to /api/mex since frontend adds API_URL)
        costumes = result.get('costumes', [])
        for costume in costumes:
            if costume.get('csp'):
                # Convert backslashes to forward slashes for URLs
                csp_path = costume['csp'].replace('\\', '/')
                costume['cspUrl'] = f"/assets/{csp_path}.png"
            if costume.get('icon'):
                # Convert backslashes to forward slashes for URLs
                icon_path = costume['icon'].replace('\\', '/')
                costume['iconUrl'] = f"/assets/{icon_path}.png"

        return jsonify({
            'success': True,
            'fighter': result.get('fighter'),
            'costumes': costumes
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/assets/<path:asset_path>', methods=['GET'])
def serve_mex_asset(asset_path):
    """Serve MEX asset files (CSP, stock icons, etc.)"""
    try:
        # Get the currently loaded project's directory
        if current_project_path is None:
            return jsonify({'success': False, 'error': 'No project loaded'}), 400

        project_dir = current_project_path.parent

        # Asset path already includes the extension from the URL
        full_path = project_dir / asset_path

        if not full_path.exists():
            return jsonify({'success': False, 'error': f'Asset not found: {asset_path}'}), 404

        return send_file(full_path, mimetype='image/png')
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/storage/<path:file_path>', methods=['GET'])
def serve_storage(file_path):
    """Serve files from storage folder (costumes, stages, screenshots, etc.)"""
    try:
        logger.info(f"========== STORAGE REQUEST ==========")
        logger.info(f"Requested file_path: {file_path}")
        logger.info(f"STORAGE_PATH: {STORAGE_PATH}")

        # Handle Windows path separators
        file_path = file_path.replace('\\', '/')
        full_path = STORAGE_PATH / file_path

        logger.info(f"Full path: {full_path}")
        logger.info(f"File exists: {full_path.exists()}")

        if not full_path.exists():
            # Log what's in the parent directory
            parent_dir = full_path.parent
            logger.warning(f"Storage file NOT FOUND: {full_path}")
            logger.warning(f"Parent directory: {parent_dir}")
            if parent_dir.exists():
                files = list(parent_dir.glob('*'))[:10]
                logger.warning(f"Files in parent dir: {[f.name for f in files]}")
            else:
                logger.warning(f"Parent directory does not exist!")
            return jsonify({'success': False, 'error': f'File not found: {file_path}'}), 404

        # Determine mimetype based on extension
        ext = os.path.splitext(file_path.lower())[1]
        mimetype_map = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.webp': 'image/webp',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.zip': 'application/zip'
        }
        mimetype = mimetype_map.get(ext, 'application/octet-stream')

        logger.info(f"[OK] Serving storage file: {full_path}")
        return send_file(full_path, mimetype=mimetype)
    except Exception as e:
        logger.error(f"EXCEPTION serving storage file {file_path}: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/vanilla/<path:file_path>', methods=['GET'])
def serve_vanilla(file_path):
    """Serve vanilla Melee assets (CSPs, stage images, etc.)"""
    try:
        # Stage screenshots are in utility/assets/stages/, not utility/assets/vanilla/stages/
        if file_path.startswith('stages/'):
            full_path = BASE_PATH / "utility" / "assets" / file_path
        else:
            # Character assets are in utility/assets/vanilla/
            full_path = VANILLA_ASSETS_DIR / file_path

        if not full_path.exists():
            logger.warning(f"Vanilla asset not found: {file_path}")
            return jsonify({'success': False, 'error': f'File not found: {file_path}'}), 404

        # Determine mimetype
        ext = file_path.lower().split('.')[-1]
        mimetype_map = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'webp': 'image/webp',
            'gif': 'image/gif'
        }
        mimetype = mimetype_map.get(ext, 'application/octet-stream')

        return send_file(full_path, mimetype=mimetype)
    except Exception as e:
        logger.error(f"Error serving vanilla asset {file_path}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/utility/<path:file_path>', methods=['GET'])
def serve_utility_assets(file_path):
    """Serve utility assets (button icons, etc.)"""
    try:
        # Serve files from utility/assets/
        full_path = BASE_PATH / "utility" / "assets" / file_path

        if not full_path.exists():
            logger.warning(f"Utility asset not found: {file_path}")
            return jsonify({'success': False, 'error': f'File not found: {file_path}'}), 404

        # Determine mimetype
        ext = file_path.lower().split('.')[-1]
        mimetype_map = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'webp': 'image/webp',
            'gif': 'image/gif',
            'svg': 'image/svg+xml'
        }
        mimetype = mimetype_map.get(ext, 'application/octet-stream')

        return send_file(full_path, mimetype=mimetype)
    except Exception as e:
        logger.error(f"Error serving utility asset: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/assets/<path:file_path>', methods=['GET'])
def serve_mex_assets(file_path):
    """Serve MEX project assets (CSPs, stock icons from currently opened project)"""
    try:
        logger.info(f"========== ASSET REQUEST ==========")
        logger.info(f"Requested file_path: {file_path}")
        logger.info(f"current_project_path: {current_project_path}")

        # Check if a project is loaded
        if current_project_path is None:
            logger.error("ERROR: No MEX project loaded!")
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400

        # Use the currently opened project's directory
        # Flask route strips "/assets/" so we need to add it back
        # Route receives: "csp/csp_038.png", we need: "assets/csp/csp_038.png"
        project_dir = current_project_path.parent
        full_path = project_dir / "assets" / file_path

        logger.info(f"project_dir: {project_dir}")
        logger.info(f"full_path: {full_path}")
        logger.info(f"File exists: {full_path.exists()}")

        if not full_path.exists():
            # Log what files ARE in the parent directory
            parent_dir = full_path.parent
            logger.warning(f"File NOT FOUND: {full_path}")
            logger.warning(f"Parent directory: {parent_dir}")
            if parent_dir.exists():
                files = list(parent_dir.glob('*'))[:10]  # First 10 files
                logger.warning(f"Files in parent dir: {[f.name for f in files]}")
            else:
                logger.warning(f"Parent directory does not exist!")
            return jsonify({'success': False, 'error': f'File not found: {file_path}'}), 404

        # Determine mimetype based on extension
        ext = file_path.lower().split('.')[-1]
        if ext in ('png', 'jpg', 'jpeg', 'webp', 'gif'):
            mimetype = f'image/{ext if ext != "jpg" else "jpeg"}'
        else:
            mimetype = 'application/octet-stream'

        logger.info(f"[OK] Serving file: {full_path}")
        return send_file(full_path, mimetype=mimetype)
    except Exception as e:
        logger.error(f"EXCEPTION serving MEX asset {file_path}: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/import', methods=['POST'])
def import_costume():
    """
    Import costume to MEX project

    Body:
    {
        "fighter": "Fox",
        "costumePath": "storage/Fox/PlFxNr_custom/PlFxNr_custom.zip"
    }
    """
    try:
        data = request.json
        fighter_name = data.get('fighter')
        costume_path = data.get('costumePath')

        logger.info(f"=== IMPORT REQUEST ===")
        logger.info(f"Fighter: {fighter_name}")
        logger.info(f"Costume Path: {costume_path}")
        logger.info(f"Request Data: {json.dumps(data, indent=2)}")

        if not fighter_name or not costume_path:
            logger.error("Missing fighter or costumePath parameter")
            return jsonify({
                'success': False,
                'error': 'Missing fighter or costumePath parameter'
            }), 400

        # Resolve costume path relative to project root
        full_costume_path = PROJECT_ROOT / costume_path

        logger.info(f"Full costume path: {full_costume_path}")
        logger.info(f"Path exists: {full_costume_path.exists()}")

        if not full_costume_path.exists():
            logger.error(f"Costume ZIP not found: {costume_path}")
            return jsonify({
                'success': False,
                'error': f'Costume ZIP not found: {costume_path}'
            }), 404

        logger.info(f"Calling MexCLI to import costume...")
        mex = get_mex_manager()
        result = mex.import_costume(fighter_name, str(full_costume_path))

        logger.info(f"Import result: {json.dumps(result, indent=2)}")

        # Small delay to ensure file system has flushed the write
        time.sleep(0.15)

        # Force reload to pick up file changes for subsequent requests
        reload_mex_manager()
        logger.info(f"Reloaded MEX manager to pick up changes")

        logger.info(f"=== IMPORT COMPLETE ===")

        return jsonify({
            'success': True,
            'result': result
        })
    except MexManagerError as e:
        logger.error(f"MexManagerError: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }), 500


@app.route('/api/mex/remove', methods=['POST'])
def remove_costume():
    """
    Remove costume from MEX project

    Body:
    {
        "fighter": "Fox",
        "costumeIndex": 3
    }
    """
    try:
        data = request.json
        fighter_name = data.get('fighter')
        costume_index = data.get('costumeIndex')

        logger.info(f"=== REMOVE REQUEST ===")
        logger.info(f"Fighter: {fighter_name}")
        logger.info(f"Costume Index: {costume_index}")

        if fighter_name is None or costume_index is None:
            logger.error("Missing fighter or costumeIndex parameter")
            return jsonify({
                'success': False,
                'error': 'Missing fighter or costumeIndex parameter'
            }), 400

        # Validate costume index
        if not isinstance(costume_index, int) or costume_index < 0:
            logger.error(f"Invalid costume index: {costume_index}")
            return jsonify({
                'success': False,
                'error': 'costumeIndex must be a non-negative integer'
            }), 400

        logger.info(f"Calling MexCLI to remove costume...")
        mex = get_mex_manager()
        result = mex.remove_costume(fighter_name, costume_index)

        logger.info(f"Remove result: {json.dumps(result, indent=2)}")

        # Force reload to pick up file changes for subsequent requests
        reload_mex_manager()
        logger.info(f"Reloaded MEX manager to pick up changes")

        logger.info(f"=== REMOVE COMPLETE ===")

        return jsonify({
            'success': True,
            'result': result
        })
    except MexManagerError as e:
        logger.error(f"MexManagerError: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }), 500


@app.route('/api/mex/reorder', methods=['POST'])
def reorder_costume():
    """
    Reorder costume in MEX project (swap positions)

    Body:
    {
        "fighter": "Fox",
        "fromIndex": 2,
        "toIndex": 0
    }

    Note: For Ice Climbers (Popo), paired Nana costumes are automatically reordered
    """
    try:
        data = request.json
        fighter_name = data.get('fighter')
        from_index = data.get('fromIndex')
        to_index = data.get('toIndex')

        logger.info(f"=== REORDER REQUEST ===")
        logger.info(f"Fighter: {fighter_name}")
        logger.info(f"From Index: {from_index}")
        logger.info(f"To Index: {to_index}")

        if fighter_name is None or from_index is None or to_index is None:
            logger.error("Missing fighter, fromIndex, or toIndex parameter")
            return jsonify({
                'success': False,
                'error': 'Missing fighter, fromIndex, or toIndex parameter'
            }), 400

        # Validate indices
        if not isinstance(from_index, int) or from_index < 0:
            logger.error(f"Invalid from_index: {from_index}")
            return jsonify({
                'success': False,
                'error': 'fromIndex must be a non-negative integer'
            }), 400

        if not isinstance(to_index, int) or to_index < 0:
            logger.error(f"Invalid to_index: {to_index}")
            return jsonify({
                'success': False,
                'error': 'toIndex must be a non-negative integer'
            }), 400

        logger.info(f"Calling MexCLI to reorder costume...")
        mex = get_mex_manager()
        result = mex.reorder_costume(fighter_name, from_index, to_index)

        logger.info(f"Reorder result: {json.dumps(result, indent=2)}")

        # Force reload to pick up file changes for subsequent requests
        reload_mex_manager()
        logger.info(f"Reloaded MEX manager to pick up changes")

        logger.info(f"=== REORDER COMPLETE ===")

        return jsonify({
            'success': True,
            'result': result
        })
    except MexManagerError as e:
        logger.error(f"MexManagerError: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }), 500


@app.route('/api/mex/export/start', methods=['POST'])
def start_export():
    """
    Start ISO export (async operation with WebSocket progress)

    Body:
    {
        "filename": "modded_game.iso",  // optional
        "cspCompression": 1.0,  // optional, 0.1-1.0, default 1.0
        "useColorSmash": false  // optional, boolean, default false
    }
    """
    try:
        data = request.json or {}
        filename = data.get('filename', f'game_{datetime.now().strftime("%Y%m%d_%H%M%S")}.iso')
        csp_compression = data.get('cspCompression', 1.0)
        use_color_smash = data.get('useColorSmash', False)

        # Validate compression range
        if not isinstance(csp_compression, (int, float)) or csp_compression < 0.1 or csp_compression > 1.0:
            return jsonify({
                'success': False,
                'error': 'cspCompression must be a number between 0.1 and 1.0'
            }), 400

        # Validate useColorSmash
        if not isinstance(use_color_smash, bool):
            return jsonify({
                'success': False,
                'error': 'useColorSmash must be a boolean'
            }), 400

        output_file = OUTPUT_PATH / filename

        logger.info(f"=== ISO EXPORT START ===")
        logger.info(f"Filename: {filename}")
        logger.info(f"CSP Compression: {csp_compression}")
        logger.info(f"Use Color Smash: {use_color_smash}")

        def export_with_progress():
            """Export ISO in background thread with WebSocket progress updates"""
            try:
                def progress_callback(percentage, message):
                    socketio.emit('export_progress', {
                        'percentage': percentage,
                        'message': message
                    })

                mex = get_mex_manager()
                result = mex.export_iso(str(output_file), progress_callback, csp_compression, use_color_smash)

                socketio.emit('export_complete', {
                    'success': True,
                    'filename': filename,
                    'path': str(output_file)
                })
            except Exception as e:
                socketio.emit('export_error', {
                    'success': False,
                    'error': str(e)
                })

        # Start export in background thread
        thread = threading.Thread(target=export_with_progress)
        thread.start()

        return jsonify({
            'success': True,
            'message': 'Export started',
            'filename': filename
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/export/download/<filename>', methods=['GET'])
def download_iso(filename):
    """Download exported ISO file"""
    try:
        file_path = OUTPUT_PATH / filename

        if not file_path.exists():
            return jsonify({
                'success': False,
                'error': 'File not found'
            }), 404

        @after_this_request
        def remove_file(response):
            try:
                os.remove(file_path)
                logger.info(f"Deleted ISO file after download: {filename}")
            except Exception as error:
                logger.error(f"Error deleting ISO file {filename}: {str(error)}")
            return response

        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/costumes', methods=['GET'])
def list_storage_costumes():
    """List all costumes in storage with MEX-compatible ZIPs.
    Folders in the skins array are skipped - only actual skins are returned.
    """
    try:
        character = request.args.get('character')

        costumes = []

        # Read metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({
                'success': True,
                'costumes': []
            })

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        characters_data = metadata.get('characters', {})

        # Filter by character if specified
        if character:
            characters_data = {character: characters_data.get(character, {})}

        # Build costume list
        for char_name, char_data in characters_data.items():
            skins = char_data.get('skins', [])

            # Iterate through skins array in order, skipping folders
            for skin in skins:
                # Skip folder entries
                if skin.get('type') == 'folder':
                    continue

                # Skip hidden skins (e.g., Ice Climbers Nana)
                if skin.get('visible') is False:
                    continue

                # ZIPs are stored directly in character folder: storage/Character/filename.zip
                zip_path = STORAGE_PATH / char_name / skin.get('filename', '')

                if zip_path.exists():
                    costume_data = {
                        'character': char_name,
                        'name': f"{char_name} - {skin.get('color', 'Custom')}",
                        'folder': skin['id'],
                        'costumeCode': skin['costume_code'],
                        'zipPath': str(zip_path.relative_to(PROJECT_ROOT)),
                        # These paths are relative to viewer/public/ which Vite serves at root
                        'cspUrl': f"/storage/{char_name}/{skin['id']}_csp.png" if skin.get('has_csp') else None,
                        'stockUrl': f"/storage/{char_name}/{skin['id']}_stc.png" if skin.get('has_stock') else None,
                        # Ice Climbers pairing metadata
                        'isPopo': skin.get('is_popo', False),
                        'isNana': skin.get('is_nana', False),
                        'pairedNanaId': skin.get('paired_nana_id'),
                        'pairedPopoId': skin.get('paired_popo_id'),
                        # Slippi safety
                        'slippiSafe': skin.get('slippi_safe', False)
                    }
                    costumes.append(costume_data)

        return jsonify({
            'success': True,
            'costumes': costumes
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/costumes/delete', methods=['POST'])
def delete_storage_costume():
    """Delete character costume from storage"""
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')

        if not character or not skin_id:
            return jsonify({
                'success': False,
                'error': 'Missing character or skinId parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        # Find and remove the skin from metadata
        if character not in metadata.get('characters', {}):
            return jsonify({
                'success': False,
                'error': f'Character {character} not found in metadata'
            }), 404

        char_data = metadata['characters'][character]
        skins = char_data.get('skins', [])
        skin_to_delete = None
        skin_index = None

        for idx, skin in enumerate(skins):
            if skin['id'] == skin_id:
                skin_to_delete = skin
                skin_index = idx
                break

        if not skin_to_delete:
            return jsonify({
                'success': False,
                'error': f'Skin {skin_id} not found for {character}'
            }), 404

        # Delete physical files
        char_folder = STORAGE_PATH / character
        zip_file = char_folder / skin_to_delete['filename']
        csp_file = char_folder / f"{skin_id}_csp.png"
        stc_file = char_folder / f"{skin_id}_stc.png"

        deleted_files = []
        if zip_file.exists():
            zip_file.unlink()
            deleted_files.append(str(zip_file))
        if csp_file.exists():
            csp_file.unlink()
            deleted_files.append(str(csp_file))
        if stc_file.exists():
            stc_file.unlink()
            deleted_files.append(str(stc_file))

        # Remove from metadata
        skins.pop(skin_index)

        # Save updated metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Deleted costume {skin_id} for {character}")
        logger.info(f"  Deleted files: {deleted_files}")

        return jsonify({
            'success': True,
            'message': f'Successfully deleted {skin_id}',
            'deleted_files': deleted_files
        })
    except Exception as e:
        logger.error(f"Delete costume error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/costumes/rename', methods=['POST'])
def rename_storage_costume():
    """Rename character costume (update color field)"""
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')
        new_name = data.get('newName')

        if not character or not skin_id or not new_name:
            return jsonify({
                'success': False,
                'error': 'Missing character, skinId, or newName parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        # Find and update the skin in metadata
        if character not in metadata.get('characters', {}):
            return jsonify({
                'success': False,
                'error': f'Character {character} not found in metadata'
            }), 404

        char_data = metadata['characters'][character]
        skins = char_data.get('skins', [])
        skin_found = False

        for skin in skins:
            if skin['id'] == skin_id:
                skin['color'] = new_name
                skin_found = True
                break

        if not skin_found:
            return jsonify({
                'success': False,
                'error': f'Skin {skin_id} not found for {character}'
            }), 404

        # Save updated metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Renamed costume {skin_id} to '{new_name}'")

        return jsonify({
            'success': True,
            'message': f'Successfully renamed to {new_name}'
        })
    except Exception as e:
        logger.error(f"Rename costume error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/costumes/update-csp', methods=['POST'])
def update_costume_csp():
    """Update CSP image for a character costume"""
    try:
        character = request.form.get('character')
        skin_id = request.form.get('skinId')

        if not character or not skin_id:
            return jsonify({
                'success': False,
                'error': 'Missing character or skinId parameter'
            }), 400

        if 'csp' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No CSP file provided'
            }), 400

        csp_file = request.files['csp']

        if csp_file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400

        # Validate image file
        if not csp_file.content_type.startswith('image/'):
            return jsonify({
                'success': False,
                'error': 'File must be an image'
            }), 400

        # Read the image data
        csp_data = csp_file.read()

        # Paths
        char_folder = STORAGE_PATH / character
        zip_path = char_folder / f"{skin_id}.zip"
        standalone_csp = char_folder / f"{skin_id}_csp.png"

        if not zip_path.exists():
            return jsonify({
                'success': False,
                'error': f'Costume zip not found: {skin_id}'
            }), 404

        # Update standalone CSP file
        with open(standalone_csp, 'wb') as f:
            f.write(csp_data)

        # Update CSP inside the zip file
        temp_zip = char_folder / f"{skin_id}_temp.zip"

        with zipfile.ZipFile(zip_path, 'r') as source_zip:
            with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as dest_zip:
                # Copy all existing entries except csp.png
                for item in source_zip.infolist():
                    if item.filename.lower() not in ['csp.png', 'csp']:
                        data = source_zip.read(item.filename)
                        dest_zip.writestr(item, data)

                # Write new CSP
                dest_zip.writestr('csp.png', csp_data)

        # Replace original zip with updated one
        zip_path.unlink()
        temp_zip.rename(zip_path)

        # Update metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)

            if character in metadata.get('characters', {}):
                for skin in metadata['characters'][character].get('skins', []):
                    if skin['id'] == skin_id:
                        skin['has_csp'] = True
                        skin['csp_source'] = 'custom'
                        break

                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Updated CSP for {character} - {skin_id}")

        return jsonify({
            'success': True,
            'message': 'CSP updated successfully'
        })
    except Exception as e:
        logger.error(f"Update CSP error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/costumes/update-stock', methods=['POST'])
def update_costume_stock():
    """Update stock icon for a character costume"""
    try:
        character = request.form.get('character')
        skin_id = request.form.get('skinId')

        if not character or not skin_id:
            return jsonify({
                'success': False,
                'error': 'Missing character or skinId parameter'
            }), 400

        if 'stock' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No stock file provided'
            }), 400

        stock_file = request.files['stock']

        if stock_file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400

        # Validate image file
        if not stock_file.content_type.startswith('image/'):
            return jsonify({
                'success': False,
                'error': 'File must be an image'
            }), 400

        # Read the image data
        stock_data = stock_file.read()

        # Paths
        char_folder = STORAGE_PATH / character
        zip_path = char_folder / f"{skin_id}.zip"
        standalone_stock = char_folder / f"{skin_id}_stc.png"

        if not zip_path.exists():
            return jsonify({
                'success': False,
                'error': f'Costume zip not found: {skin_id}'
            }), 404

        # Update standalone stock file
        with open(standalone_stock, 'wb') as f:
            f.write(stock_data)

        # Update stock inside the zip file
        temp_zip = char_folder / f"{skin_id}_temp.zip"

        with zipfile.ZipFile(zip_path, 'r') as source_zip:
            with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as dest_zip:
                # Copy all existing entries except stc.png
                for item in source_zip.infolist():
                    if item.filename.lower() not in ['stc.png', 'stock.png', 'stock']:
                        data = source_zip.read(item.filename)
                        dest_zip.writestr(item, data)

                # Write new stock icon
                dest_zip.writestr('stc.png', stock_data)

        # Replace original zip with updated one
        zip_path.unlink()
        temp_zip.rename(zip_path)

        # Update metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)

            if character in metadata.get('characters', {}):
                for skin in metadata['characters'][character].get('skins', []):
                    if skin['id'] == skin_id:
                        skin['has_stock'] = True
                        skin['stock_source'] = 'custom'
                        break

                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Updated stock icon for {character} - {skin_id}")

        return jsonify({
            'success': True,
            'message': 'Stock icon updated successfully'
        })
    except Exception as e:
        logger.error(f"Update stock error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/costumes/retest-slippi', methods=['POST'])
def retest_costume_slippi():
    """Retest a character costume for slippi safety and optionally apply fix"""
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')
        auto_fix = data.get('autoFix', False)

        if not character or not skin_id:
            return jsonify({
                'success': False,
                'error': 'Missing character or skinId parameter'
            }), 400

        # Paths
        char_folder = STORAGE_PATH / character
        zip_path = char_folder / f"{skin_id}.zip"

        if not zip_path.exists():
            return jsonify({
                'success': False,
                'error': f'Costume zip not found: {skin_id}'
            }), 404

        # Extract DAT from ZIP
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            dat_files = [f for f in zip_ref.namelist() if f.lower().endswith('.dat')]
            if not dat_files:
                return jsonify({
                    'success': False,
                    'error': 'No DAT file found in costume ZIP'
                }), 400

            dat_filename = dat_files[0]
            dat_data = zip_ref.read(dat_filename)

        # Create temp file for validation (same as import - let validate_for_slippi handle detection)
        with tempfile.NamedTemporaryFile(suffix='.dat', delete=False) as tmp_dat:
            tmp_dat.write(dat_data)
            tmp_dat_path = tmp_dat.name

        logger.info(f"Retesting {character} - {skin_id}: DAT file = {dat_filename}")

        try:
            # Validate for slippi
            logger.info(f"Calling validate_for_slippi with auto_fix={auto_fix}")
            validation = validate_for_slippi(tmp_dat_path, auto_fix=auto_fix)
            logger.info(f"Validation result: {validation}")

            # If auto_fix was applied, update the ZIP with the fixed DAT
            if auto_fix and validation.get('fix_applied'):
                with open(tmp_dat_path, 'rb') as f:
                    fixed_dat_data = f.read()

                # Update ZIP with fixed DAT
                temp_zip = char_folder / f"{skin_id}_temp.zip"
                with zipfile.ZipFile(zip_path, 'r') as source_zip:
                    with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as dest_zip:
                        for item in source_zip.infolist():
                            if item.filename.lower().endswith('.dat'):
                                dest_zip.writestr(item.filename, fixed_dat_data)
                            else:
                                data = source_zip.read(item.filename)
                                dest_zip.writestr(item, data)

                zip_path.unlink()
                temp_zip.rename(zip_path)
                logger.info(f"Applied slippi fix to {character} - {skin_id}")

        finally:
            # Clean up temp file
            try:
                os.unlink(tmp_dat_path)
            except:
                pass

        # Update metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)

            if character in metadata.get('characters', {}):
                for skin in metadata['characters'][character].get('skins', []):
                    if skin['id'] == skin_id:
                        skin['slippi_safe'] = validation['slippi_safe']
                        skin['slippi_tested'] = True
                        skin['slippi_test_date'] = datetime.now().isoformat()
                        # Clear manual override after retest
                        skin['slippi_manual_override'] = None
                        break

                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Retested slippi for {character} - {skin_id}: {validation['slippi_safe']}")

        return jsonify({
            'success': True,
            'slippi_safe': validation['slippi_safe'],
            'message': 'Slippi Safe' if validation['slippi_safe'] else 'Not Slippi Safe'
        })
    except Exception as e:
        logger.error(f"Retest slippi error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/costumes/override-slippi', methods=['POST'])
def override_costume_slippi():
    """Manually override slippi safety status for a character costume"""
    try:
        data = request.json
        logger.info("=== OVERRIDE COSTUME SLIPPI REQUEST ===")
        logger.info(f"Request data: {data}")

        character = data.get('character')
        skin_id = data.get('skinId')
        slippi_safe = data.get('slippiSafe')

        logger.info(f"character: {character}")
        logger.info(f"skin_id: {skin_id}")
        logger.info(f"slippi_safe: {slippi_safe}")

        if not character or not skin_id or slippi_safe is None:
            logger.error("Missing parameters!")
            return jsonify({
                'success': False,
                'error': 'Missing character, skinId, or slippiSafe parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        logger.info(f"Metadata file path: {metadata_file}")
        logger.info(f"Metadata file exists: {metadata_file.exists()}")

        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        logger.info(f"Loaded metadata, characters: {list(metadata.get('characters', {}).keys())}")

        # Find and update the skin
        if character not in metadata.get('characters', {}):
            logger.error(f"Character {character} not found in metadata!")
            return jsonify({
                'success': False,
                'error': f'Character {character} not found in metadata'
            }), 404

        logger.info(f"Found character {character}, skins: {[s['id'] for s in metadata['characters'][character].get('skins', [])]}")

        skin_found = False
        for skin in metadata['characters'][character].get('skins', []):
            if skin['id'] == skin_id:
                logger.info(f"Found skin {skin_id}, updating slippi_safe from {skin.get('slippi_safe')} to {slippi_safe}")
                skin['slippi_safe'] = slippi_safe
                skin['slippi_manual_override'] = True
                skin['slippi_test_date'] = datetime.now().isoformat()
                skin_found = True
                break

        if not skin_found:
            logger.error(f"Skin {skin_id} not found!")
            return jsonify({
                'success': False,
                'error': f'Skin {skin_id} not found for {character}'
            }), 404

        # Save updated metadata
        logger.info(f"Saving updated metadata to {metadata_file}")
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        logger.info("Metadata saved successfully")

        logger.info(f"[OK] Manually set slippi status for {character} - {skin_id}: {slippi_safe}")

        return jsonify({
            'success': True,
            'slippi_safe': slippi_safe,
            'message': f"Manually set to {'Slippi Safe' if slippi_safe else 'Not Slippi Safe'}"
        })
    except Exception as e:
        logger.error(f"Override slippi error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/stages/set-slippi', methods=['POST'])
def set_stage_slippi():
    """Manually set slippi safety status for a stage variant"""
    try:
        data = request.json
        logger.info("=== SET STAGE SLIPPI REQUEST ===")
        logger.info(f"Request data: {data}")

        stage_name = data.get('stageName')
        variant_id = data.get('variantId')
        slippi_safe = data.get('slippiSafe')

        logger.info(f"stage_name: {stage_name}")
        logger.info(f"variant_id: {variant_id}")
        logger.info(f"slippi_safe: {slippi_safe}")

        if not stage_name or not variant_id or slippi_safe is None:
            logger.error("Missing parameters!")
            return jsonify({
                'success': False,
                'error': 'Missing stageName, variantId, or slippiSafe parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        logger.info(f"Metadata file path: {metadata_file}")
        logger.info(f"Metadata file exists: {metadata_file.exists()}")

        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        logger.info(f"Loaded metadata, stages: {list(metadata.get('stages', {}).keys())}")

        # Find and update the stage variant
        if stage_name not in metadata.get('stages', {}):
            logger.error(f"Stage {stage_name} not found in metadata!")
            return jsonify({
                'success': False,
                'error': f'Stage {stage_name} not found in metadata'
            }), 404

        logger.info(f"Found stage {stage_name}, variants: {[v['id'] for v in metadata['stages'][stage_name].get('variants', [])]}")

        variant_found = False
        for variant in metadata['stages'][stage_name].get('variants', []):
            if variant['id'] == variant_id:
                logger.info(f"Found variant {variant_id}, updating slippi_safe from {variant.get('slippi_safe')} to {slippi_safe}")
                variant['slippi_safe'] = slippi_safe
                variant['slippi_tested'] = True
                variant['slippi_test_date'] = datetime.now().isoformat()
                variant_found = True
                break

        if not variant_found:
            logger.error(f"Variant {variant_id} not found!")
            return jsonify({
                'success': False,
                'error': f'Variant {variant_id} not found for {stage_name}'
            }), 404

        # Save updated metadata
        logger.info(f"Saving updated metadata to {metadata_file}")
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        logger.info("Metadata saved successfully")

        logger.info(f"[OK] Set slippi status for {stage_name} - {variant_id}: {slippi_safe}")

        return jsonify({
            'success': True,
            'slippi_safe': slippi_safe,
            'message': f"Set to {'Slippi Safe' if slippi_safe else 'Not Slippi Safe'}"
        })
    except Exception as e:
        logger.error(f"Set stage slippi error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/metadata', methods=['GET'])
def get_storage_metadata():
    """Get storage metadata.json"""
    try:
        metadata_file = STORAGE_PATH / 'metadata.json'

        if not metadata_file.exists():
            return jsonify({
                'success': True,
                'metadata': {'characters': {}}
            })

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        return jsonify({
            'success': True,
            'metadata': metadata
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/clear', methods=['POST'])
def clear_storage_endpoint():
    """Clear storage based on provided options"""
    try:
        data = request.json or {}
        clear_intake = data.get('clearIntake', False)
        clear_logs = data.get('clearLogs', False)

        logger.info("=== CLEAR STORAGE REQUEST ===")
        logger.info(f"Clear Intake: {clear_intake}")
        logger.info(f"Clear Logs: {clear_logs}")

        removed_count = 0
        output_lines = []

        # Clear storage
        logger.info("Clearing storage...")
        output_lines.append("Clearing storage...")

        # Remove character folders in storage (excluding 'das' folder)
        if STORAGE_PATH.exists():
            for item in STORAGE_PATH.iterdir():
                if item.is_dir() and item.name != "das":
                    logger.info(f"  Removing: {item.name}/")
                    output_lines.append(f"  Removing: {item.name}/")
                    shutil.rmtree(item)
                    removed_count += 1

        # Remove stage variant folders in storage/das/
        das_dir = STORAGE_PATH / "das"
        if das_dir.exists():
            for stage_folder in das_dir.iterdir():
                if stage_folder.is_dir():
                    # Clear contents of each stage folder
                    variant_count = 0
                    for variant_item in stage_folder.iterdir():
                        if variant_item.is_file():
                            variant_item.unlink()
                        else:
                            shutil.rmtree(variant_item)
                        variant_count += 1
                    if variant_count > 0:
                        logger.info(f"  Removing: das/{stage_folder.name}/ ({variant_count} items)")
                        output_lines.append(f"  Removing: das/{stage_folder.name}/ ({variant_count} items)")
                        removed_count += 1

        # Clear Python cache directories
        for cache_dir in PROJECT_ROOT.rglob("__pycache__"):
            if cache_dir.is_dir():
                logger.info(f"  Removing: {cache_dir.relative_to(PROJECT_ROOT)}")
                output_lines.append(f"  Removing: {cache_dir.relative_to(PROJECT_ROOT)}")
                shutil.rmtree(cache_dir)
                removed_count += 1

        # Reset metadata.json to default structure
        metadata_file = STORAGE_PATH / 'metadata.json'
        if metadata_file.exists() or STORAGE_PATH.exists():
            logger.info(f"  Resetting: metadata.json")
            output_lines.append(f"  Resetting: metadata.json")
            STORAGE_PATH.mkdir(parents=True, exist_ok=True)
            with open(metadata_file, 'w') as f:
                json.dump({'version': '1.0', 'characters': {}, 'stages': {}}, f, indent=2)
            removed_count += 1

        if removed_count > 0:
            output_lines.append(f"[OK] Cleared {removed_count} items from storage")
        else:
            output_lines.append("[INFO] Storage is already empty")

        # Optionally clear intake
        if clear_intake:
            logger.info("\nClearing intake...")
            output_lines.append("\nClearing intake...")
            intake_dir = PROJECT_ROOT / "intake"
            intake_count = 0
            if intake_dir.exists():
                for item in intake_dir.iterdir():
                    if item.is_file():
                        logger.info(f"  Removing: {item.name}")
                        output_lines.append(f"  Removing: {item.name}")
                        item.unlink()
                        intake_count += 1
            if intake_count > 0:
                output_lines.append(f"[OK] Cleared {intake_count} files from intake")
            else:
                output_lines.append("[INFO] Intake is already empty")

        # Optionally clear logs
        if clear_logs:
            logger.info("\nClearing logs...")
            output_lines.append("\nClearing logs...")
            logs_count = 0
            if LOGS_PATH.exists():
                for item in LOGS_PATH.iterdir():
                    if item.is_file() and item.suffix == '.log':
                        logger.info(f"  Removing: {item.name}")
                        output_lines.append(f"  Removing: {item.name}")
                        item.unlink()
                        logs_count += 1
            if logs_count > 0:
                output_lines.append(f"[OK] Cleared {logs_count} log files")
            else:
                output_lines.append("[INFO] No log files to clear")

        logger.info("=== CLEAR STORAGE COMPLETE ===")
        output_lines.append("\nDone!")

        return jsonify({
            'success': True,
            'message': 'Storage cleared successfully',
            'output': '\n'.join(output_lines)
        })
    except Exception as e:
        logger.error(f"Clear storage error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/backup', methods=['POST'])
def backup_vault():
    """Create a backup ZIP of the entire storage vault"""
    try:
        logger.info("=== VAULT BACKUP REQUEST ===")

        # Create backups directory if it doesn't exist
        backups_dir = PROJECT_ROOT / "output" / "vault_backups"
        backups_dir.mkdir(parents=True, exist_ok=True)

        # Create timestamped backup filename
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_filename = f"vault_backup_{timestamp}.zip"
        backup_path = backups_dir / backup_filename

        logger.info(f"Creating backup: {backup_path}")

        # Create ZIP archive of storage directory
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Walk through storage directory and add all files
            for root, dirs, files in os.walk(STORAGE_PATH):
                for file in files:
                    file_path = Path(root) / file
                    # Create archive path relative to storage directory
                    arcname = file_path.relative_to(STORAGE_PATH)
                    zipf.write(file_path, arcname)

        backup_size = backup_path.stat().st_size
        logger.info(f"Backup created successfully: {backup_size} bytes")
        logger.info("=== VAULT BACKUP COMPLETE ===")

        return jsonify({
            'success': True,
            'filename': backup_filename,
            'size': backup_size,
            'path': str(backup_path)
        })
    except Exception as e:
        logger.error(f"Vault backup error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/backup/download/<filename>', methods=['GET'])
def download_backup(filename):
    """Download a backup file"""
    try:
        backups_dir = PROJECT_ROOT / "output" / "vault_backups"
        backup_path = backups_dir / filename

        if not backup_path.exists():
            return jsonify({
                'success': False,
                'error': 'Backup file not found'
            }), 404

        @after_this_request
        def remove_file(response):
            try:
                os.remove(backup_path)
                logger.info(f"Deleted backup file after download: {filename}")
            except Exception as error:
                logger.error(f"Error deleting backup file {filename}: {str(error)}")
            return response

        return send_file(
            backup_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/zip'
        )
    except Exception as e:
        logger.error(f"Backup download error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/restore', methods=['POST'])
def restore_vault():
    """Restore vault from a backup ZIP file"""
    try:
        logger.info("=== VAULT RESTORE REQUEST ===")

        # Check if file was uploaded
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No backup file uploaded'
            }), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400

        if not file.filename.lower().endswith('.zip'):
            return jsonify({
                'success': False,
                'error': 'Only ZIP files are supported'
            }), 400

        # Get restore mode: 'replace' or 'merge'
        restore_mode = request.form.get('mode', 'replace')

        # Save uploaded backup to temp location
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
            file.save(tmp.name)
            tmp_path = Path(tmp.name)

        try:
            # Validate backup structure
            with zipfile.ZipFile(tmp_path, 'r') as zipf:
                file_list = zipf.namelist()

                # Check if metadata.json exists in backup
                if 'metadata.json' not in file_list:
                    return jsonify({
                        'success': False,
                        'error': 'Invalid backup file: metadata.json not found'
                    }), 400

            logger.info(f"Restore mode: {restore_mode}")

            # If replace mode, clear existing storage first
            if restore_mode == 'replace':
                logger.info("Clearing existing storage...")
                if STORAGE_PATH.exists():
                    shutil.rmtree(STORAGE_PATH)
                STORAGE_PATH.mkdir(parents=True, exist_ok=True)

            # Extract backup to storage directory
            logger.info("Extracting backup...")
            with zipfile.ZipFile(tmp_path, 'r') as zipf:
                zipf.extractall(STORAGE_PATH)

            logger.info("=== VAULT RESTORE COMPLETE ===")

            return jsonify({
                'success': True,
                'message': f'Vault restored successfully ({restore_mode} mode)',
                'mode': restore_mode
            })
        finally:
            # Clean up temp file
            if tmp_path.exists():
                tmp_path.unlink()
    except Exception as e:
        logger.error(f"Vault restore error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============= Mod Export Endpoints =============

@app.route('/api/mex/storage/costumes/export', methods=['POST'])
def export_costume():
    """Export a single costume as a ZIP file"""
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')
        color_name = data.get('colorName', 'costume')

        logger.info("=== COSTUME EXPORT REQUEST ===")
        logger.info(f"Character: {character}, Skin ID: {skin_id}")

        if not character or not skin_id:
            return jsonify({
                'success': False,
                'error': 'Missing character or skinId parameter'
            }), 400

        # Paths
        char_folder = STORAGE_PATH / character
        zip_path = char_folder / f"{skin_id}.zip"
        csp_path = char_folder / f"{skin_id}_csp.png"
        stock_path = char_folder / f"{skin_id}_stc.png"

        if not zip_path.exists():
            return jsonify({
                'success': False,
                'error': f'Costume not found: {skin_id}'
            }), 404

        # Check if this is Ice Climbers Popo with paired Nana
        metadata_file = STORAGE_PATH / 'metadata.json'
        paired_nana_id = None
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)

            if character in metadata.get('characters', {}):
                for skin in metadata['characters'][character]['skins']:
                    if skin['id'] == skin_id:
                        if skin.get('is_popo') and skin.get('paired_nana_id'):
                            paired_nana_id = skin['paired_nana_id']
                            logger.info(f"Ice Climbers Popo detected, paired Nana: {paired_nana_id}")
                        break

        # Create export directory
        export_dir = OUTPUT_PATH / "mod_exports"
        export_dir.mkdir(parents=True, exist_ok=True)

        # Create export filename
        safe_character = "".join(c for c in character if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
        safe_color = "".join(c for c in color_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
        export_filename = f"{safe_character}_{safe_color}.zip"
        export_path = export_dir / export_filename

        # Create ZIP with .dat, CSP, and stock icon
        with zipfile.ZipFile(export_path, 'w', zipfile.ZIP_DEFLATED) as export_zip:
            # Extract and add .dat file from source ZIP
            with zipfile.ZipFile(zip_path, 'r') as source_zip:
                for item in source_zip.namelist():
                    if item.lower().endswith('.dat'):
                        dat_data = source_zip.read(item)
                        export_zip.writestr(item, dat_data)
                        logger.info(f"  Added: {item}")

            # Add CSP if exists
            if csp_path.exists():
                export_zip.write(csp_path, 'csp.png')
                logger.info(f"  Added: csp.png")

            # Add stock icon if exists
            if stock_path.exists():
                export_zip.write(stock_path, 'stc.png')
                logger.info(f"  Added: stc.png")

            # Ice Climbers: Add paired Nana DAT if this is Popo
            if paired_nana_id:
                nana_zip_path = char_folder / f"{paired_nana_id}.zip"
                if nana_zip_path.exists():
                    with zipfile.ZipFile(nana_zip_path, 'r') as nana_zip:
                        for item in nana_zip.namelist():
                            if item.lower().endswith('.dat'):
                                nana_dat_data = nana_zip.read(item)
                                export_zip.writestr(item, nana_dat_data)
                                logger.info(f"  Added Nana: {item}")
                else:
                    logger.warning(f"Paired Nana ZIP not found: {nana_zip_path}")

        logger.info(f"[OK] Costume exported: {export_filename}")

        return jsonify({
            'success': True,
            'filename': export_filename
        })
    except Exception as e:
        logger.error(f"Costume export error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/stages/export', methods=['POST'])
def export_stage():
    """Export a single stage variant as a ZIP file"""
    try:
        data = request.json
        stage_code = data.get('stageCode')
        stage_name = data.get('stageName', 'stage')
        variant_id = data.get('variantId')
        variant_name = data.get('variantName', 'variant')

        logger.info("=== STAGE EXPORT REQUEST ===")
        logger.info(f"Stage Code: {stage_code}, Variant ID: {variant_id}")

        if not stage_code or not variant_id:
            return jsonify({
                'success': False,
                'error': 'Missing stageCode or variantId parameter'
            }), 400

        # Get stage folder from DAS_STAGES
        if stage_code not in DAS_STAGES:
            return jsonify({
                'success': False,
                'error': f'Unknown stage code: {stage_code}'
            }), 400

        stage_info = DAS_STAGES[stage_code]
        stage_folder = stage_info['folder']

        # Get stage file extension (.usd for Pokemon Stadium, .dat for others)
        file_ext = '.usd' if stage_code == 'GrPs' else '.dat'

        # Paths in storage
        storage_stage_path = STORAGE_PATH / 'das' / stage_folder
        stage_zip_path = storage_stage_path / f"{variant_id}.zip"
        screenshot_path = storage_stage_path / f"{variant_id}_screenshot.png"

        if not stage_zip_path.exists():
            return jsonify({
                'success': False,
                'error': f'Stage variant not found in storage: {variant_id}'
            }), 404

        # Create export directory
        export_dir = OUTPUT_PATH / "mod_exports"
        export_dir.mkdir(parents=True, exist_ok=True)

        # Create export filename
        safe_stage = "".join(c for c in stage_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
        safe_variant = "".join(c for c in variant_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
        export_filename = f"{safe_stage}_{safe_variant}.zip"
        export_path = export_dir / export_filename

        # Create ZIP with stage file and screenshot
        with zipfile.ZipFile(export_path, 'w', zipfile.ZIP_DEFLATED) as export_zip:
            # Extract and add stage .dat/.usd file from storage ZIP
            with zipfile.ZipFile(stage_zip_path, 'r') as source_zip:
                for item in source_zip.namelist():
                    if item.lower().endswith(file_ext):
                        stage_data = source_zip.read(item)
                        export_zip.writestr(item, stage_data)
                        logger.info(f"  Added: {item}")

            # Add screenshot if exists
            if screenshot_path.exists():
                export_zip.write(screenshot_path, 'screenshot.png')
                logger.info(f"  Added: screenshot.png")

        logger.info(f"[OK] Stage exported: {export_filename}")

        return jsonify({
            'success': True,
            'filename': export_filename
        })
    except Exception as e:
        logger.error(f"Stage export error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/export/mod/<filename>', methods=['GET'])
def download_mod(filename):
    """Download an exported mod file"""
    try:
        export_dir = OUTPUT_PATH / "mod_exports"
        file_path = export_dir / filename

        if not file_path.exists():
            return jsonify({
                'success': False,
                'error': 'Export file not found'
            }), 404

        @after_this_request
        def remove_file(response):
            try:
                os.remove(file_path)
                logger.info(f"Deleted mod export file after download: {filename}")
            except Exception as error:
                logger.error(f"Error deleting mod export file {filename}: {str(error)}")
            return response

        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/zip'
        )
    except Exception as e:
        logger.error(f"Mod download error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# REMOVED: Old intake/import endpoint - replaced with unified /api/mex/import/file endpoint


# ============= Unified Import Endpoint =============

@app.route('/api/mex/import/file', methods=['POST'])
def import_file():
    """
    Unified import endpoint for both character costumes and stage mods.

    Accepts ZIP file upload, auto-detects type, and processes accordingly.
    Includes slippi safety validation with user choice to fix or import as-is.
    """
    try:
        # Check if file was uploaded
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file uploaded'
            }), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400

        # Check if file is a supported archive type
        is_zip = file.filename.lower().endswith('.zip')
        is_7z = file.filename.lower().endswith('.7z')

        if not (is_zip or is_7z):
            return jsonify({
                'success': False,
                'error': 'Only ZIP and 7z files are supported'
            }), 400

        # Get slippi_action parameter (can be "fix", "import_as_is", or None)
        slippi_action = request.form.get('slippi_action')

        # Get custom_title parameter if provided (for nucleus:// imports)
        custom_title = request.form.get('custom_title')
        logger.info(f"[DEBUG] custom_title from form: '{custom_title}' (type: {type(custom_title).__name__})")

        # Save uploaded file to temp location with correct suffix
        suffix = '.zip' if is_zip else '.7z'
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            file.save(tmp.name)
            temp_zip_path = tmp.name

        try:
            logger.info(f"=== UNIFIED IMPORT: {file.filename} ===")

            # PHASE 1: Try character detection first
            logger.info("Phase 1: Attempting character detection...")
            character_infos = detect_character_from_zip(temp_zip_path)

            if character_infos:
                logger.info(f"[OK] Detected {len(character_infos)} character costume(s)")

                # SLIPPI VALIDATION: Check if any costume needs slippi validation dialog
                if slippi_action is None:
                    # First time upload - validate slippi safety
                    unsafe_costumes = []
                    with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                        for char_info in character_infos:
                            # Extract DAT to temp file for validation
                            dat_data = zip_ref.read(char_info['dat_file'])
                            with tempfile.NamedTemporaryFile(suffix='.dat', delete=False) as tmp_dat:
                                tmp_dat.write(dat_data)
                                tmp_dat_path = tmp_dat.name

                            try:
                                validation = validate_for_slippi(tmp_dat_path, auto_fix=False)
                                if not validation['slippi_safe']:
                                    unsafe_costumes.append({
                                        'character': char_info['character'],
                                        'color': char_info['color']
                                    })
                            finally:
                                os.unlink(tmp_dat_path)

                    # If any costume is not slippi safe, ask user what to do
                    if unsafe_costumes:
                        return jsonify({
                            'success': False,
                            'type': 'slippi_dialog',
                            'unsafe_costumes': unsafe_costumes,
                            'message': 'This costume is not Slippi safe. Choose an action:'
                        }), 200

                # Sort Ice Climbers: Popo before Nana (Nana copies Popo's CSP)
                def ice_climbers_sort_key(char_info):
                    if char_info.get('is_popo'):
                        return 0  # Popo first
                    elif char_info.get('is_nana'):
                        return 1  # Nana second
                    else:
                        return 0  # Other characters

                character_infos_sorted = sorted(character_infos, key=ice_climbers_sort_key)

                # Determine auto_fix setting based on user choice
                auto_fix = (slippi_action == 'fix')

                # Import each detected costume
                results = []
                imported_skin_ids = {}  # Track actual skin IDs: costume_code -> skin_id
                for character_info in character_infos_sorted:
                    logger.info(f"  - Importing {character_info['character']} - {character_info['color']}")
                    logger.info(f"[DEBUG] Calling import_character_costume with custom_name='{custom_title}'")
                    result = import_character_costume(temp_zip_path, character_info, file.filename, auto_fix=auto_fix, custom_name=custom_title)
                    if result.get('success'):
                        results.append({
                            'character': character_info['character'],
                            'color': character_info['color']
                        })
                        # Track the actual skin ID that was created
                        if result.get('skin_id'):
                            imported_skin_ids[character_info['costume_code']] = result['skin_id']

                # Post-process: Fix Ice Climbers pairing with actual skin IDs
                if any(ci.get('is_popo') or ci.get('is_nana') for ci in character_infos_sorted):
                    fix_ice_climbers_pairing(character_infos_sorted, imported_skin_ids)

                return jsonify({
                    'success': True,
                    'type': 'character',
                    'imported_count': len(results),
                    'costumes': results,
                    'message': f"Imported {len(results)} costume(s)"
                })

            # PHASE 2: Try stage detection
            logger.info("Phase 2: Attempting stage detection...")
            stage_infos = detect_stage_from_zip(temp_zip_path)

            if stage_infos:
                logger.info(f"[OK] Detected {len(stage_infos)} stage mod(s)")

                # Import each detected stage
                results = []
                for stage_info in stage_infos:
                    logger.info(f"  - Importing {stage_info['stage_name']}")
                    result = import_stage_mod(temp_zip_path, stage_info, file.filename, custom_name=custom_title)
                    if result.get('success'):
                        results.append({
                            'stage': stage_info['stage_name'],
                            'variant': result.get('variant_id')
                        })

                return jsonify({
                    'success': True,
                    'type': 'stage',
                    'imported_count': len(results),
                    'stages': results,
                    'message': f"Imported {len(results)} stage variant(s)"
                })

            # PHASE 3: Detection failed
            logger.warning("✗ Could not detect type - not a character costume or stage mod")
            return jsonify({
                'success': False,
                'error': 'Could not detect mod type. Make sure the ZIP contains a valid character costume (.dat with Ply symbols) or stage file (GrXx.dat/.usd)'
            }), 400

        finally:
            # Clean up temp file
            try:
                os.unlink(temp_zip_path)
            except:
                pass

    except Exception as e:
        logger.error(f"Import error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Import error: {str(e)}'
        }), 500


def fix_ice_climbers_pairing(character_infos: list, imported_skin_ids: dict):
    """
    Fix Ice Climbers pairing after import using actual skin IDs.

    Args:
        character_infos: List of character info dicts with pairing metadata
        imported_skin_ids: Dict mapping costume_code -> actual skin_id created
    """
    try:
        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        if 'Ice Climbers' not in metadata.get('characters', {}):
            return

        # Build a mapping of costume_code -> character_info for easy lookup
        info_by_code = {ci['costume_code']: ci for ci in character_infos}

        # Update each Ice Climbers skin with actual paired IDs
        updated = False
        for skin in metadata['characters']['Ice Climbers']['skins']:
            # Skip if this specific skin wasn't just imported
            # Check by skin ID, not costume code, since multiple skins can share the same costume code
            if skin['id'] not in imported_skin_ids.values():
                continue

            costume_code = skin['costume_code']
            char_info = info_by_code.get(costume_code)
            if not char_info:
                continue

            # Update Popo with actual Nana ID
            if char_info.get('is_popo') and char_info.get('pair_costume_code'):
                nana_costume_code = char_info['pair_costume_code']
                actual_nana_id = imported_skin_ids.get(nana_costume_code)
                if actual_nana_id:
                    skin['paired_nana_id'] = actual_nana_id
                    logger.info(f"Linked Popo {skin['id']} -> Nana {actual_nana_id}")
                    updated = True

            # Update Nana with actual Popo ID
            elif char_info.get('is_nana') and char_info.get('pair_costume_code'):
                popo_costume_code = char_info['pair_costume_code']
                actual_popo_id = imported_skin_ids.get(popo_costume_code)
                if actual_popo_id:
                    skin['paired_popo_id'] = actual_popo_id
                    logger.info(f"Linked Nana {skin['id']} -> Popo {actual_popo_id}")
                    updated = True

        # Save metadata if we made changes
        if updated:
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            logger.info("[OK] Updated Ice Climbers pairing with actual skin IDs")

    except Exception as e:
        logger.error(f"Failed to fix Ice Climbers pairing: {e}", exc_info=True)


def extract_custom_name_from_filename(filename: str, character_name: str) -> str:
    """
    Extract a custom name from the zip filename to use in costume ID.

    Args:
        filename: Original zip filename (e.g., "Villager Climbers (2).zip")
        character_name: Detected character name (e.g., "Ice Climbers")

    Returns:
        Custom name string, or None if no meaningful name could be extracted

    Examples:
        "Villager Climbers (2).zip" -> "villager-climbers"
        "Fox - Shadow Link.zip" -> "shadow-link"
        "Ice Climbers_CustomSkin.zip" -> "customskin"
        "costume.zip" -> None (too generic)
    """
    # Remove file extension
    base_name = Path(filename).stem

    # Remove numbers in parentheses: "(2)", "(1)", etc.
    base_name = re.sub(r'\s*\(\d+\)\s*$', '', base_name)

    # Try to remove character name prefix if present
    # Handle patterns like "Fox - CustomName" or "Ice Climbers - CustomName"
    char_pattern = re.escape(character_name)
    base_name = re.sub(rf'^{char_pattern}\s*[-_:]\s*', '', base_name, flags=re.IGNORECASE)

    # Remove common version patterns: v1, v2, V1.0, etc.
    base_name = re.sub(r'\s*[vV]\d+(\.\d+)?\s*$', '', base_name)

    # Clean up: convert to lowercase, replace spaces/underscores with hyphens
    base_name = base_name.lower()
    base_name = re.sub(r'[_\s]+', '-', base_name)

    # Remove special characters except hyphens
    base_name = re.sub(r'[^a-z0-9-]', '', base_name)

    # Remove multiple consecutive hyphens
    base_name = re.sub(r'-+', '-', base_name)

    # Remove leading/trailing hyphens
    base_name = base_name.strip('-')

    # Check if result is too generic or empty
    generic_names = {'costume', 'skin', 'mod', 'custom', 'default', 'new', 'import'}
    if not base_name or base_name in generic_names or len(base_name) < 2:
        return None

    return base_name


def import_character_costume(zip_path: str, char_info: dict, original_filename: str, auto_fix: bool = False, custom_name: str = None) -> dict:
    """
    Import a character costume to storage.

    Args:
        zip_path: Path to the uploaded ZIP file
        char_info: Character detection info
        original_filename: Original filename of the upload
        auto_fix: If True, apply slippi fixes to the DAT file
        custom_name: Optional custom name to use instead of extracting from filename
    """
    try:
        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
        else:
            metadata = {'characters': {}, 'stages': {}}

        # Ensure 'stages' section exists
        if 'stages' not in metadata:
            metadata['stages'] = {}

        character = char_info['character']

        # Create character folder
        char_folder = STORAGE_PATH / character
        char_folder.mkdir(parents=True, exist_ok=True)

        # Generate unique ID for this skin
        char_data = metadata.get('characters', {}).get(character, {'skins': []})
        existing_ids = [skin['id'] for skin in char_data.get('skins', [])]

        logger.info(f"[DEBUG import_character_costume] custom_name parameter: '{custom_name}' (type: {type(custom_name).__name__})")
        logger.info(f"[DEBUG import_character_costume] original_filename: '{original_filename}'")

        # Use provided custom name, or extract from filename
        if not custom_name:
            logger.info(f"[DEBUG] custom_name is falsy, extracting from filename")
            custom_name = extract_custom_name_from_filename(original_filename, character)
            logger.info(f"[DEBUG] Extracted custom_name from filename: '{custom_name}'")

        # Extract descriptive name from DAT filename (remove .dat extension and clean up)
        dat_basename = os.path.splitext(os.path.basename(char_info['dat_file']))[0]
        # Clean and sanitize: lowercase, replace spaces/special chars with hyphens
        dat_name_clean = re.sub(r'[^\w\s-]', '', dat_basename)  # Remove special chars except space and hyphen
        dat_name_clean = re.sub(r'[\s_]+', '-', dat_name_clean)  # Replace spaces/underscores with hyphens
        dat_name_clean = dat_name_clean.lower().strip('-')  # Lowercase and remove leading/trailing hyphens

        # Generate base ID: use custom name if found, otherwise use DAT filename
        if custom_name:
            base_id = f"{custom_name}-{dat_name_clean}"
            logger.info(f"Using custom name from filename: '{custom_name}' -> '{base_id}'")
        else:
            base_id = dat_name_clean
            logger.info(f"Using DAT filename as name: '{base_id}'")

        # Handle duplicates: append 2-digit counter without dash (e.g., "name01", "name02")
        skin_id = base_id
        counter = 1
        while skin_id in existing_ids:
            skin_id = f"{base_id}{counter:02d}"
            counter += 1

        # Final paths
        final_zip = char_folder / f"{skin_id}.zip"

        # Copy files from uploaded ZIP to final ZIP with correct structure
        csp_source = 'imported'

        # SLIPPI VALIDATION: Validate DAT before importing
        slippi_validation = None
        with zipfile.ZipFile(zip_path, 'r') as source_zip:
            # Extract DAT for validation
            dat_data = source_zip.read(char_info['dat_file'])
            with tempfile.NamedTemporaryFile(suffix='.dat', delete=False) as tmp_dat:
                tmp_dat.write(dat_data)
                tmp_dat_path = tmp_dat.name

            try:
                slippi_validation = validate_for_slippi(tmp_dat_path, auto_fix=auto_fix)
                logger.info(f"Slippi validation: slippi_safe={slippi_validation['slippi_safe']}, auto_fix={auto_fix}")

                # If auto_fix was applied, read the fixed DAT
                if auto_fix and slippi_validation.get('fix_applied'):
                    with open(tmp_dat_path, 'rb') as f:
                        dat_data = f.read()
                    logger.info("Using slippi-fixed DAT file")
            finally:
                os.unlink(tmp_dat_path)

        with zipfile.ZipFile(zip_path, 'r') as source_zip:
            with zipfile.ZipFile(final_zip, 'w') as dest_zip:
                # Copy DAT file (potentially fixed version)
                dest_zip.writestr(f"{char_info['costume_code']}Mod.dat", dat_data)

                # Handle CSP - copy if found, generate if missing
                csp_data = None
                if char_info['csp_file']:
                    # CSP found in ZIP - copy it
                    csp_data = source_zip.read(char_info['csp_file'])
                    logger.info(f"Using CSP from ZIP: {char_info['csp_file']}")
                else:
                    # No CSP in ZIP - generate one
                    logger.info("No CSP found in ZIP, generating...")

                    # Ice Climbers Popo: Extract both Popo and Nana DATs to same temp dir
                    # so generate_csp can find the pair and create composite CSP
                    if char_info.get('is_popo'):
                        logger.info("Ice Climbers Popo detected - extracting pair for composite CSP")
                        temp_dir = tempfile.mkdtemp()
                        try:
                            # Extract Popo DAT
                            popo_dat_name = os.path.basename(char_info['dat_file'])
                            tmp_dat_path = os.path.join(temp_dir, popo_dat_name)
                            with open(tmp_dat_path, 'wb') as f:
                                f.write(dat_data)

                            # Extract paired Nana DAT
                            nana_dat_name = os.path.basename(char_info['pair_dat_file'])
                            nana_dat_path = os.path.join(temp_dir, nana_dat_name)
                            nana_dat_data = source_zip.read(char_info['pair_dat_file'])
                            with open(nana_dat_path, 'wb') as f:
                                f.write(nana_dat_data)

                            # Generate composite CSP (generate_csp will detect pair)
                            generated_csp_path = generate_csp(tmp_dat_path)
                            if generated_csp_path and os.path.exists(generated_csp_path):
                                with open(generated_csp_path, 'rb') as f:
                                    csp_data = f.read()
                                logger.info("Successfully generated composite Ice Climbers CSP")
                                csp_source = 'generated'
                                # Clean up generated CSP
                                try:
                                    os.unlink(generated_csp_path)
                                except:
                                    pass
                            else:
                                logger.warning("Ice Climbers CSP generation failed")
                        finally:
                            # Clean up temp directory
                            try:
                                import shutil
                                shutil.rmtree(temp_dir)
                            except:
                                pass
                    else:
                        # Regular character or Nana - single DAT extraction
                        with tempfile.NamedTemporaryFile(suffix='.dat', delete=False) as tmp_dat:
                            tmp_dat.write(dat_data)
                            tmp_dat_path = tmp_dat.name

                        try:
                            generated_csp_path = generate_csp(tmp_dat_path)
                            if generated_csp_path and os.path.exists(generated_csp_path):
                                with open(generated_csp_path, 'rb') as f:
                                    csp_data = f.read()
                                logger.info("Successfully generated CSP")
                                csp_source = 'generated'
                                # Clean up generated CSP
                                try:
                                    os.unlink(generated_csp_path)
                                except:
                                    pass
                            else:
                                logger.warning("CSP generation failed")
                        finally:
                            # Clean up temp DAT
                            try:
                                os.unlink(tmp_dat_path)
                            except:
                                pass

                # Ice Climbers: Nana should copy composite CSP from Popo
                if char_info.get('is_nana') and not csp_data:
                    # Look for paired Popo in metadata
                    popo_color = char_info.get('pair_color')
                    if popo_color:
                        popo_id = f"{character.lower().replace(' ', '-')}-{popo_color.lower()}"

                        # Check if Popo already imported
                        if character in metadata.get('characters', {}):
                            for skin in metadata['characters'][character]['skins']:
                                if skin['id'] == popo_id:
                                    # Found Popo - copy its CSP
                                    popo_csp_path = STORAGE_PATH / character / f"{popo_id}_csp.png"
                                    if popo_csp_path.exists():
                                        csp_data = popo_csp_path.read_bytes()
                                        csp_source = 'copied_from_popo'
                                        logger.info(f"Copied composite CSP from Popo: {popo_id}")
                                    break

                # Save CSP to ZIP and storage if we have one
                if csp_data:
                    dest_zip.writestr('csp.png', csp_data)
                    # Save to storage for preview
                    storage_char_folder = STORAGE_PATH / character
                    storage_char_folder.mkdir(parents=True, exist_ok=True)
                    (storage_char_folder / f"{skin_id}_csp.png").write_bytes(csp_data)

                # Handle stock - copy if found, use vanilla if missing
                stock_data = None
                stock_source = 'imported'
                if char_info['stock_file']:
                    # Stock found in ZIP (using improved matching from character detector)
                    stock_data = source_zip.read(char_info['stock_file'])
                else:
                    # No stock in ZIP - try vanilla matching costume
                    vanilla_stock_path = VANILLA_ASSETS_DIR / character / char_info['costume_code'] / "stock.png"
                    if vanilla_stock_path.exists():
                        with open(vanilla_stock_path, 'rb') as f:
                            stock_data = f.read()
                        stock_source = 'vanilla'

                # Ice Climbers: Nana should copy stock from Popo
                if char_info.get('is_nana') and not stock_data:
                    # Look for paired Popo in metadata
                    popo_color = char_info.get('pair_color')
                    if popo_color:
                        popo_id = f"{character.lower().replace(' ', '-')}-{popo_color.lower()}"

                        # Check if Popo already imported
                        if character in metadata.get('characters', {}):
                            for skin in metadata['characters'][character]['skins']:
                                if skin['id'] == popo_id:
                                    # Found Popo - copy its stock
                                    popo_stock_path = STORAGE_PATH / character / f"{popo_id}_stc.png"
                                    if popo_stock_path.exists():
                                        stock_data = popo_stock_path.read_bytes()
                                        stock_source = 'copied_from_popo'
                                        logger.info(f"Copied stock from Popo: {popo_id}")
                                    break

                # Save stock if we have one
                if stock_data:
                    dest_zip.writestr('stc.png', stock_data)
                    storage_char_folder = STORAGE_PATH / character
                    (storage_char_folder / f"{skin_id}_stc.png").write_bytes(stock_data)

        # Update metadata
        if character not in metadata['characters']:
            metadata['characters'][character] = {'skins': []}

        # Determine display name: use custom_name if provided, otherwise use DAT filename
        display_name = custom_name if custom_name else dat_name_clean
        logger.info(f"[DEBUG] Final display_name: '{display_name}' (custom_name: '{custom_name}', dat_name_clean: '{dat_name_clean}')")

        # Build skin entry
        skin_entry = {
            'id': skin_id,
            'color': display_name,  # Display name shown in UI
            'costume_code': char_info['costume_code'],
            'filename': f"{skin_id}.zip",
            'has_csp': csp_data is not None,
            'has_stock': stock_data is not None,
            'csp_source': csp_source,
            'stock_source': stock_source if stock_data else None,
            'date_added': datetime.now().isoformat(),
            # Slippi safety metadata
            'slippi_safe': slippi_validation['slippi_safe'] if slippi_validation else False,
            'slippi_tested': True,
            'slippi_test_date': datetime.now().isoformat(),
            'slippi_manual_override': None
        }

        # Ice Climbers pairing metadata
        # Note: paired_nana_id/paired_popo_id will be set by fix_ice_climbers_pairing()
        # after both costumes are imported, using actual skin IDs
        if char_info.get('is_popo'):
            skin_entry['is_popo'] = True
            skin_entry['visible'] = True
            # Placeholder - will be updated with actual Nana ID after import
            skin_entry['paired_nana_id'] = None

        elif char_info.get('is_nana'):
            skin_entry['is_nana'] = True
            skin_entry['visible'] = False  # Hidden in UI
            # Placeholder - will be updated with actual Popo ID after import
            skin_entry['paired_popo_id'] = None

        metadata['characters'][character]['skins'].append(skin_entry)

        # Save metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Saved character costume: {final_zip}")

        return {
            'success': True,
            'type': 'character',
            'character': character,
            'color': dat_name_clean,  # Use descriptive name
            'skin_id': skin_id,  # Return the actual skin ID for pairing
            'message': f"Imported {character} - {dat_name_clean} costume"
        }

    except Exception as e:
        logger.error(f"Character import error: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def import_stage_mod(zip_path: str, stage_info: dict, original_filename: str, custom_name: str = None) -> dict:
    """Import a stage mod to storage"""
    try:
        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
        else:
            metadata = {'characters': {}, 'stages': {}}

        # Ensure 'stages' section exists
        if 'stages' not in metadata:
            metadata['stages'] = {}

        stage_folder_name = stage_info['folder']
        stage_name = stage_info['stage_name']

        # Create stage folder in storage/das/
        das_folder = STORAGE_PATH / 'das' / stage_folder_name
        das_folder.mkdir(parents=True, exist_ok=True)

        # Generate unique ID for this variant
        stage_data = metadata.get('stages', {}).get(stage_folder_name, {'variants': []})
        existing_ids = [v['id'] for v in stage_data.get('variants', [])]

        # Generate sequential ID based on custom_name or original filename
        if custom_name:
            # Sanitize and limit stage names to 10 characters to prevent crashes
            base_name = sanitize_filename(custom_name)[:10].lower().replace(' ', '-')
        else:
            base_name = sanitize_filename(Path(original_filename).stem)[:10].lower().replace(' ', '-')

        variant_id = base_name
        counter = 1
        while variant_id in existing_ids:
            variant_id = f"{base_name}-{counter:03d}"
            counter += 1

        # Final paths
        final_zip = das_folder / f"{variant_id}.zip"

        # Create a new ZIP with only this stage's files
        with zipfile.ZipFile(zip_path, 'r') as source_zf:
            with zipfile.ZipFile(final_zip, 'w', zipfile.ZIP_DEFLATED) as dest_zf:
                # Add the specific stage DAT file
                stage_file_data = source_zf.read(stage_info['stage_file'])
                stage_file_basename = os.path.basename(stage_info['stage_file'])
                dest_zf.writestr(stage_file_basename, stage_file_data)
                logger.info(f"[OK] Added stage file to ZIP: {stage_file_basename}")

                # Add screenshot to ZIP if available
                if stage_info['screenshot']:
                    screenshot_data = source_zf.read(stage_info['screenshot'])
                    screenshot_basename = os.path.basename(stage_info['screenshot'])
                    dest_zf.writestr(screenshot_basename, screenshot_data)
                    logger.info(f"[OK] Added screenshot to ZIP: {screenshot_basename}")

        # Extract screenshot to storage folder for preview
        has_screenshot = False
        if stage_info['screenshot']:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                screenshot_data = zf.read(stage_info['screenshot'])
                screenshot_ext = os.path.splitext(stage_info['screenshot'])[1]

                # Save to storage folder
                screenshot_path = das_folder / f"{variant_id}_screenshot{screenshot_ext}"
                screenshot_path.write_bytes(screenshot_data)

                has_screenshot = True
                logger.info(f"[OK] Saved screenshot preview: {screenshot_path}")

        # Update metadata
        if stage_folder_name not in metadata['stages']:
            metadata['stages'][stage_folder_name] = {'variants': []}

        # Use variant_id as display name (it's already limited to 10 chars and uses custom_name if provided)
        display_name = variant_id

        metadata['stages'][stage_folder_name]['variants'].append({
            'id': variant_id,
            'name': display_name,
            'filename': f"{variant_id}.zip",
            'has_screenshot': has_screenshot,
            'date_added': datetime.now().isoformat()
            # No default slippi status - will show as "Unknown" until manually set
        })

        # Save metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Saved stage mod: {final_zip}")

        return {
            'success': True,
            'type': 'stage',
            'stage': stage_name,
            'variant_id': variant_id,
            'message': f"Imported {stage_name} stage variant"
        }

    except Exception as e:
        logger.error(f"Stage import error: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


# ============= DAS (Dynamic Alternate Stages) Endpoints =============

DAS_STAGES = {
    'GrNBa': {'code': 'GrNBa', 'name': 'Battlefield', 'folder': 'battlefield'},
    'GrNLa': {'code': 'GrNLa', 'name': 'Final Destination', 'folder': 'final_destination'},
    'GrSt': {'code': 'GrSt', 'name': "Yoshi's Story", 'folder': 'yoshis_story'},
    'GrOp': {'code': 'GrOp', 'name': 'Dreamland', 'folder': 'dreamland'},
    'GrPs': {'code': 'GrPs', 'name': 'Pokemon Stadium', 'folder': 'pokemon_stadium'},
    'GrIz': {'code': 'GrIz', 'name': 'Fountain of Dreams', 'folder': 'fountain_of_dreams'}
}

# Button indicator utility functions for DAS stage variants
def strip_button_indicator(filename):
    """
    Remove button indicator from filename stem
    Example: vanilla(B) -> vanilla
    """
    import re
    return re.sub(r'\(([ABXYLRZ])\)$', '', filename, flags=re.IGNORECASE)

def extract_button_indicator(filename):
    """
    Extract button indicator from filename stem
    Example: vanilla(B) -> B
    Returns None if no button indicator found
    """
    import re
    match = re.search(r'\(([ABXYLRZ])\)$', filename, flags=re.IGNORECASE)
    return match.group(1).upper() if match else None

def add_button_indicator(filename, button):
    """
    Add button indicator to filename (replaces existing if present)
    Example: vanilla, B -> vanilla(B)
    """
    cleaned = strip_button_indicator(filename)
    return f"{cleaned}({button.upper()})"

def sanitize_filename(name):
    """
    Sanitize a display name for use as a filename
    Removes filesystem-unsafe characters while keeping readability
    Example: "Grop's: Dreamland!" -> "Grop's Dreamland!"
    """
    import re
    # Remove characters that are illegal on Windows/Mac/Linux
    # Keep: letters, numbers, spaces, hyphens, underscores, apostrophes, parentheses
    sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
    # Remove leading/trailing whitespace
    sanitized = sanitized.strip()
    return sanitized


def find_stage_screenshot(folder_path: Path, variant_id: str):
    """
    Find a stage screenshot with any image extension.
    Returns (exists: bool, path: Path or None, extension: str or None)
    """
    import glob
    # Look for screenshot with any common image extension
    pattern = str(folder_path / f"{variant_id}_screenshot.*")
    matches = glob.glob(pattern)

    # Filter to only image extensions
    image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
    for match in matches:
        ext = os.path.splitext(match)[1].lower()
        if ext in image_extensions:
            return True, Path(match), ext

    return False, None, None


# Mapping of stage codes to default screenshot filenames
DAS_DEFAULT_SCREENSHOTS = {
    'GrNBa': 'battlefield.jpg',
    'GrNLa': 'final destination.png',
    'GrSt': 'Yoshis story.jpg',
    'GrOp': 'dreamland.jpg',
    'GrPs': 'pokemon stadium.jpg',
    'GrIz': 'Fountain of Dreams.webp'
}

@app.route('/api/mex/das/status', methods=['GET'])
def das_get_status():
    """Check if DAS framework is installed"""
    try:
        # Check if DAS loader files exist in current project's files/
        project_files_path = get_project_files_dir()
        installed_stages = []

        for stage_code, stage_info in DAS_STAGES.items():
            loader_path = project_files_path / f"{stage_code}.dat"
            folder_path = project_files_path / stage_code

            if loader_path.exists() and folder_path.exists():
                installed_stages.append(stage_code)

        is_installed = len(installed_stages) > 0

        return jsonify({
            'success': True,
            'installed': is_installed,
            'installedStages': installed_stages,
            'totalStages': len(DAS_STAGES)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/das/install', methods=['POST'])
def das_install():
    """Install DAS framework"""
    try:
        import shutil

        logger.info("=== DAS FRAMEWORK INSTALLATION ===")

        # Use BASE_PATH for bundled resources (includes DAS files)
        das_source = BASE_PATH / "utility" / "DynamicAlternateStages"
        project_files = get_project_files_dir()

        if not das_source.exists():
            return jsonify({
                'success': False,
                'error': f'DAS framework source not found at {das_source}'
            }), 500

        project_files.mkdir(parents=True, exist_ok=True)

        # Install each stage
        for stage_code, stage_info in DAS_STAGES.items():
            logger.info(f"Installing DAS for {stage_info['name']} ({stage_code})...")

            # Pokemon Stadium uses .usd, others use .dat
            file_ext = '.usd' if stage_code == 'GrPs' else '.dat'

            # Create stage folder first
            stage_folder = project_files / stage_code
            stage_folder.mkdir(exist_ok=True)
            logger.info(f"  Created folder: {stage_code}/")

            # Get paths
            original_stage = project_files / f"{stage_code}{file_ext}"
            loader_src = das_source / f"{stage_code}{file_ext}"
            vanilla_in_folder = stage_folder / f"vanilla{file_ext}"

            # If vanilla variant doesn't exist yet and original stage exists, copy it into folder
            if not vanilla_in_folder.exists() and original_stage.exists():
                shutil.copy2(original_stage, vanilla_in_folder)
                logger.info(f"  Copied vanilla stage to {stage_code}/vanilla{file_ext}")

                # Copy default screenshot for vanilla variant to storage
                if stage_code in DAS_DEFAULT_SCREENSHOTS:
                    default_screenshot = BASE_PATH / "utility" / "assets" / "stages" / DAS_DEFAULT_SCREENSHOTS[stage_code]
                    if default_screenshot.exists():
                        storage_das_folder = STORAGE_PATH / 'das' / stage_info['folder']
                        storage_das_folder.mkdir(parents=True, exist_ok=True)
                        storage_screenshot = storage_das_folder / f"vanilla_screenshot.png"
                        shutil.copy2(default_screenshot, storage_screenshot)
                        logger.info(f"  Copied default screenshot to storage: {storage_screenshot.name}")

            # Install DAS loader (replaces original stage file)
            if loader_src.exists():
                shutil.copy2(loader_src, original_stage)
                logger.info(f"  Installed DAS loader: {stage_code}{file_ext}")
            else:
                logger.warning(f"  DAS loader not found: {loader_src}")

        logger.info("DAS framework installed successfully")

        return jsonify({
            'success': True,
            'message': 'DAS framework installed successfully'
        })
    except Exception as e:
        logger.error(f"DAS installation error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/das/stages', methods=['GET'])
def das_list_stages():
    """List all DAS-supported stages"""
    try:
        stages = []
        for stage_code, stage_info in DAS_STAGES.items():
            stages.append({
                'code': stage_code,
                'name': stage_info['name'],
                'folder': stage_info['folder']
            })

        return jsonify({
            'success': True,
            'stages': stages
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/das/stages/<stage_code>/variants', methods=['GET'])
def das_get_stage_variants(stage_code):
    """Get DAS variants for a specific stage from MEX project"""
    try:
        if stage_code not in DAS_STAGES:
            return jsonify({
                'success': False,
                'error': f'Unknown stage code: {stage_code}'
            }), 400

        # List stage files in current project's files/{stage_code}/ (.dat or .usd for Pokemon Stadium)
        project_files = get_project_files_dir()
        stage_folder = project_files / stage_code
        variants = []

        if stage_folder.exists() and stage_folder.is_dir():
            # Pokemon Stadium uses .usd, others use .dat
            file_pattern = '*.usd' if stage_code == 'GrPs' else '*.dat'

            # Load metadata to get slippi status and other info
            metadata_file = STORAGE_PATH / 'metadata.json'
            metadata = {}
            if metadata_file.exists():
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)

            stage_folder_name = DAS_STAGES[stage_code]['folder']
            stage_metadata = metadata.get('stages', {}).get(stage_folder_name, {})
            metadata_variants = {v['id']: v for v in stage_metadata.get('variants', [])}

            for stage_file in stage_folder.glob(file_pattern):
                filename_stem = stage_file.stem  # e.g., "Autumn Dreamland" or "Autumn Dreamland(B)"

                # Extract button indicator (e.g., "Autumn Dreamland(B)" -> "B")
                button = extract_button_indicator(filename_stem)

                # Strip button indicator for matching
                # e.g., "Autumn Dreamland(B)" -> "Autumn Dreamland"
                display_name_from_file = strip_button_indicator(filename_stem)

                # Reverse-lookup: display name -> variant_id using metadata
                # This allows us to find the screenshot which is named with variant_id
                variant_id_for_screenshot = None
                variant_meta = {}

                # Try to match display name to variant in metadata
                sanitized_display_name = sanitize_filename(display_name_from_file).lower()
                for vid, vmeta in metadata_variants.items():
                    variant_display_name = vmeta.get('name', vid)
                    if sanitize_filename(variant_display_name).lower() == sanitized_display_name:
                        variant_id_for_screenshot = vid  # This is the storage filename (without .zip)
                        variant_meta = vmeta
                        logger.info(f"Matched display name '{display_name_from_file}' to variant_id '{vid}'")
                        break

                # Fallback: if no match in metadata, treat filename as variant_id (backwards compatibility)
                if variant_id_for_screenshot is None:
                    variant_id_for_screenshot = display_name_from_file
                    variant_meta = metadata_variants.get(variant_id_for_screenshot, {})
                    logger.info(f"No metadata match for '{display_name_from_file}', using as variant_id (backwards compatibility)")

                # Check if screenshot exists in storage (supports multiple extensions)
                screenshot_folder = STORAGE_PATH / 'das' / stage_folder_name
                has_screenshot, screenshot_path, screenshot_ext = find_stage_screenshot(screenshot_folder, variant_id_for_screenshot)

                variants.append({
                    'name': filename_stem,  # Display name with button indicator (what user sees in files)
                    'filename': stage_file.name,
                    'stageCode': stage_code,
                    'button': button,  # Button indicator (B, X, Y, L, R, Z) or None
                    'hasScreenshot': has_screenshot,
                    'screenshotUrl': f"/storage/das/{stage_folder_name}/{variant_id_for_screenshot}_screenshot{screenshot_ext}" if has_screenshot else None,
                    'slippi_safe': variant_meta.get('slippi_safe'),
                    'slippi_tested': variant_meta.get('slippi_tested', False)
                })

        return jsonify({
            'success': True,
            'stage': DAS_STAGES[stage_code],
            'variants': variants
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/das/storage/variants', methods=['GET'])
def das_list_storage_variants():
    """List all DAS variants in storage"""
    try:
        stage_code = request.args.get('stage')
        variants = []

        # Load metadata to get proper names
        metadata_file = STORAGE_PATH / 'metadata.json'
        metadata = {}
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)

        # Determine which stages to scan
        stages_to_scan = {stage_code: DAS_STAGES[stage_code]} if stage_code and stage_code in DAS_STAGES else DAS_STAGES

        for code, stage_info in stages_to_scan.items():
            stage_folder = stage_info['folder']
            stage_storage_path = STORAGE_PATH / "das" / stage_folder

            # Get variants from metadata for this stage
            stage_metadata = metadata.get('stages', {}).get(stage_folder, {})
            metadata_variants_list = stage_metadata.get('variants', [])

            if stage_storage_path.exists():
                # Build a lookup of all zip files that exist on disk
                zip_files = {zip_file.stem: zip_file for zip_file in stage_storage_path.glob('*.zip')}

                # First, add variants in metadata order (if they exist on disk)
                for variant_meta in metadata_variants_list:
                    variant_id = variant_meta['id']
                    zip_file = zip_files.get(variant_id)

                    # Only add if the zip file actually exists
                    if zip_file:
                        variant_name = variant_meta.get('name', variant_id)

                        # Check for screenshot in storage (supports multiple extensions)
                        has_screenshot, screenshot_path, screenshot_ext = find_stage_screenshot(stage_storage_path, variant_id)

                        variants.append({
                            'stageCode': code,
                            'stageName': stage_info['name'],
                            'id': variant_id,  # ← Immutable ID (filename)
                            'name': variant_name,  # ← Editable display name
                            'zipPath': str(zip_file.relative_to(PROJECT_ROOT)),
                            'hasScreenshot': has_screenshot,
                            'screenshotUrl': f"/storage/das/{stage_info['folder']}/{variant_id}_screenshot{screenshot_ext}" if has_screenshot else None,
                            'slippi_safe': variant_meta.get('slippi_safe'),
                            'slippi_tested': variant_meta.get('slippi_tested', False),
                            'slippi_test_date': variant_meta.get('slippi_test_date')
                        })

                        # Remove from zip_files so we don't add it again
                        del zip_files[variant_id]

                # Then, add any remaining zip files that aren't in metadata (shouldn't happen normally)
                for variant_id, zip_file in zip_files.items():
                    has_screenshot, screenshot_path, screenshot_ext = find_stage_screenshot(stage_storage_path, variant_id)

                    variants.append({
                        'stageCode': code,
                        'stageName': stage_info['name'],
                        'id': variant_id,
                        'name': variant_id,  # Fallback: use ID as name
                        'zipPath': str(zip_file.relative_to(PROJECT_ROOT)),
                        'hasScreenshot': has_screenshot,
                        'screenshotUrl': f"/storage/das/{stage_info['folder']}/{variant_id}_screenshot{screenshot_ext}" if has_screenshot else None,
                        'slippi_safe': None,
                        'slippi_tested': False,
                        'slippi_test_date': None
                    })

        return jsonify({
            'success': True,
            'variants': variants
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/das/import', methods=['POST'])
def das_import_variant():
    """Import DAS variant to MEX project"""
    try:
        data = request.json
        stage_code = data.get('stageCode')
        variant_path = data.get('variantPath')

        logger.info(f"=== DAS IMPORT REQUEST ===")
        logger.info(f"Stage Code: {stage_code}")
        logger.info(f"Variant Path: {variant_path}")

        if not stage_code or not variant_path:
            return jsonify({
                'success': False,
                'error': 'Missing stageCode or variantPath parameter'
            }), 400

        if stage_code not in DAS_STAGES:
            return jsonify({
                'success': False,
                'error': f'Unknown stage code: {stage_code}'
            }), 400

        # Resolve variant path
        full_variant_path = PROJECT_ROOT / variant_path

        if not full_variant_path.exists():
            return jsonify({
                'success': False,
                'error': f'Variant ZIP not found: {variant_path}'
            }), 404

        # Import logic will be implemented via mex_bridge
        # For now, just copy the .dat file from the zip to the stage folder
        import zipfile
        import shutil

        project_files = get_project_files_dir()
        stage_folder = project_files / stage_code
        stage_folder.mkdir(exist_ok=True)

        # Pokemon Stadium uses .usd, others use .dat
        file_ext = '.usd' if stage_code == 'GrPs' else '.dat'

        with zipfile.ZipFile(full_variant_path, 'r') as zip_ref:
            # Find the stage file in the zip (.dat or .usd)
            stage_files = [f for f in zip_ref.namelist() if f.endswith(file_ext) or f.endswith('.dat')]
            if not stage_files:
                return jsonify({
                    'success': False,
                    'error': f'No {file_ext} file found in ZIP'
                }), 400

            # Read the stage file data
            stage_file = stage_files[0]
            stage_data = zip_ref.read(stage_file)

            # Get variant_id from ZIP filename
            variant_id = Path(full_variant_path).stem  # e.g., "autumn-dreamland"

            # Load metadata to get display name
            metadata_file = STORAGE_PATH / 'metadata.json'
            display_name = variant_id  # Fallback to variant_id if metadata not found

            if metadata_file.exists():
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)

                stage_folder_name = DAS_STAGES[stage_code]['folder']
                stage_metadata = metadata.get('stages', {}).get(stage_folder_name, {})

                # Find the variant in metadata by id
                for variant in stage_metadata.get('variants', []):
                    if variant['id'] == variant_id:
                        display_name = variant.get('name', variant_id)
                        logger.info(f"Found display name in metadata: '{display_name}' for variant_id '{variant_id}'")
                        break

            # Use sanitized display name for filename
            final_name = sanitize_filename(display_name)
            final_path = stage_folder / f"{final_name}{file_ext}"

            # If file already exists, append suffix to avoid conflicts
            if final_path.exists():
                count = 1
                while True:
                    final_name = f"{sanitize_filename(display_name)}_{count}"
                    final_path = stage_folder / f"{final_name}{file_ext}"
                    if not final_path.exists():
                        break
                    count += 1

            # Write directly to final location
            final_path.write_bytes(stage_data)
            logger.info(f"[OK] Extracted stage file to: {final_path}")
            logger.info(f"  Using mod name: {final_name}")

            # No screenshot copying needed - frontend references storage folder directly
            # Screenshot path: storage/das/{folder}/{variant_id}_screenshot.png

        logger.info(f"DAS variant imported to: {final_path}")

        return jsonify({
            'success': True,
            'message': 'DAS variant imported successfully',
            'path': str(final_path)
        })
    except Exception as e:
        logger.error(f"DAS import error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/das/remove', methods=['POST'])
def das_remove_variant():
    """Remove DAS variant from MEX project"""
    try:
        data = request.json
        stage_code = data.get('stageCode')
        variant_name = data.get('variantName')

        logger.info(f"=== DAS REMOVE REQUEST ===")
        logger.info(f"Stage Code: {stage_code}")
        logger.info(f"Variant Name: {variant_name}")

        if not stage_code or not variant_name:
            return jsonify({
                'success': False,
                'error': 'Missing stageCode or variantName parameter'
            }), 400

        if stage_code not in DAS_STAGES:
            return jsonify({
                'success': False,
                'error': f'Unknown stage code: {stage_code}'
            }), 400

        # Find and remove the variant file
        # Pokemon Stadium uses .usd, others use .dat
        file_ext = '.usd' if stage_code == 'GrPs' else '.dat'
        project_files = get_project_files_dir()
        stage_folder = project_files / stage_code
        variant_path = stage_folder / f"{variant_name}{file_ext}"

        if not variant_path.exists():
            return jsonify({
                'success': False,
                'error': f'Variant not found: {variant_name}{file_ext}'
            }), 404

        variant_path.unlink()
        logger.info(f"DAS variant removed: {variant_path}")

        return jsonify({
            'success': True,
            'message': 'DAS variant removed successfully'
        })
    except Exception as e:
        logger.error(f"DAS remove error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/das/rename', methods=['POST'])
def das_rename_variant():
    """
    Rename a DAS variant file (e.g., add/remove button indicator)

    Body:
    {
      "stageCode": "GrOp",
      "oldName": "vanilla",
      "newName": "vanilla(B)"
    }
    """
    try:
        data = request.json
        stage_code = data.get('stageCode')
        old_name = data.get('oldName')
        new_name = data.get('newName')

        logger.info(f"DAS Rename Request - Stage: {stage_code}, Old: {old_name}, New: {new_name}")

        if not stage_code or not old_name or not new_name:
            return jsonify({
                'success': False,
                'error': 'Missing stageCode, oldName, or newName parameter'
            }), 400

        if stage_code not in DAS_STAGES:
            return jsonify({
                'success': False,
                'error': f'Unknown stage code: {stage_code}'
            }), 400

        # Pokemon Stadium uses .usd, others use .dat
        file_ext = '.usd' if stage_code == 'GrPs' else '.dat'
        project_files = get_project_files_dir()
        stage_folder = project_files / stage_code

        old_path = stage_folder / f"{old_name}{file_ext}"
        new_path = stage_folder / f"{new_name}{file_ext}"

        # Check if old file exists
        if not old_path.exists():
            return jsonify({
                'success': False,
                'error': f'Source file not found: {old_name}{file_ext}'
            }), 404

        # Check if new file already exists (prevent overwriting)
        if new_path.exists():
            return jsonify({
                'success': False,
                'error': f'Target file already exists: {new_name}{file_ext}'
            }), 409

        # Rename the file
        old_path.rename(new_path)
        logger.info(f"DAS variant renamed: {old_path} -> {new_path}")

        return jsonify({
            'success': True,
            'message': 'DAS variant renamed successfully',
            'oldName': old_name,
            'newName': new_name
        })
    except Exception as e:
        logger.error(f"DAS rename error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/stages/delete', methods=['POST'])
def delete_storage_stage():
    """Delete stage variant from storage"""
    try:
        data = request.json
        stage_folder = data.get('stageFolder')
        variant_id = data.get('variantId')

        if not stage_folder or not variant_id:
            return jsonify({
                'success': False,
                'error': 'Missing stageFolder or variantId parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        # Find and remove the variant from metadata
        if stage_folder not in metadata.get('stages', {}):
            return jsonify({
                'success': False,
                'error': f'Stage folder {stage_folder} not found in metadata'
            }), 404

        stage_data = metadata['stages'][stage_folder]
        variants = stage_data.get('variants', [])
        variant_to_delete = None
        variant_index = None

        for idx, variant in enumerate(variants):
            if variant['id'] == variant_id:
                variant_to_delete = variant
                variant_index = idx
                break

        if not variant_to_delete:
            return jsonify({
                'success': False,
                'error': f'Variant {variant_id} not found in {stage_folder}'
            }), 404

        # Delete physical files
        das_folder = STORAGE_PATH / 'das' / stage_folder
        zip_file = das_folder / variant_to_delete['filename']
        screenshot_file = das_folder / f"{variant_id}_screenshot.png"

        deleted_files = []
        if zip_file.exists():
            zip_file.unlink()
            deleted_files.append(str(zip_file))
        if screenshot_file.exists():
            screenshot_file.unlink()
            deleted_files.append(str(screenshot_file))

        # Remove from metadata
        variants.pop(variant_index)

        # Save updated metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Deleted stage variant {variant_id} from {stage_folder}")
        logger.info(f"  Deleted files: {deleted_files}")

        return jsonify({
            'success': True,
            'message': f'Successfully deleted {variant_id}',
            'deleted_files': deleted_files
        })
    except Exception as e:
        logger.error(f"Delete stage variant error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/stages/rename', methods=['POST'])
def rename_storage_stage():
    """Rename stage variant (update name field)"""
    try:
        data = request.json
        logger.info("=== RENAME STAGE REQUEST ===")
        logger.info(f"Request data: {data}")

        stage_folder = data.get('stageFolder')
        variant_id = data.get('variantId')
        new_name = data.get('newName')

        logger.info(f"stage_folder: {stage_folder}")
        logger.info(f"variant_id: {variant_id}")
        logger.info(f"new_name: {new_name}")

        if not stage_folder or not variant_id or not new_name:
            logger.error("Missing parameters!")
            return jsonify({
                'success': False,
                'error': 'Missing stageFolder, variantId, or newName parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        logger.info(f"Metadata file path: {metadata_file}")
        logger.info(f"Metadata file exists: {metadata_file.exists()}")

        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        logger.info(f"Loaded metadata, stages: {list(metadata.get('stages', {}).keys())}")

        # Find and update the variant in metadata
        if stage_folder not in metadata.get('stages', {}):
            logger.error(f"Stage folder {stage_folder} not found in metadata!")
            return jsonify({
                'success': False,
                'error': f'Stage folder {stage_folder} not found in metadata'
            }), 404

        stage_data = metadata['stages'][stage_folder]
        variants = stage_data.get('variants', [])
        logger.info(f"Found stage folder {stage_folder}, variants: {[v['id'] for v in variants]}")

        # Check for duplicate display names (case-insensitive, sanitized comparison)
        sanitized_new_name = sanitize_filename(new_name).lower()
        for variant in variants:
            if variant['id'] != variant_id:  # Don't check against itself
                existing_name = sanitize_filename(variant.get('name', '')).lower()
                if existing_name == sanitized_new_name:
                    logger.error(f"Duplicate name found: '{new_name}' matches existing variant '{variant['name']}'")
                    return jsonify({
                        'success': False,
                        'error': f"A variant named '{variant['name']}' already exists in this stage"
                    }), 400

        variant_found = False

        for variant in variants:
            if variant['id'] == variant_id:
                logger.info(f"Found variant {variant_id}, updating name from '{variant.get('name')}' to '{new_name}'")
                variant['name'] = new_name
                variant_found = True
                break

        if not variant_found:
            logger.error(f"Variant {variant_id} not found!")
            return jsonify({
                'success': False,
                'error': f'Variant {variant_id} not found in {stage_folder}'
            }), 404

        # Save updated metadata
        logger.info(f"Saving updated metadata to {metadata_file}")
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Renamed stage variant {variant_id} to '{new_name}'")

        return jsonify({
            'success': True,
            'message': f'Successfully renamed to {new_name}'
        })
    except Exception as e:
        logger.error(f"Rename stage variant error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/stages/update-screenshot', methods=['POST'])
def update_stage_screenshot():
    """Update screenshot for a stage variant"""
    try:
        stage_folder = request.form.get('stageFolder')
        variant_id = request.form.get('variantId')

        if not stage_folder or not variant_id:
            return jsonify({
                'success': False,
                'error': 'Missing stageFolder or variantId parameter'
            }), 400

        if 'screenshot' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No screenshot file provided'
            }), 400

        screenshot_file = request.files['screenshot']

        if screenshot_file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400

        # Read the image data
        screenshot_data = screenshot_file.read()

        # Save to storage/das
        das_folder = STORAGE_PATH / 'das' / stage_folder
        das_folder.mkdir(parents=True, exist_ok=True)
        storage_screenshot_path = das_folder / f"{variant_id}_screenshot.png"
        storage_screenshot_path.write_bytes(screenshot_data)

        # Update metadata to mark screenshot as available
        metadata_file = STORAGE_PATH / 'metadata.json'
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)

            if stage_folder in metadata.get('stages', {}):
                stage_data = metadata['stages'][stage_folder]
                variants = stage_data.get('variants', [])

                for variant in variants:
                    if variant['id'] == variant_id:
                        variant['has_screenshot'] = True
                        break

                # Save updated metadata
                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Updated screenshot for {stage_folder}/{variant_id}")
        logger.info(f"  Saved to: {storage_screenshot_path}")

        return jsonify({
            'success': True,
            'message': 'Screenshot updated successfully',
            'screenshotUrl': f"/storage/das/{stage_folder}/{variant_id}_screenshot.png"
        })
    except Exception as e:
        logger.error(f"Update screenshot error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def get_folder_id_at_position(skins, position):
    """Determine folder membership based on position.
    Look backwards from position - if we find a skin with folder_id or a folder,
    that determines our folder membership.
    """
    for i in range(position - 1, -1, -1):
        item = skins[i]
        if item.get('type') == 'folder':
            # We're right after a folder - in that folder
            return item['id']
        if item.get('folder_id'):
            # Previous item is in a folder - we're in that folder too
            return item['folder_id']
        # Previous item is at root level (no folder_id, not a folder)
        return None
    return None  # At the start, root level


@app.route('/api/mex/storage/costumes/reorder', methods=['POST'])
def reorder_costumes():
    """Reorder character skins in storage.
    Also updates folder_id based on new position for proper folder membership.
    """
    try:
        data = request.json
        character = data.get('character')
        from_index = data.get('fromIndex')
        to_index = data.get('toIndex')

        if character is None or from_index is None or to_index is None:
            return jsonify({
                'success': False,
                'error': 'Missing character, fromIndex, or toIndex parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        # Find character in metadata
        if character not in metadata.get('characters', {}):
            return jsonify({
                'success': False,
                'error': f'Character {character} not found in metadata'
            }), 404

        character_data = metadata['characters'][character]
        skins = character_data.get('skins', [])

        # Validate indices
        if from_index < 0 or from_index >= len(skins) or to_index < 0 or to_index >= len(skins):
            return jsonify({
                'success': False,
                'error': 'Invalid fromIndex or toIndex'
            }), 400

        # Reorder the skins array
        item = skins.pop(from_index)
        skins.insert(to_index, item)

        # Update folder_id based on new position (only for skins, not folders)
        if item.get('type') != 'folder':
            new_folder_id = get_folder_id_at_position(skins, to_index)
            if new_folder_id:
                item['folder_id'] = new_folder_id
            elif 'folder_id' in item:
                del item['folder_id']
            logger.info(f"[OK] Updated folder_id to {new_folder_id} for item at position {to_index}")

        # Save updated metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Reordered {character} skins: moved index {from_index} to {to_index}")

        return jsonify({
            'success': True,
            'skins': skins
        })
    except Exception as e:
        logger.error(f"Reorder costumes error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/costumes/move-to-top', methods=['POST'])
def move_costume_to_top():
    """Move a character skin to the top of the list"""
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')

        if not character or not skin_id:
            return jsonify({
                'success': False,
                'error': 'Missing character or skinId parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        # Find character in metadata
        if character not in metadata.get('characters', {}):
            return jsonify({
                'success': False,
                'error': f'Character {character} not found in metadata'
            }), 404

        character_data = metadata['characters'][character]
        skins = character_data.get('skins', [])

        # Find the skin by ID
        skin_index = None
        for i, skin in enumerate(skins):
            if skin['id'] == skin_id:
                skin_index = i
                break

        if skin_index is None:
            return jsonify({
                'success': False,
                'error': f'Skin {skin_id} not found'
            }), 404

        # Move to top (position 0)
        if skin_index > 0:
            skin = skins.pop(skin_index)
            skins.insert(0, skin)

            # Save updated metadata
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"[OK] Moved {character} skin {skin_id} to top")

        return jsonify({
            'success': True,
            'skins': skins
        })
    except Exception as e:
        logger.error(f"Move costume to top error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/costumes/move-to-bottom', methods=['POST'])
def move_costume_to_bottom():
    """Move a character skin to the bottom of the list"""
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')

        if not character or not skin_id:
            return jsonify({
                'success': False,
                'error': 'Missing character or skinId parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        # Find character in metadata
        if character not in metadata.get('characters', {}):
            return jsonify({
                'success': False,
                'error': f'Character {character} not found in metadata'
            }), 404

        character_data = metadata['characters'][character]
        skins = character_data.get('skins', [])

        # Find the skin by ID
        skin_index = None
        for i, skin in enumerate(skins):
            if skin['id'] == skin_id:
                skin_index = i
                break

        if skin_index is None:
            return jsonify({
                'success': False,
                'error': f'Skin {skin_id} not found'
            }), 404

        # Move to bottom (last position)
        if skin_index < len(skins) - 1:
            skin = skins.pop(skin_index)
            skins.append(skin)

            # Save updated metadata
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"[OK] Moved {character} skin {skin_id} to bottom")

        return jsonify({
            'success': True,
            'skins': skins
        })
    except Exception as e:
        logger.error(f"Move costume to bottom error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============= Folder Management Endpoints =============
# Simplified approach: folders are entries in the skins array itself.
# Skins can have optional folder_id to indicate membership.
# This keeps the existing reorder endpoint working unchanged.


def find_folder_in_skins(skins, folder_id):
    """Find a folder by ID in the skins array."""
    for i, item in enumerate(skins):
        if item.get('type') == 'folder' and item.get('id') == folder_id:
            return item, i
    return None, -1


@app.route('/api/mex/storage/folders/create', methods=['POST'])
def create_folder():
    """Create a new folder for organizing skins.
    Folders are added directly to the skins array.
    """
    try:
        data = request.json
        character = data.get('character')
        name = data.get('name', 'New Folder')

        if not character:
            return jsonify({
                'success': False,
                'error': 'Missing character parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        if character not in metadata.get('characters', {}):
            return jsonify({
                'success': False,
                'error': f'Character {character} not found in metadata'
            }), 404

        character_data = metadata['characters'][character]
        skins = character_data.get('skins', [])

        # Generate unique folder ID
        import uuid
        folder_id = f"folder_{uuid.uuid4().hex[:8]}"

        # Create new folder (as an entry in skins array)
        new_folder = {
            'type': 'folder',
            'id': folder_id,
            'name': name,
            'expanded': True
        }

        # Add folder to end of skins array
        skins.append(new_folder)
        character_data['skins'] = skins

        # Save metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Created folder '{name}' for {character}")

        return jsonify({
            'success': True,
            'folder': new_folder,
            'skins': skins
        })
    except Exception as e:
        logger.error(f"Create folder error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/folders/rename', methods=['POST'])
def rename_folder():
    """Rename a folder"""
    try:
        data = request.json
        character = data.get('character')
        folder_id = data.get('folderId')
        new_name = data.get('newName')

        if not character or not folder_id or not new_name:
            return jsonify({
                'success': False,
                'error': 'Missing character, folderId, or newName parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        if character not in metadata.get('characters', {}):
            return jsonify({
                'success': False,
                'error': f'Character {character} not found in metadata'
            }), 404

        character_data = metadata['characters'][character]
        skins = character_data.get('skins', [])

        # Find and update folder
        folder, idx = find_folder_in_skins(skins, folder_id)
        if not folder:
            return jsonify({
                'success': False,
                'error': f'Folder {folder_id} not found'
            }), 404

        folder['name'] = new_name

        # Save metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Renamed folder {folder_id} to '{new_name}'")

        return jsonify({
            'success': True,
            'skins': skins
        })
    except Exception as e:
        logger.error(f"Rename folder error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/folders/delete', methods=['POST'])
def delete_folder():
    """Delete a folder.
    Removes folder_id from any skins that belonged to this folder.
    Does NOT delete the skins themselves.
    """
    try:
        data = request.json
        character = data.get('character')
        folder_id = data.get('folderId')

        if not character or not folder_id:
            return jsonify({
                'success': False,
                'error': 'Missing character or folderId parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        if character not in metadata.get('characters', {}):
            return jsonify({
                'success': False,
                'error': f'Character {character} not found in metadata'
            }), 404

        character_data = metadata['characters'][character]
        skins = character_data.get('skins', [])

        # Find folder
        folder, folder_idx = find_folder_in_skins(skins, folder_id)
        if not folder:
            return jsonify({
                'success': False,
                'error': f'Folder {folder_id} not found'
            }), 404

        # Remove folder_id from any skins that had it
        for skin in skins:
            if skin.get('folder_id') == folder_id:
                del skin['folder_id']

        # Remove the folder itself from skins array
        skins.pop(folder_idx)

        # Save metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Deleted folder {folder_id}")

        return jsonify({
            'success': True,
            'skins': skins
        })
    except Exception as e:
        logger.error(f"Delete folder error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/folders/toggle', methods=['POST'])
def toggle_folder():
    """Toggle folder expanded state"""
    try:
        data = request.json
        character = data.get('character')
        folder_id = data.get('folderId')

        if not character or not folder_id:
            return jsonify({
                'success': False,
                'error': 'Missing character or folderId parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        if character not in metadata.get('characters', {}):
            return jsonify({
                'success': False,
                'error': f'Character {character} not found in metadata'
            }), 404

        character_data = metadata['characters'][character]
        skins = character_data.get('skins', [])

        # Find and toggle folder
        folder, idx = find_folder_in_skins(skins, folder_id)
        if not folder:
            return jsonify({
                'success': False,
                'error': f'Folder {folder_id} not found'
            }), 404

        folder['expanded'] = not folder.get('expanded', True)

        # Save metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Toggled folder {folder_id} expanded: {folder['expanded']}")

        return jsonify({
            'success': True,
            'expanded': folder['expanded'],
            'skins': skins
        })
    except Exception as e:
        logger.error(f"Toggle folder error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/skins/set-folder', methods=['POST'])
def set_skin_folder():
    """Assign or unassign a skin to a folder"""
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')
        folder_id = data.get('folderId')  # null to remove from folder

        if not character or not skin_id:
            return jsonify({
                'success': False,
                'error': 'Missing character or skinId parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        if character not in metadata.get('characters', {}):
            return jsonify({
                'success': False,
                'error': f'Character {character} not found in metadata'
            }), 404

        character_data = metadata['characters'][character]
        skins = character_data.get('skins', [])

        # Find the skin
        skin = None
        for s in skins:
            if s.get('id') == skin_id and s.get('type') != 'folder':
                skin = s
                break

        if not skin:
            return jsonify({
                'success': False,
                'error': f'Skin {skin_id} not found'
            }), 404

        # Verify folder exists if provided
        if folder_id:
            folder, _ = find_folder_in_skins(skins, folder_id)
            if not folder:
                return jsonify({
                    'success': False,
                    'error': f'Folder {folder_id} not found'
                }), 404

        # Set or remove folder_id
        if folder_id:
            skin['folder_id'] = folder_id
        elif 'folder_id' in skin:
            del skin['folder_id']

        # Save metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Set skin {skin_id} folder to {folder_id}")

        return jsonify({
            'success': True,
            'skins': skins
        })
    except Exception as e:
        logger.error(f"Set skin folder error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/stages/reorder', methods=['POST'])
def reorder_stages():
    """Reorder stage variants in storage"""
    try:
        data = request.json
        stage_folder = data.get('stageFolder')
        from_index = data.get('fromIndex')
        to_index = data.get('toIndex')

        if stage_folder is None or from_index is None or to_index is None:
            return jsonify({
                'success': False,
                'error': 'Missing stageFolder, fromIndex, or toIndex parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        # Find stage in metadata
        if stage_folder not in metadata.get('stages', {}):
            return jsonify({
                'success': False,
                'error': f'Stage folder {stage_folder} not found in metadata'
            }), 404

        stage_data = metadata['stages'][stage_folder]
        variants = stage_data.get('variants', [])

        # Validate indices
        if from_index < 0 or from_index >= len(variants) or to_index < 0 or to_index >= len(variants):
            return jsonify({
                'success': False,
                'error': 'Invalid fromIndex or toIndex'
            }), 400

        # Reorder the variants array
        variant = variants.pop(from_index)
        variants.insert(to_index, variant)

        # Save updated metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"[OK] Reordered {stage_folder} variants: moved index {from_index} to {to_index}")

        return jsonify({
            'success': True,
            'variants': variants
        })
    except Exception as e:
        logger.error(f"Reorder stages error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/stages/move-to-top', methods=['POST'])
def move_stage_to_top():
    """Move a stage variant to the top of the list"""
    try:
        data = request.json
        stage_folder = data.get('stageFolder')
        variant_id = data.get('variantId')

        if not stage_folder or not variant_id:
            return jsonify({
                'success': False,
                'error': 'Missing stageFolder or variantId parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        # Find stage in metadata
        if stage_folder not in metadata.get('stages', {}):
            return jsonify({
                'success': False,
                'error': f'Stage folder {stage_folder} not found in metadata'
            }), 404

        stage_data = metadata['stages'][stage_folder]
        variants = stage_data.get('variants', [])

        # Find the variant by ID
        variant_index = None
        for i, variant in enumerate(variants):
            if variant['id'] == variant_id:
                variant_index = i
                break

        if variant_index is None:
            return jsonify({
                'success': False,
                'error': f'Variant {variant_id} not found'
            }), 404

        # Move to top (position 0)
        if variant_index > 0:
            variant = variants.pop(variant_index)
            variants.insert(0, variant)

            # Save updated metadata
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"[OK] Moved {stage_folder} variant {variant_id} to top")

        return jsonify({
            'success': True,
            'variants': variants
        })
    except Exception as e:
        logger.error(f"Move stage to top error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/storage/stages/move-to-bottom', methods=['POST'])
def move_stage_to_bottom():
    """Move a stage variant to the bottom of the list"""
    try:
        data = request.json
        stage_folder = data.get('stageFolder')
        variant_id = data.get('variantId')

        if not stage_folder or not variant_id:
            return jsonify({
                'success': False,
                'error': 'Missing stageFolder or variantId parameter'
            }), 400

        # Load metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        # Find stage in metadata
        if stage_folder not in metadata.get('stages', {}):
            return jsonify({
                'success': False,
                'error': f'Stage folder {stage_folder} not found in metadata'
            }), 404

        stage_data = metadata['stages'][stage_folder]
        variants = stage_data.get('variants', [])

        # Find the variant by ID
        variant_index = None
        for i, variant in enumerate(variants):
            if variant['id'] == variant_id:
                variant_index = i
                break

        if variant_index is None:
            return jsonify({
                'success': False,
                'error': f'Variant {variant_id} not found'
            }), 404

        # Move to bottom (last position)
        if variant_index < len(variants) - 1:
            variant = variants.pop(variant_index)
            variants.append(variant)

            # Save updated metadata
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"[OK] Moved {stage_folder} variant {variant_id} to bottom")

        return jsonify({
            'success': True,
            'variants': variants
        })
    except Exception as e:
        logger.error(f"Move stage to bottom error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@socketio.on('connect')
def handle_connect():
    """Handle WebSocket connection"""
    print('Client connected')
    emit('connected', {'message': 'Connected to MEX API'})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle WebSocket disconnection"""
    print('Client disconnected')


@app.route('/api/mex/shutdown', methods=['POST'])
def shutdown():
    """Gracefully shutdown the Flask server"""
    logger.info("Shutdown request received")

    def shutdown_server():
        func = request.environ.get('werkzeug.server.shutdown')
        if func is None:
            # In production or when using app.run()
            import os
            os._exit(0)
        else:
            func()

    shutdown_server()
    return jsonify({'success': True, 'message': 'Server shutting down...'})


# ============= Vanilla ISO Verification =============

VANILLA_ISO_MD5 = "0e63d4223b01d9aba596259dc155a174"


@app.route('/api/mex/verify-iso', methods=['POST'])
def verify_vanilla_iso():
    """Verify that an ISO file is a valid vanilla Melee 1.02 ISO"""
    try:
        import hashlib

        data = request.json or {}
        iso_path = data.get('isoPath')

        if not iso_path:
            return jsonify({
                'success': False,
                'error': 'No ISO path provided'
            }), 400

        iso_file = Path(iso_path)
        if not iso_file.exists():
            return jsonify({
                'success': False,
                'error': 'ISO file not found'
            }), 404

        # Calculate MD5 hash
        logger.info(f"Calculating MD5 for: {iso_path}")
        md5_hash = hashlib.md5()

        with open(iso_file, 'rb') as f:
            # Read in chunks to handle large files
            for chunk in iter(lambda: f.read(8192 * 1024), b''):  # 8MB chunks
                md5_hash.update(chunk)

        calculated_md5 = md5_hash.hexdigest()
        is_valid = calculated_md5.lower() == VANILLA_ISO_MD5.lower()

        logger.info(f"ISO MD5: {calculated_md5} (valid: {is_valid})")

        return jsonify({
            'success': True,
            'valid': is_valid,
            'md5': calculated_md5,
            'expected': VANILLA_ISO_MD5
        })
    except Exception as e:
        logger.error(f"Verify ISO error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============= XDelta Patches =============

XDELTA_PATH = STORAGE_PATH / "xdelta"
XDELTA_PATH.mkdir(exist_ok=True)


def load_xdelta_metadata():
    """Load xdelta metadata from metadata.json"""
    metadata_file = STORAGE_PATH / 'metadata.json'
    if not metadata_file.exists():
        return []

    with open(metadata_file, 'r') as f:
        metadata = json.load(f)

    return metadata.get('xdelta', [])


def save_xdelta_metadata(xdelta_list):
    """Save xdelta metadata to metadata.json"""
    metadata_file = STORAGE_PATH / 'metadata.json'

    if metadata_file.exists():
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
    else:
        metadata = {'version': '1.0', 'characters': {}, 'stages': {}}

    metadata['xdelta'] = xdelta_list

    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)


@app.route('/api/mex/xdelta/list', methods=['GET'])
def list_xdelta_patches():
    """List all xdelta patches in storage"""
    try:
        patches = load_xdelta_metadata()

        # Add image URLs
        for patch in patches:
            patch_id = patch.get('id')
            if patch_id:
                image_path = XDELTA_PATH / f"{patch_id}.png"
                if image_path.exists():
                    patch['imageUrl'] = f"/storage/xdelta/{patch_id}.png"
                else:
                    patch['imageUrl'] = None

        return jsonify({
            'success': True,
            'patches': patches
        })
    except Exception as e:
        logger.error(f"List xdelta patches error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/xdelta/import', methods=['POST'])
def import_xdelta_patch():
    """Import a new xdelta patch"""
    try:
        # Check if file was uploaded
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No xdelta file uploaded'
            }), 400

        file = request.files['file']
        name = request.form.get('name', 'Unnamed Patch')
        description = request.form.get('description', '')

        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400

        # Validate file extension
        if not file.filename.lower().endswith('.xdelta'):
            return jsonify({
                'success': False,
                'error': 'File must be an .xdelta file'
            }), 400

        # Generate unique ID
        import uuid
        patch_id = str(uuid.uuid4())[:8]

        # Save xdelta file
        xdelta_filename = f"{patch_id}.xdelta"
        xdelta_path = XDELTA_PATH / xdelta_filename
        file.save(str(xdelta_path))

        # Save image if provided
        if 'image' in request.files:
            image_file = request.files['image']
            if image_file.filename:
                image_path = XDELTA_PATH / f"{patch_id}.png"
                image_file.save(str(image_path))

        # Add to metadata
        patches = load_xdelta_metadata()
        patches.append({
            'id': patch_id,
            'name': name,
            'description': description,
            'filename': file.filename,
            'created': datetime.now().isoformat()
        })
        save_xdelta_metadata(patches)

        logger.info(f"[OK] Imported xdelta patch: {name} ({patch_id})")

        return jsonify({
            'success': True,
            'patch': {
                'id': patch_id,
                'name': name,
                'description': description
            }
        })
    except Exception as e:
        logger.error(f"Import xdelta patch error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/xdelta/update/<patch_id>', methods=['POST'])
def update_xdelta_patch(patch_id):
    """Update an xdelta patch's metadata"""
    try:
        data = request.json or {}
        name = data.get('name')
        description = data.get('description')

        patches = load_xdelta_metadata()
        patch = next((p for p in patches if p['id'] == patch_id), None)

        if not patch:
            return jsonify({
                'success': False,
                'error': 'Patch not found'
            }), 404

        if name is not None:
            patch['name'] = name
        if description is not None:
            patch['description'] = description

        save_xdelta_metadata(patches)

        return jsonify({
            'success': True,
            'patch': patch
        })
    except Exception as e:
        logger.error(f"Update xdelta patch error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/xdelta/update-image/<patch_id>', methods=['POST'])
def update_xdelta_image(patch_id):
    """Update an xdelta patch's image"""
    try:
        if 'image' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No image file uploaded'
            }), 400

        image_file = request.files['image']
        if image_file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400

        # Verify patch exists
        patches = load_xdelta_metadata()
        patch = next((p for p in patches if p['id'] == patch_id), None)

        if not patch:
            return jsonify({
                'success': False,
                'error': 'Patch not found'
            }), 404

        # Save image
        image_path = XDELTA_PATH / f"{patch_id}.png"
        image_file.save(str(image_path))

        return jsonify({
            'success': True,
            'imageUrl': f"/storage/xdelta/{patch_id}.png"
        })
    except Exception as e:
        logger.error(f"Update xdelta image error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/xdelta/delete/<patch_id>', methods=['POST'])
def delete_xdelta_patch(patch_id):
    """Delete an xdelta patch"""
    try:
        # Remove from metadata
        patches = load_xdelta_metadata()
        patches = [p for p in patches if p['id'] != patch_id]
        save_xdelta_metadata(patches)

        # Delete files
        xdelta_path = XDELTA_PATH / f"{patch_id}.xdelta"
        image_path = XDELTA_PATH / f"{patch_id}.png"

        if xdelta_path.exists():
            os.remove(xdelta_path)
        if image_path.exists():
            os.remove(image_path)

        logger.info(f"[OK] Deleted xdelta patch: {patch_id}")

        return jsonify({
            'success': True
        })
    except Exception as e:
        logger.error(f"Delete xdelta patch error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def run_xdelta_build(patch_id, patch_name, vanilla_iso_path, xdelta_path, output_path, expected_size):
    """Background thread function to run xdelta and emit progress"""
    try:
        # Find xdelta executable
        if os.name == 'nt':
            if getattr(sys, 'frozen', False):
                xdelta_exe = RESOURCES_DIR / "utility" / "xdelta" / "xdelta3.exe"
            else:
                xdelta_exe = PROJECT_ROOT / "utility" / "xdelta" / "xdelta3.exe"
            if not xdelta_exe.exists():
                xdelta_exe = "xdelta3"
        else:
            xdelta_exe = "xdelta3"

        cmd = [
            str(xdelta_exe),
            '-d',  # Decode/decompress
            '-s', str(vanilla_iso_path),
            str(xdelta_path),
            str(output_path)
        ]

        # Hide CMD window on Windows
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

        # Start the process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags
        )

        # Monitor progress by checking output file size
        last_progress = 0
        while process.poll() is None:
            time.sleep(0.3)  # Check every 300ms
            try:
                if output_path.exists():
                    current_size = output_path.stat().st_size
                    progress = min(int((current_size / expected_size) * 100), 99)
                    if progress != last_progress:
                        socketio.emit('xdelta_progress', {
                            'patch_id': patch_id,
                            'percentage': progress,
                            'message': f'Patching... {progress}%'
                        })
                        last_progress = progress
            except:
                pass

        # Process finished - check result
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else stdout.decode() if stdout else 'Unknown xdelta error'
            logger.error(f"xdelta3 failed: {error_msg}")
            socketio.emit('xdelta_error', {
                'patch_id': patch_id,
                'error': f'Failed to apply patch: {error_msg}'
            })
        else:
            logger.info(f"[OK] Successfully built ISO: {output_path.name}")
            socketio.emit('xdelta_complete', {
                'patch_id': patch_id,
                'filename': output_path.name,
                'path': str(output_path)
            })

    except Exception as e:
        logger.error(f"xdelta build thread error: {str(e)}", exc_info=True)
        socketio.emit('xdelta_error', {
            'patch_id': patch_id,
            'error': str(e)
        })


@app.route('/api/mex/xdelta/build/<patch_id>', methods=['POST'])
def build_xdelta_iso(patch_id):
    """Build an ISO from an xdelta patch using the vanilla ISO"""
    try:
        data = request.json or {}
        vanilla_iso_path = data.get('vanillaIsoPath')

        if not vanilla_iso_path:
            return jsonify({
                'success': False,
                'error': 'No vanilla ISO path provided. Please set it in Settings.'
            }), 400

        vanilla_iso = Path(vanilla_iso_path)
        if not vanilla_iso.exists():
            return jsonify({
                'success': False,
                'error': f'Vanilla ISO not found: {vanilla_iso_path}'
            }), 404

        # Get expected output size from vanilla ISO
        expected_size = vanilla_iso.stat().st_size

        # Get patch info
        patches = load_xdelta_metadata()
        patch = next((p for p in patches if p['id'] == patch_id), None)

        if not patch:
            return jsonify({
                'success': False,
                'error': 'Patch not found'
            }), 404

        xdelta_path = XDELTA_PATH / f"{patch_id}.xdelta"
        if not xdelta_path.exists():
            return jsonify({
                'success': False,
                'error': 'Xdelta file not found'
            }), 404

        # Create output filename
        safe_name = re.sub(r'[^\w\-_]', '_', patch['name'])
        output_filename = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.iso"
        output_path = OUTPUT_PATH / output_filename

        logger.info(f"Building ISO from xdelta patch: {patch['name']}")
        logger.info(f"  Vanilla ISO: {vanilla_iso_path} ({expected_size} bytes)")
        logger.info(f"  Patch: {xdelta_path}")
        logger.info(f"  Output: {output_path}")

        # Run in background thread
        thread = threading.Thread(
            target=run_xdelta_build,
            args=(patch_id, patch['name'], vanilla_iso_path, xdelta_path, output_path, expected_size)
        )
        thread.start()

        return jsonify({
            'success': True,
            'message': 'Build started',
            'filename': output_filename
        })
    except Exception as e:
        logger.error(f"Build xdelta ISO error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/xdelta/download/<filename>', methods=['GET'])
def download_xdelta_iso(filename):
    """Download a built xdelta ISO"""
    try:
        file_path = OUTPUT_PATH / filename

        if not file_path.exists():
            return jsonify({
                'success': False,
                'error': 'ISO file not found'
            }), 404

        # Delete after download
        @after_this_request
        def cleanup(response):
            try:
                os.remove(file_path)
                logger.info(f"Deleted ISO file after download: {filename}")
            except Exception as error:
                logger.error(f"Error deleting ISO file {filename}: {str(error)}")
            return response

        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        logger.error(f"Download xdelta ISO error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def run_xdelta_create(create_id, name, description, vanilla_iso_path, modded_iso_path, output_path, image_path=None):
    """Background thread function to create xdelta patch and emit progress"""
    try:
        # Find xdelta executable
        if os.name == 'nt':
            if getattr(sys, 'frozen', False):
                xdelta_exe = RESOURCES_DIR / "utility" / "xdelta" / "xdelta3.exe"
            else:
                xdelta_exe = PROJECT_ROOT / "utility" / "xdelta" / "xdelta3.exe"
            if not xdelta_exe.exists():
                xdelta_exe = "xdelta3"
        else:
            xdelta_exe = "xdelta3"

        # Get modded ISO size for progress estimation
        modded_size = Path(modded_iso_path).stat().st_size

        cmd = [
            str(xdelta_exe),
            '-e',  # Encode (create patch)
            '-1',  # Fast compression (good speed, slightly larger files)
            '-s', str(vanilla_iso_path),
            str(modded_iso_path),
            str(output_path)
        ]

        logger.info(f"Creating xdelta patch: {' '.join(cmd)}")

        # Hide CMD window on Windows
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

        # Start the process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags
        )

        # xdelta3 doesn't output progress, so we just show current output size
        last_size_mb = 0

        while process.poll() is None:
            time.sleep(1)  # Check every second
            try:
                if output_path.exists():
                    current_size = output_path.stat().st_size
                    current_size_mb = current_size / (1024 * 1024)
                    if int(current_size_mb) != int(last_size_mb):
                        socketio.emit('xdelta_create_progress', {
                            'create_id': create_id,
                            'percentage': -1,  # -1 means indeterminate
                            'message': f'Creating patch... ({current_size_mb:.1f} MB so far)'
                        })
                        last_size_mb = current_size_mb
            except:
                pass

        # Process finished - check result
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else stdout.decode() if stdout else 'Unknown xdelta error'
            logger.error(f"xdelta3 create failed: {error_msg}")
            # Clean up failed output
            if output_path.exists():
                os.remove(output_path)
            socketio.emit('xdelta_create_error', {
                'create_id': create_id,
                'error': f'Failed to create patch: {error_msg}'
            })
        else:
            # Success - save to storage
            import uuid
            patch_id = str(uuid.uuid4())[:8]

            # Move to storage
            final_path = XDELTA_PATH / f"{patch_id}.xdelta"
            import shutil
            shutil.move(str(output_path), str(final_path))

            # Copy image if provided
            if image_path and Path(image_path).exists():
                image_dest = XDELTA_PATH / f"{patch_id}.png"
                shutil.copy(str(image_path), str(image_dest))

            # Get patch file size for display
            patch_size = final_path.stat().st_size
            patch_size_mb = patch_size / (1024 * 1024)

            # Add to metadata
            patches = load_xdelta_metadata()
            patches.append({
                'id': patch_id,
                'name': name,
                'description': description,
                'filename': f"{name}.xdelta",
                'size': patch_size,
                'created': datetime.now().isoformat()
            })
            save_xdelta_metadata(patches)

            logger.info(f"[OK] Created xdelta patch: {name} ({patch_id}) - {patch_size_mb:.2f} MB")
            socketio.emit('xdelta_create_complete', {
                'create_id': create_id,
                'patch_id': patch_id,
                'name': name,
                'size': patch_size,
                'size_mb': round(patch_size_mb, 2)
            })

    except Exception as e:
        logger.error(f"xdelta create thread error: {str(e)}", exc_info=True)
        socketio.emit('xdelta_create_error', {
            'create_id': create_id,
            'error': str(e)
        })


@app.route('/api/mex/xdelta/create', methods=['POST'])
def create_xdelta_patch():
    """Create a new xdelta patch from a modded ISO"""
    try:
        data = request.json or {}
        vanilla_iso_path = data.get('vanillaIsoPath')
        modded_iso_path = data.get('moddedIsoPath')
        name = data.get('name', 'New Patch')
        description = data.get('description', '')

        if not vanilla_iso_path:
            return jsonify({
                'success': False,
                'error': 'No vanilla ISO path provided. Please set it in Settings.'
            }), 400

        if not modded_iso_path:
            return jsonify({
                'success': False,
                'error': 'No modded ISO path provided.'
            }), 400

        vanilla_iso = Path(vanilla_iso_path)
        modded_iso = Path(modded_iso_path)

        if not vanilla_iso.exists():
            return jsonify({
                'success': False,
                'error': f'Vanilla ISO not found: {vanilla_iso_path}'
            }), 404

        if not modded_iso.exists():
            return jsonify({
                'success': False,
                'error': f'Modded ISO not found: {modded_iso_path}'
            }), 404

        # Generate unique ID for this creation session
        import uuid
        create_id = str(uuid.uuid4())[:8]

        # Create temporary output path
        safe_name = re.sub(r'[^\w\-_]', '_', name)
        temp_filename = f"temp_patch_{create_id}.xdelta"
        temp_output_path = OUTPUT_PATH / temp_filename

        logger.info(f"Creating xdelta patch: {name}")
        logger.info(f"  Vanilla ISO: {vanilla_iso_path}")
        logger.info(f"  Modded ISO: {modded_iso_path}")
        logger.info(f"  Temp output: {temp_output_path}")

        # Run in background thread
        thread = threading.Thread(
            target=run_xdelta_create,
            args=(create_id, name, description, vanilla_iso_path, modded_iso_path, temp_output_path)
        )
        thread.start()

        return jsonify({
            'success': True,
            'message': 'Patch creation started',
            'create_id': create_id
        })
    except Exception as e:
        logger.error(f"Create xdelta patch error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mex/xdelta/download-patch/<patch_id>', methods=['GET'])
def download_xdelta_patch(patch_id):
    """Download an xdelta patch file"""
    try:
        # Get patch info
        patches = load_xdelta_metadata()
        patch = next((p for p in patches if p['id'] == patch_id), None)

        if not patch:
            return jsonify({
                'success': False,
                'error': 'Patch not found'
            }), 404

        file_path = XDELTA_PATH / f"{patch_id}.xdelta"

        if not file_path.exists():
            return jsonify({
                'success': False,
                'error': 'Patch file not found'
            }), 404

        # Use the original name for the download
        download_name = f"{patch['name']}.xdelta"

        return send_file(
            file_path,
            as_attachment=True,
            download_name=download_name,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        logger.error(f"Download xdelta patch error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# =====================
# 3D Viewer Endpoints
# =====================

@app.route('/api/viewer/start', methods=['POST'])
def start_viewer():
    """Start the 3D model viewer for a costume"""
    global viewer_process, viewer_port

    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')

        if not character or not skin_id:
            return jsonify({'success': False, 'error': 'Missing character or skinId'}), 400

        # Stop any existing viewer
        if viewer_process is not None:
            try:
                viewer_process.terminate()
                viewer_process.wait(timeout=2)
            except:
                viewer_process.kill()
            viewer_process = None

        # Find the costume in metadata
        metadata_file = STORAGE_PATH / 'metadata.json'
        if not metadata_file.exists():
            return jsonify({'success': False, 'error': 'No costumes in storage'}), 404

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        # Find the costume
        characters = metadata.get('characters', {})
        if character not in characters:
            return jsonify({'success': False, 'error': f'Character {character} not found'}), 404

        skins = characters[character].get('skins', [])
        costume = None
        for skin in skins:
            if skin.get('id') == skin_id:
                costume = skin
                break

        if costume is None:
            return jsonify({'success': False, 'error': f'Costume {skin_id} not found'}), 404

        # Get the ZIP file path
        zip_path = STORAGE_PATH / character / costume['filename']
        if not zip_path.exists():
            return jsonify({'success': False, 'error': f'Costume file not found: {zip_path}'}), 404

        # Extract DAT file to temp location
        temp_dir = Path(tempfile.mkdtemp(prefix='viewer_'))
        dat_path = None

        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                if name.lower().endswith('.dat'):
                    zf.extract(name, temp_dir)
                    dat_path = temp_dir / name
                    break

        if dat_path is None or not dat_path.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            return jsonify({'success': False, 'error': 'No DAT file found in costume'}), 404

        # Check if HSDRawViewer exists
        if not HSDRAW_EXE.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            return jsonify({
                'success': False,
                'error': f'HSDRawViewer not found at {HSDRAW_EXE}. Please build it first.'
            }), 500

        # Find an available port
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('localhost', 0))
        viewer_port = sock.getsockname()[1]
        sock.close()

        # Convert paths for Windows if running in WSL
        def to_windows_path(path):
            path_str = str(path)
            if os.name != 'nt' and path_str.startswith('/mnt/'):
                # Convert WSL path to Windows path
                drive = path_str[5].upper()
                return f"{drive}:{path_str[6:]}".replace('/', '\\')
            return path_str

        exe_path = to_windows_path(HSDRAW_EXE)
        dat_windows_path = to_windows_path(dat_path)
        logs_windows_path = to_windows_path(LOGS_PATH)

        # Look for a scene file for this character
        scene_path = None
        csp_data_dir = PROCESSOR_DIR / "csp_data" / character

        if csp_data_dir.exists():
            # Try scene.yml first (most common)
            if (csp_data_dir / "scene.yml").exists():
                scene_path = csp_data_dir / "scene.yml"
            else:
                # Look for any .yml file (cspfinal.yml, CSP.yml, etc.)
                yml_files = sorted(csp_data_dir.glob("*.yml"))
                if yml_files:
                    scene_path = yml_files[0]

        scene_windows_path = None
        if scene_path:
            scene_windows_path = to_windows_path(scene_path)
            logger.info(f"Found scene file: {scene_path}")

        # Look for AJ file (animation archive) for this character
        char_prefixes = {
            "C. Falcon": "PlCa", "Falco": "PlFc", "Fox": "PlFx",
            "Marth": "PlMs", "Roy": "PlFe", "Bowser": "PlKp",
            "DK": "PlDk", "Ganondorf": "PlGn", "Jigglypuff": "PlPr",
            "Kirby": "PlKb", "Link": "PlLk", "Luigi": "PlLg",
            "Mario": "PlMr", "Mewtwo": "PlMt", "Ness": "PlNs",
            "Peach": "PlPe", "Pichu": "PlPc", "Pikachu": "PlPk",
            "Ice Climbers": "PlPp", "Samus": "PlSs", "Sheik": "PlSk",
            "Yoshi": "PlYs", "Young Link": "PlCl", "Zelda": "PlZd",
            "Dr. Mario": "PlDr", "G&W": "PlGw"
        }

        aj_windows_path = None
        if character in char_prefixes:
            prefix = char_prefixes[character]
            aj_path = VANILLA_ASSETS_DIR / character / f"{prefix}AJ.dat"
            if aj_path.exists():
                aj_windows_path = to_windows_path(aj_path)
                logger.info(f"Found AJ file: {aj_path}")

        # Build command with logs path, optional scene file, and optional AJ file
        cmd = [exe_path, '--stream', str(viewer_port), dat_windows_path, logs_windows_path]
        if scene_windows_path:
            cmd.append(scene_windows_path)
        else:
            cmd.append('')  # Empty placeholder for scene file
        if aj_windows_path:
            cmd.append(aj_windows_path)

        logger.info(f"Starting viewer: {' '.join(cmd)}")

        # Start the viewer process
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        viewer_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags
        )

        # Poll until server is ready (check HTTP health endpoint)
        import urllib.request
        max_wait = 15  # seconds
        poll_interval = 0.5
        server_ready = False

        for _ in range(int(max_wait / poll_interval)):
            time.sleep(poll_interval)

            # Check if process died
            if viewer_process is None:
                return jsonify({
                    'success': False,
                    'error': 'Viewer was stopped during startup'
                }), 500

            if viewer_process.poll() is not None:
                stdout, stderr = viewer_process.communicate()
                viewer_process = None
                return jsonify({
                    'success': False,
                    'error': f'Viewer failed to start: {stderr.decode() if stderr else stdout.decode()}'
                }), 500

            # Try to connect to health endpoint
            try:
                req = urllib.request.urlopen(f'http://localhost:{viewer_port}/', timeout=1)
                if req.status == 200:
                    server_ready = True
                    break
            except:
                pass  # Server not ready yet

        if not server_ready:
            # Kill the process since it didn't start in time
            if viewer_process:
                viewer_process.kill()
                viewer_process = None
            return jsonify({
                'success': False,
                'error': 'Viewer failed to start within timeout'
            }), 500

        return jsonify({
            'success': True,
            'port': viewer_port,
            'wsUrl': f'ws://localhost:{viewer_port}/'
        })

    except Exception as e:
        logger.error(f"Start viewer error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/mex/viewer/start-vanilla', methods=['POST'])
def start_viewer_vanilla():
    """Start the 3D model viewer for a vanilla costume (for skin creator)"""
    global viewer_process, viewer_port

    try:
        data = request.json
        character = data.get('character')
        costume_code = data.get('costumeCode')  # e.g., "PlFxNr"

        if not character or not costume_code:
            return jsonify({'success': False, 'error': 'Missing character or costumeCode'}), 400

        # Stop any existing viewer
        if viewer_process is not None:
            try:
                viewer_process.terminate()
                viewer_process.wait(timeout=2)
            except:
                viewer_process.kill()
            viewer_process = None

        # Find the DAT file in vanilla assets
        dat_path = VANILLA_ASSETS_DIR / character / costume_code / f"{costume_code}.dat"
        if not dat_path.exists():
            return jsonify({'success': False, 'error': f'Vanilla costume not found: {dat_path}'}), 404

        # Check if HSDRawViewer exists
        if not HSDRAW_EXE.exists():
            return jsonify({
                'success': False,
                'error': f'HSDRawViewer not found at {HSDRAW_EXE}. Please build it first.'
            }), 500

        # Find an available port
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('localhost', 0))
        viewer_port = sock.getsockname()[1]
        sock.close()

        # Convert paths for Windows if running in WSL
        def to_windows_path(path):
            path_str = str(path)
            if os.name != 'nt' and path_str.startswith('/mnt/'):
                drive = path_str[5].upper()
                return f"{drive}:{path_str[6:]}".replace('/', '\\')
            return path_str

        exe_path = to_windows_path(HSDRAW_EXE)
        dat_windows_path = to_windows_path(dat_path)
        logs_windows_path = to_windows_path(LOGS_PATH)

        # Look for a scene file for this character
        scene_path = None
        csp_data_dir = PROCESSOR_DIR / "csp_data" / character
        if csp_data_dir.exists():
            if (csp_data_dir / "scene.yml").exists():
                scene_path = csp_data_dir / "scene.yml"
            else:
                yml_files = sorted(csp_data_dir.glob("*.yml"))
                if yml_files:
                    scene_path = yml_files[0]

        scene_windows_path = to_windows_path(scene_path) if scene_path else None

        # Look for AJ file
        char_prefixes = {
            "C. Falcon": "PlCa", "Falco": "PlFc", "Fox": "PlFx",
            "Marth": "PlMs", "Roy": "PlFe", "Bowser": "PlKp",
            "DK": "PlDk", "Ganondorf": "PlGn", "Jigglypuff": "PlPr",
            "Kirby": "PlKb", "Link": "PlLk", "Luigi": "PlLg",
            "Mario": "PlMr", "Mewtwo": "PlMt", "Ness": "PlNs",
            "Peach": "PlPe", "Pichu": "PlPc", "Pikachu": "PlPk",
            "Ice Climbers": "PlPp", "Samus": "PlSs", "Sheik": "PlSk",
            "Yoshi": "PlYs", "Young Link": "PlCl", "Zelda": "PlZd",
            "Dr. Mario": "PlDr", "G&W": "PlGw"
        }

        aj_windows_path = None
        if character in char_prefixes:
            prefix = char_prefixes[character]
            aj_path = VANILLA_ASSETS_DIR / character / f"{prefix}AJ.dat"
            if aj_path.exists():
                aj_windows_path = to_windows_path(aj_path)

        # Build command
        cmd = [exe_path, '--stream', str(viewer_port), dat_windows_path, logs_windows_path]
        if scene_windows_path:
            cmd.append(scene_windows_path)
        else:
            cmd.append('')
        if aj_windows_path:
            cmd.append(aj_windows_path)

        logger.info(f"Starting vanilla viewer: {' '.join(cmd)}")

        # Start the viewer process
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        viewer_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags
        )

        # Poll until server is ready
        import urllib.request
        max_wait = 15
        poll_interval = 0.5
        server_ready = False

        for _ in range(int(max_wait / poll_interval)):
            time.sleep(poll_interval)

            if viewer_process is None:
                return jsonify({'success': False, 'error': 'Viewer was stopped during startup'}), 500

            if viewer_process.poll() is not None:
                stdout, stderr = viewer_process.communicate()
                viewer_process = None
                return jsonify({
                    'success': False,
                    'error': f'Viewer failed to start: {stderr.decode() if stderr else stdout.decode()}'
                }), 500

            try:
                req = urllib.request.urlopen(f'http://localhost:{viewer_port}/', timeout=1)
                if req.status == 200:
                    server_ready = True
                    break
            except:
                pass

        if not server_ready:
            if viewer_process:
                viewer_process.kill()
                viewer_process = None
            return jsonify({'success': False, 'error': 'Viewer failed to start within timeout'}), 500

        return jsonify({
            'success': True,
            'port': viewer_port,
            'wsUrl': f'ws://localhost:{viewer_port}/'
        })

    except Exception as e:
        logger.error(f"Start vanilla viewer error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/mex/vanilla/costumes/<character>', methods=['GET'])
def get_vanilla_costumes(character):
    """Get list of vanilla costumes for a character"""
    try:
        char_dir = VANILLA_ASSETS_DIR / character
        if not char_dir.exists():
            return jsonify({'success': False, 'error': f'Character {character} not found'}), 404

        costumes = []
        for folder in sorted(char_dir.iterdir()):
            if folder.is_dir() and folder.name.startswith('Pl'):
                # Check if DAT file exists
                dat_file = folder / f"{folder.name}.dat"
                if dat_file.exists():
                    # Get color code from folder name (last 2 chars)
                    color_code = folder.name[-2:]
                    color_names = {
                        'Nr': 'Default', 'Bu': 'Blue', 'Re': 'Red', 'Gr': 'Green',
                        'Ye': 'Yellow', 'Bk': 'Black', 'Wh': 'White', 'Pi': 'Pink',
                        'Or': 'Orange', 'La': 'Lavender', 'Aq': 'Aqua', 'Gy': 'Grey',
                        'Cy': 'Cyan', 'Pr': 'Purple', 'Br': 'Brown'
                    }
                    costumes.append({
                        'code': folder.name,
                        'colorCode': color_code,
                        'colorName': color_names.get(color_code, color_code),
                        'hasCsp': (folder / 'csp.png').exists(),
                        'hasStock': (folder / 'stock.png').exists()
                    })

        return jsonify({'success': True, 'costumes': costumes})

    except Exception as e:
        logger.error(f"Get vanilla costumes error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/viewer/stop', methods=['POST'])
def stop_viewer():
    """Stop the 3D model viewer"""
    global viewer_process, viewer_port

    try:
        if viewer_process is not None:
            try:
                viewer_process.terminate()
                viewer_process.wait(timeout=2)
            except:
                viewer_process.kill()

            viewer_process = None
            viewer_port = None

        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"Stop viewer error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/viewer/status', methods=['GET'])
def viewer_status():
    """Get the current viewer status"""
    global viewer_process, viewer_port

    running = viewer_process is not None and viewer_process.poll() is None

    return jsonify({
        'success': True,
        'running': running,
        'port': viewer_port if running else None,
        'wsUrl': f'ws://localhost:{viewer_port}/' if running else None
    })


def cleanup_on_exit():
    """Cleanup function called on exit"""
    global mex_manager, viewer_process
    logger.info("Cleaning up MEX API Backend...")

    # Stop viewer if running
    if viewer_process is not None:
        try:
            viewer_process.terminate()
            viewer_process.wait(timeout=2)
        except:
            viewer_process.kill()
        viewer_process = None

    # Clean up any temporary files
    try:
        if mex_manager:
            # Close any open project
            mex_manager = None
    except:
        pass

    logger.info("MEX API Backend shutdown complete")


def signal_handler(sig, frame):
    """Handle termination signals"""
    logger.info(f"Received signal {sig}")
    cleanup_on_exit()
    sys.exit(0)


if __name__ == '__main__':
    print(f"Starting MEX API Backend...")
    print(f"MexCLI: {MEXCLI_PATH}")
    print(f"Default Project: {MEX_PROJECT_PATH}")
    print(f"Storage: {STORAGE_PATH}")

    # Verify MexCLI exists
    if not MEXCLI_PATH.exists():
        print(f"ERROR: MexCLI not found at {MEXCLI_PATH}")
        print("Please build it first: cd utility/MexManager/MexCLI && dotnet build -c Release")
        sys.exit(1)

    # Register cleanup handlers
    atexit.register(cleanup_on_exit)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    if hasattr(signal, 'SIGBREAK'):
        # Windows-specific signal
        signal.signal(signal.SIGBREAK, signal_handler)

    # Run migration for legacy character names
    print("Checking for legacy character names to migrate...")
    migrate_legacy_character_names()

    # No auto-loading - user must select a project
    print(f"INFO: MEX Manager ready. Please open a project to get started.")

    # Use regular Flask app.run() to avoid socket issues on Windows
    # SocketIO will still work through the middleware
    # Set use_reloader=False in production to prevent double startup
    app.run(host='127.0.0.1', port=5000, debug=True, use_reloader=False)
