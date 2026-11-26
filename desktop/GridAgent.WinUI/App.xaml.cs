using Microsoft.UI.Xaml;
namespace GridAgent.Windows;
public partial class App : Application
{
    private MainWindow? _window;
    public App() => InitializeComponent();
    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        AppDataPaths.ConfigureProcess();
        bool smoke = AppDataPaths.IsPackaged && global::Windows.ApplicationModel.Package.Current.Id.Name == "GridAgent.Development" &&
            (args.Arguments.Trim() == "--msix-smoke" || Environment.GetCommandLineArgs().Contains("--msix-smoke"));
        _window = new MainWindow(skipOnboarding: smoke);
        _window.Activate();
        if (smoke)
            _ = MsixSmoke.RunAsync();
    }
}
