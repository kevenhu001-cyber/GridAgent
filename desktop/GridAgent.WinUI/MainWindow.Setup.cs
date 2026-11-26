using System.IO;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.Storage.Pickers;

namespace GridAgent.Windows;

public partial class MainWindow
{
    private bool _setupOpen;

    private static Image? BrandImage()
    {
        if (!File.Exists(Path.Combine(AppContext.BaseDirectory, "BrandAssets", "GridAgent-logo.png"))) return null;
        return new Image
        {
            Source = new Microsoft.UI.Xaml.Media.Imaging.BitmapImage(new Uri("ms-appx:///BrandAssets/GridAgent-logo.png")),
            Width = 180, Height = 180, Stretch = Stretch.Uniform,
            HorizontalAlignment = HorizontalAlignment.Left
        };
    }

    private static TextBlock SetupText(string text, double size = 14) => new()
    {
        Text = text, FontSize = size, TextWrapping = TextWrapping.Wrap
    };

    private async void OpenSetupGuide(object sender, RoutedEventArgs e) => await ShowSetupAsync();
    private async void ShowAbout(object sender, RoutedEventArgs e)
    {
        if (_setupOpen || _busy) return;
        var content = new StackPanel { Spacing = 10, MaxWidth = 480 };
        if (BrandImage() is Image logo) content.Children.Add(logo);
        content.Children.Add(new TextBlock { Text = ProductInfo.Name, FontSize = 30, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold });
        content.Children.Add(SetupText(ProductInfo.Description));
        content.Children.Add(SetupText("Version " + ProductInfo.Version + " · " + ProductInfo.Distribution));
        content.Children.Add(SetupText("Developer: " + ProductInfo.Developer));
        content.Children.Add(SetupText("Lead developer: " + ProductInfo.LeadDeveloper));
        content.Children.Add(SetupText("Open-source license: " + ProductInfo.License));
        content.Children.Add(SetupText("For research and engineering analysis. Numerical results require independent verification; not a live grid-control product."));
        var dialog = new ContentDialog { XamlRoot = Root.XamlRoot, Title = "About GridAgent", Content = content, CloseButtonText = "Close" };
        await dialog.ShowAsync();
    }

