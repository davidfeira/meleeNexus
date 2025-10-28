using mexLib.AssetTypes;
using mexLib.Utilties;
using System.ComponentModel;
using System.IO.Compression;
using System.Text;
using System.Text.Json.Serialization;

namespace mexLib.Types
{
    /// <summary>
    /// Represents a Dynamic Alternate Stage variant
    /// </summary>
    public class MexDASStage : MexReactiveObject
    {
        [DisplayName("Name")]
        public string Name { get => _name; set { _name = value; OnPropertyChanged(); } }
        private string _name = "New Stage Variant";

        [DisplayName("File")]
        public string? FileName { get => _fileName; set { _fileName = value; OnPropertyChanged(); } }
        private string? _fileName;

        [Browsable(false)]
        [JsonInclude]
        public string? Screenshot { get => ScreenshotAsset.AssetFileName; internal set => ScreenshotAsset.AssetFileName = value; }

        [DisplayName("Screenshot")]
        [JsonIgnore]
        [Browsable(false)]
        public MexTextureAsset ScreenshotAsset { get; set; } = new MexTextureAsset()
        {
            AssetPath = "das/screenshots",
            Width = -1,  // Variable dimensions
            Height = -1, // Variable dimensions
            Format = HSDRaw.GX.GXTexFmt.CMPR,
            TlutFormat = HSDRaw.GX.GXTlutFmt.RGB5A3,
        };

        /// <summary>
        ///
        /// </summary>
        /// <returns></returns>
        public override string ToString()
        {
            return Name;
        }

        /// <summary>
        /// Delete the stage file
        /// </summary>
        public void DeleteFile(MexWorkspace workspace)
        {
            if (FileName != null)
                workspace.FileManager.Remove(workspace.GetFilePath(FileName));
        }

        /// <summary>
        /// Delete the screenshot asset
        /// </summary>
        public void DeleteAssets(MexWorkspace workspace)
        {
            ScreenshotAsset.Delete(workspace);
        }

        /// <summary>
        /// Import DAS stage from ZIP package
        /// </summary>
        public static MexDASStage? FromZip(MexWorkspace workspace, Stream zipstream, StringBuilder log)
        {
            MexDASStage? stage = null;

            using (ZipArchive zip = new(zipstream, ZipArchiveMode.Read, true))
            {
                foreach (ZipArchiveEntry entry in zip.Entries)
                {
                    using Stream fstream = entry.Open();
                    using MemoryStream stream = new();
                    fstream.CopyTo(stream);
                    fstream.Close();

                    // .dat file
                    if (entry.Name.EndsWith(".dat"))
                    {
                        string targetPath = workspace.GetFilePath(entry.Name.Replace(" ", "_"));
                        string path = workspace.FileManager.GetUniqueFilePath(targetPath);

                        workspace.FileManager.Set(path, stream.ToArray());

                        stage = new MexDASStage
                        {
                            Name = Path.GetFileNameWithoutExtension(path),
                            FileName = Path.GetFileName(path)
                        };

                        log.AppendLine($"Imported \"{entry.FullName}\" as DAS stage");
                    }
                }
            }

            zipstream.Position = 0;

            // Search for screenshot
            using (ZipArchive zip = new(zipstream))
            {
                foreach (ZipArchiveEntry entry in zip.Entries)
                {
                    using Stream fstream = entry.Open();
                    using MemoryStream stream = new();
                    fstream.CopyTo(stream);
                    fstream.Close();

                    // Screenshot assets
                    if (Path.GetExtension(entry.Name).ToLower() == ".png" && stage != null)
                    {
                        switch (entry.Name.ToLower())
                        {
                            case "screenshot.png":
                            case "preview.png":
                            case "stage.png":
                                log.AppendLine($"Imported \"{entry.FullName}\" as screenshot");
                                stage.ScreenshotAsset.SetFromImageFile(workspace, stream);
                                break;
                        }
                    }
                }
            }

            return stage;
        }

        /// <summary>
        /// Import DAS stage from .dat file
        /// </summary>
        public static MexDASStage? FromDATFile(MexWorkspace workspace, string datpath, out string log)
        {
            string name = Path.GetFileName(datpath);

            // Add file to filesystem
            string targetPath = workspace.GetFilePath(name);
            string path = workspace.FileManager.GetUniqueFilePath(targetPath);
            workspace.FileManager.Set(path, workspace.FileManager.Get(datpath));

            // Setup DAS stage
            MexDASStage stage = new()
            {
                Name = Path.GetFileNameWithoutExtension(datpath),
                FileName = Path.GetFileName(path)
            };

            log = "";
            return stage;
        }

        /// <summary>
        /// Export DAS stage to ZIP package
        /// </summary>
        public void PackToZip(MexWorkspace workspace, Stream stream)
        {
            using ZipWriter zip = new(stream);
            zip.TryWriteFile(workspace, FileName, FileName);
            zip.TryWriteTextureAsset(workspace, ScreenshotAsset, "screenshot.png");
        }
    }
}
