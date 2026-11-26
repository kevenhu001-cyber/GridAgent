using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace GridAgent.Windows;

// A packaged app must never write to its installation directory. Package-local
// defaults are explicit; users may select a separate, durable research workspace.
internal static class AppDataPaths
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetCurrentPackageFullName(ref uint length, StringBuilder? name);
    public static bool IsPackaged
    {
        get
        {
            uint length = 0;
            return GetCurrentPackageFullName(ref length, null) == 122; // ERROR_INSUFFICIENT_BUFFER
        }
    }
    public static string DataRoot => IsPackaged
        ? global::Windows.Storage.ApplicationData.Current.LocalFolder.Path
        : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "GridAgent");
    public static string DefaultWorkspace => IsPackaged ? Path.Combine(DataRoot, "workspace") : DataRoot;
    public static string ThemeFile => Path.Combine(DataRoot, "desktop-theme.txt");
    public static void ConfigureProcess()
    {
        if (!IsPackaged) return;
        var plugins = Path.Combine(DataRoot, "plugins");
        var cache = Path.Combine(DataRoot, "cache", "numba");
        Directory.CreateDirectory(plugins);
        Directory.CreateDirectory(cache);
        Environment.SetEnvironmentVariable("GRIDAGENT_PLUGIN_ROOT", plugins);
        Environment.SetEnvironmentVariable("NUMBA_CACHE_DIR", cache);
        Environment.SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1");
    }
}
