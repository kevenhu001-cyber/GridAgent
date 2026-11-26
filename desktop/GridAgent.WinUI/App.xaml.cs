using Microsoft.UI.Xaml;
namespace GridAgent.Windows;
public partial class App : Application
{
    private MainWindow? _window;
    public App() => InitializeComponent();
    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        AppDataPaths.ConfigureProcess();
        _window = new MainWindow();
        _window.Activate();
        if (AppDataPaths.IsPackaged && global::Windows.ApplicationModel.Package.Current.Id.Name == "GridAgent.Development" &&
            (args.Arguments.Trim() == "--msix-smoke" || Environment.GetCommandLineArgs().Contains("--msix-smoke")))
            _ = MsixSmoke.RunAsync();
    }
}
