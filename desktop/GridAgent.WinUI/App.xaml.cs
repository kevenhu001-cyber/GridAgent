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
    }
}
