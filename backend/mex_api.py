"""
MEX API Backend - Flask server for MexManager operations

Provides REST API endpoints for costume import and ISO export operations.
"""

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import os
import sys
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

# Add parent directory to path for mex_bridge import
sys.path.insert(0, str(Path(__file__).parent.parent))
from mex_bridge import MexManager, MexManagerError

# Configuration
PROJECT_ROOT = Path(__file__).parent.parent

# Add backend directory to path for detectors
BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKEND_DIR))
from character_detector import detect_character_from_zip, DATParser
from stage_detector import detect_stage_from_zip, extract_stage_files

# Add processor tools to path for CSP generation and slippi validation
PROCESSOR_DIR = PROJECT_ROOT / "utility" / "website" / "backend" / "tools" / "processor"
sys.path.insert(0, str(PROCESSOR_DIR))
from generate_csp import generate_csp

# Add services for DAT processing (slippi validation)
SERVICES_DIR = PROJECT_ROOT / "utility" / "website" / "backend" / "app" / "services"
sys.path.insert(0, str(SERVICES_DIR))
from dat_processor import validate_for_slippi

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*")
MEXCLI_PATH = PROJECT_ROOT / "utility/MexManager/MexCLI/bin/Release/net6.0/mexcli.exe"
MEX_PROJECT_PATH = PROJECT_ROOT / "build/project.mexproj"
STORAGE_PATH = PROJECT_ROOT / "storage"
OUTPUT_PATH = PROJECT_ROOT / "output"
LOGS_PATH = PROJECT_ROOT / "logs"
VANILLA_ASSETS_DIR = PROJECT_ROOT / "utility" / "assets" / "vanilla"

