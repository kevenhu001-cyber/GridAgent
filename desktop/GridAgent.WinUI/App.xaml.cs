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
            StartupDiagnostics.Record("window.construct.begin");
            _window = new MainWindow(skipOnboarding: smoke);
            StartupDiagnostics.Record("window.construct.complete");
            _window.Activate();
            StartupDiagnostics.Record("window.activate.complete");
            if (smoke)
                _ = MsixSmoke.RunAsync();
        }
        catch (Exception ex)
        {
            StartupDiagnostics.Record("launch.failed", ex);
            throw;
        }
    }
}

// Development package only; best-effort local diagnostics must not mask the original exception.
internal static class StartupDiagnostics
{
    internal static void Record(string stage, Exception? error = null)
    {
        try
        {
            if (!AppDataPaths.IsPackaged || global::Windows.ApplicationModel.Package.Current.Id.Name != "GridAgent.Development") return;
            var path = Path.Combine(AppDataPaths.DataRoot, "startup-diagnostics.log");
            File.AppendAllText(path, $"{DateTimeOffset.UtcNow:O} {stage}" +
                (error is null ? "" : $" {error}") + Environment.NewLine);
        }
        catch { /* Never replace an original startup failure with a logging failure. */ }
    }
}
