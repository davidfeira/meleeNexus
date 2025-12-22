using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using SixLabors.ImageSharp.Processing;
using SixLabors.ImageSharp.Formats.Png;
using HSDRawViewer.Rendering;
using HSDRawViewer.Rendering.Models;
using HSDRawViewer.Tools.Animation;
using HSDRawViewer.Converters.Animation;
using HSDRawViewer.GUI.Controls.JObjEditor;
namespace HSDRawViewer
{
    static class Program
    {
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        static extern bool AllocConsole();

        private static System.IO.StreamWriter logFile;

        /// <summary>
        /// The main entry point for the application.
        /// </summary>
        [STAThread]
        static void Main(string[] args)
        {
            // Allocate console for output when running from command line
            if (args.Length >= 2 && args[0] == "--csp")
            {
                AllocConsole();
                // Redirect Console output to both console and file
                logFile = new System.IO.StreamWriter("csp_debug.log", false);
                logFile.AutoFlush = true;
                var multiWriter = new MultiTextWriter(Console.Out, logFile);
                Console.SetOut(multiWriter);
            }

            Console.WriteLine($"Main called with {args.Length} arguments");
            for (int i = 0; i < args.Length; i++)
            {
                Console.WriteLine($"Arg[{i}]: {args[i]}");
            }

            // Check for CLI CSP generation mode
            if (args.Length >= 2 && args[0] == "--csp")
            {
                Console.WriteLine("CSP mode detected, calling RunCSPGeneration");
                RunCSPGeneration(args);
                Console.WriteLine("RunCSPGeneration returned");
                logFile?.Close();
                return;
            }

            // Check for streaming mode
            if (args.Length >= 3 && args[0] == "--stream")
            {
                AllocConsole();
                Console.WriteLine("Streaming mode detected");
                RunStreamingServer(args);
                return;
            }

            Console.WriteLine("Starting normal GUI mode");
            // Normal GUI mode
            Application.EnableVisualStyles();
            Application.SetHighDpiMode(HighDpiMode.SystemAware);
            Application.SetCompatibleTextRenderingDefault(false);
            Thread.CurrentThread.CurrentCulture = System.Globalization.CultureInfo.InvariantCulture;
            PluginManager.Init();
            Rendering.OpenTKResources.Init();
            MainForm.Init();
            ApplicationSettings.Init();
            if (args.Length > 0)
                MainForm.Instance.OpenFile(args[0]);
            Application.Run(MainForm.Instance);
        }

        static void RunStreamingServer(string[] args)
        {
            try
            {
                if (args.Length < 3)
                {
                    Console.WriteLine("Usage: HSDRawViewer.exe --stream <port> <dat_file> [logs_path] [scene_file]");
                    Console.WriteLine("Example: HSDRawViewer.exe --stream 8765 PlFxNr.dat C:\\projects\\logs scene.yml");
                    return;
                }

                int port = int.Parse(args[1]);
                string datFile = args[2];
                string logsPath = args.Length >= 4 ? args[3] : null;
                string sceneFile = args.Length >= 5 ? args[4] : null;

                Console.WriteLine($"Starting streaming server on port {port}...");
                Console.WriteLine($"DAT file: {datFile}");
                if (logsPath != null)
                    Console.WriteLine($"Logs path: {logsPath}");
                if (sceneFile != null)
                    Console.WriteLine($"Scene file: {sceneFile}");

                using var server = new StreamingServer(port, logsPath);

                // Handle Ctrl+C
                Console.CancelKeyPress += (sender, e) =>
                {
                    e.Cancel = true;
                    Console.WriteLine("Shutdown requested...");
                    server.Stop();
                };

                // Run server (blocking)
                server.StartAsync(datFile, sceneFile).GetAwaiter().GetResult();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Streaming server error: {ex.Message}");
                Console.WriteLine($"Stack trace: {ex.StackTrace}");
                Environment.Exit(1);
            }
        }

