using System.IO;
using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Graphics.Imaging;
using Windows.Storage;
using Windows.Storage.Streams;

namespace GridAgent.Windows;

public partial class MainWindow
{
    // Invoked only by explicit portable --ui-smoke with startup diagnostics enabled.
    // Fixed synthetic fixtures, no provider calls, workspace reads or solver execution.
    internal async Task RunUiSmokeAsync()
    {
        _uiSmokeActive = true;
        try
        {
            for (int i = 0; i < 40 && Root.XamlRoot == null; i++) await Task.Delay(100);
            if (Root.XamlRoot == null) throw new InvalidOperationException("Root did not load");
            var output = Path.Combine(AppContext.BaseDirectory, "ui-snapshots");
            Directory.CreateDirectory(output);
            ClearMessages();
            ModelName.Text = "Scientific assistant";
            BaseUrl.Text = "";
            ApiKey.Password = "";
            WorkspacePath.Text = "C:\\GridAgent\\Example";
            Append("Analyze the response of a second-order system.", "You");
            _conversation.Activity("Prepare the model");
            _conversation.Activity("Compute response");
            Append("## Simulation results\nThe response settles toward its steady-state value.\n\n| Quantity | Value |\n|---|---:|\n| Damping ratio | 0.7 |\n| Final value | 1.0 |", "Assistant");
            UpdateConversationViewport();
            _sessionsLoaded = true;
            SetSessions(new List<Entry> { new("fixture", "Analyze a second-order system") });
            using var catalog = JsonDocument.Parse("""[{"id":"fixture","title":"Example solver","installed":true,"managed":true,"tools":["solve"],"requirements":["example"],"versions":{"example":"1.0"},"rollback_available":false}]""");
            _pluginCatalog = catalog.RootElement.Clone();
            RenderPlugins();
            KnowledgePacks.ItemsSource = new List<Entry> { new("fixture", "Example references", Summary: "12 references") };
            _knowledgeLoaded = true;
            _workspaceIndexLoaded = true;
            RefreshEmptyStates();

            async Task SelectPage(string key)
            {
                Navigation.SelectedItem = key == "settings" ? Navigation.SettingsItem :
                    Navigation.MenuItems.OfType<NavigationViewItem>().First(i => (string?)i.Tag == key);
                await Task.Delay(220);
                Root.UpdateLayout();
                var page = key switch
                {
                    "chat" => (FrameworkElement)ChatPage, "tasks" => TasksPage, "models" => ModelsPage,
                    "runs" => RunsPage, "studies" => StudiesPage, "tools" => ToolsPage, "plugins" => PluginsPage,
                    "knowledge" => KnowledgePage, "settings" => SettingsPage,
                    _ => throw new InvalidOperationException("Unknown smoke page")
                };
                if (page.Visibility != Visibility.Visible || page.ActualWidth <= 0 || page.ActualHeight <= 0)
                    throw new InvalidOperationException("Invalid layout for " + key);
                StartupDiagnostics.Record("ui.page." + key);
            }
            async Task Snapshot(string name)
            {
                try
                {
                    var bitmap = new RenderTargetBitmap();
                    await bitmap.RenderAsync(Root);
                    var pixels = await bitmap.GetPixelsAsync();
                    if (bitmap.PixelWidth <= 0 || bitmap.PixelHeight <= 0 || pixels.Length == 0)
                        throw new InvalidOperationException("Empty snapshot");
                    byte[] bytes = new byte[pixels.Length];
                    using (var reader = DataReader.FromBuffer(pixels)) reader.ReadBytes(bytes);
                    var path = Path.Combine(output, name + ".png");
                    File.WriteAllBytes(path, Array.Empty<byte>());
                    var file = await StorageFile.GetFileFromPathAsync(path);
                    using var stream = await file.OpenAsync(FileAccessMode.ReadWrite);
                    var encoder = await BitmapEncoder.CreateAsync(BitmapEncoder.PngEncoderId, stream);
                    encoder.SetPixelData(BitmapPixelFormat.Bgra8, BitmapAlphaMode.Premultiplied,
                        (uint)bitmap.PixelWidth, (uint)bitmap.PixelHeight, 96, 96, bytes);
                    await encoder.FlushAsync();
                    StartupDiagnostics.Record("ui.snapshot." + name);
                }
                catch (Exception ex)
                {
                    // Some CI desktops cannot read back composition surfaces. Record, never fabricate.
                    StartupDiagnostics.Record("ui.snapshot.unavailable." + name, ex);
                }
            }

            Root.RequestedTheme = ElementTheme.Light;
            await SelectPage("chat");
            Prompt.Text = "";
            if (SendButton.IsEnabled) throw new InvalidOperationException("Empty prompt enabled");
            Prompt.Text = "Example follow-up";
            if (!SendButton.IsEnabled) throw new InvalidOperationException("Nonempty prompt disabled");
            await Snapshot("chat-light");
            foreach (var page in new[] { "tasks", "models", "runs", "studies", "tools", "plugins", "knowledge", "settings" })
                await SelectPage(page);
            await Snapshot("settings-light");
            await SelectPage("plugins");
            await Snapshot("plugins-light");
            await SelectPage("knowledge");
            await Snapshot("knowledge-light");
            Root.RequestedTheme = ElementTheme.Dark;
            await SelectPage("chat");
            await Snapshot("chat-dark");
            AppWindow.Resize(new global::Windows.Graphics.SizeInt32(640, 740));
            await Task.Delay(350);
            await SelectPage("chat");
            await Snapshot("chat-narrow-dark");

            var chart = new ChartData("Example response", "Time (s)", "Value", false,
                new[] { new ChartTrace("Response", new double[] { 0, 1, 2 }, new double[] { 0, 0.8, 1 }) });
            var plot = new ScientificPlotView(new[] { chart });
            var plotWindow = OpenEngineeringWindow("UI smoke chart", plot, plot.Release);
            await Task.Delay(350);
            if (plot.ActualWidth <= 0) throw new InvalidOperationException("Chart did not lay out");
            plotWindow.Close();
            StartupDiagnostics.Record("ui.viewer.chart");
            foreach (var raw in new[] {
                """{"kind":"heatmap","title":"Example field","run_id":"0000000000000000","x_label":"x","y_label":"y","value_label":"z","x":[0,1],"y":[0,1],"z":[[1,2],[3,4]]}""",
                """{"kind":"surface","title":"Example surface","run_id":"0000000000000000","x_label":"x","y_label":"y","value_label":"z","x":[0,1],"y":[0,1],"z":[[1,2],[3,4]]}""",
                """{"kind":"topology","title":"Example network","run_id":"0000000000000000","nodes":[{"id":"a","label":"A","x":0,"y":0},{"id":"b","label":"B","x":1,"y":1}],"edges":[{"source":"a","target":"b"}]}""",
                """{"kind":"table","title":"Example data","run_id":"0000000000000000","columns":["Time","Value"],"rows":[[0,1],[1,2]]}""" })
            {
                using var json = JsonDocument.Parse(raw);
                var viewer = new ScientificDataView(json.RootElement.Clone());
                var window = OpenEngineeringWindow("UI smoke view", viewer, viewer.Release);
                await Task.Delay(300);
                if (viewer.ActualWidth <= 0) throw new InvalidOperationException("Scientific view did not lay out");
                window.Close();
                StartupDiagnostics.Record("ui.viewer." + json.RootElement.GetProperty("kind").GetString());
            }
            StartupDiagnostics.Record("ui.smoke.complete");
        }
        catch (Exception ex) { StartupDiagnostics.Record("ui.smoke.failed", ex); }
    }
}
