"""
MexManager Bridge - Python wrapper for MexManager CLI operations

This module provides a Python interface to MexManager's costume import and ISO export
functionality through the mexcli command-line interface.
"""

import json
import subprocess
import os
from pathlib import Path
from typing import Dict, List, Optional, Callable
import logging

# Configure logging
logger = logging.getLogger(__name__)


class MexManagerError(Exception):
    """Base exception for MexManager operations"""
    pass


class MexManager:
    """
    Python bridge to MexManager CLI for costume import and ISO export.

    Example usage:
        mex = MexManager(
            cli_path="utility/MexManager/MexCLI/bin/Release/net6.0/mexcli.exe",
            project_path="build/project.mexproj"
        )

        info = mex.open_project()
        fighters = mex.list_fighters()
        mex.import_costume("Fox", "storage/Fox/custom/PlFxNr_custom.zip")
        mex.export_iso("output/game.iso")
    """

    def __init__(self, cli_path: str, project_path: str):
        """
        Initialize MexManager bridge.

        Args:
            cli_path: Path to mexcli.exe executable
            project_path: Path to .mexproj project file
        """
        self.cli_path = Path(cli_path).resolve()  # Convert to absolute path
        self.project_path = Path(project_path).resolve()  # Convert to absolute path

        if not self.cli_path.exists():
            raise MexManagerError(f"MexCLI executable not found: {self.cli_path}")

        if not self.project_path.exists():
            raise MexManagerError(f"MEX project not found: {self.project_path}")

    def _run_command(self, *args) -> Dict:
        """
        Run mexcli command and return parsed JSON output.

        Args:
            *args: Command arguments to pass to mexcli

        Returns:
            Parsed JSON output from mexcli

        Raises:
            MexManagerError: If command fails or returns invalid JSON
        """
        cmd = [str(self.cli_path)] + list(args)

        logger.info(f"Running MexCLI command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=str(self.cli_path.parent)
            )

            logger.debug(f"MexCLI stdout: {result.stdout}")
            logger.debug(f"MexCLI stderr: {result.stderr}")
            logger.debug(f"MexCLI return code: {result.returncode}")

            # Try to parse JSON from stdout
            # MexCLI may output progress messages before JSON, so we need to find the JSON
            if result.stdout.strip():
                # Try to parse the entire output as JSON first
                try:
                    output = json.loads(result.stdout)
                    logger.info(f"MexCLI response: {json.dumps(output, indent=2)}")

                    # Check for error in JSON response
                    if isinstance(output, dict) and not output.get('success', True):
                        error_msg = output.get('error', 'Unknown error')
                        logger.error(f"MexCLI returned error: {error_msg}")
                        raise MexManagerError(f"MexCLI error: {error_msg}")

                    return output
                except json.JSONDecodeError:
                    # If full output isn't JSON, try parsing line by line to find JSON
                    # (MexCLI may output progress messages like "Trimmed Image X Y")
                    logger.debug("Full output is not JSON, trying line-by-line parsing")
                    lines = result.stdout.strip().split('\n')

                    # Filter out known progress messages but keep original lines (not stripped)
                    filtered_lines = [
                        line for line in lines
                        if not line.strip().startswith('Trimmed Image')
                    ]

                    # Rejoin filtered lines and try parsing as complete JSON
                    if filtered_lines:
                        filtered_output = '\n'.join(filtered_lines)
                        try:
                            output = json.loads(filtered_output)
                            logger.info(f"MexCLI response (filtered): {json.dumps(output, indent=2)}")

                            # Check for error in JSON response
                            if isinstance(output, dict) and not output.get('success', True):
                                error_msg = output.get('error', 'Unknown error')
                                logger.error(f"MexCLI returned error: {error_msg}")
                                raise MexManagerError(f"MexCLI error: {error_msg}")

                            return output
                        except json.JSONDecodeError as e:
                            # Still couldn't parse - try line-by-line as fallback
                            logger.debug(f"Filtered output still not valid JSON: {e}")

                    # Final fallback: Try from last line backwards to find valid JSON
                    for line in reversed(lines):
                        line = line.strip()
                        if line.startswith('{') or line.startswith('['):
                            try:
                                output = json.loads(line)
                                logger.info(f"MexCLI response (single line): {json.dumps(output, indent=2)}")

                                # Check for error in JSON response
                                if isinstance(output, dict) and not output.get('success', True):
                                    error_msg = output.get('error', 'Unknown error')
                                    logger.error(f"MexCLI returned error: {error_msg}")
                                    raise MexManagerError(f"MexCLI error: {error_msg}")

                                return output
                            except json.JSONDecodeError:
                                continue

                    # No valid JSON found anywhere
                    logger.error(f"Failed to parse any JSON from MexCLI output: {result.stdout}")
                    raise MexManagerError(f"Invalid JSON response from mexcli. Output: {result.stdout[:500]}")

            # If no stdout, check stderr
            if result.stderr:
                logger.error(f"MexCLI stderr output: {result.stderr}")
                raise MexManagerError(f"MexCLI error: {result.stderr}")

            # Return code non-zero without output
            if result.returncode != 0:
                logger.error(f"MexCLI failed with return code {result.returncode}")
                raise MexManagerError(f"MexCLI command failed with code {result.returncode}")

            # Empty but successful
            return {"success": True}

        except subprocess.SubprocessError as e:
            logger.error(f"Failed to execute mexcli: {e}")
            raise MexManagerError(f"Failed to execute mexcli: {e}")

    def open_project(self) -> Dict:
        """
        Open and validate MEX project.

        Returns:
            Dict with project information:
                - success: bool
                - projectPath: str
                - projectName: str
                - version: str
                - fighterCount: int
                - stageCount: int
        """
        return self._run_command("open", str(self.project_path))

    def get_info(self) -> Dict:
        """
        Get detailed project information.

        Returns:
            Dict with detailed project info including build info and counts
        """
        return self._run_command("info", str(self.project_path))

    def list_fighters(self) -> List[Dict]:
        """
        List all fighters in the project.

        Returns:
            List of fighter dicts with:
                - internalId: int
                - externalId: int
                - name: str
                - costumeCount: int
                - isMexFighter: bool
        """
        result = self._run_command("list-fighters", str(self.project_path))
        return result.get('fighters', [])

    def get_fighter_by_name(self, name: str) -> Optional[Dict]:
        """
        Get fighter info by name (case-insensitive).

        Args:
            name: Fighter name (e.g., "Fox", "Mario")

        Returns:
            Fighter dict or None if not found
        """
        fighters = self.list_fighters()
        for fighter in fighters:
            if fighter['name'].lower() == name.lower():
                return fighter
        return None

    def import_costume(self, fighter_name: str, zip_path: str) -> Dict:
        """
        Import costume ZIP file for a character.

        Args:
            fighter_name: Name of fighter (e.g., "Fox")
            zip_path: Path to costume ZIP file

        Returns:
            Dict with import results:
                - success: bool
                - fighter: str
                - fighterInternalId: int
                - costumesImported: int
                - totalCostumes: int
                - importLog: str
        """
        zip_path = Path(zip_path)
        if not zip_path.exists():
            raise MexManagerError(f"ZIP file not found: {zip_path}")

        return self._run_command(
            "import-costume",
            str(self.project_path),
            fighter_name,
            str(zip_path)
        )

    def remove_costume(self, fighter_name: str, costume_index: int) -> Dict:
        """
        Remove a costume from a fighter.

        Args:
            fighter_name: Name of fighter (e.g., "Fox")
            costume_index: Index of costume to remove (0-based)

        Returns:
            Dict with removal results:
                - success: bool
                - fighter: str
                - fighterInternalId: int
                - removedCostume: dict (index, name, fileName)
                - remainingCostumes: int
        """
        return self._run_command(
            "remove-costume",
            str(self.project_path),
            fighter_name,
            str(costume_index)
        )

    def save_project(self) -> Dict:
        """
        Save project changes.

        Returns:
            Dict with success status
        """
        return self._run_command("save", str(self.project_path))

    def export_iso(
        self,
        output_path: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        csp_compression: float = 1.0
    ) -> Dict:
        """
        Export modified ISO.

        Args:
            output_path: Path for output ISO file
            progress_callback: Optional callback function(percentage, message)
            csp_compression: CSP compression level (0.1-1.0, default 1.0)

        Returns:
            Dict with export results
        """
        cmd = [str(self.cli_path), "export", str(self.project_path), str(output_path), str(csp_compression)]

        try:
            # Run process with streaming output for progress
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self.cli_path.parent),
                bufsize=1  # Line buffered
            )

            final_result = None

            # Read output line by line for progress updates
            if process.stdout:
                for line in process.stdout:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                        status = data.get('status', '')

                        if status == 'progress' and progress_callback:
                            percentage = data.get('percentage', 0)
                            message = data.get('message', '')
                            progress_callback(percentage, message)
                        elif status in ('completed', 'error') or data.get('success') is not None:
                            final_result = data
                    except json.JSONDecodeError:
                        # Non-JSON output, ignore
                        pass

            process.wait()

            if process.returncode != 0:
                stderr = process.stderr.read() if process.stderr else ""
                raise MexManagerError(f"ISO export failed: {stderr}")

            return final_result or {"success": True, "outputPath": output_path}

        except subprocess.SubprocessError as e:
            raise MexManagerError(f"Failed to export ISO: {e}")

    def get_character_id(self, character_name: str) -> Optional[int]:
        """
        Convert character name to internal ID.

        Args:
            character_name: Character name (e.g., "Fox")

        Returns:
            Internal ID or None if not found
        """
        fighter = self.get_fighter_by_name(character_name)
        return fighter['internalId'] if fighter else None


