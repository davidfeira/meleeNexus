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
from werkzeug.utils import secure_filename

# Add parent directory to path for mex_bridge import
sys.path.insert(0, str(Path(__file__).parent.parent))
from mex_bridge import MexManager, MexManagerError

# Add backend directory to path for detectors
BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKEND_DIR))
from character_detector import detect_character_from_zip
from stage_detector import detect_stage_from_zip, extract_stage_files

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuration
PROJECT_ROOT = Path(__file__).parent.parent
MEXCLI_PATH = PROJECT_ROOT / "utility/MexManager/MexCLI/bin/Release/net6.0/mexcli.exe"
MEX_PROJECT_PATH = PROJECT_ROOT / "build/project.mexproj"
STORAGE_PATH = PROJECT_ROOT / "storage"
OUTPUT_PATH = PROJECT_ROOT / "output"
LOGS_PATH = PROJECT_ROOT / "logs"
VIEWER_STORAGE = PROJECT_ROOT / "viewer" / "public" / "storage"

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

# Global MEX manager instance
mex_manager = None

def get_mex_manager():
    """Get or initialize MEX manager instance"""
    global mex_manager
    if mex_manager is None:
        try:
            mex_manager = MexManager(
                cli_path=str(MEXCLI_PATH),
                project_path=str(MEX_PROJECT_PATH)
            )
        except MexManagerError as e:
            raise Exception(f"Failed to initialize MexManager: {e}")
    return mex_manager


