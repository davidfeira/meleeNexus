using mexLib.Types;
using System;
using System.IO;

namespace mexLib.Installer
{
    /// <summary>
    /// Installer for Dynamic Alternate Stages (DAS) framework
    /// </summary>
    public class DASInstaller
    {
        /// <summary>
        /// Stage code to display name mapping
        /// </summary>
        public static readonly Dictionary<string, string> StageCodeToName = new()
        {
            { "GrNBa", "Battlefield" },
            { "GrNLa", "Final Destination" },
            { "GrSt", "Yoshi's Story" },
            { "GrOp", "Dreamland" },
            { "GrPs", "Pokemon Stadium" },
            { "GrIz", "Fountain of Dreams" }
        };

        /// <summary>
        /// Check if DAS framework is installed
        /// </summary>
        public static bool IsInstalled(MexWorkspace workspace)
        {
            // Check if any of the DAS loader files exist
            foreach (string stageCode in StageCodeToName.Keys)
            {
                string loaderPath = workspace.GetFilePath($"{stageCode}.dat");
                string folderPath = workspace.GetFilePath(stageCode);

                if (File.Exists(loaderPath) && Directory.Exists(folderPath))
                    return true;
            }

            return false;
        }

        /// <summary>
        /// Install DAS framework into the workspace
        /// </summary>
        public static MexInstallerError? Install(MexWorkspace workspace)
        {
            try
            {
                // Find the DAS framework folder
                string dasFrameworkPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "DynamicAlternateStages");

                if (!Directory.Exists(dasFrameworkPath))
                {
                    // Try relative to workspace
                    dasFrameworkPath = Path.GetFullPath(Path.Combine(workspace.WorkingDirectory, "..", "..", "utility", "DynamicAlternateStages"));
                }

                if (!Directory.Exists(dasFrameworkPath))
                {
                    return new MexInstallerError($"DAS framework not found at expected location: {dasFrameworkPath}");
                }

                // Install each stage
                foreach (var kvp in StageCodeToName)
                {
                    string stageCode = kvp.Key;

                    // Copy loader .dat file
                    string sourceLoaderPath = Path.Combine(dasFrameworkPath, $"{stageCode}.dat");
                    string destLoaderPath = workspace.GetFilePath($"{stageCode}.dat");

                    if (File.Exists(sourceLoaderPath))
                    {
                        // Backup existing stage file if it exists
                        if (File.Exists(destLoaderPath))
                        {
                            string backupPath = workspace.GetFilePath($"{stageCode}_vanilla.dat");
                            if (!File.Exists(backupPath))
                            {
                                File.Copy(destLoaderPath, backupPath, true);
                            }
                        }

                        File.Copy(sourceLoaderPath, destLoaderPath, true);
                    }
                    else
                    {
                        return new MexInstallerError($"DAS loader file not found: {sourceLoaderPath}");
                    }

                    // Create stage folder
                    string stageFolderPath = workspace.GetFilePath(stageCode);
                    Directory.CreateDirectory(stageFolderPath);

                    // Copy vanilla stage file into folder if backup exists
                    string vanillaBackupPath = workspace.GetFilePath($"{stageCode}_vanilla.dat");
                    if (File.Exists(vanillaBackupPath))
                    {
                        string vanillaInFolderPath = Path.Combine(stageFolderPath, $"{stageCode}_00.dat");
                        File.Copy(vanillaBackupPath, vanillaInFolderPath, true);
                    }
                }

                return null; // Success
            }
            catch (Exception ex)
            {
                return new MexInstallerError($"Error installing DAS framework: {ex.Message}");
            }
        }

        /// <summary>
        /// Get the folder path for a specific stage code
        /// </summary>
        public static string GetStageFolderPath(MexWorkspace workspace, string stageCode)
        {
            return workspace.GetFilePath(stageCode);
        }

        /// <summary>
        /// Get next available DAS file name for a stage
        /// </summary>
        public static string GetNextDASFileName(MexWorkspace workspace, string stageCode)
        {
            string stageFolderPath = GetStageFolderPath(workspace, stageCode);

            if (!Directory.Exists(stageFolderPath))
                return $"{stageCode}_00.dat";

            int index = 0;
            while (true)
            {
                string fileName = $"{stageCode}_{index:D2}.dat";
                string filePath = Path.Combine(stageFolderPath, fileName);

                if (!File.Exists(filePath))
                    return fileName;

                index++;

                if (index > 99)
                    throw new InvalidOperationException($"Maximum number of DAS stages reached for {stageCode}");
            }
        }

        /// <summary>
        /// Install a DAS stage variant
        /// </summary>
        public static MexInstallerError? InstallStageVariant(MexWorkspace workspace, string stageCode, MexDASStage dasStage)
        {
            try
            {
                if (dasStage.FileName == null)
                    return new MexInstallerError("DAS stage has no file name");

                // Get source file
                string sourceFilePath = workspace.GetFilePath(dasStage.FileName);
                if (!File.Exists(sourceFilePath))
                    return new MexInstallerError($"DAS stage file not found: {sourceFilePath}");

                // Get destination folder
                string stageFolderPath = GetStageFolderPath(workspace, stageCode);
                if (!Directory.Exists(stageFolderPath))
                    return new MexInstallerError($"DAS framework not installed for {stageCode}");

                // Get next available file name
                string newFileName = GetNextDASFileName(workspace, stageCode);
                string destFilePath = Path.Combine(stageFolderPath, newFileName);

                // Copy file
                File.Copy(sourceFilePath, destFilePath, false);

                // Update DAS stage file name to the new location
                // Note: We keep the original in files/ and copy to GrXX folder

                return null; // Success
            }
            catch (Exception ex)
            {
                return new MexInstallerError($"Error installing DAS stage variant: {ex.Message}");
            }
        }

        /// <summary>
        /// Uninstall a DAS stage variant
        /// </summary>
        public static MexInstallerError? UninstallStageVariant(MexWorkspace workspace, string stageCode, string fileName)
        {
            try
            {
                string stageFolderPath = GetStageFolderPath(workspace, stageCode);
                string filePath = Path.Combine(stageFolderPath, fileName);

                if (File.Exists(filePath))
                {
                    File.Delete(filePath);
                }

                return null; // Success
            }
            catch (Exception ex)
            {
                return new MexInstallerError($"Error uninstalling DAS stage variant: {ex.Message}");
            }
        }
    }
}
