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

# Add parent directory to path for mex_bridge import
sys.path.insert(0, str(Path(__file__).parent.parent))
from mex_bridge import MexManager, MexManagerError

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


@app.route('/api/mex/intake/import', methods=['POST'])
def import_from_intake():
    """Import costumes from intake folder using manage_storage.py"""
    try:
        manage_storage_path = PROJECT_ROOT / 'manage_storage.py'

        if not manage_storage_path.exists():
            return jsonify({
                'success': False,
                'error': 'manage_storage.py not found'
            }), 500

        # Run manage_storage.py with import command
        result = subprocess.run(
            [sys.executable, str(manage_storage_path), 'import'],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        if result.returncode != 0:
            return jsonify({
                'success': False,
                'error': f'Import failed: {result.stderr}'
            }), 500

        return jsonify({
            'success': True,
            'message': 'Intake import completed successfully',
            'output': result.stdout
        })
    except subprocess.TimeoutExpired:
        return jsonify({
            'success': False,
            'error': 'Import timed out after 5 minutes'
        }), 500
    except Exception as e:
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
