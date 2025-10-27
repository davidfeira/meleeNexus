using System.Text.Json;
using mexLib;
using mexLib.Types;

namespace MexCLI
{
    class Program
    {
        static int Main(string[] args)
        {
            try
            {
                if (args.Length == 0)
                {
                    PrintUsage();
                    return 1;
                }

                string command = args[0].ToLower();

                switch (command)
                {
                    case "open":
                        return Commands.OpenCommand.Execute(args);
                    case "list-fighters":
                        return Commands.ListFightersCommand.Execute(args);
                    case "get-costumes":
                        return Commands.GetFighterCostumesCommand.Execute(args);
                    case "import-costume":
                        return Commands.ImportCostumeCommand.Execute(args);
                    case "remove-costume":
                        return Commands.RemoveCostumeCommand.Execute(args);
                    case "save":
                        return Commands.SaveCommand.Execute(args);
                    case "export":
                        return Commands.ExportCommand.Execute(args);
                    case "info":
                        return Commands.InfoCommand.Execute(args);
                    case "help":
                    case "--help":
                    case "-h":
                        PrintUsage();
                        return 0;
                    default:
                        Console.Error.WriteLine($"Unknown command: {command}");
                        PrintUsage();
                        return 1;
                }
            }
            catch (Exception ex)
            {
                var errorOutput = new
                {
                    success = false,
                    error = ex.Message,
                    stackTrace = ex.StackTrace
                };
                Console.Error.WriteLine(JsonSerializer.Serialize(errorOutput, new JsonSerializerOptions { WriteIndented = true }));
                return 1;
            }
        }

        static void PrintUsage()
        {
            Console.WriteLine("MexCLI - Command-line interface for MexManager");
            Console.WriteLine();
            Console.WriteLine("Usage:");
            Console.WriteLine("  mexcli <command> [options]");
            Console.WriteLine();
            Console.WriteLine("Commands:");
            Console.WriteLine("  open <project.mexproj>                     - Open and validate project");
            Console.WriteLine("  list-fighters <project.mexproj>            - List all fighters");
            Console.WriteLine("  get-costumes <project> <fighter>           - Get costumes for fighter");
            Console.WriteLine("  import-costume <project> <fighter> <zip>   - Import costume ZIP");
            Console.WriteLine("  remove-costume <project> <fighter> <index> - Remove costume by index");
            Console.WriteLine("  save <project.mexproj>                     - Save project changes");
            Console.WriteLine("  export <project.mexproj> <output.iso>      - Export ISO");
            Console.WriteLine("  info <project.mexproj>                     - Get project information");
            Console.WriteLine("  help                                       - Show this help message");
        }
    }
}
