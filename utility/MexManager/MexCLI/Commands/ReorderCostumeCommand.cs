using System.Text.Json;
using mexLib;
using mexLib.Types;

namespace MexCLI.Commands
{
    public static class ReorderCostumeCommand
    {
        public static int Execute(string[] args)
        {
            if (args.Length < 5)
            {
                Console.Error.WriteLine("Usage: mexcli reorder-costume <project.mexproj> <fighter_name_or_id> <from_index> <to_index>");
                return 1;
            }

            string projectPath = args[1];
            string fighterNameOrId = args[2];
            string fromIndexStr = args[3];
            string toIndexStr = args[4];

            // Parse indices
            if (!int.TryParse(fromIndexStr, out int fromIndex))
            {
                var errorOutput = new
                {
                    success = false,
                    error = $"Invalid from_index: {fromIndexStr}"
                };
                Console.WriteLine(JsonSerializer.Serialize(errorOutput, new JsonSerializerOptions { WriteIndented = true }));
                return 1;
            }

            if (!int.TryParse(toIndexStr, out int toIndex))
            {
                var errorOutput = new
                {
                    success = false,
                    error = $"Invalid to_index: {toIndexStr}"
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

            // Validate indices
            if (fromIndex < 0 || fromIndex >= fighter.Costumes.Count)
            {
                var errorOutput = new
                {
                    success = false,
                    error = $"From index out of range: {fromIndex} (fighter has {fighter.Costumes.Count} costumes)"
                };
                Console.WriteLine(JsonSerializer.Serialize(errorOutput, new JsonSerializerOptions { WriteIndented = true }));
                return 1;
            }

            if (toIndex < 0 || toIndex >= fighter.Costumes.Count)
            {
                var errorOutput = new
                {
                    success = false,
                    error = $"To index out of range: {toIndex} (fighter has {fighter.Costumes.Count} costumes)"
                };
                Console.WriteLine(JsonSerializer.Serialize(errorOutput, new JsonSerializerOptions { WriteIndented = true }));
                return 1;
            }

            // If indices are the same, nothing to do
            if (fromIndex == toIndex)
            {
                var output = new
                {
                    success = true,
                    message = "Indices are the same, no reordering needed",
                    fighter = fighter.Name
                };
                Console.WriteLine(JsonSerializer.Serialize(output, new JsonSerializerOptions { WriteIndented = true }));
                return 0;
            }

            // Reorder costumes
            try
            {
                // Swap costumes (same logic as FighterView.MoveCostume)
                (fighter.Costumes[fromIndex], fighter.Costumes[toIndex]) = (fighter.Costumes[toIndex], fighter.Costumes[fromIndex]);

                // Special handling for Kirby (fighter index 4) - also reorder Kirby hats
                if (fighterInternalId == 4)
                {
                    foreach (MexFighter f in workspace.Project.Fighters)
                    {
                        if (f.HasKirbyCostumes)
                        {
                            (f.KirbyCostumes[fromIndex], f.KirbyCostumes[toIndex]) = (f.KirbyCostumes[toIndex], f.KirbyCostumes[fromIndex]);
                        }
                    }
                }

                // Special handling for Ice Climbers - reorder paired fighter's costumes
                // Ice Climbers (Popo) is at index 9, Nana is at index 11
                if (fighterInternalId == 9 || fighterInternalId == 11)
                {
                    // Find the paired fighter (if reordering Popo, find Nana; if reordering Nana, find Popo)
                    int pairedFighterId = (fighterInternalId == 9) ? 11 : 9;

                    if (pairedFighterId >= 0 && pairedFighterId < workspace.Project.Fighters.Count)
                    {
                        MexFighter pairedFighter = workspace.Project.Fighters[pairedFighterId];

                        // Only swap if both indices are valid for the paired fighter
                        if (fromIndex < pairedFighter.Costumes.Count && toIndex < pairedFighter.Costumes.Count)
                        {
                            (pairedFighter.Costumes[fromIndex], pairedFighter.Costumes[toIndex]) =
                                (pairedFighter.Costumes[toIndex], pairedFighter.Costumes[fromIndex]);
                        }
                    }
                }

                // Save the workspace
                workspace.Save(null);

                // Build updated costume list
                var costumes = new List<object>();
                for (int i = 0; i < fighter.Costumes.Count; i++)
                {
                    var costume = fighter.Costumes[i];
                    costumes.Add(new
                    {
                        index = i,
                        name = costume.Name,
                        fileName = costume.File.FileName,
                        colorSmashGroup = costume.ColorSmashGroup,
                        hasCSP = !string.IsNullOrEmpty(costume.CSP),
                        hasIcon = !string.IsNullOrEmpty(costume.Icon),
                        csp = costume.CSP,
                        icon = costume.Icon
                    });
                }

                var output = new
                {
                    success = true,
                    fighter = fighter.Name,
                    fighterInternalId = fighterInternalId,
                    reordered = new
                    {
                        fromIndex = fromIndex,
                        toIndex = toIndex
                    },
                    costumes = costumes
                };

                Console.WriteLine(JsonSerializer.Serialize(output, new JsonSerializerOptions { WriteIndented = true }));
                return 0;
            }
            catch (Exception ex)
            {
                var errorOutput = new
                {
                    success = false,
                    error = $"Failed to reorder costume: {ex.Message}",
                    stackTrace = ex.StackTrace
                };
                Console.WriteLine(JsonSerializer.Serialize(errorOutput, new JsonSerializerOptions { WriteIndented = true }));
                return 1;
            }
        }
    }
}