# Ensure directories exist
OUTPUT_PATH.mkdir(exist_ok=True)
LOGS_PATH.mkdir(exist_ok=True)

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

        logger.info(f"✓ Opened MEX project: {project_path}")

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

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT
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

        logger.info(f"✓ Project created successfully: {created_project_path}")
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
                costume['cspUrl'] = f"/assets/assets/{csp_path}.png"
            if costume.get('icon'):
                # Convert backslashes to forward slashes for URLs
                icon_path = costume['icon'].replace('\\', '/')
                costume['iconUrl'] = f"/assets/assets/{icon_path}.png"

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
        full_path = STORAGE_PATH / file_path

        if not full_path.exists():
            return jsonify({'success': False, 'error': f'File not found: {file_path}'}), 404

        # Determine mimetype based on extension
        if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            mimetype = 'image/png'
        elif file_path.lower().endswith('.zip'):
            mimetype = 'application/zip'
        else:
            mimetype = 'application/octet-stream'

        return send_file(full_path, mimetype=mimetype)
    except Exception as e:
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
    """List all costumes in storage with MEX-compatible ZIPs"""
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
            for skin in char_data.get('skins', []):
                # ZIPs are stored directly in character folder: storage/Character/filename.zip
                zip_path = STORAGE_PATH / char_name / skin['filename']

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

        logger.info(f"✓ Deleted costume {skin_id} for {character}")
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

        logger.info(f"✓ Renamed costume {skin_id} to '{new_name}'")

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

        logger.info(f"✓ Updated CSP for {character} - {skin_id}")

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

        logger.info(f"✓ Updated stock icon for {character} - {skin_id}")

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

        logger.info(f"✓ Retested slippi for {character} - {skin_id}: {validation['slippi_safe']}")

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
        character = data.get('character')
        skin_id = data.get('skinId')
        slippi_safe = data.get('slippiSafe')

        if not character or not skin_id or slippi_safe is None:
            return jsonify({
                'success': False,
                'error': 'Missing character, skinId, or slippiSafe parameter'
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

        # Find and update the skin
        if character not in metadata.get('characters', {}):
            return jsonify({
                'success': False,
                'error': f'Character {character} not found in metadata'
            }), 404

        skin_found = False
        for skin in metadata['characters'][character].get('skins', []):
            if skin['id'] == skin_id:
                skin['slippi_safe'] = slippi_safe
                skin['slippi_manual_override'] = True
                skin['slippi_test_date'] = datetime.now().isoformat()
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

        logger.info(f"✓ Manually set slippi status for {character} - {skin_id}: {slippi_safe}")

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
        stage_name = data.get('stageName')
        variant_id = data.get('variantId')
        slippi_safe = data.get('slippiSafe')

        if not stage_name or not variant_id or slippi_safe is None:
            return jsonify({
                'success': False,
                'error': 'Missing stageName, variantId, or slippiSafe parameter'
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

        # Find and update the stage variant
        if stage_name not in metadata.get('stages', {}):
            return jsonify({
                'success': False,
                'error': f'Stage {stage_name} not found in metadata'
            }), 404

        variant_found = False
        for variant in metadata['stages'][stage_name].get('variants', []):
            if variant['id'] == variant_id:
                variant['slippi_safe'] = slippi_safe
                variant['slippi_test_date'] = datetime.now().isoformat()
                variant_found = True
                break

        if not variant_found:
            return jsonify({
                'success': False,
                'error': f'Variant {variant_id} not found for {stage_name}'
            }), 404

        # Save updated metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"✓ Set slippi status for {stage_name} - {variant_id}: {slippi_safe}")

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

        # Build command arguments
        clear_script = PROJECT_ROOT / "clear_storage.py"
        cmd = [sys.executable, str(clear_script)]

        if clear_intake and clear_logs:
            cmd.append("--all")
        elif clear_intake:
            cmd.append("--clear-intake")
        elif clear_logs:
            cmd.append("--clear-logs")

        # Execute clear_storage.py script
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT
        )

        if result.returncode != 0:
            logger.error(f"Clear storage script failed: {result.stderr}")
            return jsonify({
                'success': False,
                'error': f'Failed to clear storage: {result.stderr}'
            }), 500

        logger.info(f"Clear storage output:\n{result.stdout}")
        logger.info("=== CLEAR STORAGE COMPLETE ===")

        return jsonify({
            'success': True,
            'message': 'Storage cleared successfully',
            'output': result.stdout
        })
    except Exception as e:
        logger.error(f"Clear storage error: {str(e)}", exc_info=True)
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
                logger.info(f"✓ Detected {len(character_infos)} character costume(s)")

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
                    result = import_character_costume(temp_zip_path, character_info, file.filename, auto_fix=auto_fix)
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
            stage_info = detect_stage_from_zip(temp_zip_path)

            if stage_info:
                logger.info(f"✓ Detected stage mod: {stage_info['stage_name']}")
                result = import_stage_mod(temp_zip_path, stage_info, file.filename)
                return jsonify(result)

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
            costume_code = skin['costume_code']

            # Skip if this costume wasn't just imported
            if costume_code not in imported_skin_ids:
                continue

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
            logger.info("✓ Updated Ice Climbers pairing with actual skin IDs")

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


def import_character_costume(zip_path: str, char_info: dict, original_filename: str, auto_fix: bool = False) -> dict:
    """
    Import a character costume to storage.

    Args:
        zip_path: Path to the uploaded ZIP file
        char_info: Character detection info
        original_filename: Original filename of the upload
        auto_fix: If True, apply slippi fixes to the DAT file
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

        # Try to extract custom name from filename
        custom_name = extract_custom_name_from_filename(original_filename, character)

        # Sanitize color name: replace spaces and slashes with hyphens
        color_safe = char_info['color'].lower().replace(' ', '-').replace('/', '-')

        # Generate base ID: use custom name if found, otherwise use character name
        if custom_name:
            base_id = f"{custom_name}-{color_safe}"
            logger.info(f"Using custom name from filename: '{custom_name}' -> '{base_id}'")
        else:
            base_id = f"{character.lower().replace(' ', '-')}-{color_safe}"
            logger.info(f"Using default naming: '{base_id}'")

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

        # Build skin entry
        skin_entry = {
            'id': skin_id,
            'color': char_info['color'],
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

        logger.info(f"✓ Saved character costume: {final_zip}")

        return {
            'success': True,
            'type': 'character',
            'character': character,
            'color': char_info['color'],
            'skin_id': skin_id,  # Return the actual skin ID for pairing
            'message': f"Imported {character} - {char_info['color']} costume"
        }

    except Exception as e:
        logger.error(f"Character import error: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def import_stage_mod(zip_path: str, stage_info: dict, original_filename: str) -> dict:
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

        # Generate sequential ID based on original filename
        base_name = Path(original_filename).stem.lower().replace(' ', '-')
        variant_id = base_name
        counter = 1
        while variant_id in existing_ids:
            variant_id = f"{base_name}-{counter:03d}"
            counter += 1

        # Final paths
        final_zip = das_folder / f"{variant_id}.zip"

        # Copy the entire ZIP
        shutil.copy2(zip_path, final_zip)

        # Extract screenshot if available
        has_screenshot = False
        if stage_info['screenshot']:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                screenshot_data = zf.read(stage_info['screenshot'])
                screenshot_ext = os.path.splitext(stage_info['screenshot'])[1]

                # Save to storage folder
                screenshot_path = das_folder / f"{variant_id}_screenshot{screenshot_ext}"
                screenshot_path.write_bytes(screenshot_data)

                has_screenshot = True
                logger.info(f"✓ Saved screenshot: {screenshot_path}")

        # Update metadata
        if stage_folder_name not in metadata['stages']:
            metadata['stages'][stage_folder_name] = {'variants': []}

        metadata['stages'][stage_folder_name]['variants'].append({
            'id': variant_id,
            'name': variant_id.replace('-', ' ').title(),
            'filename': f"{variant_id}.zip",
            'has_screenshot': has_screenshot,
            'date_added': datetime.now().isoformat()
            # No default slippi status - will show as "Unknown" until manually set
        })

        # Save metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"✓ Saved stage mod: {final_zip}")

        return {
            'success': True,
            'type': 'stage',
            'stage': stage_name,
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

        das_source = PROJECT_ROOT / "utility" / "DynamicAlternateStages"
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
                    default_screenshot = PROJECT_ROOT / "utility" / "assets" / "stages" / DAS_DEFAULT_SCREENSHOTS[stage_code]
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

            for stage_file in stage_folder.glob(file_pattern):
                # Check if screenshot exists in storage (single source of truth)
                # Screenshot name matches the .dat filename
                # e.g., autumn-dreamland.dat → autumn-dreamland_screenshot.png
                storage_screenshot = STORAGE_PATH / 'das' / DAS_STAGES[stage_code]['folder'] / f"{stage_file.stem}_screenshot.png"

                variants.append({
                    'name': stage_file.stem,
                    'filename': stage_file.name,
                    'stageCode': stage_code,
                    'hasScreenshot': storage_screenshot.exists(),
                    'screenshotUrl': f"/storage/das/{DAS_STAGES[stage_code]['folder']}/{stage_file.stem}_screenshot.png" if storage_screenshot.exists() else None
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
            metadata_variants = {v['id']: v for v in stage_metadata.get('variants', [])}

            if stage_storage_path.exists():
                # Look for .zip files and their associated screenshots
                for zip_file in stage_storage_path.glob('*.zip'):
                    variant_id = zip_file.stem

                    # Get name from metadata, fallback to ID if not found
                    variant_meta = metadata_variants.get(variant_id, {})
                    variant_name = variant_meta.get('name', variant_id)

                    # Check for screenshot in storage (single source of truth)
                    storage_screenshot = stage_storage_path / f"{variant_id}_screenshot.png"

                    variants.append({
                        'stageCode': code,
                        'stageName': stage_info['name'],
                        'id': variant_id,  # ← Immutable ID (filename)
                        'name': variant_name,  # ← Editable display name
                        'zipPath': str(zip_file.relative_to(PROJECT_ROOT)),
                        'hasScreenshot': storage_screenshot.exists(),
                        'screenshotUrl': f"/storage/das/{stage_info['folder']}/{variant_id}_screenshot.png" if storage_screenshot.exists() else None
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

            # Use mod name from ZIP filename instead of sequential numbering
            variant_id = Path(full_variant_path).stem  # e.g., "autumn-dreamland"
            final_name = variant_id
            final_path = stage_folder / f"{final_name}{file_ext}"

            # If file already exists, append suffix to avoid conflicts
            if final_path.exists():
                count = 1
                while True:
                    final_name = f"{variant_id}_{count}"
                    final_path = stage_folder / f"{final_name}{file_ext}"
                    if not final_path.exists():
                        break
                    count += 1

            # Write directly to final location
            final_path.write_bytes(stage_data)
            logger.info(f"✓ Extracted stage file to: {final_path}")
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

        # Also remove screenshot from storage if it exists
        storage_screenshot = STORAGE_PATH / 'das' / DAS_STAGES[stage_code]['folder'] / f"{variant_name}_screenshot.png"
        if storage_screenshot.exists():
            storage_screenshot.unlink()
            logger.info(f"Removed screenshot: {storage_screenshot}")

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

        logger.info(f"✓ Deleted stage variant {variant_id} from {stage_folder}")
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
        stage_folder = data.get('stageFolder')
        variant_id = data.get('variantId')
        new_name = data.get('newName')

        if not stage_folder or not variant_id or not new_name:
            return jsonify({
                'success': False,
                'error': 'Missing stageFolder, variantId, or newName parameter'
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

        # Find and update the variant in metadata
        if stage_folder not in metadata.get('stages', {}):
            return jsonify({
                'success': False,
                'error': f'Stage folder {stage_folder} not found in metadata'
            }), 404

        stage_data = metadata['stages'][stage_folder]
        variants = stage_data.get('variants', [])
        variant_found = False

        for variant in variants:
            if variant['id'] == variant_id:
                variant['name'] = new_name
                variant_found = True
                break

        if not variant_found:
            return jsonify({
                'success': False,
                'error': f'Variant {variant_id} not found in {stage_folder}'
            }), 404

        # Save updated metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"✓ Renamed stage variant {variant_id} to '{new_name}'")

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

        logger.info(f"✓ Updated screenshot for {stage_folder}/{variant_id}")
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


@socketio.on('connect')
def handle_connect():
    """Handle WebSocket connection"""
    print('Client connected')
    emit('connected', {'message': 'Connected to MEX API'})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle WebSocket disconnection"""
    print('Client disconnected')


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

    # No auto-loading - user must select a project
    print(f"INFO: MEX Manager ready. Please open a project to get started.")

    socketio.run(app, host='127.0.0.1', port=5000, debug=True)
