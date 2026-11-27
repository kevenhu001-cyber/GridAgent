using System.IO;
using Microsoft.UI.Xaml;

namespace GridAgent.Windows;

public partial class App : Application
{
    private MainWindow? _window;

    public App()
    {
        StartupDiagnostics.Record("application.initialize.begin");
        try
        {
            UnhandledException += (_, e) => StartupDiagnostics.Record("application.unhandled", e.Exception);
            InitializeComponent();
            StartupDiagnostics.Record("application.initialize.complete");
        }
        catch (Exception ex)
        {
            StartupDiagnostics.Record("application.initialize.failed", ex);
            throw;
        }
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        try
        {
            StartupDiagnostics.Record("launch.configure");
            AppDataPaths.ConfigureProcess();
            bool smoke = AppDataPaths.IsPackaged && global::Windows.ApplicationModel.Package.Current.Id.Name == "GridAgent.Development" &&
                (args.Arguments.Trim() == "--msix-smoke" || Environment.GetCommandLineArgs().Contains("--msix-smoke"));
            bool uiOnly = !AppDataPaths.IsPackaged &&
                Environment.GetEnvironmentVariable("GRIDAGENT_STARTUP_DIAGNOSTICS") == "1" &&
                Environment.GetCommandLineArgs().Contains("--ui-smoke");
            StartupDiagnostics.Record("window.construct.begin");
            _window = new MainWindow(skipOnboarding: smoke || uiOnly);
            StartupDiagnostics.Record("window.construct.complete");
            _window.Activate();
            StartupDiagnostics.Record("window.activate.complete");
            if (smoke)
                _ = MsixSmoke.RunAsync();
            else if (uiOnly)
                _ = _window.RunUiSmokeAsync();
        }
        catch (Exception ex)
        {
            StartupDiagnostics.Record("launch.failed", ex);
            throw;
        }
    }
}

// Explicit CI opt-in for portable builds, or development package only.
 // Best-effort local diagnostics must not mask the original exception.
internal static class StartupDiagnostics
{
    internal static void Record(string stage, Exception? error = null)
    {
        try
        {
            string path;
            if (AppDataPaths.IsPackaged)
            {
                if (global::Windows.ApplicationModel.Package.Current.Id.Name != "GridAgent.Development") return;
                path = Path.Combine(AppDataPaths.DataRoot, "startup-diagnostics.log");
            }
            else
            {
                if (Environment.GetEnvironmentVariable("GRIDAGENT_STARTUP_DIAGNOSTICS") != "1") return;
                path = Path.Combine(AppContext.BaseDirectory, "startup-diagnostics.log");
            }
            File.AppendAllText(path, $"{DateTimeOffset.UtcNow:O} {stage}" +
                (error is null ? "" : $" {error}") + Environment.NewLine);
        }
        catch { /* Never replace an original startup failure with a logging failure. */ }
    }
}