@app.route('/api/mex/status', methods=['GET'])
def get_status():
    """Get MEX project status"""
    try:
        mex = get_mex_manager()
        info = mex.get_info()

        return jsonify({
            'success': True,
            'connected': True,
            'project': {
                'name': info['build']['name'],
                'version': f"{info['build']['majorVersion']}.{info['build']['minorVersion']}.{info['build']['patchVersion']}",
                'path': str(MEX_PROJECT_PATH)
            },
            'counts': info['counts']
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'connected': False,
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
        # Asset path already includes the extension from the URL
        full_path = PROJECT_ROOT / "build" / asset_path

        if not full_path.exists():
            return jsonify({'success': False, 'error': f'Asset not found: {asset_path}'}), 404

        return send_file(full_path, mimetype='image/png')
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


@app.route('/api/mex/export/start', methods=['POST'])
def start_export():
    """
    Start ISO export (async operation with WebSocket progress)

    Body:
    {
        "filename": "modded_game.iso",  // optional
        "cspCompression": 1.0  // optional, 0.1-1.0, default 1.0
    }
    """
    try:
        data = request.json or {}
        filename = data.get('filename', f'game_{datetime.now().strftime("%Y%m%d_%H%M%S")}.iso')
        csp_compression = data.get('cspCompression', 1.0)

        # Validate compression range
        if not isinstance(csp_compression, (int, float)) or csp_compression < 0.1 or csp_compression > 1.0:
            return jsonify({
                'success': False,
                'error': 'cspCompression must be a number between 0.1 and 1.0'
            }), 400

        output_file = OUTPUT_PATH / filename

        logger.info(f"=== ISO EXPORT START ===")
        logger.info(f"Filename: {filename}")
        logger.info(f"CSP Compression: {csp_compression}")

        def export_with_progress():
            """Export ISO in background thread with WebSocket progress updates"""
            try:
                def progress_callback(percentage, message):
                    socketio.emit('export_progress', {
                        'percentage': percentage,
                        'message': message
                    })

                mex = get_mex_manager()
                result = mex.export_iso(str(output_file), progress_callback, csp_compression)

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
                    costumes.append({
                        'character': char_name,
                        'name': f"{char_name} - {skin.get('color', 'Custom')}",
                        'folder': skin['id'],
                        'costumeCode': skin['costume_code'],
                        'zipPath': str(zip_path.relative_to(PROJECT_ROOT)),
                        # These paths are relative to viewer/public/ which Vite serves at root
                        'cspUrl': f"/storage/{char_name}/{skin['id']}_csp.png" if skin.get('has_csp') else None,
                        'stockUrl': f"/storage/{char_name}/{skin['id']}_stc.png" if skin.get('has_stock') else None
                    })

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

        viewer_folder = VIEWER_STORAGE / character
        csp_file = viewer_folder / f"{skin_id}_csp.png"
        stc_file = viewer_folder / f"{skin_id}_stc.png"

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


# REMOVED: Old intake/import endpoint - replaced with unified /api/mex/import/file endpoint


# ============= Unified Import Endpoint =============

@app.route('/api/mex/import/file', methods=['POST'])
def import_file():
    """
    Unified import endpoint for both character costumes and stage mods.

    Accepts ZIP file upload, auto-detects type, and processes accordingly.
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

        if not file.filename.endswith('.zip'):
            return jsonify({
                'success': False,
                'error': 'Only ZIP files are supported'
            }), 400

        # Save uploaded file to temp location
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
            file.save(tmp.name)
            temp_zip_path = tmp.name

        try:
            logger.info(f"=== UNIFIED IMPORT: {file.filename} ===")

            # PHASE 1: Try character detection first
            logger.info("Phase 1: Attempting character detection...")
            character_info = detect_character_from_zip(temp_zip_path)

            if character_info:
                logger.info(f"✓ Detected character costume: {character_info['character']} - {character_info['color']}")
                result = import_character_costume(temp_zip_path, character_info, file.filename)
                return jsonify(result)

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


def import_character_costume(zip_path: str, char_info: dict, original_filename: str) -> dict:
    """Import a character costume to storage"""
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

        # Generate sequential ID
        base_id = f"{character.lower().replace(' ', '-')}-{char_info['color'].lower()}"
        skin_id = base_id
        counter = 1
        while skin_id in existing_ids:
            skin_id = f"{base_id}-{counter:03d}"
            counter += 1

        # Final paths
        final_zip = char_folder / f"{skin_id}.zip"

        # Copy files from uploaded ZIP to final ZIP with correct structure
        with zipfile.ZipFile(zip_path, 'r') as source_zip:
            with zipfile.ZipFile(final_zip, 'w') as dest_zip:
                # Copy DAT file
                dat_data = source_zip.read(char_info['dat_file'])
                dest_zip.writestr(f"{char_info['costume_code']}Mod.dat", dat_data)

                # Copy CSP if found
                if char_info['csp_file']:
                    csp_data = source_zip.read(char_info['csp_file'])
                    dest_zip.writestr('csp.png', csp_data)

                    # Also save to viewer/public/storage for preview
                    viewer_char_folder = VIEWER_STORAGE / character
                    viewer_char_folder.mkdir(parents=True, exist_ok=True)
                    (viewer_char_folder / f"{skin_id}_csp.png").write_bytes(csp_data)

                # Copy stock if found
                if char_info['stock_file']:
                    stock_data = source_zip.read(char_info['stock_file'])
                    dest_zip.writestr('stc.png', stock_data)

                    # Also save to viewer/public/storage for preview
                    viewer_char_folder = VIEWER_STORAGE / character
                    (viewer_char_folder / f"{skin_id}_stc.png").write_bytes(stock_data)

        # Update metadata
        if character not in metadata['characters']:
            metadata['characters'][character] = {'skins': []}

        metadata['characters'][character]['skins'].append({
            'id': skin_id,
            'color': char_info['color'],
            'costume_code': char_info['costume_code'],
            'filename': f"{skin_id}.zip",
            'has_csp': char_info['csp_file'] is not None,
            'has_stock': char_info['stock_file'] is not None,
            'csp_source': 'imported',
            'stock_source': 'imported',
            'date_added': datetime.now().isoformat()
        })

        # Save metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"✓ Saved character costume: {final_zip}")

        return {
            'success': True,
            'type': 'character',
            'character': character,
            'color': char_info['color'],
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

                # Also save to viewer/public/storage for preview
                viewer_das_folder = VIEWER_STORAGE / 'das' / stage_folder_name
                viewer_das_folder.mkdir(parents=True, exist_ok=True)
                viewer_screenshot_path = viewer_das_folder / f"{variant_id}_screenshot.png"
                viewer_screenshot_path.write_bytes(screenshot_data)

                has_screenshot = True
                logger.info(f"✓ Saved screenshot: {screenshot_path}")
                logger.info(f"✓ Saved viewer screenshot: {viewer_screenshot_path}")

        # Update metadata
        if stage_folder_name not in metadata['stages']:
            metadata['stages'][stage_folder_name] = {'variants': []}

        metadata['stages'][stage_folder_name]['variants'].append({
            'id': variant_id,
            'name': variant_id.replace('-', ' ').title(),
            'filename': f"{variant_id}.zip",
            'has_screenshot': has_screenshot,
            'date_added': datetime.now().isoformat()
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

@app.route('/api/mex/das/status', methods=['GET'])
def das_get_status():
    """Check if DAS framework is installed"""
    try:
        # Check if DAS loader files exist in build/files/
        build_files_path = PROJECT_ROOT / "build" / "files"
        installed_stages = []

        for stage_code, stage_info in DAS_STAGES.items():
            loader_path = build_files_path / f"{stage_code}.dat"
            folder_path = build_files_path / stage_code

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
        build_files = PROJECT_ROOT / "build" / "files"

        if not das_source.exists():
            return jsonify({
                'success': False,
                'error': f'DAS framework source not found at {das_source}'
            }), 500

        build_files.mkdir(parents=True, exist_ok=True)

        # Install each stage
        for stage_code, stage_info in DAS_STAGES.items():
            logger.info(f"Installing DAS for {stage_info['name']} ({stage_code})...")

            # Pokemon Stadium uses .usd, others use .dat
            file_ext = '.usd' if stage_code == 'GrPs' else '.dat'

            # Copy loader file
            loader_src = das_source / f"{stage_code}{file_ext}"
            loader_dst = build_files / f"{stage_code}{file_ext}"

            if loader_src.exists():
                # Backup original stage file if it exists
                if loader_dst.exists():
                    backup_dst = build_files / f"{stage_code}_vanilla{file_ext}"
                    if not backup_dst.exists():
                        shutil.copy2(loader_dst, backup_dst)
                        logger.info(f"  Backed up original {stage_code}{file_ext} to {stage_code}_vanilla{file_ext}")

                # Copy loader file
                shutil.copy2(loader_src, loader_dst)
                logger.info(f"  Installed loader: {stage_code}{file_ext}")
            else:
                logger.warning(f"  Loader not found: {loader_src}")

            # Create stage folder
            stage_folder = build_files / stage_code
            stage_folder.mkdir(exist_ok=True)
            logger.info(f"  Created folder: {stage_code}/")

            # Copy vanilla stage into folder if backup exists
            vanilla_backup = build_files / f"{stage_code}_vanilla{file_ext}"
            if vanilla_backup.exists():
                vanilla_in_folder = stage_folder / f"{stage_code}_00{file_ext}"
                shutil.copy2(vanilla_backup, vanilla_in_folder)
                logger.info(f"  Copied vanilla stage to {stage_code}/{stage_code}_00{file_ext}")

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

        # List stage files in build/files/{stage_code}/ (.dat or .usd for Pokemon Stadium)
        stage_folder = PROJECT_ROOT / "build" / "files" / stage_code
        variants = []

        if stage_folder.exists() and stage_folder.is_dir():
            # Pokemon Stadium uses .usd, others use .dat
            file_pattern = '*.usd' if stage_code == 'GrPs' else '*.dat'

            for stage_file in stage_folder.glob(file_pattern):
                # Check if screenshot exists in viewer/public/storage
                viewer_screenshot = VIEWER_STORAGE / 'das' / DAS_STAGES[stage_code]['folder'] / f"{stage_file.stem}_screenshot.png"

                variants.append({
                    'name': stage_file.stem,
                    'filename': stage_file.name,
                    'stageCode': stage_code,
                    'hasScreenshot': viewer_screenshot.exists(),
                    'screenshotUrl': f"/storage/das/{DAS_STAGES[stage_code]['folder']}/{stage_file.stem}_screenshot.png" if viewer_screenshot.exists() else None
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

        # Determine which stages to scan
        stages_to_scan = {stage_code: DAS_STAGES[stage_code]} if stage_code and stage_code in DAS_STAGES else DAS_STAGES

        for code, stage_info in stages_to_scan.items():
            stage_storage_path = STORAGE_PATH / "das" / stage_info['folder']

            if stage_storage_path.exists():
                # Look for .zip files and their associated screenshots
                for zip_file in stage_storage_path.glob('*.zip'):
                    variant_id = zip_file.stem

                    # Check for screenshot in viewer/public/storage (where it's accessible)
                    viewer_screenshot = VIEWER_STORAGE / 'das' / stage_info['folder'] / f"{variant_id}_screenshot.png"

                    variants.append({
                        'stageCode': code,
                        'stageName': stage_info['name'],
                        'name': variant_id,
                        'zipPath': str(zip_file.relative_to(PROJECT_ROOT)),
                        'hasScreenshot': viewer_screenshot.exists(),
                        'screenshotUrl': f"/storage/das/{stage_info['folder']}/{variant_id}_screenshot.png" if viewer_screenshot.exists() else None
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

        stage_folder = PROJECT_ROOT / "build" / "files" / stage_code
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

            # Find next available slot
            existing_count = 0
            while True:
                final_name = f"{stage_code}_{existing_count:02d}"
                final_path = stage_folder / f"{final_name}{file_ext}"
                if not final_path.exists():
                    break
                existing_count += 1

            # Write directly to final location
            final_path.write_bytes(stage_data)
            logger.info(f"✓ Extracted stage file to: {final_path}")

            # Also extract screenshot if it exists in the ZIP
            screenshot_files = [f for f in zip_ref.namelist() if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
            if screenshot_files:
                screenshot_file = screenshot_files[0]
                screenshot_data = zip_ref.read(screenshot_file)

                # Save to viewer/public/storage for display
                viewer_das_folder = VIEWER_STORAGE / 'das' / DAS_STAGES[stage_code]['folder']
                viewer_das_folder.mkdir(parents=True, exist_ok=True)
                viewer_screenshot_path = viewer_das_folder / f"{final_name}_screenshot.png"
                viewer_screenshot_path.write_bytes(screenshot_data)
                logger.info(f"✓ Saved screenshot: {viewer_screenshot_path}")

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
        stage_folder = PROJECT_ROOT / "build" / "files" / stage_code
        variant_path = stage_folder / f"{variant_name}{file_ext}"

        if not variant_path.exists():
            return jsonify({
                'success': False,
                'error': f'Variant not found: {variant_name}{file_ext}'
            }), 404

        variant_path.unlink()
        logger.info(f"DAS variant removed: {variant_path}")

        # Also remove screenshot from viewer if it exists
        viewer_screenshot = VIEWER_STORAGE / 'das' / DAS_STAGES[stage_code]['folder'] / f"{variant_name}_screenshot.png"
        if viewer_screenshot.exists():
            viewer_screenshot.unlink()
            logger.info(f"Removed screenshot: {viewer_screenshot}")

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

        viewer_das_folder = VIEWER_STORAGE / 'das' / stage_folder
        screenshot_file = viewer_das_folder / f"{variant_id}_screenshot.png"

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

        # Save to viewer/public/storage for display
        viewer_das_folder = VIEWER_STORAGE / 'das' / stage_folder
        viewer_das_folder.mkdir(parents=True, exist_ok=True)
        viewer_screenshot_path = viewer_das_folder / f"{variant_id}_screenshot.png"
        viewer_screenshot_path.write_bytes(screenshot_data)

        # Also save to storage/das as backup
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
        logger.info(f"  Saved to: {viewer_screenshot_path}")

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
    print(f"Project: {MEX_PROJECT_PATH}")
    print(f"Storage: {STORAGE_PATH}")

    # Verify MexCLI exists
    if not MEXCLI_PATH.exists():
        print(f"ERROR: MexCLI not found at {MEXCLI_PATH}")
        print("Please build it first: cd utility/MexManager/MexCLI && dotnet build -c Release")
        sys.exit(1)

    # Verify project exists
    if not MEX_PROJECT_PATH.exists():
        print(f"WARNING: MEX project not found at {MEX_PROJECT_PATH}")

    socketio.run(app, host='127.0.0.1', port=5000, debug=True)