        static void RunCSPGeneration(string[] args)
        {
            try
            {
                Console.WriteLine("Starting CSP generation...");

                if (args.Length < 3)
                {
                    Console.WriteLine("Usage: HSDRawViewer.exe --csp <dat_file> <output_file> [anim_file] [camera_yml]");
                    Console.WriteLine("Example: HSDRawViewer.exe --csp PlKpNr.dat bowser_csp.png cspfinal.anim cspfinal.yml");
                    return;
                }

                string datFile = args[1];
                string outputFile = args[2];
                string animFile = args.Length > 3 ? args[3] : null;
                string cameraFile = args.Length > 4 ? args[4] : null;

                // Detect if we're using a scene file by filename
                // If the yml file is named "scene.yml", use scene mode
                bool useSceneFile = false;
                string sceneFileToCheck = cameraFile ?? animFile;

                if (!string.IsNullOrEmpty(sceneFileToCheck) && System.IO.File.Exists(sceneFileToCheck))
                {
                    string filename = System.IO.Path.GetFileName(sceneFileToCheck).ToLower();
                    if (filename == "scene.yml")
                    {
                        useSceneFile = true;
                        // If scene file was passed as animFile (arg[3]), move it to cameraFile
                        if (cameraFile == null && animFile != null)
                        {
                            cameraFile = animFile;
                            animFile = null;  // Clear animFile since it's actually a scene file
                        }
                        Console.WriteLine("*** SCENE FILE DETECTED (scene.yml) ***");
                    }
                }

                Console.WriteLine($"Generating CSP for: {datFile}");
                Console.WriteLine($"Output: {outputFile}");
                Console.WriteLine($"Scene file mode: {useSceneFile}");

                // Initialize core systems (no GUI)
                Thread.CurrentThread.CurrentCulture = System.Globalization.CultureInfo.InvariantCulture;
                PluginManager.Init();
                ApplicationSettings.Init();

                // Load DAT file
                Console.WriteLine($"Loading DAT file: {datFile}");
                if (!System.IO.File.Exists(datFile))
                {
                    throw new System.IO.FileNotFoundException($"DAT file not found: {datFile}");
                }

                var rawFile = new HSDRaw.HSDRawFile();
                rawFile.Open(datFile);

                // Initialize headless OpenGL context using GLControl approach
                Console.WriteLine("Setting up headless OpenGL context...");

                // Use the EXACT same approach as the working GUI - create actual ViewportControl
                Console.WriteLine("Creating ViewportControl with loaded DAT...");

                // Initialize MainForm like normal GUI mode (this sets up all the renderers properly)
                MainForm.Init();
                MainForm.Instance.OpenFile(datFile);

                // Wait for file to load
                System.Threading.Thread.Sleep(500);

                // Find and select the character JOBJ node (like PlyPichu5K_Share_joint)
                Console.WriteLine("Looking for character JOBJ to render...");
                DataNode characterJobjNode = null;

                // Search through all roots for character JOBJ nodes
                foreach (var root in rawFile.Roots)
                {
                    Console.WriteLine($"Checking root: {root.Name} (Type: {root.Data?.GetType().Name})");

                    // Look for JOBJ nodes with character-like names
                    if (root.Data is HSDRaw.Common.HSD_JOBJ &&
                        (root.Name.Contains("Share_joint") || root.Name.Contains("_joint") || root.Name.Contains("Ply")))
                    {
                        Console.WriteLine($"Found character JOBJ: {root.Name}");
                        characterJobjNode = new DataNode(root.Name, root.Data, root: root);
                        break;
                    }
                }

                if (characterJobjNode != null)
                {
                    Console.WriteLine($"Selecting character JOBJ: {characterJobjNode.Text}");
                    MainForm.SelectedDataNode = characterJobjNode;
                    MainForm.Instance.OpenEditor(); // This triggers the viewport rendering
                }
                else
                {
                    Console.WriteLine("No character JOBJ found - trying first JOBJ as fallback");
                    // Fallback to first JOBJ found
                    foreach (var root in rawFile.Roots)
                    {
                        if (root.Data is HSDRaw.Common.HSD_JOBJ)
                        {
                            Console.WriteLine($"Using fallback JOBJ: {root.Name}");
                            characterJobjNode = new DataNode(root.Name, root.Data, root: root);
                            MainForm.SelectedDataNode = characterJobjNode;
                            MainForm.Instance.OpenEditor();
                            break;
                        }
                    }
                }

                // Wait for editor to open
                System.Threading.Thread.Sleep(1000);

                // Create a ViewportControl directly
                var viewport = new HSDRawViewer.GUI.ViewportControl();

                // Manually create the RenderJObj like JObjEditorNew does
                HSDRawViewer.Rendering.Models.RenderJObj renderJObj = null;
                if (characterJobjNode != null && characterJobjNode.Accessor is HSDRaw.Common.HSD_JOBJ jobj)
                {
                    Console.WriteLine("Creating RenderJObj...");
                    renderJObj = new HSDRawViewer.Rendering.Models.RenderJObj(jobj);
                    Console.WriteLine($"RenderJObj created. DOBJs loaded: {renderJObj.DObjCount}");

                    // Note: We'll hide bones and nodes after loading YAML settings

                    // Load scene file OR separate animation file
                    if (useSceneFile && !string.IsNullOrEmpty(cameraFile))
                    {
                        Console.WriteLine($"=== LOADING SCENE FILE: {cameraFile} ===");
                        try
                        {
                            // Use SceneSettings deserializer (same as GUI)
                            var sceneSettings = SceneSettings.Deserialize(cameraFile);
                            Console.WriteLine("Scene file deserialized successfully");

                            // Apply animation from scene
                            if (sceneSettings.Animation != null)
                            {
                                Console.WriteLine($"Loading animation from scene file (FrameCount: {sceneSettings.Animation.FrameCount})");
                                renderJObj.LoadAnimation(sceneSettings.Animation, null, null);
                                Console.WriteLine("Animation loaded from scene");
                            }
                            else
                            {
                                Console.WriteLine("WARNING: Scene file has no animation data");
                            }

                            Console.WriteLine("=== SCENE FILE LOADED ===");
                        }
                        catch (Exception ex)
                        {
                            Console.WriteLine($"FAILED to load scene file: {ex.Message}");
                            Console.WriteLine($"Stack trace: {ex.StackTrace}");
                            throw; // Re-throw since this is required for Ganondorf
                        }
                    }
                    else if (!string.IsNullOrEmpty(animFile) && System.IO.File.Exists(animFile))
                    {
                        // OLD PATH: Load animation from separate .anim file
                        Console.WriteLine($"Loading animation file: {animFile}");
                        try
                        {
                            // Use the same animation loader as the GUI
                            var jointMap = new JointMap(); // Use empty joint map for basic animation loading
                            var animManager = JointAnimationLoader.LoadJointAnimFromFile(jointMap, animFile);

                            if (animManager != null)
                            {
                                Console.WriteLine("Animation loaded successfully");
                                renderJObj.LoadAnimation(animManager, null, null);
                            }
                            else
                            {
                                Console.WriteLine("Failed to load animation - loader returned null");
                            }
                        }
                        catch (Exception ex)
                        {
                            Console.WriteLine($"Failed to load animation: {ex.Message}");
                        }
                    }

                    // Create a simple drawable wrapper that calls RenderJObj.Render
                    var drawable = new SimpleJObjDrawable(renderJObj);

                    // Add the drawable to the viewport
                    Console.WriteLine("Adding drawable to viewport...");
                    viewport.AddRenderer(drawable);
                }

                // Create a form to host the viewport (hidden)
                using (var form = new Form())
                {
                    form.WindowState = FormWindowState.Minimized;
                    form.ShowInTaskbar = false;
                    viewport.Dock = DockStyle.Fill;
                    form.Controls.Add(viewport);
                    form.Show();

                    // Wait for everything to initialize
                    System.Threading.Thread.Sleep(1000);

                    // Enable CSP mode exactly like the GUI
                    Console.WriteLine("Enabling CSP mode...");
                    viewport.CSPMode = true;

                    // Disable background for transparent CSP
                    Console.WriteLine("Disabling background for transparency...");
                    viewport.EnableBack = false;

                    Console.WriteLine("*** TESTING: NEW CODE IS RUNNING ***");

                    // Load camera settings if provided
                    Console.WriteLine($"Checking camera file: '{cameraFile}'");
                    Console.WriteLine($"File exists: {System.IO.File.Exists(cameraFile)}");
                    var hiddenNodes = new List<int>();

                    // Lighting settings variables (declared here for proper scope)
                    float lightX = 30, lightY = 30, lightZ = 80;
                    float ambientPower = 0.35f, ambientR = 255, ambientG = 255, ambientB = 255;
                    float diffusePower = 1.2f, diffuseR = 255, diffuseG = 255, diffuseB = 255;
                    bool hasLightingSettings = false;
                    float animFrame = -1; // -1 means not set

                    // Load settings from scene file if using scene mode
                    if (useSceneFile && !string.IsNullOrEmpty(cameraFile) && System.IO.File.Exists(cameraFile))
                    {
                        Console.WriteLine("=== LOADING CAMERA/SETTINGS FROM SCENE FILE ===");
                        try
                        {
                            var sceneSettings = SceneSettings.Deserialize(cameraFile);

                            // Apply camera settings
                            if (sceneSettings.Camera != null)
                            {
                                viewport.Camera = sceneSettings.Camera;
                                Console.WriteLine("Camera loaded from scene file");
                            }

                            // Apply display settings
                            if (sceneSettings.Settings != null)
                            {
                                renderJObj._settings = sceneSettings.Settings;
                                Console.WriteLine("Render settings loaded from scene file");
                            }

                            // Apply frame
                            animFrame = sceneSettings.Frame;
                            Console.WriteLine($"Frame from scene: {animFrame}");

                            // Apply hidden nodes
                            if (sceneSettings.HiddenNodes != null && sceneSettings.HiddenNodes.Length > 0)
                            {
                                hiddenNodes.AddRange(sceneSettings.HiddenNodes);
                                Console.WriteLine($"Hidden nodes from scene: {hiddenNodes.Count}");
                            }

                            Console.WriteLine("=== SCENE CAMERA/SETTINGS LOADED ===");
                        }
                        catch (Exception ex)
                        {
                            Console.WriteLine($"FAILED to load camera/settings from scene: {ex.Message}");
                            Console.WriteLine($"Stack trace: {ex.StackTrace}");
                            throw; // Re-throw since this is required for Ganondorf
                        }
                    }
                    else if (!useSceneFile && !string.IsNullOrEmpty(cameraFile) && System.IO.File.Exists(cameraFile))
                    {
                        Console.WriteLine($"Loading camera settings from: {cameraFile}");
                        try
                        {
                            Console.WriteLine("*** DEBUG: Starting YAML parsing with hiddenNodes support ***");
                            var lines = System.IO.File.ReadAllLines(cameraFile);
                            bool parsingHiddenNodes = false;

                            Console.WriteLine($"Parsing YAML file with {lines.Length} lines...");
                            foreach (var line in lines)
                            {
                                var trimmedLine = line.Trim();
                                Console.WriteLine($"Processing line: '{trimmedLine}'");
                                if (trimmedLine.StartsWith("frame:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(6).Trim(), out float frame))
                                    {
                                        animFrame = frame;
                                        Console.WriteLine($"Found animation frame setting: {animFrame}");
                                    }
                                }
                                else if (trimmedLine.StartsWith("x:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(2).Trim(), out float x))
                                        viewport.Camera.X = x;
                                }
                                else if (trimmedLine.StartsWith("y:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(2).Trim(), out float y))
                                        viewport.Camera.Y = y;
                                }
                                else if (trimmedLine.StartsWith("z:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(2).Trim(), out float z))
                                        viewport.Camera.Z = z;
                                }
                                else if (trimmedLine.StartsWith("scale:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(6).Trim(), out float scale))
                                        viewport.Camera.Scale = scale;
                                }
                                else if (trimmedLine.StartsWith("fovRadians:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(11).Trim(), out float fov))
                                        viewport.Camera.FovRadians = fov;
                                }
                                else if (trimmedLine.StartsWith("rotationXRadians:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(17).Trim(), out float rotX))
                                        viewport.Camera.RotationXRadians = rotX;
                                }
                                else if (trimmedLine.StartsWith("rotationYRadians:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(17).Trim(), out float rotY))
                                        viewport.Camera.RotationYRadians = rotY;
                                }
                                else if (trimmedLine.StartsWith("farClipPlane:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(13).Trim(), out float farClip))
                                        viewport.Camera.FarClipPlane = farClip;
                                }
                                else if (trimmedLine.StartsWith("nearClipPlane:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(14).Trim(), out float nearClip))
                                        viewport.Camera.NearClipPlane = nearClip;
                                }
                                else if (trimmedLine.StartsWith("hiddenNodes:"))
                                {
                                    parsingHiddenNodes = true;
                                    Console.WriteLine("Found hiddenNodes section in YAML");
                                }
                                else if (parsingHiddenNodes && trimmedLine.StartsWith("- "))
                                {
                                    if (int.TryParse(trimmedLine.Substring(2).Trim(), out int nodeIndex))
                                    {
                                        hiddenNodes.Add(nodeIndex);
                                        Console.WriteLine($"Added node {nodeIndex} to hidden list");
                                    }
                                }
                                else if (parsingHiddenNodes && !string.IsNullOrWhiteSpace(trimmedLine) && !trimmedLine.StartsWith(" "))
                                {
                                    parsingHiddenNodes = false;
                                }
                                // Parse lighting settings
                                else if (trimmedLine.StartsWith("lightX:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(7).Trim(), out float val))
                                    {
                                        lightX = val;
                                        hasLightingSettings = true;
                                    }
                                }
                                else if (trimmedLine.StartsWith("lightY:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(7).Trim(), out float val))
                                    {
                                        lightY = val;
                                        hasLightingSettings = true;
                                    }
                                }
                                else if (trimmedLine.StartsWith("lightZ:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(7).Trim(), out float val))
                                    {
                                        lightZ = val;
                                        hasLightingSettings = true;
                                    }
                                }
                                else if (trimmedLine.StartsWith("ambientPower:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(13).Trim(), out float val))
                                    {
                                        ambientPower = val;
                                        hasLightingSettings = true;
                                    }
                                }
                                else if (trimmedLine.StartsWith("ambientR:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(9).Trim(), out float val))
                                    {
                                        ambientR = val;
                                        hasLightingSettings = true;
                                    }
                                }
                                else if (trimmedLine.StartsWith("ambientG:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(9).Trim(), out float val))
                                    {
                                        ambientG = val;
                                        hasLightingSettings = true;
                                    }
                                }
                                else if (trimmedLine.StartsWith("ambientB:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(9).Trim(), out float val))
                                    {
                                        ambientB = val;
                                        hasLightingSettings = true;
                                    }
                                }
                                else if (trimmedLine.StartsWith("diffusePower:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(13).Trim(), out float val))
                                    {
                                        diffusePower = val;
                                        hasLightingSettings = true;
                                    }
                                }
                                else if (trimmedLine.StartsWith("diffuseR:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(9).Trim(), out float val))
                                    {
                                        diffuseR = val;
                                        hasLightingSettings = true;
                                    }
                                }
                                else if (trimmedLine.StartsWith("diffuseG:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(9).Trim(), out float val))
                                    {
                                        diffuseG = val;
                                        hasLightingSettings = true;
                                    }
                                }
                                else if (trimmedLine.StartsWith("diffuseB:"))
                                {
                                    if (float.TryParse(trimmedLine.Substring(9).Trim(), out float val))
                                    {
                                        diffuseB = val;
                                        hasLightingSettings = true;
                                    }
                                }
                            }
                            Console.WriteLine("Camera settings loaded successfully");
                            Console.WriteLine($"Found {hiddenNodes.Count} nodes to hide: [{string.Join(", ", hiddenNodes)}]");

                        }
                        catch (Exception ex)
                        {
                            Console.WriteLine($"Failed to load camera settings: {ex.Message}");
                            Console.WriteLine($"Stack trace: {ex.StackTrace}");
                        }

                        // Now hide bones and apply settings after YAML is loaded
                        Console.WriteLine("Applying YAML settings...");
                        if (renderJObj != null)
                        {
                            renderJObj._settings.RenderBones = false;
                            // Ensure we're using Visible render mode so hidden objects are respected
                            renderJObj._settings.RenderObjects = HSDRawViewer.Rendering.Models.ObjectRenderMode.Visible;
                            Console.WriteLine($"Set render mode to: {renderJObj._settings.RenderObjects}");

                            // Apply animation frame if found in YAML
                            if (animFrame >= 0)
                            {
                                Console.WriteLine($"Setting animation to frame: {animFrame}");
                                renderJObj.RequestAnimationUpdate(HSDRawViewer.Rendering.Models.FrameFlags.All, animFrame);
                            }

                            // Apply lighting settings if found in YAML
                            if (hasLightingSettings)
                            {
                                Console.WriteLine("Applying custom lighting settings...");
                                ApplyLightingSettings(renderJObj, lightX, lightY, lightZ, ambientPower, ambientR, ambientG, ambientB, diffusePower, diffuseR, diffuseG, diffuseB);
                            }
                        }

                        // Note: Hidden nodes will be applied after first render when DOBJs are loaded
                    }

                    // Check if the viewport has any drawables loaded
                    Console.WriteLine("Checking viewport drawable count...");

                    // Force a render to make sure everything is loaded
                    Console.WriteLine("Forcing viewport render...");
                    viewport.Render();

                    // Now check if DOBJs are loaded and apply hiding after first render
                    if (renderJObj != null)
                    {
                        Console.WriteLine($"After first render - DOBJs loaded: {renderJObj.DObjCount}");

                        // Apply hidden nodes if any were specified (moved here after render)
                        if (hiddenNodes.Count > 0)
                        {
                            Console.WriteLine($"Applying hidden nodes after render to {hiddenNodes.Count} JOBJ indices...");
                            ApplyHiddenNodes(characterJobjNode, hiddenNodes, renderJObj);

                            // Force another render to apply the visibility changes
                            Console.WriteLine("Forcing second render to apply visibility changes...");
                            viewport.Render();
                        }
                    }

                    // Set up the screenshot callback to capture the output
                    string actualOutputFile = System.IO.Path.GetFullPath(outputFile);
                    bool screenshotTaken = false;

                    viewport.ScreenshotTaken += (control) => {
                        Console.WriteLine("Screenshot callback triggered!");
                        screenshotTaken = true;
                    };

                    // Take screenshot using the EXACT same method as GUI
                    Console.WriteLine("Taking screenshot using native method...");
                    viewport.Screenshot();

                    // Wait for screenshot to complete
                    int attempts = 0;
                    while (!screenshotTaken && attempts < 10)
                    {
                        System.Threading.Thread.Sleep(500);
                        System.Windows.Forms.Application.DoEvents(); // Process events
                        attempts++;
                    }

                    if (screenshotTaken)
                    {
                        // The screenshot should be saved in the default location
                        string datDir = System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(datFile));
                        string defaultPath = System.IO.Path.Combine(datDir, "csp_" + System.IO.Path.GetFileNameWithoutExtension(datFile) + ".png");

                        if (System.IO.File.Exists(defaultPath))
                        {
                            if (System.IO.File.Exists(actualOutputFile))
                                System.IO.File.Delete(actualOutputFile);
                            System.IO.File.Move(defaultPath, actualOutputFile);
                            Console.WriteLine($"CSP saved to: {actualOutputFile}");
                        }
                        else
                        {
                            Console.WriteLine($"Default CSP file not found at: {defaultPath}");
                        }
                    }
                    else
                    {
                        Console.WriteLine("Screenshot was not taken successfully");
                    }
                }

                Console.WriteLine("CSP generation completed successfully!");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"EXCEPTION CAUGHT: Error generating CSP: {ex.Message}");
                Console.WriteLine($"Stack trace: {ex.StackTrace}");
                Console.WriteLine($"Inner exception: {ex.InnerException?.Message}");
                Environment.Exit(1);
            }
            finally
            {
                Console.WriteLine("RunCSPGeneration finally block reached");
            }
        }

        // Helper method to find JOBJ nodes in the DAT file tree
        static DataNode FindJOBJNode(DataNode node)
        {
            if (node.Accessor is HSDRaw.Common.HSD_JOBJ)
                return node;

            foreach (DataNode child in node.Nodes)
            {
                var found = FindJOBJNode(child);
                if (found != null)
                    return found;
            }
            return null;
        }

        // Helper method to find the viewport control in the form
        static HSDRawViewer.GUI.ViewportControl FindViewportControl(Control parent)
        {
            foreach (Control control in parent.Controls)
            {
                if (control is HSDRawViewer.GUI.ViewportControl viewport)
                    return viewport;

                if (control is HSDRawViewer.GUI.Controls.DockableViewport dockableViewport)
                    return dockableViewport.glViewport;

                var found = FindViewportControl(control);
                if (found != null)
                    return found;
            }
            return null;
        }

        // Helper method to hide DOBJs by direct DOBJ indices
        static void ApplyHiddenNodes(DataNode jobjRootNode, List<int> hiddenNodeIndices, HSDRawViewer.Rendering.Models.RenderJObj renderJObj = null)
        {
            if (renderJObj != null && hiddenNodeIndices.Count > 0)
            {
                Console.WriteLine($"Hiding {hiddenNodeIndices.Count} DOBJs...");

                int hiddenCount = 0;
                foreach (int dobjIndex in hiddenNodeIndices)
                {
                    if (dobjIndex >= 0 && dobjIndex < renderJObj.DObjCount)
                    {
                        renderJObj.SetDObjVisible(dobjIndex, false);
                        hiddenCount++;
                    }
                }
                Console.WriteLine($"Successfully hid {hiddenCount} DOBJs");
            }
        }

        // Helper method to apply lighting settings from YAML
        static void ApplyLightingSettings(HSDRawViewer.Rendering.Models.RenderJObj renderJObj,
            float lightX, float lightY, float lightZ,
            float ambientPower, float ambientR, float ambientG, float ambientB,
            float diffusePower, float diffuseR, float diffuseG, float diffuseB)
        {
            try
            {
                // Set to use custom lighting
                renderJObj._settings.LightSource = HSDRawViewer.Rendering.Models.LightRenderMode.Custom;

                // Configure the primary light (Light0)
                if (renderJObj._settings._lights != null && renderJObj._settings._lights.Length > 0)
                {
                    var light0 = renderJObj._settings._lights[0];
                    light0.Enabled = true;
                    light0.Type = HSDRaw.Common.LObjType.INFINITE;
                    light0._position = new OpenTK.Mathematics.Vector3(lightX, lightY, lightZ);

                    // Set diffuse light color (convert from 0-255 range to 0-1 range)
                    light0._color = new OpenTK.Mathematics.Vector4(
                        (diffuseR / 255f) * diffusePower,
                        (diffuseG / 255f) * diffusePower,
                        (diffuseB / 255f) * diffusePower,
                        1.0f
                    );

                    Console.WriteLine($"Applied lighting: Position({lightX}, {lightY}, {lightZ}), " +
                                    $"Diffuse({diffuseR}, {diffuseG}, {diffuseB}) * {diffusePower}, " +
                                    $"Ambient({ambientR}, {ambientG}, {ambientB}) * {ambientPower}");
                }

                // Configure ambient lighting if there's a second light slot
                if (renderJObj._settings._lights.Length > 1)
                {
                    var ambientLight = renderJObj._settings._lights[1];
                    ambientLight.Enabled = true;
                    ambientLight.Type = HSDRaw.Common.LObjType.AMBIENT;

                    // Set ambient light color
                    ambientLight._color = new OpenTK.Mathematics.Vector4(
                        (ambientR / 255f) * ambientPower,
                        (ambientG / 255f) * ambientPower,
                        (ambientB / 255f) * ambientPower,
                        1.0f
                    );
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Error applying lighting settings: {ex.Message}");
            }
        }

    }

    // Simple drawable wrapper for RenderJObj
    public class SimpleJObjDrawable : IDrawable
    {
        public DrawOrder DrawOrder => DrawOrder.First;
        private readonly RenderJObj _renderJObj;

        public SimpleJObjDrawable(RenderJObj renderJObj)
        {
            _renderJObj = renderJObj;
        }

        public void GLInit()
        {
            // RenderJObj handles its own OpenGL initialization
        }

        public void GLFree()
        {
            // RenderJObj handles its own OpenGL cleanup
        }

        public void Draw(Camera cam, int windowWidth, int windowHeight)
        {
            _renderJObj.Render(cam);
        }
    }

    // Helper class to write to multiple TextWriters simultaneously
    public class MultiTextWriter : System.IO.TextWriter
    {
        private System.IO.TextWriter[] writers;

        public MultiTextWriter(params System.IO.TextWriter[] writers)
        {
            this.writers = writers;
        }

        public override void Write(char value)
        {
            foreach (var writer in writers)
                writer.Write(value);
        }

        public override void WriteLine(string value)
        {
            foreach (var writer in writers)
                writer.WriteLine(value);
        }

        public override System.Text.Encoding Encoding
        {
            get { return System.Text.Encoding.UTF8; }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                foreach (var writer in writers)
                    writer.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