# Character name mapping for convenience
DEFAULT_CHARACTERS = {
    "Mario": "PlMrNr",
    "Fox": "PlFxNr",
    "C. Falcon": "PlCaNr",
    "DK": "PlDkNr",
    "Kirby": "PlKbNr",
    "Bowser": "PlKpNr",
    "Link": "PlLkNr",
    "Sheik": "PlSkNr",
    "Ness": "PlNsNr",
    "Peach": "PlPeNr",
    "Popo": "PlPpNr",
    "Nana": "PlNnNr",
    "Pikachu": "PlPkNr",
    "Samus": "PlSmNr",
    "Yoshi": "PlYsNr",
    "Jigglypuff": "PlPrNr",
    "Mewtwo": "PlMtNr",
    "Luigi": "PlLgNr",
    "Marth": "PlMsNr",
    "Zelda": "PlZdNr",
    "Young Link": "PlClNr",
    "Dr. Mario": "PlDrNr",
    "Falco": "PlFcNr",
    "Pichu": "PlPcNr",
    "Mr. Game & Watch": "PlGwNr",
    "Ganondorf": "PlGnNr",
    "Roy": "PlFeNr"
}


if __name__ == "__main__":
    # Example usage
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python mex_bridge.py info")
        print("  python mex_bridge.py list")
        print("  python mex_bridge.py import <fighter> <zip>")
        sys.exit(1)

    # Initialize with default paths
    mex = MexManager(
        cli_path="utility/MexManager/MexCLI/bin/Release/net6.0/mexcli.exe",
        project_path="build/project.mexproj"
    )

    command = sys.argv[1].lower()

    if command == "info":
        info = mex.get_info()
        print(json.dumps(info, indent=2))

    elif command == "list":
        fighters = mex.list_fighters()
        for f in fighters:
            print(f"{f['name']:20} (ID: {f['internalId']:2}, Costumes: {f['costumeCount']:2})")

    elif command == "import" and len(sys.argv) >= 4:
        fighter = sys.argv[2]
        zip_path = sys.argv[3]
        result = mex.import_costume(fighter, zip_path)
        print(json.dumps(result, indent=2))

    else:
        print("Unknown command or missing arguments")
        sys.exit(1)
