using System.Text.Json;
using mexLib;
using mexLib.Types;

namespace MexCLI.Commands
{
    public static class RemoveCostumeCommand
    {
        public static int Execute(string[] args)
        {
            if (args.Length < 4)
            {
                Console.Error.WriteLine("Usage: mexcli remove-costume <project.mexproj> <fighter_name_or_id> <costume_index>");
                return 1;
            }

            string projectPath = args[1];
            string fighterNameOrId = args[2];
            string costumeIndexStr = args[3];

            // Parse costume index
            if (!int.TryParse(costumeIndexStr, out int costumeIndex))
            {
                var errorOutput = new
                {
                    success = false,
                    error = $"Invalid costume index: {costumeIndexStr}"
                };
                Console.WriteLine(JsonSerializer.Serialize(errorOutput, new JsonSerializerOptions { WriteIndented = true }));
                return 1;
            }

            // Open workspace
            MexWorkspace? workspace;
            string error;
            bool isoMissing;

            bool success = MexWorkspace.TryOpenWorkspace(projectPath, out workspace, out error, out isoMissing);

            if (!success || workspace == null)
            {
                var errorOutput = new
                {
                    success = false,
                    error = error
                };
                Console.WriteLine(JsonSerializer.Serialize(errorOutput, new JsonSerializerOptions { WriteIndented = true }));
                return 1;
            }

            // Find fighter by name or ID
            MexFighter? fighter = null;
            int fighterInternalId = -1;

            // Try parsing as internal ID first
            if (int.TryParse(fighterNameOrId, out int parsedId))
            {
                if (parsedId >= 0 && parsedId < workspace.Project.Fighters.Count)
                {
                    fighter = workspace.Project.Fighters[parsedId];
                    fighterInternalId = parsedId;
                }
            }

            // If not found, search by name (case-insensitive)
            if (fighter == null)
            {
                for (int i = 0; i < workspace.Project.Fighters.Count; i++)
                {
                    if (workspace.Project.Fighters[i].Name.Equals(fighterNameOrId, StringComparison.OrdinalIgnoreCase))
                    {
                        fighter = workspace.Project.Fighters[i];
                        fighterInternalId = i;
                        break;
                    }
                }
            }

            if (fighter == null)
            {
                var errorOutput = new
                {
                    success = false,
                    error = $"Fighter not found: {fighterNameOrId}"
                };
                Console.WriteLine(JsonSerializer.Serialize(errorOutput, new JsonSerializerOptions { WriteIndented = true }));
                return 1;
            }

            // Validate costume index
            if (costumeIndex < 0 || costumeIndex >= fighter.Costumes.Count)
            {
                var errorOutput = new
                {
                    success = false,
                    error = $"Costume index out of range: {costumeIndex} (fighter has {fighter.Costumes.Count} costumes)"
                };
                Console.WriteLine(JsonSerializer.Serialize(errorOutput, new JsonSerializerOptions { WriteIndented = true }));
                return 1;
            }

            // Remove costume
            try
            {
                var removedCostume = fighter.Costumes[costumeIndex];
                string removedCostumeName = removedCostume.Name;
                string removedCostumeFile = removedCostume.File.FileName;

                fighter.Costumes.RemoveAt(costumeIndex);

                // Save the workspace
                workspace.Save(null);

                var output = new
                {
                    success = true,
                    fighter = fighter.Name,
                    fighterInternalId = fighterInternalId,
                    removedCostume = new
                    {
                        index = costumeIndex,
                        name = removedCostumeName,
                        fileName = removedCostumeFile
                    },
                    remainingCostumes = fighter.Costumes.Count
                };

                Console.WriteLine(JsonSerializer.Serialize(output, new JsonSerializerOptions { WriteIndented = true }));
                return 0;
            }
            catch (Exception ex)
            {
                var errorOutput = new
                {
                    success = false,
                    error = $"Failed to remove costume: {ex.Message}",
                    stackTrace = ex.StackTrace
                };
                Console.WriteLine(JsonSerializer.Serialize(errorOutput, new JsonSerializerOptions { WriteIndented = true }));
                return 1;
            }
        }
    }
}
