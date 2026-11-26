using System.IO;
using System.Text.Json;

namespace GridAgent.Windows;

internal static class SetupPreferences
{
    private static string FilePath => Path.Combine(AppDataPaths.DataRoot, "setup-v1.json");
    private sealed record Settings(bool Completed, string? Workspace);
    private static Settings Read()
    {
        try
        {
            return JsonSerializer.Deserialize<Settings>(File.ReadAllText(FilePath)) ?? new(false, null);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException) { return new(false, null); }
    }
    public static bool Completed => Read().Completed;
    public static string? LoadWorkspace()
    {
        var path = Read().Workspace;
        return !string.IsNullOrWhiteSpace(path) && Path.IsPathFullyQualified(path) && Directory.Exists(path) ? path : null;
    }
    public static void SaveWorkspace(string workspace) => Save(new(Read().Completed, workspace));
    public static void Complete(string workspace) => Save(new(true, workspace));
    private static void Save(Settings settings)
    {
        Directory.CreateDirectory(AppDataPaths.DataRoot);
        var temp = FilePath + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { File.WriteAllText(temp, JsonSerializer.Serialize(settings)); File.Move(temp, FilePath, overwrite: true); }
        finally { if (File.Exists(temp)) File.Delete(temp); }
    }
}