    private async Task ShowSetupAsync()
    {
        if (_setupOpen || _busy) return;
        _setupOpen = true;
        string workspace = WorkspacePath.Text;
        string originalWorkspace = workspace;
        string model = ModelName.Text, endpoint = BaseUrl.Text;
        int step = 0;
        bool configuredProvider = false;
        try
        {
            while (step < 4)
            {
                var panel = new StackPanel { Spacing = 14, MaxWidth = 500 };
                panel.Children.Add(new TextBlock { Text = $"TOPODRIVE  ·  GET STARTED  ·  {step + 1}/4", FontSize = 12, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold });
                panel.Children.Add(new ProgressBar { Minimum = 0, Maximum = 4, Value = step + 1 });
                string title = "", next = "Continue";
                TextBox? modelBox = null, endpointBox = null;
                InfoBar? warning = null;
                if (step == 0)
                {
                    title = "Welcome to GridAgent";
                    if (BrandImage() is Image logo) panel.Children.Add(logo);
                    panel.Children.Add(SetupText("Your AI-assisted power system research workspace.", 22));
                    panel.Children.Add(SetupText("Build models, run local simulations and inspect numerical evidence. Optional solvers can be installed later."));
                    panel.Children.Add(SetupText("Developed by TopoDrive · Lead developer Adex Hu"));
                    panel.Children.Add(SetupText("The core runtime is already included. No account or additional solver download is required to use offline tools."));
                }
                else if (step == 1)
                {
                    title = "Choose a workspace";
                    panel.Children.Add(SetupText("Models, simulations, research records and local settings are stored here."));
                    var path = new TextBox { Header = "Workspace location", Text = workspace, IsReadOnly = true };
                    panel.Children.Add(path);
                    var browse = new Button { Content = "Choose folder…" };
                    browse.Click += async (_, _) =>
                    {
                        var picker = new FolderPicker();
                        picker.FileTypeFilter.Add("*");
                        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(this));
                        var folder = await picker.PickSingleFolderAsync();
                        if (folder != null) { workspace = folder.Path; path.Text = workspace; }
                    };
                    panel.Children.Add(browse);
                    if (AppDataPaths.IsPackaged) panel.Children.Add(SetupText("Choose an external folder to retain research data independently of app uninstall."));
                    panel.Children.Add(SetupText("The installation folder is not used for mutable research data."));
                    warning = new InfoBar { Severity = InfoBarSeverity.Error, IsOpen = false };
                    panel.Children.Add(warning);
                }
                else if (step == 2)
                {
                    title = "Connect an AI model";
                    panel.Children.Add(SetupText("Optional. Offline engineering tools work without a provider. Configure a compatible endpoint now or later in Settings."));
                    modelBox = new TextBox { Header = "Model name", Text = model, PlaceholderText = "Your model identifier" };
                    endpointBox = new TextBox { Header = "Base URL (optional)", Text = endpoint, PlaceholderText = "https://…/v1" };
                    panel.Children.Add(modelBox); panel.Children.Add(endpointBox);
                    panel.Children.Add(SetupText("API keys are entered in Settings and kept in the current session only. No credentials are saved by this guide."));
                    warning = new InfoBar { Severity = InfoBarSeverity.Error, IsOpen = false };
                    panel.Children.Add(warning);
                }
                else
                {
                    title = "Ready to explore";
                    next = "Open GridAgent";
                    panel.Children.Add(SetupText("Workspace", 16));
                    panel.Children.Add(SetupText(workspace));
                    panel.Children.Add(SetupText("AI provider", 16));
                    panel.Children.Add(SetupText(string.IsNullOrWhiteSpace(model) ? "Offline tools · configure an AI provider later" : model + " · enter your session API key in Settings"));
                    panel.Children.Add(SetupText("Start with a built-in simulation or ask a question. Verify numerical results before engineering decisions."));
                    panel.Children.Add(SetupText("Developed by TopoDrive · Adex Hu"));
                }
                var dialog = new ContentDialog
                {
                    XamlRoot = Root.XamlRoot, Title = title, Content = new ScrollViewer { Content = panel, MaxHeight = 440, VerticalScrollBarVisibility = ScrollBarVisibility.Auto },
                    PrimaryButtonText = next, CloseButtonText = "Set up later",
                    SecondaryButtonText = step == 0 ? "" : "Back", DefaultButton = ContentDialogButton.Primary
                };
                dialog.PrimaryButtonClick += (_, args) =>
                {
                    if (step == 1)
                    {
                        try
                        {
                            var candidate = Path.GetFullPath(workspace);
                            var install = Path.GetFullPath(AppContext.BaseDirectory).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
                            if ((candidate.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar).StartsWith(install, StringComparison.OrdinalIgnoreCase))
                                throw new IOException("Install directory");
                            Directory.CreateDirectory(candidate);
                            var probe = Path.Combine(candidate, ".gridagent-setup-" + Guid.NewGuid().ToString("N"));
                            using (new FileStream(probe, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1, FileOptions.DeleteOnClose)) { }
                            workspace = candidate;
                        }
                        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException or NotSupportedException)
                        {
                            args.Cancel = true; warning!.Message = "Choose a writable workspace outside the installation directory."; warning.IsOpen = true;
                        }
                    }
                    if (step == 2)
                    {
                        model = modelBox!.Text.Trim(); endpoint = endpointBox!.Text.Trim();
                        if (model.Length > 200 || endpoint.Length > 500 || (endpoint.Length > 0 &&
                            (!Uri.TryCreate(endpoint, UriKind.Absolute, out var uri) || (uri.Scheme != "http" && uri.Scheme != "https") ||
                             uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0)))
                        { args.Cancel = true; warning!.Message = "Enter a valid HTTP(S) endpoint without credentials, query or fragment."; warning.IsOpen = true; }
                        else configuredProvider = model.Length > 0;
                    }
                };
                var result = await dialog.ShowAsync();
                if (result == ContentDialogResult.None) { SetupPreferences.Complete(originalWorkspace); return; }
                if (result == ContentDialogResult.Secondary) { step--; continue; }
                step++;
            }
            if (!string.Equals(workspace, originalWorkspace, StringComparison.OrdinalIgnoreCase))
            {
                WorkspacePath.Text = workspace;
                ApiKey.Password = "";
                ClearMessages();
                await Execute(new { action = "initialize" });
                if (_operationError) { Notify("Workspace initialization failed. Reopen setup in Settings.", InfoBarSeverity.Error); return; }
            }
            if (configuredProvider)
            {
                ModelName.Text = model;
                BaseUrl.Text = endpoint;
                await Execute(new { action = "model-save", model, base_url = endpoint });
                if (_operationError) { Notify("Provider settings were not saved. Reopen setup in Settings.", InfoBarSeverity.Error); return; }
            }
            SetupPreferences.Complete(workspace);
            ShowChat();
            Notify("Workspace ready. Configure a session API key in Settings when using an online model.", InfoBarSeverity.Success);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Notify("Setup preferences could not be saved. You can still configure GridAgent in Settings.", InfoBarSeverity.Warning);
        }
        finally { _setupOpen = false; }
    }
}
